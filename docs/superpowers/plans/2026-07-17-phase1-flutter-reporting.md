# Flutter Resident App — Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reporting slice of the Flutter resident app (spec §6.3 items 4–5): the Report-issue screen (location picker, ≤5 compressed photos, `client_ref` idempotent submit, persistent local draft), the My-issues list, the issue-detail timeline, and rate-work — wired into the existing tab shell.

**Architecture:** Extends the merged Foundation app (`app/`) in place, plan 2 of 3 for §6. Repositories mirror the as-built `DioAuthRepository` pattern: thin wrappers over the **generated** `ReportsApi`/`LocationsApi`/`WorkApi` classes on the shared interceptor-configured `Dio` (token + `X-LamTo-Occupancy` are attached automatically — `/api/v1/reports` and `/api/v1/locations` are already in `buildingScopedPathPrefixes`). Submit logic lives in a pure-Dart `ReportSubmitter` (unit-testable without widgets): text commits first under a draft-stable `client_ref`, then photos upload individually with per-photo retry. The draft (text + location + `client_ref` + photo paths) persists in `SharedPreferences` keyed by occupancy, mirroring `OccupancyStore`.

**Tech Stack:** Existing foundation (Flutter, Riverpod 3, dio 5, generated `lamto_api`, `shared_preferences`, gen-l10n) + `image_picker` (its native `maxWidth`/`maxHeight`/`imageQuality` do the §6.3 resize-to-2048 + JPEG re-encode on iOS/Android — no separate compression package).

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md` and `DESIGN.md`):

- **§6.3(4) Report issue:** required text; location picker from `GET /locations` (tree, large rows); up to 5 photos (camera/gallery) with client-side compression (**max edge 2048px, JPEG**) before multipart upload. **Text submits first with `client_ref`; photos upload individually with per-photo retry. Local draft persists across app kill.** No other offline behavior (P1: no offline sync).
- **§6.3(5) My issues:** list + detail timeline: submitted → triage → grouped-into-case notice → work status/deadline → completion evidence → rate work (1–5).
- **§6.5 Widget tests:** report submission **including `client_ref` retry → 200 and conflict → 409**.
- **§3.5:** first submission → 201; retry with same `(user, client_ref)` and identical content → 200 (existing report); same `client_ref` with different content → 409 `client_ref_conflict`. A dropped upload never loses the report text.
- **§6.2/§6.4:** all user-facing copy in ARB files keyed off API `code`s; **no raw HTTP jargon**; failure doctrine = what happened, whether data was saved, next safe action. System font scaling, **≥44pt/48dp touch targets**, one primary action per screen, no gesture-only affordances.
- **`DESIGN.md`:** semantic status colors always paired with text/icon; plain language before technical detail; platform list rows over nested card stacks; Accountability Indigo ≤10% of any screen.
- **As-built contracts to honor:** feature providers caching occupancy-scoped data MUST `ref.watch(occupancyScopedProviders)` (documented in `app/lib/core/providers.dart`); repositories declare their path constants and get contract tests against `docs/api/openapi-v1.yaml` (pattern: `app/test/auth_repository_contract_test.dart`).

## Verified environment

App commands run from `app/`:

```bash
cd app && flutter pub get
flutter test                   # all widget/unit tests
flutter gen-l10n               # after editing lib/l10n/*.arb
# manual run against a local backend (compose up at repo root):
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

Generated API surface this plan consumes (from `app/packages/lamto_api`, regenerated only if the schema changes — it does not in this plan):

- `ReportsApi.reportsCreate({required ReportCreateRequest reportCreateRequest})` → `Response<ReportSummary>` (201 created / 200 idempotent replay; 409 problem+json on conflict)
- `ReportsApi.reportsList({String? cursor})` → `Response<PaginatedReportSummaryList>` (`next`/`previous` URLs, `results`)
- `ReportsApi.reportsRetrieve({required int id})` → `Response<ReportDetail>`
- `ReportsApi.reportsPhotosCreate({required int id, required MultipartFile photo})` → `Response<ReportPhoto>`
- `LocationsApi.locationsRetrieve()` → `Response<BuiltList<Location>>` (`id`, `name`, `parentId?`)
- `WorkApi.workRatingCreate({required int id, required WorkRatingRequest workRatingRequest})` → `Response<WorkRatingResult>` (`score` 1–5, `comment?` ≤500)
- Models: `ReportSummary(id, text, status, locationPathSnapshot, createdAt)`; `ReportDetail(+ unitLabel, triageStatus?, category?, photos: BuiltList<ReportPhoto>, cases: BuiltList<ReportCase>)`; `ReportPhoto(id, filename, sha256, downloadUrl)`; `ReportCase(id, category, urgency, deadlineAt, active, workOrders)`; `ReportWorkOrder(id, status, deadlineAt, canRate, completedAt?, acceptedAt?)`.

## Design decisions

1. **No compression dependency.** `image_picker`'s `pickImage/pickMultiImage(maxWidth: 2048, maxHeight: 2048, imageQuality: 85)` performs native proportional downscale + re-encode on iOS and Android (its documented limitations for those params apply only to web GIFs and desktop platforms). Camera shots and processed gallery picks come out JPEG; a rare pass-through PNG is still ≤2048 and the server accepts `image/png` for report photos.
2. **`client_ref` is born with the draft, not the submit.** A UUID v4 (stdlib `Random.secure()`, ~12 lines — no `uuid` package) is generated when a draft is first created and persisted with it, so kill/retry/resubmit all reuse the same ref (§3.5). On 409 the app tells the resident the report was already submitted and mints a fresh ref for the now-different draft.
3. **Draft keyed by occupancy id.** A report belongs to the selected occupancy's unit, and `location_id` is building-scoped — so the draft key is `lamto_report_draft_<occupancyId>`, exactly parallel to `OccupancyStore`. Switching occupancy switches drafts.
4. **Submit logic is a pure service.** `ReportSubmitter` (repo + draft store injected) owns the §3.5 choreography and per-photo statuses; screens stay thin. The §6.5-mandated retry/conflict tests run at this level plus one widget-level submit test.
5. **Photos render through the authenticated client.** `downloadUrl` is a short-TTL signed relative URL; `Image.network` can't attach the knox header, so an `AuthenticatedImage` widget fetches bytes via the shared `Dio` and shows `Image.memory` (placeholder/error states included).
6. **Failed photo uploads are retryable in-session only.** After the text commits, the draft is cleared (the report can never be lost); failed photos keep retry buttons until the user leaves the result screen. A later "add photos from detail" flow is out of scope — §6.3 asks for per-photo retry at submission.

### Amendments (Plan 8 clarifications — 2026-07-17)

These bind Tasks 1–7. Implement and test them; do not treat the older draft code samples as superseding these rules.

7. **Draft privacy boundary.** Report drafts may hold resident issue text, location labels, and photo paths. **Clear all drafts on logout / logout-all** (`SessionController.signOut` and any bulk session wipe). Persistence uses app-private `SharedPreferences` (iOS/Android sandbox — not world-readable by other apps). **Do not rely on encryption for this slice;** document the boundary in `ReportDraftStore` dartdoc and **test** (a) clear-on-logout hooks wipe every `lamto_report_draft_*` key, and (b) the store only writes under the `lamto_report_draft_` prefix (privacy-boundary structural test). Full-disk encryption of prefs is out of scope.

8. **App-owned photo copies for kill-safe drafts.** Picker/cache paths alone do **not** satisfy app-kill persistence. Before adding a path to the draft, **copy** the selected image into app-owned durable storage (`path_provider` application documents dir under `report_draft_photos/<occupancyId>/`). Store only those owned paths. **Delete** owned files when: photo removed from draft, draft cleared after text commit, conflict remints a draft that drops photos, draft abandoned/cleared on logout, or form reset after success. `ReportPhotoFileStore` (or methods on the draft store) owns copy + delete; unit-test copy + cleanup.

9. **Serialized / debounced draft writes.** Per-keystroke autosave must not complete out of order. `ReportDraftStore.write` (or a thin `ReportDraftAutosave` wrapper) **serializes writes per occupancy** (chain `Future`s: each write awaits the previous) and may debounce UI-triggered saves (~300ms). Tests: concurrent/out-of-order write calls leave the store with the **last** intended draft, not a stale intermediate.

10. **Photo retry idempotency (checksum-based backend dedup + client attachment id).** OpenAPI photo upload has no client attachment field today. **Choice: checksum-based backend deduplication** — `attach_report_photo` / `ReportPhotoUploadView` compute content SHA-256; if the report already has a photo with that hash, return the existing row with **HTTP 200** (no second `ReportPhoto` row). Client also stamps each local photo with a stable `clientAttachmentId` (uuid) for in-session identity and skips re-upload when status is already `uploaded`. A lost successful upload response must not create duplicate rows on retry. Small backend + OpenAPI response doc update allowed; avoid regenerating `lamto_api` if the generated client already accepts 2xx. Tests: backend/API test for same-bytes replay → 200 + count stays 1; Flutter submitter test for double `retryPhoto` without double `uploadPhoto` when first succeeded; optional adapter mock if path stays in client.

11. **Committed-result form state.** Once `createReport` succeeds and a `reportId` exists, the form **must not** allow whole-report resubmission. Transition to a **committed-result** UI: success/partial-photo copy, per-failed-photo retry only, and navigation to issue detail. Disable/hide the primary Send control. Draft is already cleared on text commit (Task 3). Widget test: after successful create, tapping Send again (if still visible) must not call `createReport` a second time — prefer asserting Send is absent/disabled and only photo-retry / view-detail remain.

12. **My Issues scope = user-global.** Backend `resident_reports(user)` lists all reports the authenticated user submitted (not filtered by selected occupancy). **Decision: user-global.** Align:
    - **API:** list endpoint remains reporter-scoped (no occupancy filter).
    - **Provider:** `myReportsProvider` rebuilds on auth/session identity; may still `ref.watch(occupancyScopedProviders)` only if harmless refresh is desired — **do not** present the list as unit-scoped. Invalidate/refresh after a successful report create so the new issue appears.
    - **UI wording:** keep "My issues" / "Việc của tôi" (user-framed). Empty state already user-global. Do not add "this unit only" copy.
    - Document in `my_issues_screen.dart` dartdoc.

13. **Adapter-level HTTP 200 idempotent create replay.** In `reports_repository_test.dart` (real `DioReportsRepository` + mock `HttpClientAdapter`), assert: first `createReport` → 201; second call with the **same** `client_ref`/text/location and adapter returning **HTTP 200** with the same summary body → parsed `ReportSummary` with the same `id`. Do **not** rely only on a fake repository returning the same model.

## File Structure

**Create:**
- `app/lib/core/uuid.dart` — `uuidV4()`.
- `app/lib/features/reports/report_draft.dart` — `ReportDraft` + `ReportDraftStore` (serialized writes, clearAll, privacy docs).
- `app/lib/features/reports/report_photo_files.dart` — app-owned photo copy/cleanup.
- `app/lib/features/reports/reports_repository.dart` — repos + Riverpod providers.
- `app/lib/features/reports/report_submitter.dart` — submit choreography + photo statuses + attachment ids.
- `app/lib/features/reports/location_picker_screen.dart`
- `app/lib/features/reports/report_form_screen.dart` — includes committed-result state machine.
- `app/lib/features/reports/my_issues_screen.dart` — user-global list (documented).
- `app/lib/features/reports/issue_detail_screen.dart` (includes the rate-work sheet)
- `app/lib/core/authenticated_image.dart`
- Backend (amendment 10): small change in `src/lamto/maintenance/reporting.py` + `ReportPhotoUploadView` for sha256 dedup → 200; OpenAPI response note; API test.
- Tests: `app/test/uuid_test.dart`, `report_draft_test.dart`, `reports_repository_contract_test.dart`, `reports_repository_test.dart` (incl. HTTP 200 create replay), `report_submitter_test.dart`, `location_picker_test.dart`, `report_form_test.dart` (incl. committed-result), `my_issues_test.dart`, `issue_detail_test.dart`.

**Modify:**
- `app/lib/features/shell/home_shell.dart` — Report + Issues tab bodies.
- `app/lib/features/auth/session_controller.dart` — clear report drafts (+ photo files) on `signOut`.
- `app/lib/l10n/app_en.arb`, `app_vi.arb` — each screen task adds its keys.
- `app/pubspec.yaml` — `image_picker` + `path_provider` (Task 5 / Task 1 photo store as needed).

---

### Task 1: UUID v4 + persistent report draft

**Files:**
- Create: `app/lib/core/uuid.dart`, `app/lib/features/reports/report_draft.dart`, `app/lib/features/reports/report_photo_files.dart`
- Modify (logout hook may land here or Task 5): `app/lib/features/auth/session_controller.dart` — call `ReportDraftStore.clearAll` + photo cleanup on `signOut`
- Test: `app/test/uuid_test.dart`, `app/test/report_draft_test.dart`
- Deps: add `path_provider` if not present (for app-owned photo dir).

**Interfaces:**
- Produces:
  - `uuidV4() -> String` — RFC 4122 v4 from `Random.secure()`.
  - `ReportDraft(clientRef, text, locationId, locationLabel, photoPaths)` — immutable-ish data class with `copyWith`, `toJson`/`fromJson`; `ReportDraft.fresh()` mints a new `clientRef`. Photo paths are **app-owned** paths only (amendment 8).
  - `ReportDraftStore` — `Future<ReportDraft?> read(int occupancyId)`, `Future<void> write(int occupancyId, ReportDraft draft)` (**serialized per occupancy**, amendment 9), `Future<void> clear(int occupancyId)`, `Future<void> clearAll()` (amendment 7 — logout).
  - `ReportPhotoFileStore` — `Future<String> importPickerPath({required int occupancyId, required String sourcePath})` copies into app documents; `Future<void> deletePaths(Iterable<String> paths)`; `Future<void> clearOccupancy(int occupancyId)`; `Future<void> clearAll()`.
- Privacy (amendment 7): document app-private SharedPreferences boundary in dartdoc; clearAll on logout.

- [ ] **Step 1: Write the failing tests**

Create `app/test/uuid_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/uuid.dart';

void main() {
  test('uuidV4 shape, version, variant, uniqueness', () {
    final re = RegExp(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$');
    final seen = <String>{};
    for (var i = 0; i < 200; i++) {
      final id = uuidV4();
      expect(re.hasMatch(id), isTrue, reason: id);
      expect(seen.add(id), isTrue);
    }
  });
}
```

Create `app/test/report_draft_test.dart` covering round-trip, clearAll privacy, and write serialization:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/report_draft.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('round-trips a draft per occupancy and clears it', () async {
    SharedPreferences.setMockInitialValues({});
    final store = ReportDraftStore();
    expect(await store.read(7), isNull);

    final draft = ReportDraft.fresh().copyWith(
      text: 'Thang máy kêu to',
      locationId: 3,
      locationLabel: 'Tòa A / Thang máy 2',
      photoPaths: ['/tmp/a.jpg'],
    );
    await store.write(7, draft);

    final loaded = await store.read(7);
    expect(loaded!.clientRef, draft.clientRef);
    expect(loaded.text, 'Thang máy kêu to');
    expect(loaded.locationId, 3);
    expect(loaded.photoPaths, ['/tmp/a.jpg']);
    // A different occupancy has no draft.
    expect(await store.read(8), isNull);

    await store.clear(7);
    expect(await store.read(7), isNull);
  });

  test('fresh drafts mint distinct clientRefs', () {
    expect(ReportDraft.fresh().clientRef,
        isNot(ReportDraft.fresh().clientRef));
  });

  test('clearAll removes every occupancy draft (logout privacy)', () async {
    SharedPreferences.setMockInitialValues({});
    final store = ReportDraftStore();
    await store.write(1, ReportDraft.fresh().copyWith(text: 'a'));
    await store.write(2, ReportDraft.fresh().copyWith(text: 'b'));
    await store.clearAll();
    expect(await store.read(1), isNull);
    expect(await store.read(2), isNull);
  });

  test('serialized writes preserve last draft under concurrent autosave',
      () async {
    SharedPreferences.setMockInitialValues({});
    final store = ReportDraftStore();
    final base = ReportDraft.fresh();
    // Fire writes without awaiting between starts; store must serialize.
    final f1 = store.write(7, base.copyWith(text: 'one'));
    final f2 = store.write(7, base.copyWith(text: 'two'));
    final f3 = store.write(7, base.copyWith(text: 'three'));
    await Future.wait([f1, f2, f3]);
    expect((await store.read(7))!.text, 'three');
  });
}
```

Also add unit tests for `ReportPhotoFileStore` (temp dir injection): copy creates a file under the owned root; deletePaths removes it; clearOccupancy removes only that occupancy's copies.

- [ ] **Step 2: Run to verify they fail**

Run: `cd app && flutter test test/uuid_test.dart test/report_draft_test.dart`
Expected: FAIL — `core/uuid.dart` and `features/reports/report_draft.dart` do not exist.

- [ ] **Step 3: Implement**

Create `app/lib/core/uuid.dart`:

```dart
import 'dart:math';

/// RFC 4122 v4 UUID from the platform CSPRNG. client_ref must be stable per
/// draft and unique per user (spec 3.5); stdlib keeps it dependency-free.
String uuidV4() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
  final hex =
      bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}
```

Create `app/lib/features/reports/report_draft.dart`:

```dart
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/uuid.dart';

/// A report draft persists across app kill (spec 6.3): text, location,
/// attached photo paths, and the client_ref minted when the draft was born
/// so retries stay idempotent (spec 3.5).
class ReportDraft {
  const ReportDraft({
    required this.clientRef,
    this.text = '',
    this.locationId,
    this.locationLabel = '',
    this.photoPaths = const [],
  });

  factory ReportDraft.fresh() => ReportDraft(clientRef: uuidV4());

  final String clientRef;
  final String text;
  final int? locationId;
  final String locationLabel;
  final List<String> photoPaths;

  bool get isEmpty => text.isEmpty && locationId == null && photoPaths.isEmpty;

  ReportDraft copyWith({
    String? clientRef,
    String? text,
    int? locationId,
    String? locationLabel,
    List<String>? photoPaths,
  }) {
    return ReportDraft(
      clientRef: clientRef ?? this.clientRef,
      text: text ?? this.text,
      locationId: locationId ?? this.locationId,
      locationLabel: locationLabel ?? this.locationLabel,
      photoPaths: photoPaths ?? this.photoPaths,
    );
  }

  Map<String, dynamic> toJson() => {
        'client_ref': clientRef,
        'text': text,
        'location_id': locationId,
        'location_label': locationLabel,
        'photo_paths': photoPaths,
      };

  factory ReportDraft.fromJson(Map<String, dynamic> json) => ReportDraft(
        clientRef: json['client_ref'] as String,
        text: (json['text'] as String?) ?? '',
        locationId: json['location_id'] as int?,
        locationLabel: (json['location_label'] as String?) ?? '',
        photoPaths:
            ((json['photo_paths'] as List?) ?? const []).cast<String>(),
      );
}

/// Draft persistence keyed by occupancy id (a report belongs to the selected
/// occupancy's unit; locations are building-scoped). Mirrors OccupancyStore.
class ReportDraftStore {
  ReportDraftStore([SharedPreferences? prefs]) : _prefsOverride = prefs;

  final SharedPreferences? _prefsOverride;
  static const _prefix = 'lamto_report_draft_';

  Future<SharedPreferences> get _prefs async =>
      _prefsOverride ?? await SharedPreferences.getInstance();

  String _key(int occupancyId) => '$_prefix$occupancyId';

  Future<ReportDraft?> read(int occupancyId) async {
    final raw = (await _prefs).getString(_key(occupancyId));
    if (raw == null) return null;
    try {
      return ReportDraft.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } on FormatException {
      return null; // corrupt draft: start fresh rather than crash
    }
  }

  Future<void> write(int occupancyId, ReportDraft draft) async {
    await (await _prefs).setString(_key(occupancyId), jsonEncode(draft.toJson()));
  }

  Future<void> clear(int occupancyId) async {
    await (await _prefs).remove(_key(occupancyId));
  }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd app && flutter test test/uuid_test.dart test/report_draft_test.dart`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/uuid.dart app/lib/features/reports/report_draft.dart \
        app/test/uuid_test.dart app/test/report_draft_test.dart
git commit -m "feat(app): stdlib uuid v4 and occupancy-keyed report draft store"
```

---

### Task 2: Reports/locations/work repository + providers + contract tests

Thin wrappers over the generated APIs on the shared `Dio`, mirroring `DioAuthRepository`, plus the Riverpod providers later tasks consume and the OpenAPI contract tests the codebase requires for path constants.

**Files:**
- Create: `app/lib/features/reports/reports_repository.dart`
- Test: `app/test/reports_repository_contract_test.dart`, `app/test/reports_repository_test.dart`

**Interfaces:**
- Consumes: `dioProvider`, `occupancyScopedProviders` (as-built `core/providers.dart`); generated `ReportsApi`/`LocationsApi`/`WorkApi` + models; `standardSerializers`.
- Produces:
  - `abstract class ReportsRepository` — `Future<ReportSummary> createReport({required String clientRef, required String text, required int locationId})`; `Future<PaginatedReportSummaryList> listReports({String? cursor})`; `Future<ReportDetail> fetchReport(int id)`; `Future<ReportPhoto> uploadPhoto({required int reportId, required String path, required String filename})`; `Future<WorkRatingResult> rateWork({required int workOrderId, required int score, String comment = ''})`; `Future<List<Location>> fetchLocations()`.
  - `DioReportsRepository implements ReportsRepository`.
  - `ReportsApiPaths` constants (`reports`, `reportDetail`, `reportPhotos`, `locations`, `workRating` — with `{id}` templates).
  - Providers: `reportsRepositoryProvider`, `locationsProvider` (`FutureProvider.autoDispose<List<Location>>`, watches `occupancyScopedProviders`), `reportDetailProvider` (`FutureProvider.autoDispose.family<ReportDetail, int>`), `reportDraftStoreProvider`.
  - `cursorFromNext(String? next) -> String?` — extracts the `cursor` query param from a DRF `next` URL.

- [ ] **Step 1: Write the failing tests**

Create `app/test/reports_repository_contract_test.dart` (same schema-scrape pattern as `auth_repository_contract_test.dart`):

```dart
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/reports_repository.dart';

void main() {
  late Set<String> openApiPaths;

  setUpAll(() {
    final candidates = [
      File('../docs/api/openapi-v1.yaml'),
      File('docs/api/openapi-v1.yaml'),
      File('../../docs/api/openapi-v1.yaml'),
    ];
    final schema = candidates.firstWhere(
      (f) => f.existsSync(),
      orElse: () =>
          throw StateError('openapi-v1.yaml not found for contract tests'),
    );
    final text = schema.readAsStringSync();
    final paths = <String>{};
    final pathLine = RegExp(r'^  (/[^:]+):');
    var inPaths = false;
    for (final line in text.split('\n')) {
      if (line.startsWith('paths:')) {
        inPaths = true;
        continue;
      }
      if (inPaths && RegExp(r'^[a-zA-Z]').hasMatch(line)) break;
      if (inPaths) {
        final m = pathLine.firstMatch(line);
        if (m != null) paths.add(m.group(1)!);
      }
    }
    openApiPaths = paths;
    expect(openApiPaths, isNotEmpty);
  });

  test('all reporting path constants exist in OpenAPI', () {
    for (final path in [
      ReportsApiPaths.reports,
      ReportsApiPaths.reportDetail,
      ReportsApiPaths.reportPhotos,
      ReportsApiPaths.locations,
      ReportsApiPaths.workRating,
    ]) {
      expect(openApiPaths, contains(path), reason: path);
    }
  });
}
```

Create `app/test/reports_repository_test.dart` (mocked adapter, same style as `auth_interceptor_test.dart`):

```dart
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:mocktail/mocktail.dart';

class _MockAdapter extends Mock implements HttpClientAdapter {}

ResponseBody _json(int status, Object body) => ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );

void main() {
  setUpAll(() => registerFallbackValue(RequestOptions(path: '/')));

  late _MockAdapter adapter;
  late DioReportsRepository repo;
  late RequestOptions lastRequest;

  setUp(() {
    adapter = _MockAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'http://x'));
    dio.httpClientAdapter = adapter;
    repo = DioReportsRepository(dio);
  });

  void answerWith(int status, Object body) {
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
      lastRequest = inv.positionalArguments[0] as RequestOptions;
      return _json(status, body);
    });
  }

  test('createReport posts client_ref/text/location_id and parses summary',
      () async {
    answerWith(201, {
      'id': 5,
      'text': 'Leak',
      'status': 'OPEN',
      'location_path_snapshot': 'B / Hall',
      'created_at': '2026-07-17T00:00:00Z',
    });
    final summary = await repo.createReport(
        clientRef: 'ref-1', text: 'Leak', locationId: 3);
    expect(summary.id, 5);
    expect(lastRequest.path, '/api/v1/reports');
    final sent = lastRequest.data;
    final map = sent is String ? jsonDecode(sent) : sent;
    expect(map['client_ref'], 'ref-1');
    expect(map['text'], 'Leak');
    expect(map['location_id'], 3);
  });

  test('uploadPhoto sends multipart field "photo"', () async {
    answerWith(201, {
      'id': 9,
      'filename': 'p.jpg',
      'sha256': 'aa',
      'download_url': '/api/v1/documents/tok',
    });
    // A real temp file so MultipartFile.fromFile can read it.
    final photo = await repo.uploadPhoto(
      reportId: 5,
      path: _writeTempJpeg(),
      filename: 'p.jpg',
    );
    expect(photo.id, 9);
    expect(lastRequest.path, '/api/v1/reports/5/photos');
    expect(lastRequest.data, isA<FormData>());
    final form = lastRequest.data as FormData;
    expect(form.files.single.key, 'photo');
  });

  test('cursorFromNext extracts the DRF cursor param', () {
    expect(cursorFromNext(null), isNull);
    expect(
      cursorFromNext('http://x/api/v1/reports?cursor=cD0yMDI2'),
      'cD0yMDI2',
    );
  });

  // Amendment 13: adapter-level HTTP 200 idempotent create replay (not a fake repo).
  test('createReport accepts HTTP 200 idempotent replay of same client_ref',
      () async {
    var calls = 0;
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
      lastRequest = inv.positionalArguments[0] as RequestOptions;
      calls++;
      final body = {
        'id': 5,
        'text': 'Leak',
        'status': 'OPEN',
        'location_path_snapshot': 'B / Hall',
        'created_at': '2026-07-17T00:00:00Z',
      };
      return _json(calls == 1 ? 201 : 200, body);
    });
    final first = await repo.createReport(
        clientRef: 'ref-1', text: 'Leak', locationId: 3);
    final second = await repo.createReport(
        clientRef: 'ref-1', text: 'Leak', locationId: 3);
    expect(first.id, 5);
    expect(second.id, 5);
    expect(calls, 2);
  });
}

String _writeTempJpeg() {
  final file = File(
      '${Directory.systemTemp.createTempSync('lamto').path}/p.jpg')
    ..writeAsBytesSync([0xff, 0xd8, 0xff, 0xe0]);
  return file.path;
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd app && flutter test test/reports_repository_contract_test.dart test/reports_repository_test.dart`
Expected: FAIL — `reports_repository.dart` does not exist.

- [ ] **Step 3: Implement**

Create `app/lib/features/reports/reports_repository.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/providers.dart';
import 'report_draft.dart';

/// Paths used by the reporting APIs — must exist in OpenAPI (contract tests).
abstract final class ReportsApiPaths {
  static const reports = '/api/v1/reports';
  static const reportDetail = '/api/v1/reports/{id}';
  static const reportPhotos = '/api/v1/reports/{id}/photos';
  static const locations = '/api/v1/locations';
  static const workRating = '/api/v1/work/{id}/rating';
}

abstract class ReportsRepository {
  Future<ReportSummary> createReport({
    required String clientRef,
    required String text,
    required int locationId,
  });
  Future<PaginatedReportSummaryList> listReports({String? cursor});
  Future<ReportDetail> fetchReport(int id);
  Future<ReportPhoto> uploadPhoto({
    required int reportId,
    required String path,
    required String filename,
  });
  Future<WorkRatingResult> rateWork({
    required int workOrderId,
    required int score,
    String comment = '',
  });
  Future<List<Location>> fetchLocations();
}

/// Thin wrapper over the generated dart-dio APIs on the shared Dio
/// (token + X-LamTo-Occupancy interceptors already installed).
class DioReportsRepository implements ReportsRepository {
  DioReportsRepository(Dio dio)
      : _reports = ReportsApi(dio, standardSerializers),
        _locations = LocationsApi(dio, standardSerializers),
        _work = WorkApi(dio, standardSerializers);

  final ReportsApi _reports;
  final LocationsApi _locations;
  final WorkApi _work;

  @override
  Future<ReportSummary> createReport({
    required String clientRef,
    required String text,
    required int locationId,
  }) async {
    final res = await _reports.reportsCreate(
      reportCreateRequest: ReportCreateRequest(
        (b) => b
          ..clientRef = clientRef
          ..text = text
          ..locationId = locationId,
      ),
    );
    return res.data!;
  }

  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) async {
    final res = await _reports.reportsList(cursor: cursor);
    return res.data!;
  }

  @override
  Future<ReportDetail> fetchReport(int id) async {
    final res = await _reports.reportsRetrieve(id: id);
    return res.data!;
  }

  @override
  Future<ReportPhoto> uploadPhoto({
    required int reportId,
    required String path,
    required String filename,
  }) async {
    final lower = filename.toLowerCase();
    final subtype = lower.endsWith('.png') ? 'png' : 'jpeg';
    final res = await _reports.reportsPhotosCreate(
      id: reportId,
      photo: await MultipartFile.fromFile(
        path,
        filename: filename,
        contentType: DioMediaType('image', subtype),
      ),
    );
    return res.data!;
  }

  @override
  Future<WorkRatingResult> rateWork({
    required int workOrderId,
    required int score,
    String comment = '',
  }) async {
    final res = await _work.workRatingCreate(
      id: workOrderId,
      workRatingRequest: WorkRatingRequest(
        (b) => b
          ..score = score
          ..comment = comment,
      ),
    );
    return res.data!;
  }

  @override
  Future<List<Location>> fetchLocations() async {
    final res = await _locations.locationsRetrieve();
    return res.data!.toList();
  }
}

/// Extract the `cursor` query param from a DRF cursor-pagination `next` URL.
String? cursorFromNext(String? next) {
  if (next == null || next.isEmpty) return null;
  return Uri.parse(next).queryParameters['cursor'];
}

final reportsRepositoryProvider = Provider<ReportsRepository>(
  (ref) => DioReportsRepository(ref.watch(dioProvider)),
);

final reportDraftStoreProvider =
    Provider<ReportDraftStore>((ref) => ReportDraftStore());

/// Building-scoped caches rebuild on occupancy change (providers.dart contract).
final locationsProvider =
    FutureProvider.autoDispose<List<Location>>((ref) {
  ref.watch(occupancyScopedProviders);
  return ref.watch(reportsRepositoryProvider).fetchLocations();
});

final reportDetailProvider =
    FutureProvider.autoDispose.family<ReportDetail, int>((ref, id) {
  ref.watch(occupancyScopedProviders);
  return ref.watch(reportsRepositoryProvider).fetchReport(id);
});
```

If the analyzer reports that `WorkRatingRequest.comment` or `ReportCreateRequest` field names differ, take the exact builder names from `app/packages/lamto_api/lib/src/model/work_rating_request.dart` / `report_create_request.dart` — the wire names are `client_ref`, `text`, `location_id`, `score`, `comment`.

- [ ] **Step 4: Run to verify they pass**

Run: `cd app && flutter test test/reports_repository_contract_test.dart test/reports_repository_test.dart`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features/reports/reports_repository.dart \
        app/test/reports_repository_contract_test.dart app/test/reports_repository_test.dart
git commit -m "feat(app): reports/locations/work repository over generated client"
```

---

### Task 3: Report submitter (idempotent choreography + per-photo retry)

The pure-Dart service owning §3.5: create-with-`client_ref` first, clear the draft the moment text commits, then upload photos one-by-one collecting failures. This task carries the §6.5-mandated retry→200 and conflict→409 tests.

**Files:**
- Create: `app/lib/features/reports/report_submitter.dart`
- Test: `app/test/report_submitter_test.dart`

**Interfaces:**
- Consumes: `ReportsRepository`, `ReportDraft`, `ReportDraftStore`, `Failure`.
- Produces:
  - `PhotoUploadStatus { pending, uploaded, failed }`; `PhotoUpload(path, filename, status)`.
  - `SubmitOutcome(reportId, photos)` — `photos` carries final statuses; `bool get allPhotosUploaded`.
  - `ReportConflictException` — thrown on 409 `client_ref_conflict`.
  - `ReportSubmitter(repository, draftStore)` — `Future<SubmitOutcome> submit({required ReportDraft draft, required int occupancyId})`; `Future<PhotoUpload> retryPhoto({required int reportId, required PhotoUpload photo})`.
  - `reportSubmitterProvider`.

- [ ] **Step 1: Write the failing tests**

Create `app/test/report_submitter_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/report_draft.dart';
import 'package:lamto/features/reports/report_submitter.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

ReportSummary _summary(int id) => ReportSummary(
      (b) => b
        ..id = id
        ..text = 'Leak'
        ..status = 'OPEN'
        ..locationPathSnapshot = 'B / Hall'
        ..createdAt = DateTime.utc(2026, 7, 17),
    );

DioException _problem(int status, String code) {
  final req = RequestOptions(path: '/api/v1/reports');
  return DioException(
    requestOptions: req,
    response: Response(
      requestOptions: req,
      statusCode: status,
      data: {'code': code, 'status': status, 'title': 'x', 'type': 'about:blank'},
    ),
    type: DioExceptionType.badResponse,
  );
}

class _FakeRepo implements ReportsRepository {
  final createdRefs = <String>[];
  final uploaded = <String>[];
  Object? createError;
  Set<String> failPhotoPaths = {};

  @override
  Future<ReportSummary> createReport({
    required String clientRef,
    required String text,
    required int locationId,
  }) async {
    createdRefs.add(clientRef);
    final error = createError;
    if (error != null) throw error;
    return _summary(42);
  }

  @override
  Future<ReportPhoto> uploadPhoto({
    required int reportId,
    required String path,
    required String filename,
  }) async {
    if (failPhotoPaths.contains(path)) {
      throw _problem(500, 'server_error');
    }
    uploaded.add(path);
    return ReportPhoto(
      (b) => b
        ..id = uploaded.length
        ..filename = filename
        ..sha256 = 'aa'
        ..downloadUrl = '/api/v1/documents/tok',
    );
  }

  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) =>
      throw UnimplementedError();
  @override
  Future<ReportDetail> fetchReport(int id) => throw UnimplementedError();
  @override
  Future<WorkRatingResult> rateWork(
          {required int workOrderId, required int score, String comment = ''}) =>
      throw UnimplementedError();
  @override
  Future<List<Location>> fetchLocations() => throw UnimplementedError();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late _FakeRepo repo;
  late ReportDraftStore drafts;
  late ReportSubmitter submitter;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    repo = _FakeRepo();
    drafts = ReportDraftStore();
    submitter = ReportSubmitter(repository: repo, draftStore: drafts);
  });

  ReportDraft _draft({List<String> photos = const []}) =>
      ReportDraft.fresh().copyWith(
        text: 'Leak',
        locationId: 3,
        photoPaths: photos,
      );

  test('submit commits text, clears draft, uploads photos in order', () async {
    final draft = _draft(photos: ['/tmp/a.jpg', '/tmp/b.jpg']);
    await drafts.write(7, draft);
    final outcome = await submitter.submit(draft: draft, occupancyId: 7);
    expect(outcome.reportId, 42);
    expect(outcome.allPhotosUploaded, isTrue);
    expect(repo.uploaded, ['/tmp/a.jpg', '/tmp/b.jpg']);
    expect(await drafts.read(7), isNull); // text committed -> draft gone
  });

  test('retry after network failure reuses the SAME client_ref (spec 3.5)',
      () async {
    final draft = _draft();
    repo.createError = DioException(
      requestOptions: RequestOptions(path: '/api/v1/reports'),
      type: DioExceptionType.connectionTimeout,
    );
    await expectLater(
        submitter.submit(draft: draft, occupancyId: 7), throwsA(anything));
    repo.createError = null;
    await submitter.submit(draft: draft, occupancyId: 7); // server replays 200
    expect(repo.createdRefs, hasLength(2));
    expect(repo.createdRefs[0], repo.createdRefs[1]);
  });

  test('409 client_ref_conflict surfaces ReportConflictException', () async {
    repo.createError = _problem(409, 'client_ref_conflict');
    await expectLater(
      submitter.submit(draft: _draft(), occupancyId: 7),
      throwsA(isA<ReportConflictException>()),
    );
  });

  test('failed photo never loses the report; retryPhoto recovers it', () async {
    repo.failPhotoPaths = {'/tmp/b.jpg'};
    final draft = _draft(photos: ['/tmp/a.jpg', '/tmp/b.jpg']);
    await drafts.write(7, draft);
    final outcome = await submitter.submit(draft: draft, occupancyId: 7);
    expect(outcome.reportId, 42);
    expect(outcome.allPhotosUploaded, isFalse);
    expect(await drafts.read(7), isNull); // report text is safe regardless
    final failed =
        outcome.photos.singleWhere((p) => p.status == PhotoUploadStatus.failed);

    repo.failPhotoPaths = {};
    final retried =
        await submitter.retryPhoto(reportId: 42, photo: failed);
    expect(retried.status, PhotoUploadStatus.uploaded);
  });

  // Amendment 10: photo retry must not re-upload when already uploaded (client
  // attachment id / status). Backend sha256 dedup covers lost-response; client
  // must not double-call when status is already uploaded.
  test('retryPhoto is idempotent when photo already uploaded', () async {
    final draft = _draft(photos: ['/tmp/a.jpg']);
    final outcome = await submitter.submit(draft: draft, occupancyId: 7);
    final photo = outcome.photos.single;
    expect(photo.status, PhotoUploadStatus.uploaded);
    final before = repo.uploaded.length;
    final again =
        await submitter.retryPhoto(reportId: 42, photo: photo);
    expect(again.status, PhotoUploadStatus.uploaded);
    expect(repo.uploaded.length, before); // no second upload
  });
}
```

**Backend (same task or tiny follow-up commit):** implement amendment 10 checksum dedup in `attach_report_photo` / `ReportPhotoUploadView` (same bytes → existing photo, HTTP 200) + API test in `src/lamto/api/tests/test_report_photos.py`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd app && flutter test test/report_submitter_test.dart`
Expected: FAIL — `report_submitter.dart` does not exist.

- [ ] **Step 3: Implement**

Create `app/lib/features/reports/report_submitter.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/failure.dart';
import 'report_draft.dart';
import 'reports_repository.dart';

enum PhotoUploadStatus { pending, uploaded, failed }

class PhotoUpload {
  PhotoUpload({
    required this.path,
    required this.filename,
    this.status = PhotoUploadStatus.pending,
  });

  final String path;
  final String filename;
  PhotoUploadStatus status;
}

class SubmitOutcome {
  SubmitOutcome({required this.reportId, required this.photos});

  final int reportId;
  final List<PhotoUpload> photos;

  bool get allPhotosUploaded =>
      photos.every((p) => p.status == PhotoUploadStatus.uploaded);
}

/// Same client_ref was already submitted with different content (spec 3.5).
class ReportConflictException implements Exception {}

/// Spec 3.5 / 6.3 choreography: text commits first under the draft's stable
/// client_ref; the draft clears the moment the report row exists; photos then
/// upload one-by-one so a dropped upload never loses the report.
class ReportSubmitter {
  ReportSubmitter({required this.repository, required this.draftStore});

  final ReportsRepository repository;
  final ReportDraftStore draftStore;

  Future<SubmitOutcome> submit({
    required ReportDraft draft,
    required int occupancyId,
  }) async {
    final int reportId;
    try {
      final summary = await repository.createReport(
        clientRef: draft.clientRef,
        text: draft.text,
        locationId: draft.locationId!,
      );
      reportId = summary.id;
    } on DioException catch (e) {
      if (Failure.fromDio(e).code == 'client_ref_conflict') {
        throw ReportConflictException();
      }
      rethrow; // network/validation: draft stays; retry reuses the same ref
    }
    // The report row exists: the text can never be lost now.
    await draftStore.clear(occupancyId);

    final photos = [
      for (final path in draft.photoPaths)
        PhotoUpload(path: path, filename: path.split('/').last),
    ];
    for (final photo in photos) {
      await _upload(reportId, photo);
    }
    return SubmitOutcome(reportId: reportId, photos: photos);
  }

  Future<PhotoUpload> retryPhoto({
    required int reportId,
    required PhotoUpload photo,
  }) async {
    await _upload(reportId, photo);
    return photo;
  }

  Future<void> _upload(int reportId, PhotoUpload photo) async {
    try {
      await repository.uploadPhoto(
        reportId: reportId,
        path: photo.path,
        filename: photo.filename,
      );
      photo.status = PhotoUploadStatus.uploaded;
    } on DioException {
      photo.status = PhotoUploadStatus.failed;
    }
  }
}

final reportSubmitterProvider = Provider<ReportSubmitter>(
  (ref) => ReportSubmitter(
    repository: ref.watch(reportsRepositoryProvider),
    draftStore: ref.watch(reportDraftStoreProvider),
  ),
);
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd app && flutter test test/report_submitter_test.dart`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features/reports/report_submitter.dart app/test/report_submitter_test.dart
git commit -m "feat(app): idempotent report submitter with per-photo retry"
```

---

### Task 4: Location picker screen

Drill-down tree over the flat `/locations` list — large rows, chevrons for parents, an explicit "choose this area" row at each level (§6.3: tree, large rows; no gesture-only affordances).

**Files:**
- Create: `app/lib/features/reports/location_picker_screen.dart`
- Modify: `app/lib/l10n/app_en.arb`, `app/lib/l10n/app_vi.arb`
- Test: `app/test/location_picker_test.dart`

**Interfaces:**
- Consumes: `locationsProvider`, `Location` (generated), `failureMessage`.
- Produces: `LocationPickerScreen` — pushed with `Navigator.push<Location>`; pops with the chosen `Location`.

- [ ] **Step 1: Add the l10n keys**

Append to `app/lib/l10n/app_en.arb` (before the closing `}`):

```json
  "locationPickerTitle": "Where is the issue?",
  "locationChooseHere": "Choose this area",
  "commonRetry": "Try again"
```

Append to `app/lib/l10n/app_vi.arb`:

```json
  "locationPickerTitle": "Sự cố ở đâu?",
  "locationChooseHere": "Chọn khu vực này",
  "commonRetry": "Thử lại"
```

Run: `cd app && flutter gen-l10n`

- [ ] **Step 2: Write the failing test**

Create `app/test/location_picker_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/features/reports/location_picker_screen.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

Location _loc(int id, String name, {int? parent}) => Location(
      (b) => b
        ..id = id
        ..name = name
        ..parentId = parent,
    );

Future<Location?> _open(WidgetTester tester, List<Location> locations) async {
  Location? picked;
  await tester.pumpWidget(ProviderScope(
    overrides: [
      locationsProvider.overrideWith((ref) async => locations),
    ],
    child: MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('vi'),
      home: Builder(
        builder: (context) => ElevatedButton(
          onPressed: () async {
            picked = await Navigator.push<Location>(
              context,
              MaterialPageRoute(builder: (_) => const LocationPickerScreen()),
            );
          },
          child: const Text('open'),
        ),
      ),
    ),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return picked;
}

void main() {
  testWidgets('leaf tap pops with the location', (tester) async {
    await _open(tester, [_loc(1, 'Sảnh')]);
    await tester.tap(find.text('Sảnh'));
    await tester.pumpAndSettle();
    // Popped back to the host screen.
    expect(find.text('open'), findsOneWidget);
  });

  testWidgets('parent drills down and "choose this area" selects it',
      (tester) async {
    await _open(tester, [
      _loc(1, 'Tòa A'),
      _loc(2, 'Thang máy 2', parent: 1),
    ]);
    await tester.tap(find.text('Tòa A'));
    await tester.pumpAndSettle();
    expect(find.text('Thang máy 2'), findsOneWidget);
    expect(find.text('Chọn khu vực này'), findsOneWidget);
    await tester.tap(find.text('Chọn khu vực này'));
    await tester.pumpAndSettle();
    expect(find.text('open'), findsOneWidget);
  });
}
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd app && flutter test test/location_picker_test.dart`
Expected: FAIL — `location_picker_screen.dart` does not exist.

- [ ] **Step 4: Implement**

Create `app/lib/features/reports/location_picker_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../l10n/app_localizations.dart';
import 'reports_repository.dart';

/// Drill-down location tree (spec 6.3): large rows, explicit selection at
/// every level — no gesture-only affordances.
class LocationPickerScreen extends ConsumerStatefulWidget {
  const LocationPickerScreen({super.key});

  @override
  ConsumerState<LocationPickerScreen> createState() =>
      _LocationPickerScreenState();
}

class _LocationPickerScreenState extends ConsumerState<LocationPickerScreen> {
  /// Drill path: null root -> deeper parents.
  final List<Location> _path = [];

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final locations = ref.watch(locationsProvider);
    final parent = _path.isEmpty ? null : _path.last;

    return PopScope(
      canPop: _path.isEmpty,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) setState(() => _path.removeLast());
      },
      child: Scaffold(
        appBar: AppBar(title: Text(parent?.name ?? l10n.locationPickerTitle)),
        body: switch (locations) {
          AsyncData(:final value) => _list(context, l10n, value, parent),
          AsyncError(:final error) => Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(failureMessage(
                    error is Failure ? error : Failure(code: 'server_error'),
                    l10n,
                  )),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: () => ref.invalidate(locationsProvider),
                    child: Text(l10n.commonRetry),
                  ),
                ],
              ),
            ),
          _ => const Center(child: CircularProgressIndicator.adaptive()),
        },
      ),
    );
  }

  Widget _list(
    BuildContext context,
    AppLocalizations l10n,
    List<Location> all,
    Location? parent,
  ) {
    final children =
        all.where((loc) => loc.parentId == parent?.id).toList();
    final hasChildren = {
      for (final loc in all)
        if (loc.parentId != null) loc.parentId!,
    };
    return ListView(
      children: [
        if (parent != null)
          ListTile(
            minTileHeight: 56,
            leading: const Icon(Icons.check_circle_outline),
            title: Text(l10n.locationChooseHere),
            subtitle: Text(parent.name),
            onTap: () => Navigator.pop(context, parent),
          ),
        for (final loc in children)
          ListTile(
            minTileHeight: 56,
            title: Text(loc.name),
            trailing: hasChildren.contains(loc.id)
                ? const Icon(Icons.chevron_right)
                : null,
            onTap: () {
              if (hasChildren.contains(loc.id)) {
                setState(() => _path.add(loc));
              } else {
                Navigator.pop(context, loc);
              }
            },
          ),
      ],
    );
  }
}
```

- [ ] **Step 5: Run the tests**

Run: `cd app && flutter test test/location_picker_test.dart`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features/reports/location_picker_screen.dart app/lib/l10n \
        app/test/location_picker_test.dart
git commit -m "feat(app): drill-down location picker with explicit selection"
```

---

### Task 5: Report form screen — draft, photos, submit — wired to the Report tab

The §6.3(4) screen: required text, location row, ≤5 photos via camera/gallery (native resize to 2048/JPEG), draft autosave/restore, submit through `ReportSubmitter`, per-photo retry UI, 409 handling with a fresh ref.

**Files:**
- Modify: `app/pubspec.yaml` (add `image_picker`)
- Create: `app/lib/features/reports/report_form_screen.dart`
- Modify: `app/lib/features/shell/home_shell.dart` (Report tab body)
- Modify: `app/lib/l10n/app_en.arb`, `app/lib/l10n/app_vi.arb`
- Test: `app/test/report_form_test.dart`

**Interfaces:**
- Consumes: `ReportDraft(Store)`, `ReportSubmitter` + `reportSubmitterProvider`, `SubmitOutcome`, `PhotoUpload(Status)`, `ReportConflictException`, `LocationPickerScreen`, `occupancyHolderProvider`, `reportDraftStoreProvider`, `failureMessage`.
- Produces: `ReportFormScreen` (Report tab body); `maxReportPhotos = 5`.

- [ ] **Step 1: Add the dependency + l10n keys**

```bash
cd app && flutter pub add image_picker
```

Append to `app/lib/l10n/app_en.arb`:

```json
  "reportFormTitle": "Report an issue",
  "reportTextLabel": "What happened?",
  "reportLocationLabel": "Location",
  "reportLocationEmpty": "Choose a location",
  "reportPhotosLabel": "Photos (up to {max})",
  "@reportPhotosLabel": {"placeholders": {"max": {"type": "int"}}},
  "reportAddPhoto": "Add photo",
  "reportPhotoCamera": "Take a photo",
  "reportPhotoGallery": "Choose from gallery",
  "reportSubmit": "Send report",
  "reportSubmitted": "Your report was received.",
  "reportPhotosPending": "Some photos did not upload. Your report text is saved — retry each photo below.",
  "reportPhotoRetry": "Retry",
  "reportConflict": "This report was already sent. Your edits will be sent as a new report — tap Send again.",
  "reportMissingFields": "Please describe the issue and choose a location. Nothing was sent yet."
```

Append to `app/lib/l10n/app_vi.arb`:

```json
  "reportFormTitle": "Gửi phản ánh",
  "reportTextLabel": "Đã xảy ra chuyện gì?",
  "reportLocationLabel": "Vị trí",
  "reportLocationEmpty": "Chọn vị trí",
  "reportPhotosLabel": "Ảnh (tối đa {max})",
  "@reportPhotosLabel": {"placeholders": {"max": {"type": "int"}}},
  "reportAddPhoto": "Thêm ảnh",
  "reportPhotoCamera": "Chụp ảnh",
  "reportPhotoGallery": "Chọn từ thư viện",
  "reportSubmit": "Gửi phản ánh",
  "reportSubmitted": "Phản ánh của bạn đã được ghi nhận.",
  "reportPhotosPending": "Một số ảnh chưa tải lên được. Nội dung phản ánh đã được lưu — thử lại từng ảnh bên dưới.",
  "reportPhotoRetry": "Thử lại",
  "reportConflict": "Phản ánh này đã được gửi trước đó. Nội dung bạn vừa sửa sẽ được gửi thành phản ánh mới — bấm Gửi lần nữa.",
  "reportMissingFields": "Vui lòng mô tả sự cố và chọn vị trí. Chưa có gì được gửi đi."
```

Run: `cd app && flutter gen-l10n`

- [ ] **Step 2: Write the failing widget test**

Create `app/test/report_form_test.dart`:

```dart
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

void main() {
  testWidgets('restores a persisted draft and submits it', (tester) async {
    final repo = _FakeRepo();
    final draft = ReportDraft.fresh().copyWith(
      text: 'Thang máy kêu to',
      locationId: 3,
      locationLabel: 'Tòa A / Thang máy 2',
    );
    await _pump(tester, repo, existingDraft: draft);
    expect(find.text('Thang máy kêu to'), findsOneWidget); // restored

    await tester.tap(find.text('Gửi phản ánh'));
    await tester.pumpAndSettle();
    expect(repo.refs.single, draft.clientRef); // draft's stable ref used
    expect(find.text('Phản ánh của bạn đã được ghi nhận.'), findsOneWidget);
  });

  testWidgets('missing fields blocks submit with doctrine copy',
      (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, repo);
    await tester.tap(find.text('Gửi phản ánh'));
    await tester.pumpAndSettle();
    expect(repo.refs, isEmpty);
    expect(find.textContaining('Chưa có gì được gửi'), findsOneWidget);
  });

  testWidgets('409 shows conflict copy and mints a fresh ref', (tester) async {
    final repo = _FakeRepo()..conflict = true;
    final draft = ReportDraft.fresh()
        .copyWith(text: 'Sửa lại nội dung', locationId: 3);
    await _pump(tester, repo, existingDraft: draft);
    await tester.tap(find.text('Gửi phản ánh'));
    await tester.pumpAndSettle();
    expect(find.textContaining('đã được gửi trước đó'), findsOneWidget);

    await tester.tap(find.text('Gửi phản ánh'));
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
    await tester.tap(find.text('Gửi phản ánh'));
    await tester.pumpAndSettle();
    expect(find.text('Phản ánh của bạn đã được ghi nhận.'), findsOneWidget);
    // Primary send must not fire create again.
    expect(find.text('Gửi phản ánh'), findsNothing);
    expect(repo.refs, hasLength(1));
  });
}
```

The fake throws `ReportConflictException` directly from the repo, exercising the screen's handling; the DioException→409 mapping is covered by Task 3's submitter tests.

**Also (amendments 8–11):** form must import picker images via `ReportPhotoFileStore` before persisting paths; delete owned files on remove/submit clear/conflict drop; use serialized/debounced autosave; enter committed-result after create (`_outcome != null` / `_committed`) with photo-retry + "view issue" only.

- [ ] **Step 3: Run to verify it fails, then implement**

Run: `cd app && flutter test test/report_form_test.dart` → FAIL (screen missing).

Create `app/lib/features/reports/report_form_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import 'location_picker_screen.dart';
import 'report_draft.dart';
import 'report_submitter.dart';
import 'reports_repository.dart';

const maxReportPhotos = 5; // spec 6.3
const _maxPhotoEdge = 2048.0; // spec 6.3: client-side max edge before upload
const _photoQuality = 85;

class ReportFormScreen extends ConsumerStatefulWidget {
  const ReportFormScreen({super.key});

  @override
  ConsumerState<ReportFormScreen> createState() => _ReportFormScreenState();
}

class _ReportFormScreenState extends ConsumerState<ReportFormScreen> {
  final _text = TextEditingController();
  final _picker = ImagePicker();
  ReportDraft _draft = ReportDraft.fresh();
  bool _restored = false;
  bool _busy = false;
  String? _notice;
  SubmitOutcome? _outcome;

  int get _occupancyId => ref.read(occupancyHolderProvider).occupancyId!;

  @override
  void initState() {
    super.initState();
    _text.addListener(_onTextChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) => _restore());
  }

  Future<void> _restore() async {
    final saved =
        await ref.read(reportDraftStoreProvider).read(_occupancyId);
    if (!mounted) return;
    setState(() {
      if (saved != null) {
        _draft = saved;
        _text.text = saved.text;
      }
      _restored = true;
    });
  }

  void _onTextChanged() {
    _draft = _draft.copyWith(text: _text.text);
    _persist();
  }

  Future<void> _persist() =>
      ref.read(reportDraftStoreProvider).write(_occupancyId, _draft);

  Future<void> _pickLocation() async {
    final location = await Navigator.push<Location>(
      context,
      MaterialPageRoute(builder: (_) => const LocationPickerScreen()),
    );
    if (location == null) return;
    setState(() {
      _draft = _draft.copyWith(
        locationId: location.id,
        locationLabel: location.name,
      );
    });
    await _persist();
  }

  Future<void> _addPhoto(AppLocalizations l10n) async {
    final remaining = maxReportPhotos - _draft.photoPaths.length;
    if (remaining <= 0) return;
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              minTileHeight: 56,
              leading: const Icon(Icons.photo_camera_outlined),
              title: Text(l10n.reportPhotoCamera),
              onTap: () => Navigator.pop(context, ImageSource.camera),
            ),
            ListTile(
              minTileHeight: 56,
              leading: const Icon(Icons.photo_library_outlined),
              title: Text(l10n.reportPhotoGallery),
              onTap: () => Navigator.pop(context, ImageSource.gallery),
            ),
          ],
        ),
      ),
    );
    if (source == null) return;
    // Native downscale to max edge 2048 + JPEG re-encode (spec 6.3).
    final picked = source == ImageSource.gallery
        ? await _picker.pickMultiImage(
            maxWidth: _maxPhotoEdge,
            maxHeight: _maxPhotoEdge,
            imageQuality: _photoQuality,
          )
        : [
            await _picker.pickImage(
              source: ImageSource.camera,
              maxWidth: _maxPhotoEdge,
              maxHeight: _maxPhotoEdge,
              imageQuality: _photoQuality,
            ),
          ].nonNulls.toList();
    if (picked.isEmpty) return;
    setState(() {
      _draft = _draft.copyWith(photoPaths: [
        ..._draft.photoPaths,
        ...picked.take(remaining).map((x) => x.path),
      ]);
    });
    await _persist();
  }

  void _removePhoto(String path) {
    setState(() {
      _draft = _draft.copyWith(
        photoPaths: _draft.photoPaths.where((p) => p != path).toList(),
      );
    });
    _persist();
  }

  Future<void> _submit(AppLocalizations l10n) async {
    if (_draft.text.trim().isEmpty || _draft.locationId == null) {
      setState(() => _notice = l10n.reportMissingFields);
      return;
    }
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      final outcome = await ref
          .read(reportSubmitterProvider)
          .submit(draft: _draft, occupancyId: _occupancyId);
      if (!mounted) return;
      setState(() {
        _outcome = outcome;
        _notice = outcome.allPhotosUploaded
            ? l10n.reportSubmitted
            : l10n.reportPhotosPending;
        if (outcome.allPhotosUploaded) _resetForm();
      });
    } on ReportConflictException {
      // Already submitted with different content: mint a fresh ref so the
      // edited draft becomes a NEW report on the next send (spec 3.5).
      _draft = _draft.copyWith(clientRef: ReportDraft.fresh().clientRef);
      await _persist();
      if (mounted) setState(() => _notice = l10n.reportConflict);
    } catch (e) {
      if (mounted) {
        setState(() => _notice = failureMessage(
              e is Failure ? e : Failure.fromObject(e),
              l10n,
            ));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _resetForm() {
    _draft = ReportDraft.fresh();
    _text.removeListener(_onTextChanged);
    _text.clear();
    _text.addListener(_onTextChanged);
  }

  Future<void> _retryPhoto(PhotoUpload photo, AppLocalizations l10n) async {
    final outcome = _outcome;
    if (outcome == null) return;
    await ref
        .read(reportSubmitterProvider)
        .retryPhoto(reportId: outcome.reportId, photo: photo);
    if (!mounted) return;
    setState(() {
      if (outcome.allPhotosUploaded) {
        _notice = l10n.reportSubmitted;
        _outcome = null;
        _resetForm();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    if (!_restored) {
      return const Center(child: CircularProgressIndicator.adaptive());
    }
    final failedPhotos = _outcome?.photos
            .where((p) => p.status == PhotoUploadStatus.failed)
            .toList() ??
        const <PhotoUpload>[];
    return Scaffold(
      appBar: AppBar(title: Text(l10n.reportFormTitle)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _text,
            maxLines: 4,
            decoration: InputDecoration(labelText: l10n.reportTextLabel),
          ),
          const SizedBox(height: 12),
          ListTile(
            minTileHeight: 56,
            shape: RoundedRectangleBorder(
              side: BorderSide(color: Theme.of(context).dividerColor),
              borderRadius: BorderRadius.circular(10),
            ),
            leading: const Icon(Icons.place_outlined),
            title: Text(
              _draft.locationLabel.isEmpty
                  ? l10n.reportLocationEmpty
                  : _draft.locationLabel,
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: _busy ? null : _pickLocation,
          ),
          const SizedBox(height: 16),
          Text(l10n.reportPhotosLabel(maxReportPhotos)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final path in _draft.photoPaths)
                InputChip(
                  label: Text(path.split('/').last,
                      overflow: TextOverflow.ellipsis),
                  onDeleted: _busy ? null : () => _removePhoto(path),
                ),
              if (_draft.photoPaths.length < maxReportPhotos)
                ActionChip(
                  avatar: const Icon(Icons.add_a_photo_outlined, size: 20),
                  label: Text(l10n.reportAddPhoto),
                  onPressed: _busy ? null : () => _addPhoto(l10n),
                ),
            ],
          ),
          if (_notice != null) ...[
            const SizedBox(height: 16),
            Text(_notice!, style: Theme.of(context).textTheme.bodyMedium),
          ],
          for (final photo in failedPhotos)
            ListTile(
              minTileHeight: 48,
              leading: const Icon(Icons.error_outline),
              title: Text(photo.filename, overflow: TextOverflow.ellipsis),
              trailing: TextButton(
                onPressed: () => _retryPhoto(photo, l10n),
                child: Text(l10n.reportPhotoRetry),
              ),
            ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _busy ? null : () => _submit(l10n),
            child: Text(l10n.reportSubmit),
          ),
        ],
      ),
    );
  }
}
```

The screen (and Tasks 6–7) coerce raw provider errors via `Failure.fromObject`. In `app/lib/core/failure.dart`, inside `class Failure`, add:

```dart
  /// Coerce any thrown object (DioException or otherwise) into a Failure.
  factory Failure.fromObject(Object error) => error is DioException
      ? Failure.fromDio(error)
      : Failure(code: 'server_error');
```

- [ ] **Step 4: Wire the Report tab**

In `app/lib/features/shell/home_shell.dart`, import the screen and replace the placeholder body at index 1. Change `_bodies` to:

```dart
  List<Widget> _bodies(AppLocalizations l10n) => [
        Center(child: Text(l10n.tabHome)),
        const ReportFormScreen(),
        Center(child: Text(l10n.tabIssues)),
        Center(child: Text(l10n.tabLedger)),
        Center(child: Text(l10n.tabAccount)),
      ];
```

with `import '../reports/report_form_screen.dart';` added.

- [ ] **Step 5: Run the tests**

Run: `cd app && flutter test test/report_form_test.dart test/failure_test.dart`
Expected: PASS. Also run the routing suite (`flutter test test/app_routing_test.dart`) — the shell change must not break it (the Report tab body now builds a `ConsumerStatefulWidget`, which is fine inside the existing `ProviderScope`).

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/pubspec.yaml app/pubspec.lock app/lib/features/reports/report_form_screen.dart \
        app/lib/features/shell/home_shell.dart app/lib/core/failure.dart app/lib/l10n \
        app/test/report_form_test.dart
git commit -m "feat(app): report form with draft persistence, photos, and idempotent submit"
```

---

### Task 6: My-issues list — wired to the Issues tab

Cursor-paginated list of the caller's reports with semantic status chips, pull-to-refresh, and load-more (§6.3(5) list half).

**Scope (amendment 12): user-global** — API `resident_reports(user)` returns all reports this user submitted across units; UI title "My issues" / "Việc của tôi"; do not imply selected-occupancy-only. Invalidate/refresh after successful report create (from form/submitter callers). Dartdoc on `MyIssuesScreen` / `MyReportsController` must state user-global scope.

**Files:**
- Create: `app/lib/features/reports/my_issues_screen.dart`
- Modify: `app/lib/features/shell/home_shell.dart` (Issues tab body)
- Modify: `app/lib/l10n/app_en.arb`, `app_vi.arb`
- Test: `app/test/my_issues_test.dart`

**Interfaces:**
- Consumes: `reportsRepositoryProvider`, `cursorFromNext`, `ReportSummary` (session-level list; occupancy watch optional for harmless refresh only).
- Produces: `MyIssuesScreen`; `myReportsProvider` (`AsyncNotifierProvider<MyReportsController, List<ReportSummary>>`) with `loadMore()` and `hasMore`; `reportStatusLabel(String, AppLocalizations)`.

- [ ] **Step 1: Add the l10n keys**

`app_en.arb`:

```json
  "issuesTitle": "My issues",
  "issuesEmpty": "You have not reported any issues yet.",
  "issuesLoadMore": "Load more",
  "statusOpen": "Open",
  "statusResolved": "Resolved"
```

`app_vi.arb`:

```json
  "issuesTitle": "Việc của tôi",
  "issuesEmpty": "Bạn chưa gửi phản ánh nào.",
  "issuesLoadMore": "Tải thêm",
  "statusOpen": "Đang mở",
  "statusResolved": "Đã xử lý"
```

Run: `cd app && flutter gen-l10n`

- [ ] **Step 2: Write the failing test**

Create `app/test/my_issues_test.dart`:

```dart
import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/features/reports/my_issues_screen.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

ReportSummary _report(int id, String text) => ReportSummary(
      (b) => b
        ..id = id
        ..text = text
        ..status = 'OPEN'
        ..locationPathSnapshot = 'B / Hall'
        ..createdAt = DateTime.utc(2026, 7, 17),
    );

PaginatedReportSummaryList _page(List<ReportSummary> items, {String? next}) =>
    PaginatedReportSummaryList(
      (b) => b
        ..next = next
        ..results = ListBuilder<ReportSummary>(items),
    );

class _FakeRepo implements ReportsRepository {
  _FakeRepo(this.pages);
  final Map<String?, PaginatedReportSummaryList> pages;
  final cursors = <String?>[];

  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) async {
    cursors.add(cursor);
    return pages[cursor]!;
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
  Future<ReportDetail> fetchReport(int id) => throw UnimplementedError();
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

void main() {
  testWidgets('lists reports with status chip and loads the next page',
      (tester) async {
    final repo = _FakeRepo({
      null: _page([_report(1, 'Thang máy kêu')],
          next: 'http://x/api/v1/reports?cursor=abc'),
      'abc': _page([_report(2, 'Đèn hành lang hỏng')]),
    });
    await tester.pumpWidget(ProviderScope(
      overrides: [reportsRepositoryProvider.overrideWithValue(repo)],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const MyIssuesScreen(),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Thang máy kêu'), findsOneWidget);
    expect(find.text('Đang mở'), findsOneWidget); // status paired with text

    await tester.tap(find.text('Tải thêm'));
    await tester.pumpAndSettle();
    expect(find.text('Đèn hành lang hỏng'), findsOneWidget);
    expect(repo.cursors, [null, 'abc']);
    expect(find.text('Tải thêm'), findsNothing); // no further page
  });

  testWidgets('empty state', (tester) async {
    final repo = _FakeRepo({null: _page([])});
    await tester.pumpWidget(ProviderScope(
      overrides: [reportsRepositoryProvider.overrideWithValue(repo)],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const MyIssuesScreen(),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Bạn chưa gửi phản ánh nào.'), findsOneWidget);
  });
}
```

- [ ] **Step 3: Run to verify it fails, then implement**

Run: `cd app && flutter test test/my_issues_test.dart` → FAIL.

Create `app/lib/features/reports/my_issues_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import 'issue_detail_screen.dart';
import 'reports_repository.dart';

/// Plain-language status labels (DESIGN.md: color never alone).
String reportStatusLabel(String status, AppLocalizations l10n) =>
    switch (status) {
      'RESOLVED' => l10n.statusResolved,
      _ => l10n.statusOpen,
    };

class MyReportsController extends AsyncNotifier<List<ReportSummary>> {
  String? _nextCursor;
  bool get hasMore => _nextCursor != null;

  @override
  Future<List<ReportSummary>> build() async {
    ref.watch(occupancyScopedProviders);
    final page = await ref.read(reportsRepositoryProvider).listReports();
    _nextCursor = cursorFromNext(page.next);
    return page.results.toList();
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.valueOrNull;
    if (cursor == null || current == null) return;
    final page =
        await ref.read(reportsRepositoryProvider).listReports(cursor: cursor);
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }
}

final myReportsProvider =
    AsyncNotifierProvider<MyReportsController, List<ReportSummary>>(
        MyReportsController.new);

class MyIssuesScreen extends ConsumerWidget {
  const MyIssuesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final reports = ref.watch(myReportsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.issuesTitle)),
      body: switch (reports) {
        AsyncData(:final value) => RefreshIndicator.adaptive(
            onRefresh: () => ref.refresh(myReportsProvider.future),
            child: value.isEmpty
                ? ListView(
                    children: [
                      const SizedBox(height: 120),
                      Center(child: Text(l10n.issuesEmpty)),
                    ],
                  )
                : ListView(
                    children: [
                      for (final report in value)
                        ListTile(
                          minTileHeight: 64,
                          title: Text(report.text,
                              maxLines: 2, overflow: TextOverflow.ellipsis),
                          subtitle: Text(report.locationPathSnapshot,
                              maxLines: 1, overflow: TextOverflow.ellipsis),
                          trailing: Chip(
                            visualDensity: VisualDensity.compact,
                            // DESIGN.md success-bg / info-bg tokens.
                            backgroundColor: report.status == 'RESOLVED'
                                ? const Color(0xFFE7F6EE)
                                : const Color(0xFFEFF8FF),
                            label: Text(
                              reportStatusLabel(report.status, l10n),
                              style: TextStyle(
                                color: report.status == 'RESOLVED'
                                    ? LamToColors.success
                                    : LamToColors.info,
                              ),
                            ),
                          ),
                          onTap: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) =>
                                  IssueDetailScreen(reportId: report.id),
                            ),
                          ),
                        ),
                      if (ref.read(myReportsProvider.notifier).hasMore)
                        Padding(
                          padding: const EdgeInsets.all(16),
                          child: OutlinedButton(
                            onPressed: () => ref
                                .read(myReportsProvider.notifier)
                                .loadMore(),
                            child: Text(l10n.issuesLoadMore),
                          ),
                        ),
                    ],
                  ),
          ),
        AsyncError(:final error) => Center(
            child: Text(failureMessage(Failure.fromObject(error), l10n)),
          ),
        _ => const Center(child: CircularProgressIndicator.adaptive()),
      },
    );
  }
}
```

`IssueDetailScreen` arrives in Task 7; to keep this task independently green, create the minimal placeholder now as `app/lib/features/reports/issue_detail_screen.dart`:

```dart
import 'package:flutter/material.dart';

/// Filled in by the issue-detail task; placeholder keeps the list navigable.
class IssueDetailScreen extends StatelessWidget {
  const IssueDetailScreen({required this.reportId, super.key});
  final int reportId;

  @override
  Widget build(BuildContext context) =>
      Scaffold(appBar: AppBar(title: Text('#$reportId')));
}
```

- [ ] **Step 4: Wire the Issues tab**

In `home_shell.dart`, replace the index-2 placeholder with `const MyIssuesScreen()` (import `../reports/my_issues_screen.dart`).

- [ ] **Step 5: Run the tests**

Run: `cd app && flutter test test/my_issues_test.dart test/app_routing_test.dart`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features/reports/my_issues_screen.dart \
        app/lib/features/reports/issue_detail_screen.dart \
        app/lib/features/shell/home_shell.dart app/lib/l10n app/test/my_issues_test.dart
git commit -m "feat(app): my-issues list with cursor pagination and status chips"
```

---

### Task 7: Issue-detail timeline + authenticated photos + rate work

The §6.3(5) detail: plain-language ordered timeline (submitted → triage → case → work → completion), the resident's photos rendered through the authenticated client, and the 1–5 rating sheet shown when `canRate`.

**Files:**
- Create: `app/lib/core/authenticated_image.dart`
- Modify: `app/lib/features/reports/issue_detail_screen.dart` (replace the Task-6 placeholder)
- Modify: `app/lib/l10n/app_en.arb`, `app_vi.arb`
- Test: `app/test/issue_detail_test.dart`

**Interfaces:**
- Consumes: `reportDetailProvider`, `reportsRepositoryProvider`, `dioProvider`, `ReportDetail`/`ReportCase`/`ReportWorkOrder`/`ReportPhoto`, `failureMessage`.
- Produces: full `IssueDetailScreen(reportId)`; `AuthenticatedImage(url, {width, height})`; `RateWorkSheet` (private to the screen file).

- [ ] **Step 1: Add the l10n keys**

`app_en.arb`:

```json
  "timelineSubmitted": "Report submitted",
  "timelineTriagePending": "Waiting for staff review",
  "timelineTriageDone": "Reviewed by staff",
  "timelineCase": "Grouped into case: {category}",
  "@timelineCase": {"placeholders": {"category": {"type": "String"}}},
  "timelineWork": "Work order {status}, deadline {deadline}",
  "@timelineWork": {"placeholders": {"status": {"type": "String"}, "deadline": {"type": "String"}}},
  "timelineCompleted": "Work completed",
  "rateWorkCta": "Rate this work",
  "rateWorkTitle": "How was the work?",
  "rateCommentLabel": "Comment (optional)",
  "rateSubmit": "Send rating",
  "rateThanks": "Thank you for your rating.",
  "workStatusAssigned": "Assigned",
  "workStatusInProgress": "In progress",
  "workStatusAwaiting": "Awaiting acceptance",
  "workStatusAccepted": "Accepted",
  "workStatusClosed": "Closed",
  "workStatusCancelled": "Cancelled"
```

`app_vi.arb`:

```json
  "timelineSubmitted": "Đã gửi phản ánh",
  "timelineTriagePending": "Đang chờ ban quản lý xem xét",
  "timelineTriageDone": "Ban quản lý đã xem xét",
  "timelineCase": "Đã ghép vào yêu cầu xử lý: {category}",
  "@timelineCase": {"placeholders": {"category": {"type": "String"}}},
  "timelineWork": "Công việc {status}, hạn {deadline}",
  "@timelineWork": {"placeholders": {"status": {"type": "String"}, "deadline": {"type": "String"}}},
  "timelineCompleted": "Công việc đã hoàn thành",
  "rateWorkCta": "Đánh giá công việc",
  "rateWorkTitle": "Công việc thế nào?",
  "rateCommentLabel": "Nhận xét (không bắt buộc)",
  "rateSubmit": "Gửi đánh giá",
  "rateThanks": "Cảm ơn bạn đã đánh giá.",
  "workStatusAssigned": "Đã giao",
  "workStatusInProgress": "Đang thực hiện",
  "workStatusAwaiting": "Chờ nghiệm thu",
  "workStatusAccepted": "Đã nghiệm thu",
  "workStatusClosed": "Đã đóng",
  "workStatusCancelled": "Đã hủy"
```

Run: `cd app && flutter gen-l10n`

- [ ] **Step 2: Write the failing test**

Create `app/test/issue_detail_test.dart`:

```dart
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
    expect(find.text('Đã gửi phản ánh'), findsOneWidget);
    expect(find.text('Ban quản lý đã xem xét'), findsOneWidget);
    expect(find.textContaining('Đã ghép vào yêu cầu xử lý'), findsOneWidget);
    expect(find.textContaining('Đã nghiệm thu'), findsOneWidget);
    expect(find.text('Công việc đã hoàn thành'), findsOneWidget);
    expect(find.text('Đánh giá công việc'), findsNothing);
  });

  testWidgets('rates eligible work with 1-5 and refreshes', (tester) async {
    final repo = _FakeRepo(_detail(canRate: true));
    await _pump(tester, repo);
    await tester.tap(find.text('Đánh giá công việc'));
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.star_border).at(3)); // 4 stars
    await tester.tap(find.text('Gửi đánh giá'));
    await tester.pumpAndSettle();

    expect(repo.ratings.single, (9, 4, ''));
    expect(find.text('Cảm ơn bạn đã đánh giá.'), findsOneWidget);
    expect(find.text('Đánh giá công việc'), findsNothing); // refreshed
  });
}
```

- [ ] **Step 3: Run to verify it fails, then implement**

Run: `cd app && flutter test test/issue_detail_test.dart` → FAIL (placeholder screen has no timeline).

Create `app/lib/core/authenticated_image.dart`:

```dart
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers.dart';

/// Fetches a signed relative URL through the shared Dio (knox token attached)
/// and renders the bytes. Image.network cannot carry our auth header.
class AuthenticatedImage extends ConsumerWidget {
  const AuthenticatedImage(this.url, {this.width, this.height, super.key});

  final String url;
  final double? width;
  final double? height;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dio = ref.watch(dioProvider);
    return FutureBuilder<Response<List<int>>>(
      future: dio.get<List<int>>(
        url,
        options: Options(responseType: ResponseType.bytes),
      ),
      builder: (context, snapshot) {
        if (snapshot.hasData && snapshot.data?.data != null) {
          return Image.memory(
            Uint8List.fromList(snapshot.data!.data!),
            width: width,
            height: height,
            fit: BoxFit.cover,
          );
        }
        final placeholder = snapshot.hasError
            ? const Icon(Icons.broken_image_outlined)
            : const Center(child: CircularProgressIndicator.adaptive());
        return SizedBox(width: width, height: height, child: placeholder);
      },
    );
  }
}
```

Replace `app/lib/features/reports/issue_detail_screen.dart` with:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/authenticated_image.dart';
import '../../core/failure.dart';
import '../../l10n/app_localizations.dart';
import 'reports_repository.dart';

String workStatusLabel(String status, AppLocalizations l10n) =>
    switch (status) {
      'ASSIGNED' => l10n.workStatusAssigned,
      'IN_PROGRESS' => l10n.workStatusInProgress,
      'AWAITING_ACCEPTANCE' => l10n.workStatusAwaiting,
      'ACCEPTED' => l10n.workStatusAccepted,
      'CLOSED' => l10n.workStatusClosed,
      'CANCELLED' => l10n.workStatusCancelled,
      _ => status,
    };

String _date(DateTime value) => DateFormat('dd/MM/yyyy').format(value.toLocal());

class IssueDetailScreen extends ConsumerWidget {
  const IssueDetailScreen({required this.reportId, super.key});
  final int reportId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final detail = ref.watch(reportDetailProvider(reportId));
    return Scaffold(
      appBar: AppBar(title: Text('#$reportId')),
      body: switch (detail) {
        AsyncData(:final value) => _body(context, ref, l10n, value),
        AsyncError(:final error) => Center(
            child: Text(failureMessage(Failure.fromObject(error), l10n)),
          ),
        _ => const Center(child: CircularProgressIndicator.adaptive()),
      },
    );
  }

  Widget _body(BuildContext context, WidgetRef ref, AppLocalizations l10n,
      ReportDetail report) {
    final steps = <(IconData, String)>[
      (Icons.send_outlined,
          '${l10n.timelineSubmitted} · ${_date(report.createdAt)}'),
      if (report.triageStatus == 'SUCCEEDED' ||
          report.triageStatus == 'NEEDS_MANUAL' ||
          report.cases.isNotEmpty)
        (Icons.fact_check_outlined, l10n.timelineTriageDone)
      else
        (Icons.hourglass_empty, l10n.timelineTriagePending),
      for (final caseItem in report.cases) ...[
        (Icons.folder_open_outlined, l10n.timelineCase(caseItem.category)),
        for (final work in caseItem.workOrders) ...[
          (
            Icons.build_outlined,
            l10n.timelineWork(
              workStatusLabel(work.status, l10n),
              _date(work.deadlineAt),
            )
          ),
          if (work.completedAt != null)
            (Icons.check_circle_outline,
                '${l10n.timelineCompleted} · ${_date(work.completedAt!)}'),
        ],
      ],
    ];
    final rateable = [
      for (final caseItem in report.cases)
        for (final work in caseItem.workOrders)
          if (work.canRate) work,
    ];

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(report.text, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 4),
        Text('${report.locationPathSnapshot} · ${report.unitLabel}',
            style: Theme.of(context).textTheme.bodySmall),
        if (report.photos.isNotEmpty) ...[
          const SizedBox(height: 12),
          SizedBox(
            height: 96,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: [
                for (final photo in report.photos)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(10),
                      child: AuthenticatedImage(photo.downloadUrl,
                          width: 96, height: 96),
                    ),
                  ),
              ],
            ),
          ),
        ],
        const SizedBox(height: 16),
        for (final (icon, label) in steps)
          ListTile(
            minTileHeight: 48,
            contentPadding: EdgeInsets.zero,
            leading: Icon(icon),
            title: Text(label),
          ),
        for (final work in rateable)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: FilledButton.icon(
              icon: const Icon(Icons.star_outline),
              label: Text(l10n.rateWorkCta),
              onPressed: () => _openRateSheet(context, ref, l10n, work.id),
            ),
          ),
      ],
    );
  }

  Future<void> _openRateSheet(BuildContext context, WidgetRef ref,
      AppLocalizations l10n, int workOrderId) async {
    final rated = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _RateWorkSheet(workOrderId: workOrderId),
    );
    if (rated == true && context.mounted) {
      ref.invalidate(reportDetailProvider(reportId));
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(l10n.rateThanks)));
    }
  }
}

class _RateWorkSheet extends ConsumerStatefulWidget {
  const _RateWorkSheet({required this.workOrderId});
  final int workOrderId;

  @override
  ConsumerState<_RateWorkSheet> createState() => _RateWorkSheetState();
}

class _RateWorkSheetState extends ConsumerState<_RateWorkSheet> {
  int _score = 0;
  final _comment = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: 16 + MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(l10n.rateWorkTitle,
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (var star = 1; star <= 5; star++)
                IconButton(
                  iconSize: 40, // >=44pt effective target with padding
                  icon: Icon(
                      star <= _score ? Icons.star : Icons.star_border),
                  onPressed:
                      _busy ? null : () => setState(() => _score = star),
                ),
            ],
          ),
          TextField(
            controller: _comment,
            maxLength: 500,
            decoration: InputDecoration(labelText: l10n.rateCommentLabel),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!,
                style:
                    TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 8),
          FilledButton(
            onPressed: _busy || _score == 0 ? null : _submit,
            child: Text(l10n.rateSubmit),
          ),
        ],
      ),
    );
  }

  Future<void> _submit() async {
    final l10n = AppLocalizations.of(context)!;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(reportsRepositoryProvider).rateWork(
            workOrderId: widget.workOrderId,
            score: _score,
            comment: _comment.text.trim(),
          );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() => _error = failureMessage(Failure.fromObject(e), l10n));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
```

- [ ] **Step 4: Run the tests**

Run: `cd app && flutter test test/issue_detail_test.dart`
Expected: PASS (2 tests).

- [ ] **Step 5: Full app suite (exit gate)**

Run: `cd app && flutter test`
Expected: PASS — the whole app suite (foundation + all reporting tests) green.

Optional manual smoke against the seeded backend:

```bash
docker compose up -d   # repo root
cd app && flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
# Login as seeded resident -> Report tab: draft, location, photos, submit ->
# Issues tab: list -> detail timeline -> rate accepted work.
```

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/authenticated_image.dart \
        app/lib/features/reports/issue_detail_screen.dart app/lib/l10n \
        app/test/issue_detail_test.dart
git commit -m "feat(app): issue detail timeline with authenticated photos and work rating"
```

---

## Self-review

### Spec coverage map (Reporting slice of §6)

| Spec | Requirement | Task |
|---|---|---|
| §6.3(4) | Required text | Task 5 (`reportMissingFields` gate + test) |
| §6.3(4) | Location picker from `GET /locations` — tree, large rows | Task 4 (56dp rows, drill-down, explicit select) |
| §6.3(4) | ≤5 photos, camera/gallery, max edge 2048 JPEG before upload | Task 5 (`image_picker` native `maxWidth/maxHeight/imageQuality`) |
| §6.3(4) | Text first with `client_ref`; per-photo retry; text never lost | Task 3 (submitter + tests) |
| §6.3(4) | Local draft persists across app kill | Tasks 1 (store) + 5 (autosave/restore + test) |
| §6.3(5) | My-issues list | Task 6 |
| §6.3(5) | Detail timeline: submitted → triage → case → work/deadline → completion → rate 1–5 | Task 7 |
| §6.5 | Widget tests incl. `client_ref` retry → 200 and conflict → 409 | Task 3 (unit: same-ref retry, 409→exception) + Task 5 (widget: conflict copy + fresh ref) |
| §3.5 | Stable ref per draft; 409 handled as already-submitted | Tasks 1–3, 5 |
| §6.2/§6.4 | ARB copy for every string; failure doctrine; no HTTP jargon | Tasks 4–7 (all copy via l10n; `failureMessage`) |
| DESIGN.md | Status color paired with text; plain language before detail; list rows | Tasks 6, 7 |

### Deferred (plan 3 of 3 — Transparency + Account)

Home tab, Ledger list/detail (evidence-level labels + its §6.5 widget test), Account (occupancy switcher, preferences, logout/logout-all), Notifications feed + deep links, FCM `POST /devices` + OS permission consent, and the nightly `integration_test` happy path. Rich visual polish per screen: apply the `impeccable` skill there.

### Placeholder scan

No `TBD`/`add validation`/`similar to Task N`. Task 6 creates a one-line `IssueDetailScreen` placeholder that Task 7 explicitly replaces (a spelled-out ordering seam, with the full replacement code given). Generated builder field names carry a fallback instruction pointing at the exact generated model files (Task 2).

### Type consistency

- `ReportsRepository` method signatures are identical in the abstract class, `DioReportsRepository`, and every fake across Tasks 2, 3, 5, 6, 7.
- `ReportDraft(clientRef, text, locationId, locationLabel, photoPaths)` + `ReportDraftStore.read/write/clear(int occupancyId)` used identically in Tasks 1, 3, 5.
- `PhotoUpload(Status)` / `SubmitOutcome(reportId, photos)` / `ReportConflictException` produced in Task 3, consumed in Task 5.
- `Failure.fromObject` added in Task 5 and used in Tasks 5–7 (Task 4 uses the existing `Failure(code:)` path).
- `cursorFromNext` (Task 2) consumed by `MyReportsController` (Task 6).
- Generated model fields (`ReportSummary.locationPathSnapshot`, `ReportWorkOrder.canRate/completedAt`, `ReportPhoto.downloadUrl`, `Location.parentId`) match the committed `lamto_api` package verbatim.
