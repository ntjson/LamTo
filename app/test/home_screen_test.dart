import 'dart:async';

import 'package:built_collection/built_collection.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/error_retry.dart';
import 'package:lamto/core/format.dart';
import 'package:lamto/features/home/home_screen.dart';
import 'package:lamto/features/ledger/ledger_screen.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/features/shell/home_shell.dart';
import 'package:lamto/features/transparency/fund_chart.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

FundSummary _fund() => FundSummary(
  (b) => b
    ..balanceVnd = 1500000
    ..periodDays = 30
    ..periodInflowsVnd = 200000
    ..periodOutflowsVnd = 50000,
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

LedgerEntryList _entry(int id) => LedgerEntryList(
  (b) => b
    ..id = id
    ..contractorName = 'Acme Co'
    ..actualCostVnd = 900000
    ..publishedAt = DateTime.utc(2026, 7, 10)
    ..integrityStatus = 'VERIFIED'
    ..evidenceLevel = 'CHAIN_CONFIRMED',
);

ReportSummary _report(String text, StatusEnum status) => ReportSummary(
  (b) => b
    ..id = 1
    ..text = text
    ..status = status
    ..isPrivate = false
    ..locationPathSnapshot = 'B / Hall'
    ..createdAt = DateTime.utc(2026, 7, 9),
);

class _FakeReports implements ReportsRepository {
  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) async =>
      PaginatedReportSummaryList(
        (b) => b
          ..results = ListBuilder<ReportSummary>([
            _report('Thang máy kêu', StatusEnum.SUBMITTED),
            _report('Đèn hỏng', StatusEnum.COMPLETED),
          ]),
      );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Reports list throws; used to assert home active-reports error copy.
class _ThrowingReports implements ReportsRepository {
  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) async {
    throw Exception('boom');
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _PendingReports implements ReportsRepository {
  final pending = Completer<PaginatedReportSummaryList>();

  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) =>
      pending.future;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _FakeTransparency implements TransparencyRepository {
  @override
  Future<FundSummary> fetchFundSummary() async => _fund();

  @override
  Future<FundSeries> fetchFundSeries({String range = '6m'}) async =>
      _series(range);

  @override
  Future<PaginatedLedgerEntryListList> listLedger({
    String? cursor,
    int? year,
    int? month,
  }) async => PaginatedLedgerEntryListList(
    (b) => b..results = ListBuilder<LedgerEntryList>([_entry(1)]),
  );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _ThrowingSeriesTransparency extends _FakeTransparency {
  @override
  Future<FundSeries> fetchFundSeries({String range = '6m'}) async {
    throw Exception('series down');
  }
}

class _PendingSeriesTransparency extends _FakeTransparency {
  final series = Completer<FundSeries>();

  @override
  Future<FundSeries> fetchFundSeries({String range = '6m'}) => series.future;
}

class _PendingTransparency implements TransparencyRepository {
  final fund = Completer<FundSummary>();
  final series = Completer<FundSeries>();
  final ledger = Completer<PaginatedLedgerEntryListList>();

  @override
  Future<FundSummary> fetchFundSummary() => fund.future;

  @override
  Future<FundSeries> fetchFundSeries({String range = '6m'}) => series.future;

  @override
  Future<PaginatedLedgerEntryListList> listLedger({
    String? cursor,
    int? year,
    int? month,
  }) => ledger.future;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pumpShell(WidgetTester tester) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        reportsRepositoryProvider.overrideWithValue(_FakeReports()),
        transparencyRepositoryProvider.overrideWithValue(_FakeTransparency()),
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const HomeShell(),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('home renders fund chart card', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          reportsRepositoryProvider.overrideWithValue(_FakeReports()),
          transparencyRepositoryProvider.overrideWithValue(_FakeTransparency()),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: const Scaffold(body: HomeScreen()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(FundChart), findsOneWidget);
    expect(find.byType(LineChart), findsOneWidget);
  });

  testWidgets('series loading keeps a named chart placeholder', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          reportsRepositoryProvider.overrideWithValue(_FakeReports()),
          transparencyRepositoryProvider.overrideWithValue(
            _PendingSeriesTransparency(),
          ),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: const Scaffold(body: HomeScreen()),
        ),
      ),
    );
    await tester.pump();

    expect(find.byType(FundChart), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsWidgets);
  });

  testWidgets('series failure shows retry but keeps balance', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        retry: (_, _) => null,
        overrides: [
          reportsRepositoryProvider.overrideWithValue(_FakeReports()),
          transparencyRepositoryProvider.overrideWithValue(
            _ThrowingSeriesTransparency(),
          ),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: const Scaffold(body: HomeScreen()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text(formatVnd(1500000)), findsOneWidget);
    expect(find.byType(ErrorRetry), findsWidgets);
    expect(find.byType(LineChart), findsNothing);
  });

  testWidgets('Android Home chart opens the shell Ledger tab', (tester) async {
    final previous = debugDefaultTargetPlatformOverride;
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    try {
      await _pumpShell(tester);
      await tester.tap(find.byType(FundChart));
      await tester.pumpAndSettle();

      expect(
        tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
        ledgerTabIndex,
      );
      expect(find.byType(LedgerScreen), findsOneWidget);
    } finally {
      debugDefaultTargetPlatformOverride = previous;
    }
  });

  testWidgets('iOS Home chart opens the shell Ledger tab', (tester) async {
    final previous = debugDefaultTargetPlatformOverride;
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await _pumpShell(tester);
      final controller = tester
          .widget<CupertinoTabScaffold>(find.byType(CupertinoTabScaffold))
          .controller!;

      await tester.tap(find.byType(FundChart));
      await tester.pumpAndSettle();

      expect(controller.index, ledgerTabIndex);
      expect(find.byType(LedgerScreen), findsOneWidget);
    } finally {
      debugDefaultTargetPlatformOverride = previous;
    }
  });

  testWidgets('home shows fund block, open reports only, recent spending', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          reportsRepositoryProvider.overrideWithValue(_FakeReports()),
          transparencyRepositoryProvider.overrideWithValue(_FakeTransparency()),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('vi'),
          home: const Scaffold(body: HomeScreen()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Quỹ bảo trì'), findsOneWidget);
    expect(find.text('1.500.000 ₫'), findsOneWidget); // tabular integer VND
    expect(find.text('Thang máy kêu'), findsOneWidget); // OPEN shown
    expect(find.text('Đèn hỏng'), findsNothing); // RESOLVED filtered out
    expect(find.text('Acme Co'), findsOneWidget); // recent spending row
    expect(find.byIcon(Icons.notifications_outlined), findsOneWidget); // bell
  });

  testWidgets(
    'home active-reports AsyncError shows resident failure copy, not empty',
    (tester) async {
      // Riverpod 3 auto-retries Exceptions; disable so AsyncError surfaces
      // immediately (production still retries then settles on AsyncError).
      await tester.pumpWidget(
        ProviderScope(
          retry: (_, _) => null,
          overrides: [
            reportsRepositoryProvider.overrideWithValue(_ThrowingReports()),
            transparencyRepositoryProvider.overrideWithValue(
              _FakeTransparency(),
            ),
          ],
          child: MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: const Locale('vi'),
            home: const Scaffold(body: HomeScreen()),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Fund / spending still succeed.
      expect(find.text('Quỹ bảo trì'), findsOneWidget);
      expect(find.text('1.500.000 ₫'), findsOneWidget);
      expect(find.text('Acme Co'), findsOneWidget);

      // Active-reports section header + resident-facing errServer (generic throw
      // → Failure.fromObject → server_error), not a silent empty list.
      expect(find.text('Phản ánh đang mở'), findsOneWidget);
      expect(
        find.text(
          'Đã có lỗi từ phía hệ thống. Thao tác có thể chưa được lưu. Vui lòng thử lại sau.',
        ),
        findsOneWidget,
      );
    },
  );

  testWidgets('home names section loading states instead of leaving blanks', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          reportsRepositoryProvider.overrideWithValue(_PendingReports()),
          transparencyRepositoryProvider.overrideWithValue(
            _PendingTransparency(),
          ),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('vi'),
          home: const Scaffold(body: HomeScreen()),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Đang tải phản ánh…'), findsOneWidget);
    expect(find.text('Đang tải khoản chi…'), findsOneWidget);
  });

  testWidgets('fund period stats stack at large text sizes', (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          reportsRepositoryProvider.overrideWithValue(_FakeReports()),
          transparencyRepositoryProvider.overrideWithValue(_FakeTransparency()),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('vi'),
          home: const MediaQuery(
            data: MediaQueryData(textScaler: TextScaler.linear(2)),
            child: Scaffold(body: HomeScreen()),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('fund-period-stats-stacked')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
