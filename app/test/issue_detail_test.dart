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
        ..status = 'OPEN'
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
              ..workOrders = ListBuilder<ReportWorkOrder>([
                ReportWorkOrder(
                  (w) => w
                    ..id = 9
                    ..status = 'ACCEPTED'
                    ..deadlineAt = DateTime.utc(2026, 7, 12)
                    ..completedAt = DateTime.utc(2026, 7, 11)
                    ..acceptedAt = DateTime.utc(2026, 7, 12)
                    ..canRate = canRate,
                ),
              ]),
          ),
        ]),
    );

class _FakeRepo implements ReportsRepository {
  _FakeRepo(this.detail);
  ReportDetail detail;
  final ratings = <(int, int, String)>[];

  @override
  Future<ReportDetail> fetchReport(int id) async => detail;

  @override
  Future<WorkRatingResult> rateWork(
      {required int workOrderId,
      required int score,
      String comment = ''}) async {
    ratings.add((workOrderId, score, comment));
    detail = _detail(canRate: false);
    return WorkRatingResult(
      (b) => b
        ..id = 1
        ..workOrderId = workOrderId
        ..score = score,
    );
  }

  @override
  Future<ReportSummary> createReport(
          {required String clientRef,
          required String text,
          required int locationId}) =>
      throw UnimplementedError();
  @override
  Future<List<Location>> fetchLocations() => throw UnimplementedError();
  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) =>
      throw UnimplementedError();
  @override
  Future<ReportPhoto> uploadPhoto(
          {required int reportId,
          required String path,
          required String filename}) =>
      throw UnimplementedError();
}

Future<void> _pump(WidgetTester tester, _FakeRepo repo) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [reportsRepositoryProvider.overrideWithValue(repo)],
    child: MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('vi'),
      home: const IssueDetailScreen(reportId: 42),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('renders the plain-language timeline in order', (tester) async {
    await _pump(tester, _FakeRepo(_detail(canRate: false)));
    // Submitted/completed lines include a local date suffix.
    expect(find.textContaining('Đã gửi phản ánh'), findsOneWidget);
    expect(find.text('Ban quản lý đã xem xét'), findsOneWidget);
    expect(find.textContaining('Đã ghép vào yêu cầu xử lý'), findsOneWidget);
    expect(find.textContaining('Đã nghiệm thu'), findsOneWidget);
    expect(find.textContaining('Công việc đã hoàn thành'), findsOneWidget);
    expect(find.text('Đánh giá công việc'), findsNothing);
  });

  testWidgets('rates eligible work with 1-5 and refreshes', (tester) async {
    final repo = _FakeRepo(_detail(canRate: true));
    await _pump(tester, repo);
    await tester.tap(find.text('Đánh giá công việc'));
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.star_border).at(3)); // 4 stars
    await tester.pump(); // rebuild so submit enables
    await tester.tap(find.text('Gửi đánh giá'));
    await tester.pumpAndSettle();

    expect(repo.ratings.single, (9, 4, ''));
    expect(find.text('Cảm ơn bạn đã đánh giá.'), findsOneWidget);
    expect(find.text('Đánh giá công việc'), findsNothing); // refreshed
  });
}
