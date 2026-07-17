# Flutter Resident App — Transparency + Account Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Flutter resident app (spec §6, plan 3 of 3): the Home tab (fund block, active reports, recent spending, notification bell), the Ledger tab (period-filtered list + plain-language detail with distinct evidence-level labels), the Account tab (occupancy switcher, notification preferences, logout/logout-all), the Notifications feed with deep links, client-side FCM push registration with in-context consent, and the §6.5 `integration_test` happy path.

**Architecture:** Extends the merged Foundation + Reporting app (`app/`) in place, honoring every as-built convention: tab bodies are **body-only** (the shell owns Scaffold/CupertinoPageScaffold chrome; pushed screens own their own Scaffold), repositories wrap the **generated** API classes on the shared interceptor-configured `Dio` with OpenAPI **contract tests** for path constants, building-scoped caches `ref.watch(occupancyScopedProviders)`, and occupancy switching goes through the existing `SessionController.selectOccupancy(me, id)`. One small backend change opens the plan: the feed serializer gains `event_key` so §6.3(8)'s deep links are resolvable (the model field exists; report/ledger ids it carries are already resident-visible in API URLs). Push is a best-effort seam: a `PushTokenSource` abstraction wraps `firebase_messaging`, everything no-ops gracefully when Firebase isn't configured, and widget tests never touch Firebase.

**Tech Stack:** Existing app stack (Flutter, Riverpod 3, dio 5, generated `lamto_api`, `shared_preferences`, `intl`, gen-l10n) + `firebase_core`/`firebase_messaging` (Task 7 only) + `integration_test` (SDK, Task 8). Backend: the established Django/DRF + drf-spectacular pipeline for Task 1.

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md` and `DESIGN.md`):

- **§6.3(3) Home:** fund balance block (**tabular numerals, integer VND**), period inflows/outflows, my active reports, recent published spending, notification bell.
- **§6.3(6) Ledger:** list with period filters; detail **leads with plain language** (what was fixed, why, how much, who approved, payment verified) and an expandable proof section rendering the evidence-level enum: **distinct labels/badges for `LOCAL_SIGNED` vs `CHAIN_CONFIRMED` vs `MISMATCH` (mismatch rendered prominently), hashes/event IDs in mono type only inside the expansion.**
- **§6.3(7) Account:** profile, occupancy switcher, notification preferences, logout, logout-all.
- **§6.3(8) Notifications feed:** in-app list, mark-read, **deep-links into report/ledger details**.
- **§7.4:** deep links resolve through an **allowlisted type→route map** (report, case, ledger entry, notifications feed); **anything else is ignored**; a push can never grant access — the app always re-fetches through the authenticated API; **404/403 on follow-up lands on a safe fallback screen**.
- **§7.5 Consent:** OS permission requested **in context at the first moment push has obvious value (right after first report submission)**, never as an app-launch ambush; in-app per-category preferences from Account.
- **§7.2:** register `POST /devices` after login + OS permission, upsert by `(user, install_id)`; app **re-registers on FCM's token-refresh callback**; logout deactivates that install's device. **An FCM token is never an auth credential.**
- **§6.5:** widget tests for **ledger evidence-label rendering**; **one end-to-end happy path (`integration_test`) against a compose-seeded backend, nightly**.
- **§5.2/DESIGN.md:** `LOCAL_SIGNED` never borrows chain wording; semantic colors always paired with text/icon; Accountability Indigo ≤10%; mono only inside expandable proof; ≥44pt/48dp targets; all copy in ARB files; failure doctrine everywhere (no raw HTTP jargon).
- **No secrets in git:** Firebase platform config (`google-services.json`, `GoogleService-Info.plist`) is a deployment step, not committed by this plan; app code must degrade gracefully without it.

## Verified environment

App commands run from `app/`; backend commands from the repo root:

```bash
# backend (Task 1 + integration test backend):
docker compose up -d db
set -a; . ./.env.example; set +a
export SECRET_KEY=test-secret EVIDENCE_WRITE_SECRET=test-evidence \
       POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
.venv/bin/python -m pytest <path> -q
.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn

# app:
cd app && flutter test            # widget/unit suites
flutter gen-l10n                  # after editing lib/l10n/*.arb
./tool/generate_api.sh            # regenerate packages/lamto_api from the schema
./tool/check_api_generated.sh     # drift gate
```

Generated surfaces this plan consumes (pinned from `app/packages/lamto_api`):

- `LedgerApi.ledgerList({int? xLamToOccupancy, String? cursor, int? month, int? year})` → `PaginatedLedgerEntryListList`; `ledgerRetrieve({required int id})` → `LedgerEntryDetail`
- `FundApi.fundSummaryRetrieve()` → `FundSummary(balanceVnd, periodDays, periodInflowsVnd, periodOutflowsVnd)`
- `NotificationsApi.notificationsList({String? cursor})` → `PaginatedNotificationFeedList`; `notificationsReadCreate({required int id})` → void
- `DevicesApi.devicesCreate({required DeviceRegisterRequest deviceRegisterRequest})` → `Device(installId, platform, active)`; `devicesDestroy({required String installId})` → void
- `MeApi.meNotificationPreferencesPartialUpdate({PatchedNotificationPreferenceUpdateRequest? ...})` → `BuiltList<NotificationPreference>`; request wraps `preferences: BuiltList<NotificationPreferenceUpdateItemRequest(eventCode, emailEnabled?, pushEnabled?)>`
- `AuthApi.authLogoutCreate()` / `authLogoutAllCreate()` → void
- Models: `LedgerEntryList(id, contractorName, actualCostVnd, publishedAt, integrityStatus, evidenceLevel)`; `LedgerEntryDetail(+ proposedAmountVnd?, payload: JsonObject?, verification: Verification?, redactedDocuments, corrections, proof: Proof)`; `Proof(evidenceLevel, anchoringBackend, payloadHash, events: BuiltList<ProofEvent>)`; `ProofEvent(eventId, eventType, status, evidenceLevel, transactionHash)`; `Verification(decision, verifiedBy, verifiedAt)`; `NotificationFeed(id, eventCode, subject, body, createdAt, readAt?)` (+ `eventKey` after Task 1); `NotificationPreference(eventCode, emailEnabled, pushEnabled)`; `DeviceRegisterRequest(installId, fcmToken, platform, appVersion?)`; `Me.notificationPreferences`.

## Design decisions

1. **Backend first, once (Task 1).** `NotificationFeedSerializer` gains `event_key` (`{code}:{entity}:{id}[:...]` — the field already exists on `NotificationDelivery`; the entity ids it exposes are report/ledger ids the resident already sees in API URLs). Schema + Dart client regenerate under both drift gates; no new routes, so the adversarial classifier is untouched. See **A8**: keys are codes/entity/ids only, never sensitive, never auth-granting.
2. **Deep links are one allowlist for both sources.** Push data (`{type, id}` per §7.4) and feed `event_key`s both parse into a sealed `DeepLink` (`report(id)` | `ledger(id)` | `feed`); **case and all other non-report/non-ledger entities fall back to the feed** (see **A2**). A wrong id lands on the pushed detail screen's existing failure state — the §7.4 "safe fallback" (the API re-authorizes; a push can never grant access).
3. **Push behind a seam, off by default.** `PushTokenSource` (requestPermission/getToken/onTokenRefresh) has one Firebase implementation guarded by a `Firebase.initializeApp()` try/catch; without platform config every call resolves to "unsupported" in dev/test (see **A6** for production diagnostic). Registration triggers in context right after the first successful report submission (§7.5) with **permission-requested persisted once per install (A4)**; re-registers on token refresh; deactivates on logout with **retryable/coupled deregistration (A5)**. Widget tests use a fake source.
4. **Preferences are patched one toggle at a time.** The Account screen renders the 5 resident event categories (`report.receipt`, `triage.status`, `work.completed`, `ledger.publication`, `correction.status`) with email+push switches, defaulting to on when `/me` has no row (server semantics), sending a single-item PATCH per flip.
5. **Reuse over new state.** Home reuses `myReportsProvider` (same first page as the Issues tab) and adds only two tiny providers (`fundSummaryProvider`, `recentSpendingProvider`); the Ledger and Feed get cursor controllers mirroring the as-built `MyReportsController`.
6. **Integer VND formatting** via `intl` (`1.500.000 ₫`, Vietnamese grouping, tabular numerals through the Amount text style) in one `formatVnd` helper.

## Execution amendments (2026-07-17)

Mandatory clarifications applied **before** Tasks 1–8. Implementers must treat these as plan law; they supersede conflicting sample code in later task bodies.

### A1. Ledger plain-language story (§6.3(6) complete)

`LedgerEntryDetail` and the detail UI must expose the **full** plain-language story, not only contractor / amount / evidence:

| Story element | Source of truth |
|---|---|
| What was fixed | Resident-visible narrative from entry `payload` (or a dedicated backend field if payload lacks one) — e.g. work summary / title |
| Why | Resident-visible rationale from payload (or dedicated field) |
| Amount | `actualCostVnd` via `formatVnd` |
| Approvers | Who authorized publication / approval (payload or dedicated field); do not invent if absent — extend backend minimally so the story is complete |
| Payment verification | `verification` (`decision`, `verifiedBy`, `verifiedAt`) with `ledgerVerifiedBy` / `ledgerNotVerified` copy |

**Task 4 obligation:** Inspect `LedgerEntryDetail` / resident ledger payload. If “what/why/approvers” are missing as resident-visible fields, extend the backend/detail payload **minimally**, regenerate OpenAPI + Dart client, then teach the UI. Do not fake the story client-side from empty data. Tests assert presence of all five story elements (not only contractor/amount/evidence). Mono hashes remain only inside the expandable proof.

### A2. Case deep-link behavior (documented fallback)

**Decision (this execution):** the resident app does **not** ship a Case detail screen. Per §7.4 allowlist, deep links of type/entity `case` (and other non-report/non-ledger entities such as corrections/work) **safely fall back to the notifications feed** (`DeepLinkFeed`).

Document this in:
- `deep_link.dart` (doc comments on `parsePushLink` / `parseEventKey`)
- `deep_link_test.dart` (`triage.status:case:…` → feed; `type: case` → feed)
- This plan section (source of truth for reviewers)

No resident-visible case destination is added. Unknown types also → feed. Every destination that *is* navigated still re-fetches via the authenticated API.

### A3. Home active reports — API-authoritative status semantics

**Do not** hard-code a one-off `status == 'OPEN'` scattered in the Home widget as the sole definition of “active.”

Report status enum today is `OPEN` / `RESOLVED`. Authoritative “active report” = **not resolved** / status `OPEN` (matches server list semantics for open work).

**Task 3 obligation:** centralize via a shared helper, e.g. `bool isActiveReportStatus(String status)` in the reports feature (same place as `reportStatusLabel` or a tiny `report_status.dart`), used by Home (and available to other surfaces). Home filters with that helper, not a bare magic string inline. Tests continue to show OPEN and hide RESOLVED.

### A4. Push permission requested once per install

Persist a per-install flag (e.g. `SharedPreferences` key keyed by `install_id`, such as `push_permission_requested_<install_id>`) so OS permission is requested **only once** at the first useful moment (after first successful report submission per §7.5). Subsequent report submits must **not** re-prompt if the flag is set, regardless of whether the user granted or denied. Registration still proceeds only when permission is granted and a token is available.

### A5. Device deregistration durable across logout

Best-effort local logout **must not** silently leave the install receiving push indefinitely.

**Required behavior (Task 7 + Account sign-out):**
1. On logout / logout-all: attempt `DELETE /devices/{install_id}` (or equivalent) **before** clearing local session when possible.
2. If deregistration **fails** (network/error): persist `pending_device_deregister_install_id` (or equivalent) so the next authenticated session **retries** deactivation, **or** couple install deactivation to the server logout endpoint so the server deactivates the install as part of logout.
3. Tests cover: successful deregister on logout; failed deregister leaves a retry path (or server-coupled path) — not a silent permanent active install after local session clear.

### A6. Firebase degradation + production diagnostic

Keep graceful degradation for **development and tests** (no platform config → no-op / unsupported; widget tests never touch real Firebase).

**Additionally:** when platform configuration is missing in a **production** build (`kReleaseMode` / non-debug), surface a **visible diagnostic** (e.g. debug-safe log + optional non-blocking in-app banner/snack only if product-appropriate, or at minimum a clear `debugPrint`/`logger` diagnostic that operators can see in crash/log pipelines). Do **not** commit `google-services.json` / `GoogleService-Info.plist`. Dev and test still no-op without config.

### A7. Nightly integration_test job + real-device push smoke checklist

- Wire `app/integration_test/` into an **actual** scheduled CI job (e.g. `.github/workflows/nightly-integration.yml` or equivalent) that runs the happy path against a seeded backend — not README-only prose.
- Add a **separate** real-device push smoke checklist document (e.g. `docs/ops/push-smoke-checklist.md` or under `app/docs/`) covering: permission request, device registration, token refresh re-registration, background/terminated notification-tap routing, logout deregistration.

### A8. `event_key` authorization-neutral and non-sensitive

- `event_key` format remains `{code}:{entity}:{id}[:suffix]` using **codes, entity type names, and opaque numeric/resource ids only**.
- **Never** put PII, free-text bodies, tokens, emails, phone numbers, or secret material in `event_key`.
- Keys are **authorization-neutral**: possession of a key grants nothing; every destination re-fetches through the authenticated API, which re-authorizes. Task 1 tests and notification hooks must keep this contract.

## File Structure

**Backend (Task 1):**
- Modify: `src/lamto/api/serializers.py` (`NotificationFeedSerializer` + `event_key`), `src/lamto/api/tests/test_notifications.py`, `docs/api/openapi-v1.yaml` (regenerated), `app/packages/lamto_api/` (regenerated).

**App create:**
- `app/lib/core/format.dart` — `formatVnd`.
- `app/lib/features/transparency/transparency_repository.dart` — repo + providers + controllers.
- `app/lib/features/home/home_screen.dart`
- `app/lib/features/ledger/evidence_labels.dart`
- `app/lib/features/ledger/ledger_screen.dart`
- `app/lib/features/ledger/ledger_detail_screen.dart`
- `app/lib/features/notifications/deep_link.dart`
- `app/lib/features/notifications/notifications_screen.dart`
- `app/lib/features/account/account_screen.dart`
- `app/lib/features/push/push_token_source.dart`, `app/lib/features/push/push_registrar.dart`
- `app/integration_test/app_test.dart`
- Tests: `app/test/format_test.dart`, `transparency_repository_contract_test.dart`, `transparency_repository_test.dart`, `home_screen_test.dart`, `evidence_labels_test.dart`, `ledger_screens_test.dart`, `deep_link_test.dart`, `notifications_screen_test.dart`, `account_screen_test.dart`, `push_registrar_test.dart`.

**App modify:**
- `app/lib/features/auth/auth_repository.dart` (+`logout`, `logoutAll`), `app/lib/features/auth/session_controller.dart` (signOut upgrade), `app/lib/features/shell/home_shell.dart` (tabs 0/3/4), `app/lib/features/reports/report_form_screen.dart` (push consent hook), `app/lib/core/providers.dart` (push providers, Task 7), `app/lib/l10n/*.arb` (per task), `app/pubspec.yaml` (Task 7/8 deps).

---

### Task 1: Backend — expose `event_key` in the notifications feed, regenerate both clients

**Files:**
- Modify: `src/lamto/api/serializers.py`, `src/lamto/api/tests/test_notifications.py`
- Regenerate: `docs/api/openapi-v1.yaml`, `app/packages/lamto_api/`

**Interfaces:**
- Produces: `NotificationFeed.event_key` on the wire → generated `NotificationFeed.eventKey` (Dart). Format `{code}:{entity}:{id}[:{suffix}]` (e.g. `report.receipt:report:5`, `ledger.publication:entry:42`).
- **A8:** `event_key` is authorization-neutral and non-sensitive (codes/entity/ids only; no PII, bodies, or tokens). Document in serializer help_text; tests may assert shape does not embed free text beyond the opaque key contract.

- [ ] **Step 1: Write the failing backend test**

In `src/lamto/api/tests/test_notifications.py`, inside `NotificationFeedTests`, add:

```python
    def test_feed_exposes_event_key_for_deep_links(self):
        resp = self.client.get(reverse("api:notifications"), headers=self._occ())
        assert resp.status_code == 200
        row = resp.json()["results"][0]
        assert row["event_key"] == "ledger.publication:x:1"
```

(The class's `setUp` already creates a delivery with `event_key="ledger.publication:x:1"`.)

Also assert (same test or sibling) that the exposed key is the stored opaque reference only — no subject/body fields are concatenated into `event_key`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_notifications.py -q`
Expected: FAIL — `KeyError: 'event_key'`.

- [ ] **Step 3: Add the field**

In `src/lamto/api/serializers.py`, add to `NotificationFeedSerializer` (after `event_code`):

```python
    event_key = serializers.CharField(
        help_text=(
            "Deep-link reference '{code}:{entity}:{id}' (spec 6.3/7.4). Entity ids "
            "are resident-visible resources the API re-authorizes on fetch."
        ),
    )
```

(`resident_feed` returns model instances; `NotificationDelivery.event_key` maps automatically.)

- [ ] **Step 4: Run backend tests + regenerate the schema**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_notifications.py -q` → PASS.
Run: `.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn`
Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py -q` → PASS (drift gate green against the regenerated file).

- [ ] **Step 5: Regenerate the Dart client**

```bash
cd app && ./tool/generate_api.sh && ./tool/check_api_generated.sh
grep -n "eventKey" packages/lamto_api/lib/src/model/notification_feed.dart | head -2
flutter test   # whole app suite still green (additive field)
```

Expected: `String get eventKey;` appears; gate prints `OK`; suite passes.

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add src/lamto/api/serializers.py src/lamto/api/tests/test_notifications.py \
        docs/api/openapi-v1.yaml app/packages/lamto_api
git commit -m "feat(api): expose event_key in notifications feed for app deep links"
```

---

### Task 2: Transparency repository + logout methods + VND formatter

**Files:**
- Create: `app/lib/features/transparency/transparency_repository.dart`, `app/lib/core/format.dart`
- Modify: `app/lib/features/auth/auth_repository.dart`
- Test: `app/test/transparency_repository_contract_test.dart`, `app/test/transparency_repository_test.dart`, `app/test/format_test.dart`

**Interfaces:**
- Produces:
  - `formatVnd(int amount) -> String` — `1500000` → `'1.500.000 ₫'`.
  - `abstract class TransparencyRepository` — `Future<FundSummary> fetchFundSummary()`; `Future<PaginatedLedgerEntryListList> listLedger({String? cursor, int? year, int? month})`; `Future<LedgerEntryDetail> fetchLedgerEntry(int id)`; `Future<PaginatedNotificationFeedList> listNotifications({String? cursor})`; `Future<void> markNotificationRead(int id)`; `Future<Device> registerDevice({required String installId, required String fcmToken, required String platform, String appVersion = ''})`; `Future<void> deactivateDevice(String installId)`; `Future<List<NotificationPreference>> updatePreference({required String eventCode, bool? emailEnabled, bool? pushEnabled})`.
  - `DioTransparencyRepository`; `TransparencyApiPaths` constants; `transparencyRepositoryProvider`; `fundSummaryProvider`, `recentSpendingProvider` (`FutureProvider.autoDispose`, both watch `occupancyScopedProviders`); `ledgerDetailProvider` (`FutureProvider.autoDispose.family<LedgerEntryDetail, int>`).
  - `AuthRepository.logout()` / `logoutAll()` (+ `DioAuthRepository` impls, + `AuthApiPaths.logout`/`logoutAll`).

- [ ] **Step 1: Write the failing tests**

Create `app/test/format_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/format.dart';

void main() {
  test('formatVnd groups with dots and appends dong sign', () {
    expect(formatVnd(0), '0 ₫');
    expect(formatVnd(1500000), '1.500.000 ₫');
    expect(formatVnd(-250000), '-250.000 ₫');
  });
}
```

Create `app/test/transparency_repository_contract_test.dart` (same schema-scrape pattern as the existing contract tests):

```dart
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/auth/auth_repository.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';

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

  test('all transparency path constants exist in OpenAPI', () {
    for (final path in [
      TransparencyApiPaths.ledger,
      TransparencyApiPaths.ledgerDetail,
      TransparencyApiPaths.fundSummary,
      TransparencyApiPaths.notifications,
      TransparencyApiPaths.notificationRead,
      TransparencyApiPaths.devices,
      TransparencyApiPaths.deviceDelete,
      TransparencyApiPaths.mePreferences,
      AuthApiPaths.logout,
      AuthApiPaths.logoutAll,
    ]) {
      expect(openApiPaths, contains(path), reason: path);
    }
  });
}
```

Create `app/test/transparency_repository_test.dart`:

```dart
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
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
  late DioTransparencyRepository repo;
  late RequestOptions lastRequest;

  setUp(() {
    adapter = _MockAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'http://x'));
    dio.httpClientAdapter = adapter;
    repo = DioTransparencyRepository(dio);
  });

  void answerWith(int status, Object body) {
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
      lastRequest = inv.positionalArguments[0] as RequestOptions;
      return _json(status, body);
    });
  }

  test('listLedger passes year/month/cursor query params', () async {
    answerWith(200, {'next': null, 'previous': null, 'results': []});
    await repo.listLedger(year: 2026, month: 7, cursor: 'abc');
    expect(lastRequest.path, '/api/v1/ledger');
    expect(lastRequest.queryParameters['year'], 2026);
    expect(lastRequest.queryParameters['month'], 7);
    expect(lastRequest.queryParameters['cursor'], 'abc');
  });

  test('updatePreference PATCHes one item and parses the list', () async {
    answerWith(200, [
      {'event_code': 'ledger.publication', 'email_enabled': true, 'push_enabled': false},
    ]);
    final prefs = await repo.updatePreference(
        eventCode: 'ledger.publication', pushEnabled: false);
    expect(lastRequest.method, 'PATCH');
    expect(lastRequest.path, '/api/v1/me/notification-preferences');
    final sent = lastRequest.data;
    final map = sent is String ? jsonDecode(sent) : sent;
    expect(map['preferences'][0]['event_code'], 'ledger.publication');
    expect(map['preferences'][0]['push_enabled'], false);
    expect(map['preferences'][0].containsKey('email_enabled'), isFalse);
    expect(prefs.single.pushEnabled, isFalse);
  });

  test('registerDevice posts install/token/platform', () async {
    answerWith(200, {'install_id': 'i-1', 'platform': 'ANDROID', 'active': true});
    final device = await repo.registerDevice(
        installId: 'i-1', fcmToken: 'tok', platform: 'ANDROID', appVersion: '1.0');
    expect(device.installId, 'i-1');
    final map = jsonDecode(lastRequest.data as String);
    expect(map['fcm_token'], 'tok');
  });

  test('markNotificationRead posts to the read route', () async {
    answerWith(204, '');
    await repo.markNotificationRead(9);
    expect(lastRequest.path, '/api/v1/notifications/9/read');
    expect(lastRequest.method, 'POST');
  });
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd app && flutter test test/format_test.dart test/transparency_repository_contract_test.dart test/transparency_repository_test.dart`
Expected: FAIL — the new files don't exist; `AuthApiPaths.logout` undefined.

- [ ] **Step 3: Implement**

Create `app/lib/core/format.dart`:

```dart
import 'package:intl/intl.dart';

/// Integer VND with Vietnamese grouping (DESIGN.md: tabular numerals come
/// from the Amount text style; this handles digits + currency sign).
final _vnd = NumberFormat.decimalPattern('vi');

String formatVnd(int amount) => '${_vnd.format(amount)} ₫';
```

In `app/lib/features/auth/auth_repository.dart`: add to `AuthApiPaths`:

```dart
  static const logout = '/api/v1/auth/logout';
  static const logoutAll = '/api/v1/auth/logout-all';
```

Add to `AuthRepository`:

```dart
  Future<void> logout();
  Future<void> logoutAll();
```

Add to `DioAuthRepository`:

```dart
  @override
  Future<void> logout() async {
    await _auth.authLogoutCreate();
  }

  @override
  Future<void> logoutAll() async {
    await _auth.authLogoutAllCreate();
  }
```

(Any existing test fakes implementing `AuthRepository` gain the two methods as `async {}` no-ops — the analyzer will point at each.)

Create `app/lib/features/transparency/transparency_repository.dart`:

```dart
import 'package:built_collection/built_collection.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/providers.dart';

/// Paths used by the transparency/account APIs — contract-tested vs OpenAPI.
abstract final class TransparencyApiPaths {
  static const ledger = '/api/v1/ledger';
  static const ledgerDetail = '/api/v1/ledger/{id}';
  static const fundSummary = '/api/v1/fund/summary';
  static const notifications = '/api/v1/notifications';
  static const notificationRead = '/api/v1/notifications/{id}/read';
  static const devices = '/api/v1/devices';
  static const deviceDelete = '/api/v1/devices/{install_id}';
  static const mePreferences = '/api/v1/me/notification-preferences';
}

abstract class TransparencyRepository {
  Future<FundSummary> fetchFundSummary();
  Future<PaginatedLedgerEntryListList> listLedger(
      {String? cursor, int? year, int? month});
  Future<LedgerEntryDetail> fetchLedgerEntry(int id);
  Future<PaginatedNotificationFeedList> listNotifications({String? cursor});
  Future<void> markNotificationRead(int id);
  Future<Device> registerDevice({
    required String installId,
    required String fcmToken,
    required String platform,
    String appVersion = '',
  });
  Future<void> deactivateDevice(String installId);
  Future<List<NotificationPreference>> updatePreference({
    required String eventCode,
    bool? emailEnabled,
    bool? pushEnabled,
  });
}

/// Thin wrapper over the generated dart-dio APIs on the shared Dio
/// (token + X-LamTo-Occupancy interceptors already installed).
class DioTransparencyRepository implements TransparencyRepository {
  DioTransparencyRepository(Dio dio)
      : _ledger = LedgerApi(dio, standardSerializers),
        _fund = FundApi(dio, standardSerializers),
        _notifications = NotificationsApi(dio, standardSerializers),
        _devices = DevicesApi(dio, standardSerializers),
        _me = MeApi(dio, standardSerializers);

  final LedgerApi _ledger;
  final FundApi _fund;
  final NotificationsApi _notifications;
  final DevicesApi _devices;
  final MeApi _me;

  @override
  Future<FundSummary> fetchFundSummary() async {
    final res = await _fund.fundSummaryRetrieve();
    return res.data!;
  }

  @override
  Future<PaginatedLedgerEntryListList> listLedger(
      {String? cursor, int? year, int? month}) async {
    final res =
        await _ledger.ledgerList(cursor: cursor, year: year, month: month);
    return res.data!;
  }

  @override
  Future<LedgerEntryDetail> fetchLedgerEntry(int id) async {
    final res = await _ledger.ledgerRetrieve(id: id);
    return res.data!;
  }

  @override
  Future<PaginatedNotificationFeedList> listNotifications(
      {String? cursor}) async {
    final res = await _notifications.notificationsList(cursor: cursor);
    return res.data!;
  }

  @override
  Future<void> markNotificationRead(int id) async {
    await _notifications.notificationsReadCreate(id: id);
  }

  @override
  Future<Device> registerDevice({
    required String installId,
    required String fcmToken,
    required String platform,
    String appVersion = '',
  }) async {
    final res = await _devices.devicesCreate(
      deviceRegisterRequest: DeviceRegisterRequest(
        (b) => b
          ..installId = installId
          ..fcmToken = fcmToken
          ..platform = platform
          ..appVersion = appVersion,
      ),
    );
    return res.data!;
  }

  @override
  Future<void> deactivateDevice(String installId) async {
    await _devices.devicesDestroy(installId: installId);
  }

  @override
  Future<List<NotificationPreference>> updatePreference({
    required String eventCode,
    bool? emailEnabled,
    bool? pushEnabled,
  }) async {
    final res = await _me.meNotificationPreferencesPartialUpdate(
      patchedNotificationPreferenceUpdateRequest:
          PatchedNotificationPreferenceUpdateRequest(
        (b) => b
          ..preferences = ListBuilder<NotificationPreferenceUpdateItemRequest>([
            NotificationPreferenceUpdateItemRequest(
              (i) => i
                ..eventCode = eventCode
                ..emailEnabled = emailEnabled
                ..pushEnabled = pushEnabled,
            ),
          ]),
      ),
    );
    return res.data!.toList();
  }
}

final transparencyRepositoryProvider = Provider<TransparencyRepository>(
  (ref) => DioTransparencyRepository(ref.watch(dioProvider)),
);

/// Building-scoped caches rebuild on occupancy change (providers.dart contract).
final fundSummaryProvider = FutureProvider.autoDispose<FundSummary>((ref) {
  ref.watch(occupancyScopedProviders);
  return ref.watch(transparencyRepositoryProvider).fetchFundSummary();
});

/// First few published entries for the Home "recent spending" block.
final recentSpendingProvider =
    FutureProvider.autoDispose<List<LedgerEntryList>>((ref) async {
  ref.watch(occupancyScopedProviders);
  final page =
      await ref.watch(transparencyRepositoryProvider).listLedger();
  return page.results.take(3).toList();
});

final ledgerDetailProvider =
    FutureProvider.autoDispose.family<LedgerEntryDetail, int>((ref, id) {
  ref.watch(occupancyScopedProviders);
  return ref.watch(transparencyRepositoryProvider).fetchLedgerEntry(id);
});
```

If a generated builder field name differs, take the exact name from the model file under `app/packages/lamto_api/lib/src/model/` — the wire names are `install_id`, `fcm_token`, `platform`, `app_version`, `event_code`, `email_enabled`, `push_enabled`, `preferences`.

- [ ] **Step 4: Run to verify they pass**

Run: `cd app && flutter test test/format_test.dart test/transparency_repository_contract_test.dart test/transparency_repository_test.dart`
Expected: PASS (6 tests). Then `flutter test` — the whole suite (fakes updated with the two logout no-ops).

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/format.dart app/lib/features/transparency/transparency_repository.dart \
        app/lib/features/auth/auth_repository.dart app/test/format_test.dart \
        app/test/transparency_repository_contract_test.dart app/test/transparency_repository_test.dart \
        app/test
git commit -m "feat(app): transparency repository, logout methods, and VND formatter"
```

---

### Task 3: Home tab — fund block, active reports, recent spending, bell

Body-only screen (the shell owns chrome), per the DESIGN.md fund-balance signature pattern: large tabular amount + secondary stat grid, then my open reports and recent published spending, with a bell that pushes the feed (screen arrives in Task 5 — this task links to a placeholder).

**Files:**
- Create: `app/lib/features/home/home_screen.dart`
- Create: `app/lib/features/notifications/notifications_screen.dart` (placeholder, replaced in Task 5)
- Modify: `app/lib/features/shell/home_shell.dart` (tab 0)
- Modify: `app/lib/l10n/app_en.arb`, `app_vi.arb`
- Test: `app/test/home_screen_test.dart`

**Interfaces:**
- Consumes: `fundSummaryProvider`, `recentSpendingProvider`, `myReportsProvider` + `reportStatusLabel` (as-built `my_issues_screen.dart`), `formatVnd`, `IssueDetailScreen`, `LedgerDetailScreen` placeholder? — no: recent-spending rows navigate in Task 4; this task renders rows without navigation and Task 4 adds the tap. Keep rows tappable only after Task 4? Simpler: rows push `LedgerDetailScreen` which Task 4 creates — so this task creates a minimal `LedgerDetailScreen` placeholder too? No — to keep one seam, recent-spending rows are non-tappable in this task; Task 4 Step 6 makes them tap through.
- Produces: `HomeScreen` (body-only); placeholder `NotificationsScreen`.

- [ ] **Step 1: Add the l10n keys**

`app_en.arb`:

```json
  "homeFundTitle": "Maintenance fund",
  "homeFundInflows": "In (30d)",
  "homeFundOutflows": "Out (30d)",
  "homeActiveReports": "My open reports",
  "homeRecentSpending": "Recently published spending",
  "homeNoActiveReports": "No open reports.",
  "homeNoSpending": "No published spending yet.",
  "notificationsTitle": "Notifications"
```

`app_vi.arb`:

```json
  "homeFundTitle": "Quỹ bảo trì",
  "homeFundInflows": "Thu (30 ngày)",
  "homeFundOutflows": "Chi (30 ngày)",
  "homeActiveReports": "Phản ánh đang mở",
  "homeRecentSpending": "Khoản chi mới công bố",
  "homeNoActiveReports": "Không có phản ánh đang mở.",
  "homeNoSpending": "Chưa có khoản chi nào được công bố.",
  "notificationsTitle": "Thông báo"
```

Run: `cd app && flutter gen-l10n`

- [ ] **Step 2: Write the failing test**

Create `app/test/home_screen_test.dart`:

```dart
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
}
```

Note: the fakes use `noSuchMethod` for unimplemented members so they stay short; only the methods the screen calls are real.

- [ ] **Step 3: Run to verify it fails, then implement**

Run: `cd app && flutter test test/home_screen_test.dart` → FAIL.

Create `app/lib/features/notifications/notifications_screen.dart` (placeholder; Task 5 replaces it):

```dart
import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';

/// Filled in by the notifications task; placeholder keeps the bell navigable.
class NotificationsScreen extends StatelessWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar:
            AppBar(title: Text(AppLocalizations.of(context)!.notificationsTitle)),
      );
}
```

Create `app/lib/features/home/home_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/format.dart';
import '../../l10n/app_localizations.dart';
import '../notifications/notifications_screen.dart';
import '../reports/issue_detail_screen.dart';
import '../reports/my_issues_screen.dart';
import '../transparency/transparency_repository.dart';

/// Home tab (spec 6.3(3)): fund block, period flows, my open reports, recent
/// published spending, notification bell. Body-only: the shell owns chrome.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final fund = ref.watch(fundSummaryProvider);
    final reports = ref.watch(myReportsProvider);
    final spending = ref.watch(recentSpendingProvider);

    return Material(
      color: Colors.transparent,
      child: RefreshIndicator.adaptive(
        onRefresh: () async {
          ref.invalidate(fundSummaryProvider);
          ref.invalidate(recentSpendingProvider);
          await ref.refresh(myReportsProvider.future);
        },
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(l10n.homeFundTitle,
                      style: Theme.of(context).textTheme.titleMedium),
                ),
                IconButton(
                  iconSize: 28,
                  icon: const Icon(Icons.notifications_outlined),
                  tooltip: l10n.notificationsTitle,
                  onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(
                        builder: (_) => const NotificationsScreen()),
                  ),
                ),
              ],
            ),
            switch (fund) {
              AsyncData(:final value) => _fundBlock(context, l10n, value),
              AsyncError(:final error) =>
                Text(failureMessage(Failure.fromObject(error), l10n)),
              _ => const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Center(child: CircularProgressIndicator.adaptive()),
                ),
            },
            const SizedBox(height: 24),
            Text(l10n.homeActiveReports,
                style: Theme.of(context).textTheme.titleMedium),
            switch (reports) {
              AsyncData(:final value) => _activeReports(context, l10n, value),
              AsyncError() => const SizedBox.shrink(),
              _ => const SizedBox.shrink(),
            },
            const SizedBox(height: 24),
            Text(l10n.homeRecentSpending,
                style: Theme.of(context).textTheme.titleMedium),
            switch (spending) {
              AsyncData(:final value) => _recentSpending(context, l10n, value),
              AsyncError(:final error) =>
                Text(failureMessage(Failure.fromObject(error), l10n)),
              _ => const SizedBox.shrink(),
            },
          ],
        ),
      ),
    );
  }

  /// DESIGN.md fund-balance signature: large tabular amount + stat grid.
  Widget _fundBlock(
      BuildContext context, AppLocalizations l10n, FundSummary fund) {
    final amountStyle = Theme.of(context).textTheme.headlineMedium?.copyWith(
      fontWeight: FontWeight.w700,
      fontFeatures: const [FontFeature.tabularFigures()],
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(formatVnd(fund.balanceVnd), style: amountStyle),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: Text('${l10n.homeFundInflows}: '
                  '${formatVnd(fund.periodInflowsVnd)}'),
            ),
            Expanded(
              child: Text('${l10n.homeFundOutflows}: '
                  '${formatVnd(fund.periodOutflowsVnd)}'),
            ),
          ],
        ),
      ],
    );
  }

  Widget _activeReports(
      BuildContext context, AppLocalizations l10n, List<ReportSummary> all) {
    // A3: use shared isActiveReportStatus — not a bare inline magic string.
    final open = all.where((r) => isActiveReportStatus(r.status)).take(3).toList();
    if (open.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(l10n.homeNoActiveReports),
      );
    }
    return Column(
      children: [
        for (final report in open)
          ListTile(
            minTileHeight: 56,
            contentPadding: EdgeInsets.zero,
            title: Text(report.text,
                maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text(reportStatusLabel(report.status, l10n)),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(
                  builder: (_) => IssueDetailScreen(reportId: report.id)),
            ),
          ),
      ],
    );
  }

  Widget _recentSpending(BuildContext context, AppLocalizations l10n,
      List<LedgerEntryList> entries) {
    if (entries.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(l10n.homeNoSpending),
      );
    }
    return Column(
      children: [
        for (final entry in entries)
          ListTile(
            minTileHeight: 56,
            contentPadding: EdgeInsets.zero,
            title: Text(entry.contractorName,
                maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text(formatVnd(entry.actualCostVnd)),
            // Task "Ledger" wires the tap-through to LedgerDetailScreen.
          ),
      ],
    );
  }
}
```

Add `import 'dart:ui' show FontFeature;` if the analyzer asks (usually re-exported via material).

- [ ] **Step 4: Wire tab 0**

In `app/lib/features/shell/home_shell.dart`, import `../home/home_screen.dart` and replace the index-0 placeholder with `const HomeScreen()`.

- [ ] **Step 5: Run the tests**

Run: `cd app && flutter test test/home_screen_test.dart test/app_routing_test.dart`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features/home app/lib/features/notifications/notifications_screen.dart \
        app/lib/features/shell/home_shell.dart app/lib/l10n app/test/home_screen_test.dart
git commit -m "feat(app): home tab with fund block, open reports, recent spending"
```

---

### Task 4: Ledger tab — period-filtered list + plain-language detail with evidence labels

The §6.3(6) surface and its §6.5-mandated widget test: distinct `LOCAL_SIGNED` / `CHAIN_CONFIRMED` / `MISMATCH` presentation, mismatch prominent, mono only inside the expandable proof.

**Files:**
- Create: `app/lib/features/ledger/evidence_labels.dart`, `app/lib/features/ledger/ledger_screen.dart`, `app/lib/features/ledger/ledger_detail_screen.dart`
- Modify: `app/lib/features/shell/home_shell.dart` (tab 3), `app/lib/features/home/home_screen.dart` (spending tap-through), `app/lib/l10n/*.arb`
- Test: `app/test/evidence_labels_test.dart`, `app/test/ledger_screens_test.dart`

**Interfaces:**
- Consumes: `transparencyRepositoryProvider`, `ledgerDetailProvider`, `cursorFromNext` (reports repo), `formatVnd`, `LamToColors`, `occupancyScopedProviders`.
- Produces:
  - `EvidenceBadge(level)` widget; `evidenceLevelLabel(String, l10n)`, `integrityStatusLabel(String, l10n)`.
  - `LedgerListController` (`AsyncNotifierProvider` `ledgerListProvider`) with `setPeriod(int? year, int? month)`, `loadMore()`, `hasMore`.
  - `LedgerScreen` (body-only, tab 3); `LedgerDetailScreen(entryId)` (pushed, own Scaffold).

- [ ] **Step 1: Add the l10n keys**

`app_en.arb`:

```json
  "ledgerTitle": "Building ledger",
  "ledgerEmpty": "No published spending for this period.",
  "ledgerAllTime": "All",
  "ledgerLoadMore": "Load more",
  "ledgerPublishedOn": "Published {date}",
  "@ledgerPublishedOn": {"placeholders": {"date": {"type": "String"}}},
  "ledgerAmount": "Amount",
  "ledgerContractor": "Contractor",
  "ledgerVerifiedBy": "Payment verified by {name}",
  "@ledgerVerifiedBy": {"placeholders": {"name": {"type": "String"}}},
  "ledgerNotVerified": "Payment not yet verified",
  "ledgerCorrections": "Corrections",
  "ledgerDocuments": "Redacted documents",
  "ledgerProofTitle": "Verification details",
  "ledgerProofHash": "Record hash",
  "ledgerProofEvents": "Signed events",
  "evidenceChain": "Anchored on the blockchain",
  "evidenceLocal": "Signed and hash-locked — blockchain anchoring is off for this deployment",
  "evidencePending": "Waiting for blockchain anchoring",
  "evidenceMismatch": "Data mismatch detected",
  "integrityVerified": "Record verified",
  "integrityMismatch": "Integrity mismatch detected",
  "integrityUnavailable": "Integrity check unavailable",
  "integrityUnchecked": "Published — integrity not yet checked"
```

`app_vi.arb`:

```json
  "ledgerTitle": "Sổ quỹ tòa nhà",
  "ledgerEmpty": "Không có khoản chi nào trong kỳ này.",
  "ledgerAllTime": "Tất cả",
  "ledgerLoadMore": "Tải thêm",
  "ledgerPublishedOn": "Công bố ngày {date}",
  "@ledgerPublishedOn": {"placeholders": {"date": {"type": "String"}}},
  "ledgerAmount": "Số tiền",
  "ledgerContractor": "Nhà thầu",
  "ledgerVerifiedBy": "Thanh toán đã được {name} xác nhận",
  "@ledgerVerifiedBy": {"placeholders": {"name": {"type": "String"}}},
  "ledgerNotVerified": "Thanh toán chưa được xác nhận",
  "ledgerCorrections": "Điều chỉnh",
  "ledgerDocuments": "Tài liệu (đã che thông tin)",
  "ledgerProofTitle": "Chi tiết xác thực",
  "ledgerProofHash": "Mã băm bản ghi",
  "ledgerProofEvents": "Sự kiện đã ký",
  "evidenceChain": "Đã neo trên blockchain",
  "evidenceLocal": "Đã ký và khóa băm — hệ thống này chưa bật neo blockchain",
  "evidencePending": "Đang chờ neo blockchain",
  "evidenceMismatch": "Phát hiện sai lệch dữ liệu",
  "integrityVerified": "Bản ghi đã xác minh",
  "integrityMismatch": "Phát hiện sai lệch toàn vẹn",
  "integrityUnavailable": "Chưa kiểm tra được tính toàn vẹn",
  "integrityUnchecked": "Đã công bố — chưa kiểm tra toàn vẹn"
```

Run: `cd app && flutter gen-l10n`

- [ ] **Step 2: Write the failing evidence-label test (§6.5)**

Create `app/test/evidence_labels_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/ledger/evidence_labels.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto/theme.dart';

Future<AppLocalizations> _l10n(WidgetTester tester) async {
  late AppLocalizations l10n;
  await tester.pumpWidget(MaterialApp(
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('vi'),
    home: Builder(builder: (context) {
      l10n = AppLocalizations.of(context)!;
      return const SizedBox();
    }),
  ));
  return l10n;
}

void main() {
  testWidgets('the three levels get distinct copy; LOCAL never says chain',
      (tester) async {
    final l10n = await _l10n(tester);
    final chain = evidenceLevelLabel('CHAIN_CONFIRMED', l10n);
    final local = evidenceLevelLabel('LOCAL_SIGNED', l10n);
    final mismatch = evidenceLevelLabel('MISMATCH', l10n);
    expect({chain, local, mismatch}.length, 3); // all distinct
    expect(local.toLowerCase(), isNot(contains('đã neo'))); // spec 5.2
    expect(mismatch, 'Phát hiện sai lệch dữ liệu');
  });

  testWidgets('EvidenceBadge pairs color with text and marks mismatch error',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('vi'),
      home: const Scaffold(
        body: Column(
          children: [
            EvidenceBadge(level: 'MISMATCH'),
            EvidenceBadge(level: 'LOCAL_SIGNED'),
          ],
        ),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Phát hiện sai lệch dữ liệu'), findsOneWidget);
    final mismatchText = tester.widget<Text>(
        find.text('Phát hiện sai lệch dữ liệu'));
    expect(mismatchText.style?.color, LamToColors.error); // prominent
  });
}
```

- [ ] **Step 3: Run to verify it fails, then implement the labels**

Run: `cd app && flutter test test/evidence_labels_test.dart` → FAIL.

Create `app/lib/features/ledger/evidence_labels.dart`:

```dart
import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import '../../theme.dart';

/// Distinct presentation per evidence level (spec 5.1/5.2): LOCAL_SIGNED never
/// borrows chain wording; MISMATCH renders prominently; color never alone.
String evidenceLevelLabel(String level, AppLocalizations l10n) =>
    switch (level) {
      'CHAIN_CONFIRMED' => l10n.evidenceChain,
      'LOCAL_SIGNED' => l10n.evidenceLocal,
      'MISMATCH' => l10n.evidenceMismatch,
      _ => l10n.evidencePending,
    };

String integrityStatusLabel(String status, AppLocalizations l10n) =>
    switch (status) {
      'VERIFIED' => l10n.integrityVerified,
      'MISMATCH' => l10n.integrityMismatch,
      'UNAVAILABLE' => l10n.integrityUnavailable,
      _ => l10n.integrityUnchecked,
    };

typedef _Style = ({Color bg, Color fg, IconData icon});

_Style _styleFor(String level) => switch (level) {
      'CHAIN_CONFIRMED' => (
          bg: const Color(0xFFE7F6EE), // DESIGN.md success-bg
          fg: LamToColors.success,
          icon: Icons.verified_outlined,
        ),
      'MISMATCH' => (
          bg: const Color(0xFFFEF3F2), // error-bg
          fg: LamToColors.error,
          icon: Icons.error_outline,
        ),
      'LOCAL_SIGNED' => (
          bg: const Color(0xFFEFF8FF), // info-bg
          fg: LamToColors.info,
          icon: Icons.lock_outline,
        ),
      _ => (
          bg: const Color(0xFFFFF6DD), // warning-bg
          fg: LamToColors.warning,
          icon: Icons.hourglass_empty,
        ),
    };

class EvidenceBadge extends StatelessWidget {
  const EvidenceBadge({required this.level, super.key});
  final String level;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final style = _styleFor(level);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: style.bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(style.icon, size: 16, color: style.fg),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              evidenceLevelLabel(level, l10n),
              style: TextStyle(
                color: style.fg,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
```

Run: `cd app && flutter test test/evidence_labels_test.dart` → PASS.

- [ ] **Step 4: Write the failing screens test**

Create `app/test/ledger_screens_test.dart`:

```dart
import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/features/ledger/ledger_detail_screen.dart';
import 'package:lamto/features/ledger/ledger_screen.dart';
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

LedgerEntryDetail _detail() => LedgerEntryDetail(
      (b) => b
        ..id = 42
        ..contractorName = 'Acme Co'
        ..actualCostVnd = 900000
        ..publishedAt = DateTime.utc(2026, 7, 10)
        ..proposedAmountVnd = 950000
        ..integrityStatus = 'VERIFIED'
        ..verification = Verification(
          (v) => v
            ..decision = 'VERIFIED'
            ..verifiedBy = 'Bà Lan'
            ..verifiedAt = DateTime.utc(2026, 7, 9),
        ).toBuilder()
        ..redactedDocuments = ListBuilder<RedactedDocument>()
        ..corrections = ListBuilder<Correction>()
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

  @override
  Future<PaginatedLedgerEntryListList> listLedger(
      {String? cursor, int? year, int? month}) async {
    periods.add((year, month));
    return PaginatedLedgerEntryListList(
      (b) => b
        ..results = ListBuilder<LedgerEntryList>(
            year == null ? [_entry(42, 'LOCAL_SIGNED')] : []),
    );
  }

  @override
  Future<LedgerEntryDetail> fetchLedgerEntry(int id) async => _detail();

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
  testWidgets('list shows entries with evidence badge and period filter',
      (tester) async {
    final repo = _FakeRepo();
    await tester.pumpWidget(_host(const Scaffold(body: LedgerScreen()), repo));
    await tester.pumpAndSettle();
    expect(find.text('Acme Co'), findsOneWidget);
    expect(find.textContaining('Đã ký và khóa băm'), findsOneWidget);

    // Choosing a year re-queries with the filter; empty period shows copy.
    final year = DateTime.now().year;
    await tester.tap(find.text('$year'));
    await tester.pumpAndSettle();
    expect(repo.periods.last, (year, null));
    expect(find.text('Không có khoản chi nào trong kỳ này.'), findsOneWidget);
  });

  testWidgets('detail leads with plain language; hashes only in expansion',
      (tester) async {
    final repo = _FakeRepo();
    await tester
        .pumpWidget(_host(const LedgerDetailScreen(entryId: 42), repo));
    await tester.pumpAndSettle();

    expect(find.text('900.000 ₫'), findsOneWidget);
    expect(find.textContaining('Bà Lan'), findsOneWidget); // who verified
    expect(find.text('ab12cd34'), findsNothing); // hash hidden until expanded

    await tester.tap(find.text('Chi tiết xác thực'));
    await tester.pumpAndSettle();
    expect(find.text('ab12cd34'), findsOneWidget);
    expect(find.textContaining('0xfeed'), findsOneWidget);
  });
}
```

- [ ] **Step 5: Run to verify it fails, then implement the screens**

Run: `cd app && flutter test test/ledger_screens_test.dart` → FAIL.

Create `app/lib/features/ledger/ledger_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../reports/reports_repository.dart' show cursorFromNext;
import '../transparency/transparency_repository.dart';
import 'evidence_labels.dart';
import 'ledger_detail_screen.dart';

class LedgerListController extends AsyncNotifier<List<LedgerEntryList>> {
  String? _nextCursor;
  int? year;
  int? month;

  bool get hasMore => _nextCursor != null;

  @override
  Future<List<LedgerEntryList>> build() async {
    ref.watch(occupancyScopedProviders);
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listLedger(year: year, month: month);
    _nextCursor = cursorFromNext(page.next);
    return page.results.toList();
  }

  Future<void> setPeriod({int? newYear, int? newMonth}) async {
    year = newYear;
    month = newMonth;
    ref.invalidateSelf();
    await future;
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.valueOrNull;
    if (cursor == null || current == null) return;
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listLedger(cursor: cursor, year: year, month: month);
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }
}

final ledgerListProvider =
    AsyncNotifierProvider<LedgerListController, List<LedgerEntryList>>(
        LedgerListController.new);

/// Ledger tab (spec 6.3(6)). Body-only: the shell owns chrome.
class LedgerScreen extends ConsumerWidget {
  const LedgerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final entries = ref.watch(ledgerListProvider);
    final controller = ref.read(ledgerListProvider.notifier);
    final currentYear = DateTime.now().year;
    final years = [for (var y = currentYear; y >= currentYear - 2; y--) y];

    return Material(
      color: Colors.transparent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(l10n.ledgerTitle,
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          // Period filter: "All" + recent years (spec 6.3(6) period filters).
          Wrap(
            spacing: 8,
            children: [
              ChoiceChip(
                label: Text(l10n.ledgerAllTime),
                selected: controller.year == null,
                onSelected: (_) => controller.setPeriod(),
              ),
              for (final y in years)
                ChoiceChip(
                  label: Text('$y'),
                  selected: controller.year == y,
                  onSelected: (_) => controller.setPeriod(newYear: y),
                ),
            ],
          ),
          const SizedBox(height: 8),
          switch (entries) {
            AsyncData(:final value) when value.isEmpty =>
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 24),
                child: Text(l10n.ledgerEmpty),
              ),
            AsyncData(:final value) => Column(
                children: [
                  for (final entry in value)
                    ListTile(
                      minTileHeight: 64,
                      contentPadding: EdgeInsets.zero,
                      title: Text(entry.contractorName,
                          maxLines: 1, overflow: TextOverflow.ellipsis),
                      subtitle: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(formatVnd(entry.actualCostVnd)),
                          const SizedBox(height: 4),
                          EvidenceBadge(level: entry.evidenceLevel),
                        ],
                      ),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) =>
                              LedgerDetailScreen(entryId: entry.id),
                        ),
                      ),
                    ),
                  if (controller.hasMore)
                    OutlinedButton(
                      onPressed: controller.loadMore,
                      child: Text(l10n.ledgerLoadMore),
                    ),
                ],
              ),
            AsyncError(:final error) =>
              Text(failureMessage(Failure.fromObject(error), l10n)),
            _ => const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Center(child: CircularProgressIndicator.adaptive()),
              ),
          },
        ],
      ),
    );
  }
}
```

Create `app/lib/features/ledger/ledger_detail_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/format.dart';
import '../../l10n/app_localizations.dart';
import '../transparency/transparency_repository.dart';
import 'evidence_labels.dart';

/// Ledger entry detail (spec 6.3(6)): plain language first; the proof section
/// is an expansion and is the ONLY place mono identifiers appear.
class LedgerDetailScreen extends ConsumerWidget {
  const LedgerDetailScreen({required this.entryId, super.key});
  final int entryId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final detail = ref.watch(ledgerDetailProvider(entryId));
    return Scaffold(
      appBar: AppBar(title: Text(l10n.ledgerTitle)),
      body: switch (detail) {
        AsyncData(:final value) => _body(context, l10n, value),
        AsyncError(:final error) => Center(
            child: Text(failureMessage(Failure.fromObject(error), l10n)),
          ),
        _ => const Center(child: CircularProgressIndicator.adaptive()),
      },
    );
  }

  Widget _body(
      BuildContext context, AppLocalizations l10n, LedgerEntryDetail entry) {
    final date = DateFormat('dd/MM/yyyy').format(entry.publishedAt.toLocal());
    final verification = entry.verification;
    final mono = Theme.of(context)
        .textTheme
        .bodySmall
        ?.copyWith(fontFamily: 'monospace');

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Plain language first: what, how much, when, verified by whom.
        Text(entry.contractorName,
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(l10n.ledgerPublishedOn(date)),
        const SizedBox(height: 12),
        Text('${l10n.ledgerAmount}: ${formatVnd(entry.actualCostVnd)}',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        Text(
          verification != null
              ? l10n.ledgerVerifiedBy(verification.verifiedBy)
              : l10n.ledgerNotVerified,
        ),
        const SizedBox(height: 8),
        Text(integrityStatusLabel(entry.integrityStatus, l10n)),
        const SizedBox(height: 12),
        EvidenceBadge(level: entry.proof.evidenceLevel),
        if (entry.corrections.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text(l10n.ledgerCorrections,
              style: Theme.of(context).textTheme.titleMedium),
          for (final correction in entry.corrections)
            ListTile(
              minTileHeight: 48,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.change_circle_outlined),
              title: Text(correction.reason,
                  maxLines: 2, overflow: TextOverflow.ellipsis),
              subtitle: Text(correction.status),
            ),
        ],
        if (entry.redactedDocuments.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text(l10n.ledgerDocuments,
              style: Theme.of(context).textTheme.titleMedium),
          for (final doc in entry.redactedDocuments)
            ListTile(
              minTileHeight: 48,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.description_outlined),
              title: Text(doc.label),
              subtitle: Text(doc.filename,
                  maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
        ],
        const SizedBox(height: 16),
        // Expandable proof: the only mono region (DESIGN.md Human Before Hash).
        ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: Text(l10n.ledgerProofTitle),
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(l10n.ledgerProofHash),
              subtitle: Text(entry.proof.payloadHash, style: mono),
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(l10n.ledgerProofEvents,
                    style: Theme.of(context).textTheme.labelLarge),
              ),
            ),
            for (final event in entry.proof.events)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(event.eventId, style: mono),
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (event.transactionHash.isNotEmpty)
                      Text(event.transactionHash, style: mono),
                    const SizedBox(height: 4),
                    EvidenceBadge(level: event.evidenceLevel),
                  ],
                ),
              ),
          ],
        ),
      ],
    );
  }
}
```

- [ ] **Step 6: Wire tab 3 + the Home spending tap-through**

In `home_shell.dart`, import `../ledger/ledger_screen.dart` and replace the index-3 placeholder with `const LedgerScreen()`.

In `home_screen.dart`, import `../ledger/ledger_detail_screen.dart` and give the recent-spending `ListTile` the tap:

```dart
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(
                  builder: (_) => LedgerDetailScreen(entryId: entry.id)),
            ),
```

(Replace the `// Task "Ledger" wires the tap-through...` comment.)

- [ ] **Step 7: Run the tests**

Run: `cd app && flutter test test/ledger_screens_test.dart test/evidence_labels_test.dart test/home_screen_test.dart`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features/ledger app/lib/features/home/home_screen.dart \
        app/lib/features/shell/home_shell.dart app/lib/l10n \
        app/test/evidence_labels_test.dart app/test/ledger_screens_test.dart
git commit -m "feat(app): ledger list and detail with distinct evidence-level labels"
```

---

### Task 5: Notifications feed — list, mark-read, deep links

Replaces the Task-3 placeholder. Feed rows mark read on tap and deep-link through the §7.4 allowlist parsed from `event_key`.

**Files:**
- Create: `app/lib/features/notifications/deep_link.dart`
- Modify: `app/lib/features/notifications/notifications_screen.dart` (full implementation), `app/lib/l10n/*.arb`
- Test: `app/test/deep_link_test.dart`, `app/test/notifications_screen_test.dart`

**Interfaces:**
- Consumes: `transparencyRepositoryProvider`, `cursorFromNext`, `occupancyScopedProviders`, `NotificationFeed` (with `eventKey` from Task 1), `IssueDetailScreen`, `LedgerDetailScreen`.
- Produces:
  - `sealed class DeepLink` — `DeepLinkReport(id)`, `DeepLinkLedger(id)`, `DeepLinkFeed()`.
  - `DeepLink parsePushLink({String? type, String? id})` (push `data` map) and `DeepLink parseEventKey(String eventKey)` — both allowlist-based, safe fallback `DeepLinkFeed`.
  - `NotificationsController` (`notificationsProvider`) with `loadMore()`, `hasMore`, `markRead(id)`.
  - Full `NotificationsScreen`.

- [ ] **Step 1: Write the failing deep-link test**

Create `app/test/deep_link_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/notifications/deep_link.dart';

void main() {
  test('push data parses through the allowlist with safe fallback', () {
    expect(parsePushLink(type: 'report', id: '5'), DeepLinkReport(5));
    expect(parsePushLink(type: 'ledger', id: '42'), DeepLinkLedger(42));
    expect(parsePushLink(type: 'notifications', id: ''), const DeepLinkFeed());
    expect(parsePushLink(type: 'evil', id: '1'), const DeepLinkFeed());
    expect(parsePushLink(type: 'report', id: 'abc'), const DeepLinkFeed());
    expect(parsePushLink(type: null, id: null), const DeepLinkFeed());
  });

  test('event keys parse entity segments with safe fallback', () {
    expect(parseEventKey('report.receipt:report:5'), DeepLinkReport(5));
    expect(parseEventKey('ledger.publication:entry:42'), DeepLinkLedger(42));
    // Corrections/cases/work have no resident screen of their own -> feed.
    expect(parseEventKey('correction.status:correction:7:PENDING'),
        const DeepLinkFeed());
    expect(parseEventKey('triage.status:case:3'), const DeepLinkFeed());
    expect(parseEventKey('garbage'), const DeepLinkFeed());
  });
}
```

- [ ] **Step 2: Run to verify it fails, then implement the parser**

Run: `cd app && flutter test test/deep_link_test.dart` → FAIL.

Create `app/lib/features/notifications/deep_link.dart`:

```dart
/// Allowlisted deep-link map (spec 7.4): report, ledger entry, or the feed.
/// Anything unknown falls back to the feed — a link can never widen access;
/// the pushed screen re-fetches through the authenticated API and its own
/// failure state is the safe landing for a 403/404.
sealed class DeepLink {
  const DeepLink();
}

class DeepLinkReport extends DeepLink {
  const DeepLinkReport(this.id);
  final int id;
  @override
  bool operator ==(Object other) => other is DeepLinkReport && other.id == id;
  @override
  int get hashCode => Object.hash('report', id);
}

class DeepLinkLedger extends DeepLink {
  const DeepLinkLedger(this.id);
  final int id;
  @override
  bool operator ==(Object other) => other is DeepLinkLedger && other.id == id;
  @override
  int get hashCode => Object.hash('ledger', id);
}

class DeepLinkFeed extends DeepLink {
  const DeepLinkFeed();
  @override
  bool operator ==(Object other) => other is DeepLinkFeed;
  @override
  int get hashCode => 'feed'.hashCode;
}

/// Push payload data: {'type': report|case|ledger|notifications, 'id': ...}.
DeepLink parsePushLink({String? type, String? id}) {
  final parsed = int.tryParse(id ?? '');
  return switch (type) {
    'report' when parsed != null => DeepLinkReport(parsed),
    'ledger' when parsed != null => DeepLinkLedger(parsed),
    _ => const DeepLinkFeed(),
  };
}

/// Feed event_key: '{code}:{entity}:{id}[:{suffix}]'.
DeepLink parseEventKey(String eventKey) {
  final parts = eventKey.split(':');
  if (parts.length < 3) return const DeepLinkFeed();
  final id = int.tryParse(parts[2]);
  if (id == null) return const DeepLinkFeed();
  return switch (parts[1]) {
    'report' => DeepLinkReport(id),
    'entry' => DeepLinkLedger(id),
    _ => const DeepLinkFeed(),
  };
}
```

Run: `cd app && flutter test test/deep_link_test.dart` → PASS.

- [ ] **Step 3: Add the l10n keys + write the failing screen test**

`app_en.arb`:

```json
  "notificationsEmpty": "No notifications yet.",
  "notificationsLoadMore": "Load more"
```

`app_vi.arb`:

```json
  "notificationsEmpty": "Chưa có thông báo nào.",
  "notificationsLoadMore": "Tải thêm"
```

Run: `cd app && flutter gen-l10n`

Create `app/test/notifications_screen_test.dart`:

```dart
import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/features/notifications/notifications_screen.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

NotificationFeed _notice(int id, {String? eventKey, DateTime? readAt}) =>
    NotificationFeed(
      (b) => b
        ..id = id
        ..eventCode = 'ledger.publication'
        ..eventKey = eventKey ?? 'ledger.publication:entry:42'
        ..subject = 'Khoản chi mới'
        ..body = 'Một khoản chi vừa được công bố.'
        ..createdAt = DateTime.utc(2026, 7, 15)
        ..readAt = readAt,
    );

class _FakeRepo implements TransparencyRepository {
  final read = <int>[];

  @override
  Future<PaginatedNotificationFeedList> listNotifications(
          {String? cursor}) async =>
      PaginatedNotificationFeedList(
        (b) => b..results = ListBuilder<NotificationFeed>([_notice(9)]),
      );

  @override
  Future<void> markNotificationRead(int id) async => read.add(id);

  @override
  Future<LedgerEntryDetail> fetchLedgerEntry(int id) async =>
      throw StateError('detail fetch not needed for this test');

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('lists notices; tap marks read and deep-links to ledger detail',
      (tester) async {
    final repo = _FakeRepo();
    await tester.pumpWidget(ProviderScope(
      overrides: [transparencyRepositoryProvider.overrideWithValue(repo)],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const NotificationsScreen(),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Khoản chi mới'), findsOneWidget);

    await tester.tap(find.text('Khoản chi mới'));
    await tester.pump(); // navigation begins; detail fetch may error (fine)
    expect(repo.read, [9]);
    // Landed on the pushed ledger detail scaffold (its own AppBar title).
    await tester.pumpAndSettle();
    expect(find.text('Sổ quỹ tòa nhà'), findsOneWidget);
  });
}
```

- [ ] **Step 4: Run to verify it fails, then implement the screen**

Run: `cd app && flutter test test/notifications_screen_test.dart` → FAIL (placeholder has no list).

Replace `app/lib/features/notifications/notifications_screen.dart` with:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../ledger/ledger_detail_screen.dart';
import '../reports/issue_detail_screen.dart';
import '../reports/reports_repository.dart' show cursorFromNext;
import '../transparency/transparency_repository.dart';
import 'deep_link.dart';

class NotificationsController extends AsyncNotifier<List<NotificationFeed>> {
  String? _nextCursor;
  bool get hasMore => _nextCursor != null;

  @override
  Future<List<NotificationFeed>> build() async {
    ref.watch(occupancyScopedProviders);
    final page =
        await ref.read(transparencyRepositoryProvider).listNotifications();
    _nextCursor = cursorFromNext(page.next);
    return page.results.toList();
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.valueOrNull;
    if (cursor == null || current == null) return;
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listNotifications(cursor: cursor);
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }

  /// Optimistic mark-read; the in-app feed is authoritative so a failed call
  /// simply leaves the row unread on next refresh.
  Future<void> markRead(NotificationFeed notice) async {
    if (notice.readAt != null) return;
    final current = state.valueOrNull;
    if (current != null) {
      state = AsyncData([
        for (final row in current)
          row.id == notice.id
              ? row.rebuild((b) => b..readAt = DateTime.now().toUtc())
              : row,
      ]);
    }
    try {
      await ref
          .read(transparencyRepositoryProvider)
          .markNotificationRead(notice.id);
    } catch (_) {
      // Best-effort (spec 7.4: feed authoritative; no workflow blocks on it).
    }
  }
}

final notificationsProvider =
    AsyncNotifierProvider<NotificationsController, List<NotificationFeed>>(
        NotificationsController.new);

/// Notifications feed (spec 6.3(8)): list, mark-read, allowlisted deep links.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final notices = ref.watch(notificationsProvider);
    final controller = ref.read(notificationsProvider.notifier);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.notificationsTitle)),
      body: switch (notices) {
        AsyncData(:final value) when value.isEmpty =>
          Center(child: Text(l10n.notificationsEmpty)),
        AsyncData(:final value) => RefreshIndicator.adaptive(
            onRefresh: () => ref.refresh(notificationsProvider.future),
            child: ListView(
              children: [
                for (final notice in value)
                  ListTile(
                    minTileHeight: 64,
                    leading: Icon(
                      notice.readAt == null
                          ? Icons.circle_notifications
                          : Icons.notifications_none,
                    ),
                    title: Text(
                      notice.subject,
                      style: notice.readAt == null
                          ? const TextStyle(fontWeight: FontWeight.w600)
                          : null,
                    ),
                    subtitle: Text(notice.body,
                        maxLines: 2, overflow: TextOverflow.ellipsis),
                    onTap: () => _open(context, controller, notice),
                  ),
                if (controller.hasMore)
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: OutlinedButton(
                      onPressed: controller.loadMore,
                      child: Text(l10n.notificationsLoadMore),
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

  void _open(BuildContext context, NotificationsController controller,
      NotificationFeed notice) {
    controller.markRead(notice);
    switch (parseEventKey(notice.eventKey)) {
      case DeepLinkReport(:final id):
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => IssueDetailScreen(reportId: id)),
        );
      case DeepLinkLedger(:final id):
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => LedgerDetailScreen(entryId: id)),
        );
      case DeepLinkFeed():
        break; // already on the feed
    }
  }
}
```

- [ ] **Step 5: Run the tests**

Run: `cd app && flutter test test/notifications_screen_test.dart test/deep_link_test.dart test/home_screen_test.dart`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features/notifications app/lib/l10n \
        app/test/deep_link_test.dart app/test/notifications_screen_test.dart
git commit -m "feat(app): notifications feed with mark-read and allowlisted deep links"
```

---

### Task 6: Account tab — profile, occupancy switcher, preferences, logout

Body-only tab. Occupancy switching goes through the existing `SessionController.selectOccupancy`; `signOut` gains best-effort server-side logout (`allDevices` for logout-all).

**Files:**
- Create: `app/lib/features/account/account_screen.dart`
- Modify: `app/lib/features/auth/session_controller.dart`, `app/lib/features/shell/home_shell.dart` (tab 4), `app/lib/l10n/*.arb`
- Test: `app/test/account_screen_test.dart`, `app/test/sign_out_test.dart`

**Interfaces:**
- Consumes: `sessionControllerProvider` (+ `SessionAuthenticated.me`, `selectOccupancy`), `occupancyHolderProvider`, `transparencyRepositoryProvider.updatePreference`, `Me.notificationPreferences`.
- Produces: `AccountScreen`; `SessionController.signOut({bool allDevices = false})` now calls `logout()`/`logoutAll()` best-effort before clearing local state; `residentPreferenceCategories` (the 5 event codes + l10n labels).

- [ ] **Step 1: Add the l10n keys**

`app_en.arb`:

```json
  "accountOccupancies": "My homes",
  "accountPreferences": "Notifications",
  "accountPrefEmail": "Email",
  "accountPrefPush": "Push",
  "accountSignOutAll": "Sign out of all devices",
  "prefReportReceipt": "Report received",
  "prefTriageStatus": "Report reviewed",
  "prefWorkCompleted": "Work completed",
  "prefLedgerPublication": "Published spending",
  "prefCorrectionStatus": "Corrections"
```

`app_vi.arb`:

```json
  "accountOccupancies": "Căn hộ của tôi",
  "accountPreferences": "Thông báo",
  "accountPrefEmail": "Email",
  "accountPrefPush": "Đẩy (push)",
  "accountSignOutAll": "Đăng xuất mọi thiết bị",
  "prefReportReceipt": "Đã nhận phản ánh",
  "prefTriageStatus": "Phản ánh được xem xét",
  "prefWorkCompleted": "Công việc hoàn thành",
  "prefLedgerPublication": "Khoản chi được công bố",
  "prefCorrectionStatus": "Điều chỉnh"
```

(`signOut` already exists as a key.) Run: `cd app && flutter gen-l10n`

- [ ] **Step 2: Upgrade signOut (with a test)**

Create `app/test/sign_out_test.dart` (standalone: its own fakes, so it does not depend on the shapes inside the existing session test file):

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/core/token_store.dart';
import 'package:lamto/features/auth/auth_repository.dart';
import 'package:lamto/features/auth/session_controller.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeStore implements TokenStore {
  String? token = 'knox-token';
  @override
  Future<void> clear() async => token = null;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String value) async => token = value;
}

class _FakeAuth implements AuthRepository {
  final calls = <String>[];
  bool throwOnLogout = false;

  @override
  Future<Me> fetchMe() async => Me(
        (b) => b
          ..displayName = 'R'
          ..email = 'r@example.com'
          ..occupancies = ListBuilder<Occupancy>()
          ..notificationPreferences = ListBuilder<NotificationPreference>(),
      );
  @override
  Future<String> login(String i, String p) async => 'tok';
  @override
  Future<void> logout() async {
    calls.add('logout');
    if (throwOnLogout) {
      throw DioException(requestOptions: RequestOptions(path: '/x'));
    }
  }

  @override
  Future<void> logoutAll() async => calls.add('logout-all');
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  ProviderContainer _container(_FakeAuth auth) {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer(overrides: [
      tokenStoreProvider.overrideWithValue(_FakeStore()),
      authRepositoryProvider.overrideWithValue(auth),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  test('signOut calls server logout then clears locally', () async {
    final auth = _FakeAuth();
    final container = _container(auth);
    await container.read(sessionControllerProvider.future);
    await container.read(sessionControllerProvider.notifier).signOut();
    expect(auth.calls, ['logout']);
    final state = await container.read(sessionControllerProvider.future);
    expect(state, isA<SessionUnauthenticated>());
  });

  test('logout-all variant and server failure never block local sign-out',
      () async {
    final auth = _FakeAuth()..throwOnLogout = true;
    final container = _container(auth);
    await container.read(sessionControllerProvider.future);
    // Throws server-side; still signs out locally.
    await container.read(sessionControllerProvider.notifier).signOut();
    expect(await container.read(sessionControllerProvider.future),
        isA<SessionUnauthenticated>());

    final auth2 = _FakeAuth();
    final container2 = _container(auth2);
    await container2.read(sessionControllerProvider.future);
    await container2
        .read(sessionControllerProvider.notifier)
        .signOut(allDevices: true);
    expect(auth2.calls, ['logout-all']);
  });
}
```

Add `import 'package:built_collection/built_collection.dart';` to the imports. (`signOut` also clears `ReportDraftStore`/`ReportPhotoFileStore`; both are SharedPreferences/best-effort-backed and safe under the mock.)

In `app/lib/features/auth/session_controller.dart`, change `signOut`:

```dart
  Future<void> signOut({bool allDevices = false}) async {
    // Server-side revocation is best-effort: a network failure must never
    // trap the resident in a session (spec 6.4).
    try {
      allDevices ? await _repo.logoutAll() : await _repo.logout();
    } catch (_) {}
    await _store.clear();
    _holder.occupancyId = null;
    // Amendment 7: wipe sensitive draft text/paths on logout.
    await ReportDraftStore().clearAll();
    // Amendment 8: drop app-owned photo copies. path_provider may be
    // unavailable or hang in widget tests — never block session clear.
    unawaited(
      ReportPhotoFileStore().clearAll().catchError((Object _) {}),
    );
    // My Issues watches sessionControllerProvider and rebuilds on this state.
    state = const AsyncData(SessionUnauthenticated());
  }
```

Run: `cd app && flutter test test/sign_out_test.dart test/session_controller_test.dart` → PASS (the new tests plus the existing session suite, whose fakes gain the two logout no-ops from Task 2).

- [ ] **Step 3: Write the failing account test**

Create `app/test/account_screen_test.dart`:

```dart
import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/core/token_store.dart';
import 'package:lamto/features/account/account_screen.dart';
import 'package:lamto/features/auth/auth_repository.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

Me _me() => Me(
      (b) => b
        ..displayName = 'Cư dân A'
        ..email = 'r@example.com'
        ..occupancies = ListBuilder<Occupancy>([
          Occupancy((o) => o
            ..id = 1
            ..unitLabel = 'B-1204'
            ..buildingName = 'Tòa A'),
          Occupancy((o) => o
            ..id = 2
            ..unitLabel = 'C-101'
            ..buildingName = 'Tòa C'),
        ])
        ..notificationPreferences = ListBuilder<NotificationPreference>([
          NotificationPreference((p) => p
            ..eventCode = 'ledger.publication'
            ..emailEnabled = true
            ..pushEnabled = false),
        ]),
    );

class _FakeAuth implements AuthRepository {
  @override
  Future<Me> fetchMe() async => _me();
  @override
  Future<String> login(String i, String p) async => 'tok';
  @override
  Future<void> logout() async {}
  @override
  Future<void> logoutAll() async {}
}

/// Bootstrap reads secure storage first; give it an in-memory token.
class _FakeStore implements TokenStore {
  String? token = 'knox-token';
  @override
  Future<void> clear() async => token = null;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String value) async => token = value;
}

class _FakeTransparency implements TransparencyRepository {
  final patches = <(String, bool?, bool?)>[];

  @override
  Future<List<NotificationPreference>> updatePreference({
    required String eventCode,
    bool? emailEnabled,
    bool? pushEnabled,
  }) async {
    patches.add((eventCode, emailEnabled, pushEnabled));
    return [];
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('shows profile, occupancies, preference toggles; patches a flip',
      (tester) async {
    SharedPreferences.setMockInitialValues({}); // occupancy store backing
    final repo = _FakeTransparency();
    await tester.pumpWidget(ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(_FakeStore()),
        authRepositoryProvider.overrideWithValue(_FakeAuth()),
        transparencyRepositoryProvider.overrideWithValue(repo),
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const Scaffold(body: AccountScreen()),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Cư dân A'), findsOneWidget);
    expect(find.text('Tòa A · B-1204'), findsOneWidget);
    expect(find.text('Tòa C · C-101'), findsOneWidget);
    expect(find.text('Khoản chi được công bố'), findsOneWidget);

    // Push toggle for ledger.publication starts OFF (from /me row); flip it.
    final pushSwitches = find.byType(Switch);
    expect(pushSwitches, findsWidgets);
    // The screen keys each switch: 'push_ledger.publication'.
    await tester.tap(find.byKey(const Key('push_ledger.publication')));
    await tester.pumpAndSettle();
    expect(repo.patches.single, ('ledger.publication', null, true));
    expect(find.text('Đăng xuất'), findsOneWidget);
    expect(find.text('Đăng xuất mọi thiết bị'), findsOneWidget);
  });
}
```

Note: the as-built `signOut` l10n value is whatever `signOut` maps to in `app_vi.arb` (check it; if it isn't `Đăng xuất`, use the actual string in the last two asserts).

- [ ] **Step 4: Run to verify it fails, then implement**

Run: `cd app && flutter test test/account_screen_test.dart` → FAIL.

Create `app/lib/features/account/account_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../auth/session_controller.dart';
import '../transparency/transparency_repository.dart';

/// The five resident notification categories (server defaults absent rows to
/// enabled). Labels resolve through l10n.
List<({String code, String label})> residentPreferenceCategories(
        AppLocalizations l10n) =>
    [
      (code: 'report.receipt', label: l10n.prefReportReceipt),
      (code: 'triage.status', label: l10n.prefTriageStatus),
      (code: 'work.completed', label: l10n.prefWorkCompleted),
      (code: 'ledger.publication', label: l10n.prefLedgerPublication),
      (code: 'correction.status', label: l10n.prefCorrectionStatus),
    ];

/// Account tab (spec 6.3(7)). Body-only: the shell owns chrome.
class AccountScreen extends ConsumerStatefulWidget {
  const AccountScreen({super.key});

  @override
  ConsumerState<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends ConsumerState<AccountScreen> {
  /// Local overlay of toggles the user flipped this session.
  final Map<String, bool> _email = {};
  final Map<String, bool> _push = {};

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final session = ref.watch(sessionControllerProvider);
    final me = switch (session) {
      AsyncData(value: SessionAuthenticated(:final me)) => me,
      _ => null,
    };
    if (me == null) {
      return const Center(child: CircularProgressIndicator.adaptive());
    }
    final holder = ref.watch(occupancyHolderProvider);
    final serverPrefs = {
      for (final pref in me.notificationPreferences) pref.eventCode: pref,
    };

    return Material(
      color: Colors.transparent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(me.displayName,
              style: Theme.of(context).textTheme.titleLarge),
          Text(me.email, style: Theme.of(context).textTheme.bodySmall),
          if (me.phone != null && me.phone!.isNotEmpty)
            Text(me.phone!, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 24),
          Text(l10n.accountOccupancies,
              style: Theme.of(context).textTheme.titleMedium),
          for (final occupancy in me.occupancies)
            RadioListTile<int>(
              contentPadding: EdgeInsets.zero,
              value: occupancy.id,
              groupValue: holder.occupancyId,
              title:
                  Text('${occupancy.buildingName} · ${occupancy.unitLabel}'),
              onChanged: (id) {
                if (id != null) {
                  ref
                      .read(sessionControllerProvider.notifier)
                      .selectOccupancy(me, id);
                }
              },
            ),
          const SizedBox(height: 24),
          Text(l10n.accountPreferences,
              style: Theme.of(context).textTheme.titleMedium),
          for (final category in residentPreferenceCategories(l10n))
            _prefRow(l10n, category, serverPrefs[category.code]),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: () =>
                ref.read(sessionControllerProvider.notifier).signOut(),
            child: Text(l10n.signOut),
          ),
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: () => ref
                .read(sessionControllerProvider.notifier)
                .signOut(allDevices: true),
            child: Text(l10n.accountSignOutAll),
          ),
        ],
      ),
    );
  }

  Widget _prefRow(AppLocalizations l10n, ({String code, String label}) category,
      NotificationPreference? server) {
    final email = _email[category.code] ?? server?.emailEnabled ?? true;
    final push = _push[category.code] ?? server?.pushEnabled ?? true;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text(category.label)),
          Text(l10n.accountPrefEmail,
              style: Theme.of(context).textTheme.labelSmall),
          Switch.adaptive(
            key: Key('email_${category.code}'),
            value: email,
            onChanged: (value) => _patch(category.code, email: value),
          ),
          Text(l10n.accountPrefPush,
              style: Theme.of(context).textTheme.labelSmall),
          Switch.adaptive(
            key: Key('push_${category.code}'),
            value: push,
            onChanged: (value) => _patch(category.code, push: value),
          ),
        ],
      ),
    );
  }

  Future<void> _patch(String code, {bool? email, bool? push}) async {
    setState(() {
      if (email != null) _email[code] = email;
      if (push != null) _push[code] = push;
    });
    try {
      await ref.read(transparencyRepositoryProvider).updatePreference(
            eventCode: code,
            emailEnabled: email,
            pushEnabled: push,
          );
    } catch (_) {
      // Revert the optimistic flip on failure.
      if (!mounted) return;
      setState(() {
        if (email != null) _email[code] = !email;
        if (push != null) _push[code] = !push;
      });
    }
  }
}
```

- [ ] **Step 5: Wire tab 4 + run the tests**

In `home_shell.dart`, import `../account/account_screen.dart` and replace the index-4 placeholder with `const AccountScreen()`.

Run: `cd app && flutter test test/account_screen_test.dart test/sign_out_test.dart test/app_routing_test.dart`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features/account app/lib/features/auth/session_controller.dart \
        app/lib/features/shell/home_shell.dart app/lib/l10n \
        app/test/account_screen_test.dart app/test/sign_out_test.dart
git commit -m "feat(app): account tab with occupancy switcher, preferences, and server logout"
```

---

### Task 7: Push registration — consent in context, token refresh, logout deregistration

The client half of §7: a `PushTokenSource` seam over `firebase_messaging`, a persistent `install_id`, registration right after the first successful report submission, re-registration on token refresh, deregistration on logout, and notification-tap deep links. Everything no-ops without Firebase config.

**Amendments binding this task:** **A4** (persist permission-requested once per install), **A5** (failed deregister must be retryable or logout-coupled — not silent indefinite push after local logout), **A6** (dev/test graceful no-op; production missing-config surfaces a visible diagnostic).

**Files:**
- Modify: `app/pubspec.yaml` (+`firebase_core`, `firebase_messaging`)
- Create: `app/lib/features/push/push_token_source.dart`, `app/lib/features/push/push_registrar.dart`
- Modify: `app/lib/core/providers.dart` (push providers), `app/lib/features/reports/report_form_screen.dart` (consent hook), `app/lib/features/auth/session_controller.dart` (deregister on signOut), `app/lib/app.dart` (notification-tap handling)
- Test: `app/test/push_registrar_test.dart`

**Interfaces:**
- Consumes: `uuidV4`, `TransparencyRepository.registerDevice/deactivateDevice`, `parsePushLink`, `SubmitOutcome` (report form).
- Produces:
  - `abstract class PushTokenSource` — `Future<bool> requestPermission()`, `Future<String?> getToken()`, `Stream<String> get onTokenRefresh`, `Future<Map<String, String>?> initialMessageData()`, `Stream<Map<String, String>> get onMessageOpened`.
  - `FirebasePushTokenSource` (guards `Firebase.initializeApp()`; every method resolves null/false/empty on failure).
  - `InstallIdStore` — `Future<String> get()` (mints + persists a uuid on first call).
  - `PushRegistrar(tokenSource, repository, installIdStore)` — `Future<void> registerAfterConsent()`, `void watchTokenRefresh()`, `Future<void> deregister()`.
  - Providers in `core/providers.dart`: `pushTokenSourceProvider`, `installIdStoreProvider`, `pushRegistrarProvider`.

- [ ] **Step 1: Add the dependencies**

```bash
cd app && flutter pub add firebase_core firebase_messaging
```

Do **not** add platform config files — deployment supplies `google-services.json` / `GoogleService-Info.plist`; until then `Firebase.initializeApp()` throws and the source reports unsupported.

- [ ] **Step 2: Write the failing test**

Create `app/test/push_registrar_test.dart`:

```dart
import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/push/push_registrar.dart';
import 'package:lamto/features/push/push_token_source.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeSource implements PushTokenSource {
  _FakeSource({this.permission = true, this.token = 'tok-1'});
  bool permission;
  String? token;
  final refresh = StreamController<String>.broadcast();

  @override
  Future<bool> requestPermission() async => permission;
  @override
  Future<String?> getToken() async => token;
  @override
  Stream<String> get onTokenRefresh => refresh.stream;
  @override
  Future<Map<String, String>?> initialMessageData() async => null;
  @override
  Stream<Map<String, String>> get onMessageOpened => const Stream.empty();
}

class _FakeRepo implements TransparencyRepository {
  final registered = <(String, String)>[];
  final deactivated = <String>[];

  @override
  Future<Device> registerDevice({
    required String installId,
    required String fcmToken,
    required String platform,
    String appVersion = '',
  }) async {
    registered.add((installId, fcmToken));
    return Device((b) => b
      ..installId = installId
      ..platform = platform
      ..active = true);
  }

  @override
  Future<void> deactivateDevice(String installId) async =>
      deactivated.add(installId);

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('registers after consent with a stable install id', () async {
    final source = _FakeSource();
    final repo = _FakeRepo();
    final store = InstallIdStore();
    final registrar = PushRegistrar(
        tokenSource: source, repository: repo, installIdStore: store);

    await registrar.registerAfterConsent();
    await registrar.registerAfterConsent(); // idempotent upsert
    expect(repo.registered, hasLength(2));
    expect(repo.registered[0].$1, repo.registered[1].$1); // same install id
    expect(repo.registered[0].$2, 'tok-1');
  });

  test('no permission or no token -> no registration, no crash', () async {
    final repo = _FakeRepo();
    final denied = PushRegistrar(
      tokenSource: _FakeSource(permission: false),
      repository: repo,
      installIdStore: InstallIdStore(),
    );
    await denied.registerAfterConsent();
    final tokenless = PushRegistrar(
      tokenSource: _FakeSource(token: null),
      repository: repo,
      installIdStore: InstallIdStore(),
    );
    await tokenless.registerAfterConsent();
    expect(repo.registered, isEmpty);
  });

  test('token refresh re-registers; deregister deactivates the install',
      () async {
    final source = _FakeSource();
    final repo = _FakeRepo();
    final registrar = PushRegistrar(
        tokenSource: source,
        repository: repo,
        installIdStore: InstallIdStore());
    await registrar.registerAfterConsent();
    registrar.watchTokenRefresh();
    source.refresh.add('tok-2');
    await Future<void>.delayed(Duration.zero);
    expect(repo.registered.last.$2, 'tok-2');

    await registrar.deregister();
    expect(repo.deactivated.single, repo.registered.first.$1);
  });
}
```

- [ ] **Step 3: Run to verify it fails, then implement**

Run: `cd app && flutter test test/push_registrar_test.dart` → FAIL.

Create `app/lib/features/push/push_token_source.dart`:

```dart
import 'dart:async';
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

abstract class PushTokenSource {
  Future<bool> requestPermission();
  Future<String?> getToken();
  Stream<String> get onTokenRefresh;
  Future<Map<String, String>?> initialMessageData();
  Stream<Map<String, String>> get onMessageOpened;
}

/// Real source. Without platform config Firebase.initializeApp throws and
/// every call degrades to unsupported (push is best-effort, spec 7.4).
class FirebasePushTokenSource implements PushTokenSource {
  bool? _available;

  Future<bool> _ensure() async {
    if (_available != null) return _available!;
    try {
      await Firebase.initializeApp();
      _available = true;
    } catch (_) {
      _available = false;
    }
    return _available!;
  }

  @override
  Future<bool> requestPermission() async {
    if (!await _ensure()) return false;
    try {
      final settings =
          await FirebaseMessaging.instance.requestPermission();
      return settings.authorizationStatus == AuthorizationStatus.authorized ||
          settings.authorizationStatus == AuthorizationStatus.provisional;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String?> getToken() async {
    if (!await _ensure()) return null;
    try {
      if (Platform.isIOS) {
        final apns = await FirebaseMessaging.instance.getAPNSToken();
        if (apns == null) return null; // APNS not ready: try again later
      }
      return await FirebaseMessaging.instance.getToken();
    } catch (_) {
      return null;
    }
  }

  @override
  Stream<String> get onTokenRefresh =>
      _available == true ? FirebaseMessaging.instance.onTokenRefresh : const Stream.empty();

  @override
  Future<Map<String, String>?> initialMessageData() async {
    if (!await _ensure()) return null;
    final message = await FirebaseMessaging.instance.getInitialMessage();
    return message?.data.map((k, v) => MapEntry(k, '$v'));
  }

  @override
  Stream<Map<String, String>> get onMessageOpened => _available == true
      ? FirebaseMessaging.onMessageOpenedApp
          .map((m) => m.data.map((k, v) => MapEntry(k, '$v')))
      : const Stream.empty();
}
```

Create `app/lib/features/push/push_registrar.dart`:

```dart
import 'dart:async';
import 'dart:io' show Platform;

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/uuid.dart';
import '../transparency/transparency_repository.dart';
import 'push_token_source.dart';

/// Stable per-install id (spec 7.2 upsert key). Never the auth token.
class InstallIdStore {
  InstallIdStore([SharedPreferences? prefs]) : _prefsOverride = prefs;
  final SharedPreferences? _prefsOverride;
  static const _key = 'lamto_install_id';

  Future<String> get() async {
    final prefs = _prefsOverride ?? await SharedPreferences.getInstance();
    final existing = prefs.getString(_key);
    if (existing != null && existing.isNotEmpty) return existing;
    final minted = uuidV4();
    await prefs.setString(_key, minted);
    return minted;
  }
}

/// Client half of spec 7.2/7.5: consent-gated registration, token-refresh
/// re-registration, logout deactivation. Every path is best-effort.
class PushRegistrar {
  PushRegistrar({
    required this.tokenSource,
    required this.repository,
    required this.installIdStore,
  });

  final PushTokenSource tokenSource;
  final TransparencyRepository repository;
  final InstallIdStore installIdStore;
  StreamSubscription<String>? _refreshSub;

  String get _platform {
    try {
      return Platform.isIOS ? 'IOS' : 'ANDROID';
    } catch (_) {
      return 'ANDROID';
    }
  }

  /// Ask OS permission (in context, spec 7.5) and register the device.
  Future<void> registerAfterConsent() async {
    try {
      if (!await tokenSource.requestPermission()) return;
      final token = await tokenSource.getToken();
      if (token == null || token.isEmpty) return;
      await repository.registerDevice(
        installId: await installIdStore.get(),
        fcmToken: token,
        platform: _platform,
      );
    } catch (_) {
      // Push failure never blocks any workflow (spec 7.4).
    }
  }

  /// Re-register whenever FCM rotates the token (spec 7.2).
  void watchTokenRefresh() {
    _refreshSub ??= tokenSource.onTokenRefresh.listen((token) async {
      try {
        await repository.registerDevice(
          installId: await installIdStore.get(),
          fcmToken: token,
          platform: _platform,
        );
      } catch (_) {}
    });
  }

  /// Logout deactivates this install's device (spec 7.2). Best-effort.
  Future<void> deregister() async {
    await _refreshSub?.cancel();
    _refreshSub = null;
    try {
      await repository.deactivateDevice(await installIdStore.get());
    } catch (_) {}
  }
}
```

Add to `app/lib/core/providers.dart`:

```dart
import '../features/push/push_registrar.dart';
import '../features/push/push_token_source.dart';
import '../features/transparency/transparency_repository.dart';
```

```dart
final pushTokenSourceProvider =
    Provider<PushTokenSource>((ref) => FirebasePushTokenSource());
final installIdStoreProvider =
    Provider<InstallIdStore>((ref) => InstallIdStore());
final pushRegistrarProvider = Provider<PushRegistrar>(
  (ref) => PushRegistrar(
    tokenSource: ref.watch(pushTokenSourceProvider),
    repository: ref.watch(transparencyRepositoryProvider),
    installIdStore: ref.watch(installIdStoreProvider),
  ),
);
```

- [ ] **Step 4: Run the registrar tests**

Run: `cd app && flutter test test/push_registrar_test.dart`
Expected: PASS (3 tests).

- [ ] **Step 5: Hook consent, logout, and notification taps**

**Consent in context (§7.5):** in `app/lib/features/reports/report_form_screen.dart`, in `_submit` right after a successful outcome is set (first successful submission is the moment push has obvious value), add:

```dart
      // Spec 7.5: request push consent right after the first successful
      // report submission — never as an app-launch ambush. Fire-and-forget.
      final registrar = ref.read(pushRegistrarProvider);
      unawaited(
        registrar.registerAfterConsent().then((_) => registrar.watchTokenRefresh()),
      );
```

(with `import 'dart:async';` and `import '../../core/providers.dart';` already present — add if missing.)

**Logout (§7.2):** in `session_controller.dart` `signOut`, before the server logout call, add:

```dart
    // Deactivate this install's push device first (spec 7.2); best-effort.
    try {
      await ref.read(pushRegistrarProvider).deregister();
    } catch (_) {}
```

**Notification taps (§7.4):** in `app/lib/app.dart`'s `_AppRouterState`, add an `initState` that wires tap→deep link:

```dart
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _wirePushTaps());
  }

  Future<void> _wirePushTaps() async {
    final source = ref.read(pushTokenSourceProvider);
    final initial = await source.initialMessageData();
    if (initial != null) _openPush(initial);
    source.onMessageOpened.listen(_openPush);
  }

  void _openPush(Map<String, String> data) {
    if (!mounted) return;
    final link = parsePushLink(type: data['type'], id: data['id']);
    final navigator = Navigator.of(context);
    switch (link) {
      case DeepLinkReport(:final id):
        navigator.push(MaterialPageRoute(
            builder: (_) => IssueDetailScreen(reportId: id)));
      case DeepLinkLedger(:final id):
        navigator.push(MaterialPageRoute(
            builder: (_) => LedgerDetailScreen(entryId: id)));
      case DeepLinkFeed():
        navigator.push(MaterialPageRoute(
            builder: (_) => const NotificationsScreen()));
    }
  }
```

with imports `../features/notifications/deep_link.dart`, `../features/notifications/notifications_screen.dart`, `../features/reports/issue_detail_screen.dart`, `../features/ledger/ledger_detail_screen.dart` (adjust to `features/...` relative paths from `app.dart`: `features/notifications/deep_link.dart` etc.).

For widget tests that pump `LamToApp`, the default `FirebasePushTokenSource` initializes lazily and `initialMessageData()` resolves null without config — no overrides needed; existing routing tests stay green.

- [ ] **Step 6: Run the affected suites**

Run: `cd app && flutter test test/app_routing_test.dart test/report_form_test.dart test/session_controller_test.dart test/push_registrar_test.dart`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/nts/src/LamTo
git add app/pubspec.yaml app/pubspec.lock app/lib/features/push app/lib/core/providers.dart \
        app/lib/features/reports/report_form_screen.dart \
        app/lib/features/auth/session_controller.dart app/lib/app.dart \
        app/test/push_registrar_test.dart
git commit -m "feat(app): consent-gated FCM registration with refresh and logout hygiene"
```

---

### Task 8: Integration-test happy path + full exit gate

**A7 obligations (in addition to the steps below):** (1) Wire `integration_test` into an actual scheduled nightly CI workflow under `.github/workflows/` (not README-only). (2) Add a real-device push smoke checklist document covering permission, registration, token refresh, background/terminated tap routing, and logout deregistration.

The §6.5 end-to-end: against a compose-seeded backend on a device/emulator — login → Home fund block → submit a report → see it in My Issues → open the Ledger. Documented as the nightly artifact (the repo has no CI files; the command is the contract).

**Files:**
- Modify: `app/pubspec.yaml` (dev dep `integration_test`)
- Create: `app/integration_test/app_test.dart`
- Modify: `app/README.md` (create if absent — run instructions)

**Interfaces:**
- Consumes: the whole app; dart-defines `API_BASE_URL`, `INTEGRATION_IDENTIFIER`, `INTEGRATION_PASSWORD`.

- [ ] **Step 1: Add the dev dependency**

In `app/pubspec.yaml` under `dev_dependencies:`:

```yaml
  integration_test:
    sdk: flutter
```

Run: `cd app && flutter pub get`

- [ ] **Step 2: Write the integration test**

Create `app/integration_test/app_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:integration_test/integration_test.dart';
import 'package:lamto/app.dart';

/// §6.5 happy path against a compose-seeded backend (run nightly on a device):
///
///   docker compose up -d              # repo root; then seed the pilot world
///   cd app && flutter test integration_test/app_test.dart \
///     --dart-define=API_BASE_URL=http://10.0.2.2:8000 \
///     --dart-define=INTEGRATION_IDENTIFIER=<seeded resident email/phone> \
///     --dart-define=INTEGRATION_PASSWORD=<seeded password>
const _identifier = String.fromEnvironment('INTEGRATION_IDENTIFIER');
const _password = String.fromEnvironment('INTEGRATION_PASSWORD');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('login -> home fund -> submit report -> my issues -> ledger',
      (tester) async {
    assert(_identifier.isNotEmpty && _password.isNotEmpty,
        'Pass INTEGRATION_IDENTIFIER / INTEGRATION_PASSWORD dart-defines.');

    await tester.pumpWidget(const ProviderScope(child: LamToApp()));
    await tester.pumpAndSettle(const Duration(seconds: 2));

    // Login.
    await tester.enterText(find.byType(TextField).at(0), _identifier);
    await tester.enterText(find.byType(TextField).at(1), _password);
    await tester.tap(find.text('Đăng nhập'));
    await tester.pumpAndSettle(const Duration(seconds: 5));

    // Home: fund block present (integer VND with dong sign).
    expect(find.text('Quỹ bảo trì'), findsOneWidget);
    expect(find.textContaining('₫'), findsWidgets);

    // Report tab: text + seeded location, submit without photos.
    await tester.tap(find.text('Phản ánh').last);
    await tester.pumpAndSettle();
    final reportText =
        'Kiểm thử tự động ${DateTime.now().millisecondsSinceEpoch}';
    await tester.enterText(find.byType(TextField).first, reportText);
    await tester.tap(find.text('Chọn vị trí'));
    await tester.pumpAndSettle(const Duration(seconds: 3));
    // Pick the first leaf row shown by the seeded location tree.
    await tester.tap(find.byType(ListTile).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Gửi phản ánh'));
    await tester.pumpAndSettle(const Duration(seconds: 5));
    expect(find.text('Phản ánh của bạn đã được ghi nhận.'), findsOneWidget);

    // My Issues: the new report is listed.
    await tester.tap(find.text('Việc của tôi').last);
    await tester.pumpAndSettle(const Duration(seconds: 3));
    expect(find.textContaining('Kiểm thử tự động'), findsWidgets);

    // Ledger tab renders (seeded world has a published expenditure).
    await tester.tap(find.text('Sổ quỹ').last);
    await tester.pumpAndSettle(const Duration(seconds: 3));
    expect(find.text('Sổ quỹ tòa nhà'), findsOneWidget);
  });
}
```

- [ ] **Step 3: Document the run + verify it compiles**

Create (or extend) `app/README.md`:

```markdown
# LamTo resident app

## Nightly integration test (spec §6.5)

Requires a running, seeded backend and a device/emulator:

    # repo root
    docker compose up -d
    # seed the pilot world (creates the resident login used below)
    .venv/bin/python manage.py seed_pilot

    cd app
    flutter test integration_test/app_test.dart \
      --dart-define=API_BASE_URL=http://10.0.2.2:8000 \
      --dart-define=INTEGRATION_IDENTIFIER=<resident email or phone from the seed output> \
      --dart-define=INTEGRATION_PASSWORD=<pilot password>

Android emulators reach the host at 10.0.2.2; iOS simulators use localhost.
```

Verify the test at least compiles without a device:

Run: `cd app && flutter analyze integration_test lib`
Expected: no errors.

- [ ] **Step 4: Full exit gate**

Run: `cd app && flutter test` → the entire widget/unit suite PASSES.
Run (backend unchanged since Task 1, but confirm): `cd /home/nts/src/LamTo && .venv/bin/python -m pytest src/lamto/api tests/isolation -q` → PASS.
On a device/emulator with the seeded backend, run the integration command from the README and confirm the happy path passes end-to-end.

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/pubspec.yaml app/pubspec.lock app/integration_test app/README.md
git commit -m "test(app): end-to-end happy path via integration_test"
```

---

## Self-review

### Spec coverage map (final §6/§7-client slice)

| Spec | Requirement | Task |
|---|---|---|
| §6.3(3) | Home: fund block (tabular VND), period flows, active reports, recent spending, bell | Task 3 (+2 formatter) |
| §6.3(6) | Ledger list + period filters | Task 4 |
| §6.3(6)/§5.2 | Detail: plain language first; distinct LOCAL_SIGNED/CHAIN_CONFIRMED/MISMATCH labels; mismatch prominent; mono only in expansion | Task 4 |
| §6.5 | Ledger evidence-label widget test | Task 4 (`evidence_labels_test.dart`) |
| §6.3(7) | Account: profile, occupancy switcher, preferences, logout, logout-all | Task 6 |
| §6.3(8) | Feed: list, mark-read, deep links to report/ledger | Tasks 1 (event_key), 5 |
| §7.4 | Allowlisted type→route map; unknown ignored; safe fallback; re-fetch re-authorizes | Task 5 (parser + pushed screens' failure states), Task 7 (tap wiring) |
| §7.5 | OS permission in context after first report submission; per-category prefs in Account | Tasks 7, 6 |
| §7.2 | `POST /devices` upsert; re-register on token refresh; logout deactivates install | Task 7 |
| §3.2/§6.4 | Server logout / logout-all on sign-out (best-effort, never traps the user) | Task 6 |
| §6.5 | `integration_test` happy path vs compose-seeded backend | Task 8 |
| No secrets in git | Firebase platform config deferred to deployment; code degrades without it | Task 7 |

With this plan executed, every Phase 0 + Phase 1 spec section (§2–§7) has been planned and implemented.

### Placeholder scan

No `TBD`/`add validation`/`similar to Task N`. Task 3 creates a placeholder `NotificationsScreen` that Task 5 explicitly replaces (spelled-out seam, full replacement given). Task 6's signOut tests live in a standalone `sign_out_test.dart` with their own fakes so they don't depend on the existing session test file's internals. Generated builder names carry the fallback instruction to the exact model files (Task 2).

### Type consistency

- `TransparencyRepository` signatures identical in the abstract class, `DioTransparencyRepository`, and every fake (Tasks 2–7); fakes use `noSuchMethod` for members a test doesn't exercise.
- `formatVnd(int) -> String` (Task 2) consumed in Tasks 3, 4, 8 with the `1.500.000 ₫` shape asserted in tests.
- `EvidenceBadge(level:)`, `evidenceLevelLabel`, `integrityStatusLabel` (Task 4) — used in list, detail, and proof events consistently.
- `DeepLink` variants + `parsePushLink`/`parseEventKey` (Task 5) consumed by the feed (Task 5) and push tap wiring (Task 7).
- `PushTokenSource`/`PushRegistrar`/`InstallIdStore` signatures match between implementation, providers, fakes, and hooks (Task 7).
- `signOut({bool allDevices = false})` (Task 6) matches the Account buttons and the Task 7 deregistration insert point.
- Generated names verified against the committed client: `authLogoutCreate`/`authLogoutAllCreate`, `ledgerList(cursor, month, year)`, `meNotificationPreferencesPartialUpdate`, `DeviceRegisterRequest(installId, fcmToken, platform, appVersion)`, `NotificationFeed.eventKey` (after Task 1).
