import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/features/reports/issue_detail_screen.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

ReportDetail _detail({required bool canRate}) => ReportDetail(
  (b) => b
    ..id = 42
    ..text = 'Thang máy kêu to'
    ..status = StatusEnum.SUBMITTED
    ..isPrivate = false
    ..locationPathSnapshot = 'Tòa A / Thang máy 2'
    ..unitLabel = 'B-1204'
    ..createdAt = DateTime.utc(2026, 7, 10)
    ..triageStatus = 'SUCCEEDED'
    ..category = 'Thang máy'
    ..photos = ListBuilder<ReportPhoto>()
    ..cases = ListBuilder<ReportCase>([
      ReportCase(
        (c) => c
          ..id = 1
          ..category = 'Thang máy'
          ..urgency = 'HIGH'
          ..deadlineAt = DateTime.utc(2026, 7, 12)
          ..active = true
          ..completedAt = DateTime.utc(2026, 7, 11)
          ..updates = ListBuilder<ReportWorkUpdate>([
            ReportWorkUpdate(
              (u) => u
                ..id = 9
                ..cause = 'Cáp mòn'
                ..result = 'Đã cố định cáp'
                ..createdAt = DateTime.utc(2026, 7, 11),
            ),
          ])
          ..canRate = canRate,
      ),
    ]),
);

class _FakeRepo implements ReportsRepository {
  _FakeRepo(this.detail);
  ReportDetail detail;
  final ratings = <(int, bool, String)>[];

  @override
  Future<ReportDetail> fetchReport(int id) async => detail;

  @override
  Future<CaseRatingResult> rateCase({
    required int caseId,
    required bool satisfied,
    String comment = '',
  }) async {
    ratings.add((caseId, satisfied, comment));
    detail = _detail(canRate: false);
    return CaseRatingResult(
      (b) => b
        ..id = 1
        ..caseId = caseId
        ..satisfied = satisfied,
    );
  }

  @override
  Future<ReportSummary> createReport({
    required String clientRef,
    required String text,
    required int locationId,
  }) => throw UnimplementedError();
  @override
  Future<List<Location>> fetchLocations() => throw UnimplementedError();
  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) =>
      throw UnimplementedError();
  @override
  Future<ReportPhoto> uploadPhoto({
    required int reportId,
    required String path,
    required String filename,
  }) => throw UnimplementedError();
}

Future<void> _pump(WidgetTester tester, _FakeRepo repo) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [reportsRepositoryProvider.overrideWithValue(repo)],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const IssueDetailScreen(reportId: 42),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('renders the plain-language timeline in order', (tester) async {
    await _pump(tester, _FakeRepo(_detail(canRate: false)));
    // Submitted/completed lines include a local date suffix.
    expect(find.textContaining('Đã gửi phản ánh'), findsOneWidget);
    expect(find.text('Ban quản lý đã xem xét'), findsOneWidget);
    expect(find.textContaining('Đã ghép vào yêu cầu xử lý'), findsOneWidget);
    expect(find.textContaining('Đã cố định cáp'), findsOneWidget);
    expect(find.textContaining('Công việc đã hoàn thành'), findsOneWidget);
    expect(find.text('Đánh giá công việc'), findsNothing);
  });

  testWidgets('rates eligible case as satisfied and refreshes', (tester) async {
    final repo = _FakeRepo(_detail(canRate: true));
    await _pump(tester, repo);
    await tester.tap(find.text('Đánh giá công việc'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Hài lòng'));
    await tester.pump();
    await tester.tap(find.text('Gửi đánh giá'));
    await tester.pumpAndSettle();

    expect(repo.ratings.single, (1, true, ''));
    expect(find.text('Cảm ơn bạn đã đánh giá.'), findsOneWidget);
    expect(find.text('Đánh giá công việc'), findsNothing); // refreshed
  });

  testWidgets('rates eligible case as not satisfied', (tester) async {
    final repo = _FakeRepo(_detail(canRate: true));
    await _pump(tester, repo);
    await tester.tap(find.text('Đánh giá công việc'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Không hài lòng'));
    await tester.pump();
    await tester.tap(find.text('Gửi đánh giá'));
    await tester.pumpAndSettle();

    expect(repo.ratings.single, (1, false, ''));
  });

  testWidgets('retapping the selected rating keeps a valid selection', (
    tester,
  ) async {
    final repo = _FakeRepo(_detail(canRate: true));
    await _pump(tester, repo);
    await tester.tap(find.text('Đánh giá công việc'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Hài lòng'));
    await tester.pump();
    await tester.tap(find.text('Hài lòng'));
    await tester.pump();
    await tester.tap(find.text('Gửi đánh giá'));
    await tester.pumpAndSettle();

    expect(repo.ratings.single, (1, true, ''));
  });
}
