import 'dart:typed_data';

import 'package:built_collection/built_collection.dart';
import 'package:built_value/json_object.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/authenticated_image.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/features/reports/issue_detail_screen.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

ReportDetail _detail({
  required bool canRate,
  StatusEnum status = StatusEnum.SUBMITTED,
  String? declinedReason,
  MapBuilder<String, JsonObject?>? openInfoRequest,
  List<ReportWorkUpdate>? updates,
  bool completed = true,
}) => ReportDetail(
  (b) => b
    ..id = 42
    ..text = 'Thang máy kêu to'
    ..status = status
    ..declinedReason = declinedReason
    ..isPrivate = false
    ..locationPathSnapshot = 'Tòa A / Thang máy 2'
    ..unitLabel = 'B-1204'
    ..createdAt = DateTime.utc(2026, 7, 10)
    ..triageStatus = 'SUCCEEDED'
    ..category = 'Thang máy'
    ..openInfoRequest = openInfoRequest
    ..photos = ListBuilder<ReportPhoto>()
    ..cases = ListBuilder<ReportCase>([
      ReportCase(
        (c) => c
          ..id = 1
          ..category = 'Thang máy'
          ..urgency = 'HIGH'
          ..deadlineAt = DateTime.utc(2026, 7, 12)
          ..active = true
          ..completedAt = completed ? DateTime.utc(2026, 7, 11) : null
          ..updates = ListBuilder<ReportWorkUpdate>(updates ?? [_update(9)])
          ..canRate = canRate,
      ),
    ]),
);

ReportWorkUpdate _update(
  int id, {
  String? cause,
  String? result,
  bool withPhoto = false,
}) => ReportWorkUpdate(
  (u) => u
    ..id = id
    ..cause = cause ?? 'Cáp mòn $id'
    ..result = result ?? 'Đã cố định cáp $id'
    ..createdAt = DateTime.utc(2026, 7, 10 + id)
    ..photos = ListBuilder<ReportWorkUpdatePhoto>(
      withPhoto
          ? [
              ReportWorkUpdatePhoto(
                (p) => p
                  ..id = id
                  ..filename = 'update-$id.jpg'
                  ..kind = KindEnum.AFTER
                  ..downloadUrl = '/work-updates/$id/photo',
              ),
            ]
          : [],
    ),
);

MapBuilder<String, JsonObject?> _infoRequest([JsonObject? message]) =>
    MapBuilder<String, JsonObject?>({
      'id': JsonObject(7),
      'message': ?message,
      'created_at': JsonObject('2026-07-11T00:00:00Z'),
    });

class _FakeRepo implements ReportsRepository {
  _FakeRepo(this.detail);
  ReportDetail detail;
  final ratings = <(int, bool, String)>[];
  final replies = <(int, String)>[];
  int fetches = 0;

  @override
  Future<ReportDetail> fetchReport(int id) async {
    fetches++;
    return detail;
  }

  @override
  Future<void> replyInfo({required int reportId, required String text}) async {
    replies.add((reportId, text));
    detail = _detail(canRate: false, status: StatusEnum.IN_REVIEW);
  }

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
    bool isPrivate = false,
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

class _MissingImageAdapter implements HttpClientAdapter {
  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async => ResponseBody.fromString('', 404);
}

Future<void> _pump(WidgetTester tester, _FakeRepo repo) async {
  final dio = Dio(BaseOptions(baseUrl: 'http://test'))
    ..httpClientAdapter = _MissingImageAdapter();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        reportsRepositoryProvider.overrideWithValue(repo),
        dioProvider.overrideWith((ref) => dio),
      ],
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
  testWidgets('renders progress updates in order with causes and photos', (
    tester,
  ) async {
    await _pump(
      tester,
      _FakeRepo(
        _detail(
          canRate: false,
          updates: [_update(1, withPhoto: true), _update(2, withPhoto: true)],
        ),
      ),
    );

    expect(find.text('Tiến độ xử lý'), findsOneWidget);
    expect(find.text('Cáp mòn 1'), findsOneWidget);
    expect(find.text('Đã cố định cáp 1'), findsOneWidget);
    expect(find.text('Cáp mòn 2'), findsOneWidget);
    expect(find.text('Đã cố định cáp 2'), findsOneWidget);
    expect(find.byType(AuthenticatedImage), findsNWidgets(2));
    expect(
      tester.getTopLeft(find.text('Cáp mòn 1')).dy,
      lessThan(tester.getTopLeft(find.text('Cáp mòn 2')).dy),
    );
  });

  testWidgets('shows completion before the rating action', (tester) async {
    await _pump(tester, _FakeRepo(_detail(canRate: true)));

    expect(find.textContaining('Đã hoàn thành công việc'), findsOneWidget);
    expect(find.text('Đánh giá công việc'), findsOneWidget);
  });

  testWidgets('shows a quiet line when there are no progress updates', (
    tester,
  ) async {
    await _pump(
      tester,
      _FakeRepo(_detail(canRate: false, updates: [], completed: false)),
    );

    expect(find.text('Chưa có cập nhật tiến độ.'), findsOneWidget);
    expect(find.byType(Card), findsNothing);
  });

  testWidgets('shows a declined reason and hides rating', (tester) async {
    await _pump(
      tester,
      _FakeRepo(
        _detail(
          canRate: true,
          status: StatusEnum.DECLINED,
          declinedReason: 'Outside management responsibility',
        ),
      ),
    );

    expect(find.text('Ban quản lý quyết định không tiếp nhận'), findsOneWidget);
    expect(find.text('Outside management responsibility'), findsOneWidget);
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

  testWidgets('shows an open management information request', (tester) async {
    await _pump(
      tester,
      _FakeRepo(
        _detail(
          canRate: false,
          status: StatusEnum.NEEDS_INFO,
          openInfoRequest: _infoRequest(
            JsonObject('Please describe the kitchen issue'),
          ),
        ),
      ),
    );

    expect(find.text('Ban quản lý cần thêm thông tin'), findsOneWidget);
    expect(find.text('Please describe the kitchen issue'), findsOneWidget);
    expect(find.text('Gửi trả lời'), findsOneWidget);
  });

  testWidgets('submits an information reply and refreshes the detail', (
    tester,
  ) async {
    final repo = _FakeRepo(
      _detail(
        canRate: false,
        status: StatusEnum.NEEDS_INFO,
        openInfoRequest: _infoRequest(
          JsonObject('Please describe the kitchen issue'),
        ),
      ),
    );
    await _pump(tester, repo);
    await tester.tap(find.text('Gửi trả lời'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Kitchen tap');
    await tester.pump();
    await tester.tap(find.text('Gửi trả lời').last);
    await tester.pumpAndSettle();

    expect(repo.replies.single, (42, 'Kitchen tap'));
    expect(repo.fetches, 2);
    expect(find.text('Ban quản lý cần thêm thông tin'), findsNothing);
  });

  testWidgets('keeps information reply submit disabled for empty text', (
    tester,
  ) async {
    await _pump(
      tester,
      _FakeRepo(
        _detail(
          canRate: false,
          status: StatusEnum.NEEDS_INFO,
          openInfoRequest: _infoRequest(
            JsonObject('Please describe the kitchen issue'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Gửi trả lời'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '   ');
    await tester.pump();

    final submit = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Gửi trả lời').last,
    );
    expect(submit.onPressed, isNull);
  });

  testWidgets('ignores malformed open information request messages', (
    tester,
  ) async {
    for (final request in [
      _infoRequest(),
      MapBuilder<String, JsonObject?>({'message': null}),
      _infoRequest(JsonObject(7)),
    ]) {
      await _pump(
        tester,
        _FakeRepo(
          _detail(
            canRate: false,
            status: StatusEnum.NEEDS_INFO,
            openInfoRequest: request,
          ),
        ),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Ban quản lý cần thêm thông tin'), findsNothing);
    }
  });
}
