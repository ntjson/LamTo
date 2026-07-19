import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/occupancy.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/features/reports/report_draft.dart';
import 'package:lamto/features/reports/report_form_screen.dart';
import 'package:lamto/features/reports/report_submitter.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/features/push/push_token_source.dart';
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
  Completer<ReportSummary>? createCompleter;

  @override
  Future<ReportSummary> createReport({
    required String clientRef,
    required String text,
    required int locationId,
  }) async {
    refs.add(clientRef);
    if (conflict) {
      conflict = false;
      // Bubbles through ReportSubmitter (not a DioException) to the screen's
      // ReportConflictException handler; Dio 409 mapping is in submitter tests.
      throw ReportConflictException();
    }
    final pending = createCompleter;
    if (pending != null) return pending.future;
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
  Future<WorkRatingResult> rateWork({
    required int workOrderId,
    required int score,
    String comment = '',
  }) => throw UnimplementedError();
  @override
  Future<ReportPhoto> uploadPhoto({
    required int reportId,
    required String path,
    required String filename,
  }) => throw UnimplementedError();
}

class _FakePushSource implements PushTokenSource {
  int requestCount = 0;

  @override
  Future<PushPermissionResult> requestPermission() async {
    requestCount++;
    return PushPermissionResult.denied;
  }

  @override
  Future<String?> getToken() async => null;

  @override
  Stream<String> get onTokenRefresh => const Stream.empty();

  @override
  Future<Map<String, String>?> initialMessageData() async => null;

  @override
  Stream<Map<String, String>> get onMessageOpened => const Stream.empty();
}

Future<void> _pump(
  WidgetTester tester,
  _FakeRepo repo, {
  ReportDraft? existingDraft,
  _FakePushSource? pushSource,
}) async {
  SharedPreferences.setMockInitialValues({});
  final drafts = ReportDraftStore();
  if (existingDraft != null) await drafts.write(7, existingDraft);
  final holder = OccupancyHolder()..occupancyId = 7;
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        reportsRepositoryProvider.overrideWithValue(repo),
        reportDraftStoreProvider.overrideWithValue(drafts),
        occupancyHolderProvider.overrideWithValue(holder),
        if (pushSource != null)
          pushTokenSourceProvider.overrideWithValue(pushSource),
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const ReportFormScreen(),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

/// AppBar title and submit share the same VI string; target the button.
Finder get _sendButton => find.widgetWithText(FilledButton, 'Gửi phản ánh');

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

  testWidgets('missing fields blocks submit with doctrine copy', (
    tester,
  ) async {
    final repo = _FakeRepo();
    await _pump(tester, repo);
    await tester.tap(_sendButton);
    await tester.pumpAndSettle();
    expect(repo.refs, isEmpty);
    expect(find.textContaining('Chưa có gì được gửi'), findsOneWidget);
  });

  testWidgets('announces draft saving and saved states', (tester) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Rò nước',
      locationId: 3,
      locationLabel: 'Tòa A / Sảnh',
    );
    await _pump(tester, repo, existingDraft: draft);

    await tester.enterText(find.byType(TextField).first, 'Rò nước nhiều hơn');
    await tester.pump();
    expect(find.text('Đang lưu bản nháp…'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpAndSettle();
    expect(find.text('Đã lưu bản nháp'), findsOneWidget);
  });

  testWidgets('submit action shows progress copy', (tester) async {
    final repo = _FakeRepo()..createCompleter = Completer<ReportSummary>();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Rò nước',
      locationId: 3,
      locationLabel: 'Tòa A / Sảnh',
    );
    await _pump(tester, repo, existingDraft: draft);

    await tester.tap(_sendButton);
    await tester.pump();
    expect(find.text('Đang gửi…'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    repo.createCompleter!.complete(_summary());
    await tester.pumpAndSettle();
  });

  testWidgets('409 shows conflict copy and mints a fresh ref', (tester) async {
    final repo = _FakeRepo()..conflict = true;
    final draft = ReportDraft.fresh().copyWith(
      text: 'Sửa lại nội dung',
      locationId: 3,
    );
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
  testWidgets('after success, form is committed-result (no second create)', (
    tester,
  ) async {
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

  testWidgets('push consent waits for the receipt action', (tester) async {
    final repo = _FakeRepo();
    final push = _FakePushSource();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Thang máy kêu to',
      locationId: 3,
      locationLabel: 'Tòa A / Thang máy 2',
    );
    await _pump(tester, repo, existingDraft: draft, pushSource: push);

    await tester.tap(_sendButton);
    await tester.pumpAndSettle();
    expect(find.text('Phản ánh của bạn đã được ghi nhận.'), findsOneWidget);
    expect(push.requestCount, 0);

    await tester.tap(find.text('Nhận thông báo cập nhật'));
    await tester.pumpAndSettle();
    expect(push.requestCount, 1);
  });
}
