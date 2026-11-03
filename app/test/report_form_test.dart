@Tags(['web'])
library;

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/occupancy.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/features/reports/photo_thumbnail.dart';
import 'package:lamto/features/reports/report_draft.dart';
import 'package:lamto/features/reports/report_form_screen.dart';
import 'package:lamto/features/reports/report_photo.dart';
import 'package:lamto/features/reports/report_submitter.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/features/push/push_token_source.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto/theme.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'report_photo_fakes.dart';

ReportSummary _summary() => ReportSummary(
  (b) => b
    ..id = 42
    ..text = 'Leak'
    ..status = StatusEnum.SUBMITTED
    ..isPrivate = false
    ..locationPathSnapshot = 'B / Hall'
    ..createdAt = DateTime.utc(2026, 7, 17),
);

class _FakeRepo implements ReportsRepository {
  final refs = <String>[];
  final privateValues = <bool>[];
  final uploads = <(int, PhotoFormat, Uint8List)>[];
  bool conflict = false;
  Completer<ReportSummary>? createCompleter;

  @override
  Future<ReportSummary> createReport({
    required String clientRef,
    required String text,
    required int locationId,
    bool isPrivate = false,
  }) async {
    refs.add(clientRef);
    privateValues.add(isPrivate);
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
  Future<CaseRatingResult> rateCase({
    required int caseId,
    required bool satisfied,
    String comment = '',
  }) => throw UnimplementedError();
  @override
  Future<void> replyInfo({required int reportId, required String text}) =>
      throw UnimplementedError();
  @override
  Future<ReportPhoto> uploadPhoto({
    required int reportId,
    required Uint8List bytes,
    required PhotoFormat format,
  }) async {
    uploads.add((reportId, format, bytes));
    return ReportPhoto(
      (b) => b
        ..id = uploads.length
        ..filename = 'photo${uploads.length}'
        ..sha256 = 'aa'
        ..downloadUrl = '/photos/${uploads.length}',
    );
  }
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
  FakeImagePicker? picker,
  FakePhotoFileStore? fileStore,
  ReportsRepository? repository,
  bool reload = false,
}) async {
  // A reload keeps what the app stored (prefs) and drops everything held in
  // memory: the widget tree is replaced and the draft is read back.
  if (reload) {
    await tester.pumpWidget(const SizedBox());
  } else {
    SharedPreferences.setMockInitialValues({});
  }
  final drafts = ReportDraftStore();
  if (existingDraft != null) await drafts.write(7, existingDraft);
  final holder = OccupancyHolder()..occupancyId = 7;
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        reportsRepositoryProvider.overrideWithValue(repository ?? repo),
        reportDraftStoreProvider.overrideWithValue(drafts),
        reportPhotoFileStoreProvider.overrideWithValue(
          fileStore ?? FakePhotoFileStore(),
        ),
        imagePickerProvider.overrideWithValue(
          picker ?? FakeImagePicker(const []),
        ),
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

/// Fake HTTP adapter: answers the two calls a submit makes and keeps the photo
/// part's body exactly as it would go over the wire.
class _CapturingAdapter implements HttpClientAdapter {
  String? photoPath;
  String photoBody = '';

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final Map<String, Object?> json;
    if (options.path.endsWith('/photos')) {
      photoPath = options.path;
      final chunks = await requestStream!.toList();
      photoBody = latin1.decode([for (final chunk in chunks) ...chunk]);
      json = {
        'id': 1,
        'filename': 'photo.png',
        'sha256': 'aa',
        'download_url': '/api/v1/documents/tok',
      };
    } else {
      json = {
        'id': 42,
        'text': 'Rò nước',
        'status': 'SUBMITTED',
        'is_private': false,
        'location_path_snapshot': 'B / Hall',
        'created_at': '2026-07-17T00:00:00Z',
      };
    }
    return ResponseBody.fromString(
      jsonEncode(json),
      201,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }
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

  testWidgets('draft photos render as thumbnails with working delete', (
    tester,
  ) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Rò nước',
      photoPaths: ['/owned/report_7/a.jpg', '/owned/report_7/b.jpg'],
    );
    // The app-owned copies that survived a restart; thumbnails read them back.
    final fileStore = FakePhotoFileStore()
      ..files['/owned/report_7/a.jpg'] = PickedPhoto(
        jpegBytes,
        PhotoFormat.jpeg,
      )
      ..files['/owned/report_7/b.jpg'] = PickedPhoto(
        jpegBytes,
        PhotoFormat.jpeg,
      );
    await _pump(tester, repo, existingDraft: draft, fileStore: fileStore);

    expect(find.byType(PhotoThumbnail), findsNWidgets(2));
    expect(find.text('a.jpg'), findsNothing); // no minted filenames

    await tester.tap(find.byIcon(Icons.close).first);
    await tester.pump();
    expect(find.byType(PhotoThumbnail), findsOneWidget);
  });

  testWidgets(
    'a draft restored after a reload keeps its text; only native keeps its '
    'photos',
    (tester) async {
      final repo = _FakeRepo();
      final fileStore = FakePhotoFileStore();
      final picker = FakeImagePicker([pickedFile(jpegBytes)]);
      await _pump(tester, repo, picker: picker, fileStore: fileStore);

      await tester.enterText(find.byType(TextField), 'Rò nước tầng 3');
      await tester.pump(const Duration(milliseconds: 400)); // autosave
      await tester.tap(find.text('Thêm ảnh'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Chọn từ thư viện'));
      await tester.pumpAndSettle();
      expect(find.byType(PhotoThumbnail), findsOneWidget);

      await _pump(
        tester,
        repo,
        picker: picker,
        fileStore: fileStore,
        reload: true,
      );

      expect(find.text('Rò nước tầng 3'), findsOneWidget);
      // On the web a photo exists only in memory (ADR 0009), so the reload
      // drops it quietly; native restores it from its app-owned copy.
      expect(
        find.byType(PhotoThumbnail),
        kIsWeb ? findsNothing : findsOneWidget,
      );
      expect(find.byType(StatusNotice), findsNothing);
    },
  );

  Future<void> addPhotoFromGallery(WidgetTester tester) async {
    await tester.ensureVisible(find.text('Thêm ảnh'));
    await tester.tap(find.text('Thêm ảnh'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Chọn từ thư viện'));
    await tester.pumpAndSettle();
  }

  testWidgets('a picked PNG with no extension is sent as image/png bytes', (
    tester,
  ) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Rò nước',
      locationId: 3,
      locationLabel: 'Tòa A / Thang máy 2',
    );
    await _pump(
      tester,
      repo,
      existingDraft: draft,
      picker: FakeImagePicker([pickedFile(pngBytes)]),
    );

    await addPhotoFromGallery(tester);
    expect(find.byType(PhotoThumbnail), findsOneWidget);

    await tester.ensureVisible(_sendButton);
    await tester.tap(_sendButton);
    await tester.pumpAndSettle();

    expect(repo.uploads.single, (42, PhotoFormat.png, pngBytes));
    expect(find.text('Phản ánh của bạn đã được ghi nhận.'), findsOneWidget);
  });

  testWidgets(
    'the multipart request carries the bytes, image/png for an extensionless '
    'PNG',
    (tester) async {
      // The real repository over a fake HTTP adapter: what goes on the wire.
      final adapter = _CapturingAdapter();
      final repo = DioReportsRepository(
        Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = adapter,
      );
      final draft = ReportDraft.fresh().copyWith(
        text: 'Rò nước',
        locationId: 3,
      );
      await _pump(
        tester,
        _FakeRepo(),
        existingDraft: draft,
        picker: FakeImagePicker([pickedFile(pngBytes)]),
        repository: repo,
      );

      await addPhotoFromGallery(tester);
      await tester.ensureVisible(_sendButton);
      await tester.tap(_sendButton);
      await tester.pumpAndSettle();

      expect(adapter.photoPath, '/api/v1/reports/42/photos');
      final wire = adapter.photoBody;
      expect(wire.toLowerCase(), contains('content-type: image/png'));
      expect(wire.toLowerCase(), isNot(contains('image/jpeg')));
      expect(wire, contains(latin1.decode(pngBytes)));
      expect(find.text('Phản ánh của bạn đã được ghi nhận.'), findsOneWidget);
    },
    // Real Dio inside a widget test never completes on the web: its response
    // waits on a timer the fake clock does not drive. The same multipart
    // request is checked on the web by reports_repository_test.dart.
    skip: kIsWeb,
  );

  testWidgets('a picked JPEG is sent as image/jpeg bytes', (tester) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(text: 'Rò nước', locationId: 3);
    await _pump(
      tester,
      repo,
      existingDraft: draft,
      picker: FakeImagePicker([pickedFile(jpegBytes, name: 'IMG_1.heic')]),
    );

    await addPhotoFromGallery(tester);
    await tester.ensureVisible(_sendButton);
    await tester.tap(_sendButton);
    await tester.pumpAndSettle();

    expect(repo.uploads.single, (42, PhotoFormat.jpeg, jpegBytes));
  });

  testWidgets('a photo that is not a JPEG or PNG is refused and never sent', (
    tester,
  ) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(text: 'Rò nước', locationId: 3);
    final fileStore = FakePhotoFileStore();
    await _pump(
      tester,
      repo,
      existingDraft: draft,
      // A .jpg name on GIF bytes: the filename must not decide.
      picker: FakeImagePicker([pickedFile(gifBytes, name: 'leak.jpg')]),
      fileStore: fileStore,
    );

    await addPhotoFromGallery(tester);

    expect(
      find.textContaining('Chỉ gửi được ảnh JPEG hoặc PNG'),
      findsOneWidget,
    );
    expect(find.byType(PhotoThumbnail), findsNothing);
    expect(fileStore.files, isEmpty);

    await tester.ensureVisible(_sendButton);
    await tester.tap(_sendButton);
    await tester.pumpAndSettle();
    expect(repo.uploads, isEmpty);
  });

  testWidgets('submits a private report when the switch is enabled', (
    tester,
  ) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Thang máy kêu to',
      locationId: 3,
      locationLabel: 'Tòa A / Thang máy 2',
    );
    await _pump(tester, repo, existingDraft: draft);

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    await tester.tap(_sendButton);
    await tester.pumpAndSettle();

    expect(repo.privateValues.single, isTrue);
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

  testWidgets('submit shows a busy spinner without a size jump', (
    tester,
  ) async {
    final repo = _FakeRepo()..createCompleter = Completer<ReportSummary>();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Rò nước',
      locationId: 3,
      locationLabel: 'Tòa A / Sảnh',
    );
    await _pump(tester, repo, existingDraft: draft);

    final idle = tester.getSize(_sendButton);
    await tester.tap(_sendButton);
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    // Stable geometry while busy; the action stays inert until it resolves.
    expect(tester.getSize(_sendButton), idle);
    expect(tester.widget<FilledButton>(_sendButton).onPressed, isNull);

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

  testWidgets('push consent waits for the receipt action, on native only', (
    tester,
  ) async {
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

    if (kIsWeb) {
      // The web has no push (ADR 0009): nothing offers it, nothing prompts.
      expect(find.text('Nhận thông báo cập nhật'), findsNothing);
      return;
    }
    await tester.tap(find.text('Nhận thông báo cập nhật'));
    await tester.pumpAndSettle();
    expect(push.requestCount, 1);
  });
}
