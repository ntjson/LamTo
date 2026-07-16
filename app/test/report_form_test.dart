import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/occupancy.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/features/reports/report_draft.dart';
import 'package:lamto/features/reports/report_form_screen.dart';
import 'package:lamto/features/reports/report_submitter.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

ReportSummary _summary() => ReportSummary(
      (b) => b
        ..id = 42
        ..text = 'Leak'
        ..status = 'OPEN'
        ..locationPathSnapshot = 'B / Hall'
        ..createdAt = DateTime.utc(2026, 7, 17),
    );

class _FakeRepo implements ReportsRepository {
  final refs = <String>[];
  bool conflict = false;

  @override
  Future<ReportSummary> createReport(
      {required String clientRef,
      required String text,
      required int locationId}) async {
    refs.add(clientRef);
    if (conflict) {
      conflict = false;
      // Bubbles through ReportSubmitter (not a DioException) to the screen's
      // ReportConflictException handler; Dio 409 mapping is in submitter tests.
      throw ReportConflictException();
    }
    return _summary();
  }

  @override
  Future<List<Location>> fetchLocations() async => [];
  @override
  Future<ReportDetail> fetchReport(int id) => throw UnimplementedError();
  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) =>
      throw UnimplementedError();
  @override
  Future<WorkRatingResult> rateWork(
          {required int workOrderId, required int score, String comment = ''}) =>
      throw UnimplementedError();
  @override
  Future<ReportPhoto> uploadPhoto(
          {required int reportId,
          required String path,
          required String filename}) =>
      throw UnimplementedError();
}

Future<void> _pump(WidgetTester tester, _FakeRepo repo,
    {ReportDraft? existingDraft}) async {
  SharedPreferences.setMockInitialValues({});
  final drafts = ReportDraftStore();
  if (existingDraft != null) await drafts.write(7, existingDraft);
  final holder = OccupancyHolder()..occupancyId = 7;
  await tester.pumpWidget(ProviderScope(
    overrides: [
      reportsRepositoryProvider.overrideWithValue(repo),
      reportDraftStoreProvider.overrideWithValue(drafts),
      occupancyHolderProvider.overrideWithValue(holder),
    ],
    child: MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('vi'),
      home: const ReportFormScreen(),
    ),
  ));
  await tester.pumpAndSettle();
}

/// AppBar title and submit share the same VI string; target the button.
Finder get _sendButton =>
    find.widgetWithText(FilledButton, 'Gửi phản ánh');

void main() {
  setUp(() {
    // Isolate static write chains left by prior widget tests (fake-async).
    ReportDraftStore.debugResetWriteChains();
  });

  testWidgets('restores a persisted draft and submits it', (tester) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Thang máy kêu to',
      locationId: 3,
      locationLabel: 'Tòa A / Thang máy 2',
    );
    await _pump(tester, repo, existingDraft: draft);
    expect(find.text('Thang máy kêu to'), findsOneWidget); // restored

    await tester.tap(_sendButton);
    await tester.pumpAndSettle();
    expect(repo.refs.single, draft.clientRef); // draft's stable ref used
    expect(find.text('Phản ánh của bạn đã được ghi nhận.'), findsOneWidget);
  });

  testWidgets('missing fields blocks submit with doctrine copy',
      (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, repo);
    await tester.tap(_sendButton);
    await tester.pumpAndSettle();
    expect(repo.refs, isEmpty);
    expect(find.textContaining('Chưa có gì được gửi'), findsOneWidget);
  });

  testWidgets('409 shows conflict copy and mints a fresh ref', (tester) async {
    final repo = _FakeRepo()..conflict = true;
    final draft = ReportDraft.fresh()
        .copyWith(text: 'Sửa lại nội dung', locationId: 3);
    await _pump(tester, repo, existingDraft: draft);
    await tester.tap(_sendButton);
    await tester.pumpAndSettle();
    expect(find.textContaining('đã được gửi trước đó'), findsOneWidget);

    await tester.tap(_sendButton);
    await tester.pumpAndSettle();
    expect(repo.refs, hasLength(2));
    expect(repo.refs[0], isNot(repo.refs[1])); // new ref after conflict
  });

  // Amendment 11: committed-result — no whole-report resubmit after create.
  testWidgets('after success, form is committed-result (no second create)',
      (tester) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Thang máy kêu to',
      locationId: 3,
      locationLabel: 'Tòa A / Thang máy 2',
    );
    await _pump(tester, repo, existingDraft: draft);
    await tester.tap(_sendButton);
    await tester.pumpAndSettle();
    expect(find.text('Phản ánh của bạn đã được ghi nhận.'), findsOneWidget);
    // Primary send must not fire create again (title may still say form name).
    expect(_sendButton, findsNothing);
    expect(repo.refs, hasLength(1));
  });
}
