import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/features/home/home_screen.dart';
import 'package:lamto/features/reports/reports_repository.dart';
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

LedgerEntryList _entry(int id) => LedgerEntryList(
      (b) => b
        ..id = id
        ..contractorName = 'Acme Co'
        ..actualCostVnd = 900000
        ..publishedAt = DateTime.utc(2026, 7, 10)
        ..integrityStatus = 'VERIFIED'
        ..evidenceLevel = 'CHAIN_CONFIRMED',
    );

ReportSummary _report(String text, String status) => ReportSummary(
      (b) => b
        ..id = 1
        ..text = text
        ..status = status
        ..locationPathSnapshot = 'B / Hall'
        ..createdAt = DateTime.utc(2026, 7, 9),
    );

class _FakeReports implements ReportsRepository {
  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) async =>
      PaginatedReportSummaryList(
        (b) => b
          ..results = ListBuilder<ReportSummary>(
              [_report('Thang máy kêu', 'OPEN'), _report('Đèn hỏng', 'RESOLVED')]),
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

class _FakeTransparency implements TransparencyRepository {
  @override
  Future<FundSummary> fetchFundSummary() async => _fund();

  @override
  Future<PaginatedLedgerEntryListList> listLedger(
          {String? cursor, int? year, int? month}) async =>
      PaginatedLedgerEntryListList(
        (b) => b..results = ListBuilder<LedgerEntryList>([_entry(1)]),
      );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('home shows fund block, open reports only, recent spending',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
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
    ));
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
    await tester.pumpWidget(ProviderScope(
      retry: (_, __) => null,
      overrides: [
        reportsRepositoryProvider.overrideWithValue(_ThrowingReports()),
        transparencyRepositoryProvider.overrideWithValue(_FakeTransparency()),
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const Scaffold(body: HomeScreen()),
      ),
    ));
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
          'Đã có lỗi từ phía hệ thống. Thao tác có thể chưa được lưu. Vui lòng thử lại sau.'),
      findsOneWidget,
    );
  });
}
