import 'dart:async';
import 'dart:typed_data';

import 'package:built_collection/built_collection.dart';
import 'package:built_value/json_object.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/failure.dart';
import 'package:lamto/features/ledger/ledger_detail_screen.dart';
import 'package:lamto/features/ledger/ledger_screen.dart';
import 'package:lamto/features/transparency/fund_chart.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

LedgerEntryList _entry(int id, String level) => LedgerEntryList(
  (b) => b
    ..id = id
    ..contractorName = 'Acme Co'
    ..actualCostVnd = 900000
    ..publishedAt = DateTime.utc(2026, 7, 10)
    ..integrityStatus = 'VERIFIED'
    ..evidenceLevel = level,
);

FundSeries _series(String range) => FundSeries(
  (b) => b
    ..range = range
    ..points = ListBuilder<FundSeriesPoint>([
      for (var i = 0; i < 6; i++)
        FundSeriesPoint(
          (p) => p
            ..periodStart = DateTime.utc(2026, 2 + i, 1)
            ..inflowsVnd = i == 2 ? 200000 : 0
            ..outflowsVnd = i == 4 ? -50000 : 0
            ..balanceVnd = 1500000 + i * 10000,
        ),
    ]),
);

LedgerEntryDetail _detail() => LedgerEntryDetail(
  (b) => b
    ..id = 42
    ..contractorName = 'Acme Co'
    ..actualCostVnd = 900000
    ..publishedAt = DateTime.utc(2026, 7, 10)
    ..proposedAmountVnd = 950000
    ..integrityStatus = 'VERIFIED'
    ..whatWasFixed = 'Cable secured'
    ..why = 'Worn cable'
    ..approvers = ListBuilder<JsonObject?>([
      JsonObject({'role': 'board', 'name': 'Ông Minh', 'decision': 'APPROVE'}),
      JsonObject({
        'role': 'resident_rep',
        'name': 'Bà Hoa',
        'decision': 'APPROVE',
      }),
    ])
    ..verification = Verification(
      (v) => v
        ..decision = 'VERIFIED'
        ..verifiedBy = 'Bà Lan'
        ..verifiedAt = DateTime.utc(2026, 7, 9),
    ).toBuilder()
    ..redactedDocuments = ListBuilder<RedactedDocument>([
      RedactedDocument(
        (d) => d
          ..label = 'Hóa đơn đã che thông tin'
          ..filename = 'hoa-don.pdf'
          ..sha256 = 'doc-hash'
          ..downloadUrl = '/api/v1/documents/test-token',
      ),
    ])
    ..corrections = ListBuilder<JsonObject?>()
    ..proof = Proof(
      (p) => p
        ..evidenceLevel = 'LOCAL_SIGNED'
        ..anchoringBackend = 'disabled'
        ..payloadHash = 'ab12cd34'
        ..events = ListBuilder<ProofEvent>([
          ProofEvent(
            (e) => e
              ..eventId = '0xfeed'
              ..eventType = 9
              ..status = 'LOCAL'
              ..evidenceLevel = 'LOCAL_SIGNED'
              ..transactionHash = '',
          ),
        ]),
    ).toBuilder(),
);

class _FakeRepo implements TransparencyRepository {
  final periods = <(int?, int?)>[];
  final seriesRanges = <String>[];
  final document = Completer<Uint8List>();
  final documentRetryErrors = <Object>[
    Failure(code: 'permission_denied'),
    StateError('broken file'),
  ];
  int documentCalls = 0;

  @override
  Future<FundSeries> fetchFundSeries({String range = '6m'}) async {
    seriesRanges.add(range);
    return _series(range);
  }

  @override
  Future<PaginatedLedgerEntryListList> listLedger({
    String? cursor,
    int? year,
    int? month,
  }) async {
    periods.add((year, month));
    return PaginatedLedgerEntryListList(
      (b) => b
        ..results = ListBuilder<LedgerEntryList>(
          year == null ? [_entry(42, 'LOCAL_SIGNED')] : [],
        ),
    );
  }

  @override
  Future<LedgerEntryDetail> fetchLedgerEntry(int id) async => _detail();

  @override
  Future<Uint8List> fetchDocument(String downloadUrl) {
    documentCalls++;
    if (documentCalls == 1) return document.future;
    return Future.error(documentRetryErrors.removeAt(0));
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget _host(Widget child, _FakeRepo repo) => ProviderScope(
  overrides: [transparencyRepositoryProvider.overrideWithValue(repo)],
  child: MaterialApp(
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('vi'),
    home: child,
  ),
);

void main() {
  testWidgets('ledger tab shows full fund chart with range selector', (
    tester,
  ) async {
    final repo = _FakeRepo();
    await tester.pumpWidget(_host(const Scaffold(body: LedgerScreen()), repo));
    await tester.pumpAndSettle();
    expect(find.text('Số dư quỹ'), findsOneWidget);
    expect(find.byType(FundChart), findsOneWidget);
    expect(find.byType(LineChart), findsOneWidget);
    expect(find.byType(BarChart), findsOneWidget);
    expect(find.byType(SegmentedButton<String>), findsOneWidget);
  });

  testWidgets('range selector switches the series', (tester) async {
    final repo = _FakeRepo();
    final container = ProviderContainer(
      overrides: [transparencyRepositoryProvider.overrideWithValue(repo)],
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('vi'),
          home: const Scaffold(body: LedgerScreen()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('30 ngày'));
    await tester.pumpAndSettle();
    expect(container.read(fundChartRangeProvider), '30d');
    expect(repo.seriesRanges, containsAllInOrder(['6m', '30d']));
  });

  testWidgets('ledger chart supports large text without overflow', (
    tester,
  ) async {
    final repo = _FakeRepo();
    await tester.pumpWidget(
      _host(
        const MediaQuery(
          data: MediaQueryData(textScaler: TextScaler.linear(2)),
          child: Scaffold(body: LedgerScreen()),
        ),
        repo,
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byType(FundChart), findsOneWidget);
  });

  testWidgets('list shows entries with evidence badge and period filter', (
    tester,
  ) async {
    final repo = _FakeRepo();
    await tester.pumpWidget(_host(const Scaffold(body: LedgerScreen()), repo));
    await tester.pumpAndSettle();
    expect(find.text('Acme Co'), findsOneWidget);
    expect(find.textContaining('Đã ký — chưa bật neo'), findsOneWidget);

    // Choosing a year re-queries with the filter; empty period shows copy.
    final year = DateTime.now().year;
    await tester.tap(find.text('$year'));
    await tester.pumpAndSettle();
    expect(repo.periods.last, (year, null));
    expect(find.text('Không có khoản chi nào trong kỳ này.'), findsOneWidget);
  });

  testWidgets(
    'detail leads with conclusion then expands accountability chain',
    (tester) async {
      final repo = _FakeRepo();
      await tester.pumpWidget(
        _host(const LedgerDetailScreen(entryId: 42), repo),
      );
      await tester.pumpAndSettle();

      expect(find.text('Khoản chi này đã được xác minh'), findsOneWidget);
      expect(find.text('Chuỗi trách nhiệm'), findsOneWidget);
      expect(find.text('Phản ánh và lý do'), findsNothing);
      expect(find.text('ab12cd34'), findsNothing); // hash hidden until expanded

      await tester.tap(find.text('Chuỗi trách nhiệm'));
      await tester.pumpAndSettle();
      expect(find.text('Phản ánh và lý do'), findsOneWidget);
      expect(find.text('Công việc đã hoàn thành'), findsOneWidget);
      expect(find.text('Phê duyệt'), findsOneWidget);
      expect(find.text('Chứng từ thanh toán'), findsOneWidget);
      expect(find.text('Xác minh độc lập'), findsOneWidget);
      expect(find.text('Cable secured'), findsOneWidget);
      expect(find.text('Worn cable'), findsOneWidget);
      expect(find.textContaining('900.000 ₫'), findsWidgets);
      expect(find.textContaining('Ông Minh'), findsOneWidget);
      expect(find.textContaining('Bà Hoa'), findsOneWidget);
      expect(find.textContaining('Bà Lan'), findsOneWidget);

      await tester.scrollUntilVisible(
        find.text('Chi tiết xác thực'),
        200,
        scrollable: find.byType(Scrollable).last,
      );
      expect(find.text('ab12cd34'), findsOneWidget);
      expect(find.textContaining('0xfeed'), findsOneWidget);
    },
  );

  testWidgets('document row covers loading, offline, authorization and retry', (
    tester,
  ) async {
    final repo = _FakeRepo();
    await tester.pumpWidget(_host(const LedgerDetailScreen(entryId: 42), repo));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Chuỗi trách nhiệm'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('Hóa đơn đã che thông tin'),
      200,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.ensureVisible(find.text('Hóa đơn đã che thông tin'));
    await tester.pumpAndSettle();
    expect(find.text('Xem hoặc tải xuống'), findsOneWidget);
    await tester.tap(find.text('Hóa đơn đã che thông tin'));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    repo.document.completeError(Failure(code: 'network_error'));
    await tester.pumpAndSettle();
    expect(find.textContaining('ngoại tuyến'), findsOneWidget);
    expect(find.text('Thử lại'), findsOneWidget);

    await tester.tap(find.text('Thử lại'));
    await tester.pumpAndSettle();
    expect(find.textContaining('không có quyền'), findsOneWidget);

    await tester.tap(find.text('Thử lại'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Không mở được tài liệu'), findsOneWidget);
    expect(repo.documentCalls, 3);
  });
}
