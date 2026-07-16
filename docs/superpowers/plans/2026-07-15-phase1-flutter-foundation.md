# Flutter Resident App — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Flutter resident app's foundation (spec §6): a platform-adaptive Material 3 scaffold, a Dart API client generated from the committed OpenAPI schema, the single auth/occupancy HTTP interceptor, problem-json failure mapping, Vietnamese-first l10n, the `GET /me`-driven app-start routing, and the Login + Occupancy-picker screens.

**Architecture:** A new `app/` Flutter project in this monorepo (see **Repository decision** below). The `dart-dio` generator turns `docs/api/openapi-v1.yaml` into a committed, CI-diffed typed model + serializer package (`app/packages/lamto_api`); thin repositories issue requests through one interceptor-configured `Dio` (attach knox token, inject `X-LamTo-Occupancy` **only on building-scoped endpoints**, map `application/problem+json`, clear the token on 401) and deserialize responses with the generated `standardSerializers` (preferred: use generated dart-dio API classes with that Dio; any manual path must have a contract test). Riverpod 3 holds session/occupancy state; a root `ConsumerWidget` routes on the async session state. Bootstrap reads secure storage first and distinguishes no-token/401 (Login) from network/timeout/server/schema (retryable error). Occupancy is persisted per user/install, validated against `/me`, and clears occupancy-scoped providers/caches on change. This plan delivers login → occupancy pick → an empty platform-adaptive tab shell; the feature screens land in the two follow-on plans (see Scope Check).

**Tech Stack:** Flutter (Material 3 + `.adaptive`), Dart 3, `flutter_riverpod` ^3, `dio` ^5, `flutter_secure_storage` ^9, `shared_preferences` (occupancy id only — never the auth token), `built_value`/`built_collection` (generated client), `openapi-generator-cli` v7 (dart-dio), Flutter `gen-l10n` (ARB), `flutter_test` + `mocktail`.

## Repository decision (required before scaffold)

**Decision (2026-07-16): monorepo — Flutter app lives at `app/` in this repository.**

Rationale:
- The OpenAPI schema at `docs/api/openapi-v1.yaml` is the single source of truth; co-locating the app with the schema and backend lets the CI drift gate (`check_api_generated.sh`) run in the same workflow as backend checks without cross-repo sync.
- Foundation plan, DESIGN.md, and product docs already assume monorepo `app/`.
- Separate-repo would force schema publishing/version pinning for Phase 1 with no compensating multi-team benefit yet.

**Do not run `flutter create` until this decision is recorded (this section). Scaffold path is `app/` under the monorepo root.**

## Plan amendments (eight clarifications)

These bind every task below (supersede conflicting original snippets):

1. **Bootstrap error taxonomy.** On start: read secure storage first. No token → `SessionUnauthenticated` (Login). With token: call `GET /me`. Only confirmed auth failure (HTTP 401 / `not_authenticated` / `authentication_failed`) routes to Login and clears the token. Transient failures — network, timeout, connection error, 5xx server, schema/deserialization errors — must surface as a **retryable bootstrap error state** (not Login). Do **not** treat bare `AsyncError` as Login.
2. **Occupancy persist / validate / clear.** Persist the selected occupancy id per user/install (keyed by user identity when available, else install-scoped). On each successful `/me`, validate the stored id is still in `me.occupancies`; if missing, clear it and force re-pick when multi-occupancy. When the selected occupancy changes, clear all occupancy-scoped providers and caches (invalidate occupancy-scoped Riverpod providers; reset holder/caches).
3. **Building-scoped occupancy header only.** Inject `X-LamTo-Occupancy` **only** on endpoints explicitly marked building-scoped (OpenAPI paths that declare the `X-LamTo-Occupancy` parameter, or an allowlist of path prefixes derived from the schema — e.g. locations, reports, ledger, notifications, fund). Do **not** attach the header to every request after selection (not on `/auth/*`, `/me`, `/devices` unless the schema marks them building-scoped).
4. **Generated client or contract tests.** Prefer generated dart-dio API classes wired to the interceptor-configured Dio. If any endpoint path is hand-written (string path on Dio), add a **contract test** that asserts that exact path string matches the OpenAPI path (one test per manual path).
5. **CI job.** Wire `check_api_generated.sh`, `flutter analyze`, and `flutter test` into an **actual** CI workflow job under `.github/workflows/` (not only local scripts).
6. **Theme completeness.** Implement **real tabular numeral styles** for VND (e.g. `FontFeature.tabularFigures()` on money text styles / `ThemeData` text theme where money is shown). Resolve incomplete dark-theme tokens: dark `ColorScheme` must set surface, onSurface, background/scaffold, primary, error, and border/outline-equivalent values — no critical null/default-only dark tokens.
7. **Platform-adaptive tab shell.** Material `NavigationBar` on Android; iOS-appropriate tab bar (`CupertinoTabBar` / adaptive chrome) while **reusing the same five screen bodies**. Branch chrome by platform (`Theme.of(context).platform` or `defaultTargetPlatform`); do not maintain two full product UI trees.
8. **Repo location.** See **Repository decision** above — decided and documented before scaffold.

## Scope Check (spec §6 is three plans)

§6 is a full mobile client — too large for one plan. It decomposes into three, each producing working, testable software:

1. **This plan — Foundation:** project + theme, generated API client, auth/occupancy interceptor, failure doctrine, l10n, session routing, Login, Occupancy picker. Runnable app that authenticates and lands on an (empty) tab shell.
2. **Reporting (next):** Report-issue (location picker from `/locations`, ≤5 photos with compression + `client_ref` retry + local draft), My-issues list/detail timeline, rate work.
3. **Transparency + Account (last):** Home (fund block + period flows + active reports + recent spending + bell), Ledger list/detail (evidence-level labels), Account (occupancy switcher, notification preferences via `PATCH /me/notification-preferences`, logout/logout-all), Notifications feed + mark-read, FCM registration (`POST /devices`) + OS permission, and the `integration_test` happy path.

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md` and `DESIGN.md`):

- **§6.1/§6.2 Flutter, one codebase iOS + Android.** Material 3 base with Flutter's platform-adaptive behaviors (`.adaptive` constructors, navigation transitions, back gesture) — **not two hand-built UI trees**. The **Dart API client is generated from the committed OpenAPI schema (regenerated + diffed in app CI)**; thin repository layer; **Riverpod** for state.
- **§6.2 Vietnamese-first l10n via ARB files.** All user-facing copy lives in the app, keyed off API `code` fields; **the server never sends display strings** (except OS-rendered push copy, out of scope here).
- **§6.2 Accessibility:** system font scaling end-to-end, screen-reader semantics, **≥44pt touch targets**, AA contrast with `DESIGN.md` tokens. Older-adult defaults: generous type, **one primary action per screen**, no gesture-only affordances.
- **§6.4 One HTTP interceptor owns auth:** attach token; **any 401 → clear secure storage → login**. App start: `GET /me` decides route. Every error path follows the failure doctrine — **what happened, whether data was saved, next safe action** — mapped from problem-json `code`s; **no raw HTTP jargon shown to residents**.
- **§3.2 Client token storage:** iOS Keychain / Android Keystore only (`flutter_secure_storage`); **never plain preferences**. Auth is the knox `Authorization: Token <token>` scheme (no JWT/OAuth).
- **§3.4 Occupancy context:** send `X-LamTo-Occupancy: <id>` on building-scoped calls; the server validates it. A client-supplied building ID is never sent — only the occupancy id.
- **`DESIGN.md`:** Accountability Indigo `#2f3a8f` ≤10% of a screen; semantic integrity colors (success `#0f7a45`, warning `#9a6700`, error `#b42318`, info `#175cd3`) always paired with text/icon; flat by default; motion only for state change; tabular numerals for money; WCAG 2.2 AA. Resident nav is a platform tab bar (Home · Report · Issues · Ledger · Account).

## Verified environment

The backend serves the committed schema at `docs/api/openapi-v1.yaml`. App commands run from `app/`:

```bash
# one-time: install openapi-generator-cli (Node) and Flutter deps
cd app && flutter pub get
# generate the API client (Task 2 wraps this in tool/generate_api.sh):
npx @openapitools/openapi-generator-cli version   # pins v7
flutter test                                       # runs widget/unit tests
# backend for manual runs: `docker compose up -d` at repo root, API at /api/v1/
```

The Android emulator reaches a host backend at `http://10.0.2.2:8000`; iOS simulator at `http://localhost:8000`. Base URL is a `--dart-define=API_BASE_URL=...` (default `http://10.0.2.2:8000`).

## File Structure

```
app/
  pubspec.yaml                      # deps; path dep on packages/lamto_api
  l10n.yaml                         # gen-l10n config
  analysis_options.yaml             # flutter_lints
  tool/
    generate_api.sh                 # openapi-generator + build_runner
    check_api_generated.sh          # CI drift gate
  packages/lamto_api/               # GENERATED dart-dio client (committed)
  lib/
    main.dart                       # runApp(ProviderScope(child: LamToApp()))
    app.dart                        # LamToApp: theme + l10n + AppRouter
    theme.dart                      # DESIGN.md tokens -> Material 3 ThemeData
    core/
      config.dart                   # apiBaseUrl (dart-define)
      token_store.dart              # flutter_secure_storage wrapper
      api_client.dart               # Dio + AuthInterceptor + OccupancyInterceptor
      failure.dart                  # Failure + failureFromDio + messageForCode
      providers.dart                # Riverpod: dio, tokenStore, occupancy, session
    features/auth/
      session_controller.dart       # AsyncNotifier<SessionState>
      auth_repository.dart          # login(), fetchMe()
      login_screen.dart
      occupancy_picker_screen.dart
    features/shell/
      home_shell.dart               # 5-tab adaptive scaffold (placeholder tabs)
    l10n/
      app_en.arb                    # template
      app_vi.arb                    # Vietnamese (primary)
  test/
    ...                             # one test file per task
```

---

### Task 1: Flutter project scaffold, theme, and tooling

Create the app, wire the `DESIGN.md` design tokens into a Material 3 theme, and prove the harness runs.

**Files:**
- Create: `app/` (via `flutter create`), `app/pubspec.yaml`, `app/analysis_options.yaml`, `app/lib/main.dart`, `app/lib/app.dart`, `app/lib/theme.dart`, `app/lib/core/config.dart`
- Test: `app/test/theme_test.dart`

**Interfaces:**
- Produces: `lamToTheme(Brightness)` → `ThemeData`; `apiBaseUrl` (const from `--dart-define`); `LamToApp` widget (theme + placeholder home).

- [ ] **Step 1: Create the project + dependencies**

```bash
cd /home/nts/src/LamTo
flutter create --org com.lamto --project-name lamto app
cd app
# Latest majors resolve to riverpod ^3, dio ^5, flutter_secure_storage ^9.
flutter pub add flutter_riverpod dio flutter_secure_storage intl
flutter pub add dev:mocktail
flutter pub add flutter_localizations --sdk=flutter
```

In `app/pubspec.yaml`, enable l10n + Material and add the (soon-to-exist) generated client path dep under `dependencies:`:

```yaml
  lamto_api:
    path: packages/lamto_api
```

Add under the top level:

```yaml
flutter:
  uses-material-design: true
  generate: true
```

(`lamto_api` won't resolve until Task 2 generates it; comment the two lines out until then, or do Task 2 Step 1 first. Note this in the commit.)

- [ ] **Step 2: Add the design tokens + theme**

Create `app/lib/core/config.dart`:

```dart
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);
```

Create `app/lib/theme.dart` (tokens from `DESIGN.md`; Accountability Indigo seed, semantic colors paired with text/icon elsewhere):

```dart
import 'package:flutter/material.dart';

class LamToColors {
  static const primary = Color(0xFF2F3A8F);
  static const onPrimary = Color(0xFFFFFFFF);
  static const bg = Color(0xFFF6F7FB);
  static const surface = Color(0xFFFFFFFF);
  static const ink = Color(0xFF1C2434);
  static const muted = Color(0xFF5B6577);
  static const border = Color(0xFFD7DCE8);
  static const success = Color(0xFF0F7A45);
  static const warning = Color(0xFF9A6700);
  static const error = Color(0xFFB42318);
  static const info = Color(0xFF175CD3);
}

/// Dark-theme tokens (complete — clarification #6; no critical null tokens).
class LamToColorsDark {
  static const bg = Color(0xFF12141C);
  static const surface = Color(0xFF1C2030);
  static const ink = Color(0xFFE8EAF2);
  static const muted = Color(0xFFA0A8B8);
  static const border = Color(0xFF3A4158);
  static const onPrimary = Color(0xFFFFFFFF);
}

/// Money / VND text style with real tabular figures (DESIGN.md + clarification #6).
TextStyle moneyTextStyle(TextTheme base, {Color? color}) {
  return (base.titleMedium ?? const TextStyle()).copyWith(
    fontFeatures: const [FontFeature.tabularFigures()],
    color: color,
    fontWeight: FontWeight.w600,
  );
}

ThemeData lamToTheme(Brightness brightness) {
  final isDark = brightness == Brightness.dark;
  final surface = isDark ? LamToColorsDark.surface : LamToColors.surface;
  final bg = isDark ? LamToColorsDark.bg : LamToColors.bg;
  final onSurface = isDark ? LamToColorsDark.ink : LamToColors.ink;
  final outline = isDark ? LamToColorsDark.border : LamToColors.border;
  final scheme = ColorScheme.fromSeed(
    seedColor: LamToColors.primary,
    brightness: brightness,
    primary: LamToColors.primary,
    onPrimary: LamToColors.onPrimary,
    error: LamToColors.error,
    surface: surface,
    onSurface: onSurface,
    outline: outline,
  );
  final baseText = Typography.material2021(platform: TargetPlatform.android)
      .black
      .apply(
        bodyColor: onSurface,
        displayColor: onSurface,
        fontFamilyFallback: const ['Roboto'],
      );
  // Apply tabular figures to titleMedium used for money (VND).
  final textTheme = baseText.copyWith(
    titleMedium: moneyTextStyle(baseText, color: onSurface),
  );
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: bg,
    textTheme: textTheme,
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      border: const OutlineInputBorder(),
      filled: true,
      fillColor: surface,
    ),
  );
}
```

Theme tests must assert: light primary indigo; dark scheme has non-default surface/onSurface/outline/scaffoldBackgroundColor; `moneyTextStyle` includes `FontFeature.tabularFigures()`.

- [ ] **Step 3: Minimal app entrypoint**

Create `app/lib/app.dart`:

```dart
import 'package:flutter/material.dart';
import 'theme.dart';

class LamToApp extends StatelessWidget {
  const LamToApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'LamTo',
      theme: lamToTheme(Brightness.light),
      darkTheme: lamToTheme(Brightness.dark),
      home: const Scaffold(body: Center(child: Text('LamTo'))),
    );
  }
}
```

Replace `app/lib/main.dart` with:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'app.dart';

void main() => runApp(const ProviderScope(child: LamToApp()));
```

- [ ] **Step 4: Write the failing test**

Create `app/test/theme_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/theme.dart';

void main() {
  test('theme uses Accountability Indigo as primary', () {
    final theme = lamToTheme(Brightness.light);
    expect(theme.colorScheme.primary, LamToColors.primary);
    expect(theme.useMaterial3, isTrue);
  });
}
```

- [ ] **Step 5: Run the test**

Run: `cd app && flutter test test/theme_test.dart`
Expected: PASS (1 test).

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
echo "app/build/" >> app/.gitignore
git add app/pubspec.yaml app/pubspec.lock app/analysis_options.yaml app/lib app/test app/.gitignore \
        app/l10n.yaml 2>/dev/null; git add app
git commit -m "feat(app): Flutter scaffold with DESIGN.md Material 3 theme"
```

---

### Task 2: Generated Dart API client + CI drift gate

Generate the `dart-dio` client from the committed schema into a committed path-dependency package, with a regenerate-and-diff CI gate (spec §6.2).

**Files:**
- Create: `app/tool/generate_api.sh`, `app/tool/check_api_generated.sh`
- Create: `app/packages/lamto_api/` (generated, committed)
- Test: `app/test/api_client_models_test.dart`

**Interfaces:**
- Produces: package `lamto_api` exposing generated built_value models (`TokenResponse`, `Me`, `Occupancy`, `Problem`, …) and `standardSerializers` (built_value `Serializers`).

- [ ] **Step 1: Write the generate script**

Create `app/tool/generate_api.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SCHEMA="../docs/api/openapi-v1.yaml"
OUT="packages/lamto_api"
rm -rf "$OUT"
# dateLibrary=core avoids the timemachine dependency; the schema's required/
# nullable markers drive field nullability (phone is nullable, token is not).
npx --yes @openapitools/openapi-generator-cli@v7.19.0 generate \
  -i "$SCHEMA" -g dart-dio -o "$OUT" \
  --additional-properties=pubName=lamto_api,dateLibrary=core
# built_value codegen for the generated package:
( cd "$OUT" && dart pub get && dart run build_runner build --delete-conflicting-outputs )
```

Make it executable: `chmod +x app/tool/generate_api.sh`

- [ ] **Step 2: Generate the client**

Run: `cd app && ./tool/generate_api.sh`
Expected: creates `app/packages/lamto_api/` with `lib/lamto_api.dart`, `lib/src/model/*.dart` (built_value models incl. their `*.g.dart`), and `lib/src/serializers.dart` exporting `standardSerializers`.

- [ ] **Step 3: Uncomment the path dependency**

In `app/pubspec.yaml`, uncomment/confirm the `lamto_api: { path: packages/lamto_api }` dependency, add `built_collection` (the app and tests build generated models), then resolve:

Run: `cd app && flutter pub add built_collection && flutter pub get`
Expected: resolves the local `lamto_api` package and `built_collection`.

- [ ] **Step 4: Write the failing test**

Create `app/test/api_client_models_test.dart` (proves the generated models compile + deserialize; component names come from the server serializers — `TokenResponseSerializer` → `TokenResponse`, etc.):

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto_api/lamto_api.dart';

void main() {
  test('generated TokenResponse deserializes via standardSerializers', () {
    final token = standardSerializers.deserializeWith(
      TokenResponse.serializer,
      {'token': 'abc', 'expiry': '2026-08-01T00:00:00Z'},
    );
    expect(token!.token, 'abc');
  });
}
```

- [ ] **Step 5: Run the test**

Run: `cd app && flutter test test/api_client_models_test.dart`
Expected: PASS. (If the generated class name for the schema title differs, this test surfaces it immediately — the model component names are `TokenResponse`, `Me`, `Occupancy`, `Problem` from the serializers.)

- [ ] **Step 6: Write the CI drift gate**

Create `app/tool/check_api_generated.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./tool/generate_api.sh
if ! git diff --quiet -- packages/lamto_api; then
  echo "ERROR: packages/lamto_api is stale. Run app/tool/generate_api.sh and commit." >&2
  git --no-pager diff --stat -- packages/lamto_api >&2
  exit 1
fi
echo "OK: generated API client matches the committed schema."
```

Make it executable: `chmod +x app/tool/check_api_generated.sh`. Verify it passes now: `cd app && ./tool/check_api_generated.sh` → `OK`.

- [ ] **Step 7: Commit**

```bash
cd /home/nts/src/LamTo
# Do not gitignore the generated .g.dart — the schema is the source of truth and CI diffs the output.
git add app/tool app/packages/lamto_api app/pubspec.yaml app/pubspec.lock
git commit -m "feat(app): generate dart-dio API client from committed OpenAPI schema with drift gate"
```

---

### Task 3: Secure token storage + Dio + auth interceptor

The knox token store (Keychain/Keystore) and the single interceptor that attaches the token and clears it on 401 (spec §3.2, §6.4).

**Files:**
- Create: `app/lib/core/token_store.dart`, `app/lib/core/api_client.dart`
- Test: `app/test/auth_interceptor_test.dart`

**Interfaces:**
- Produces:
  - `TokenStore` — `Future<String?> read()`, `Future<void> write(String)`, `Future<void> clear()`.
  - `buildDio({required TokenStore store, required void Function() onUnauthorized, String? baseUrl})` → `Dio` with the auth interceptor installed.

- [ ] **Step 1: Write the failing test**

Create `app/test/auth_interceptor_test.dart` (uses Dio's in-memory `HttpClientAdapter` mock via `mocktail`):

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/api_client.dart';
import 'package:lamto/core/token_store.dart';
import 'package:mocktail/mocktail.dart';

class _FakeStore implements TokenStore {
  String? token;
  @override
  Future<void> clear() async => token = null;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String value) async => token = value;
}

class _MockAdapter extends Mock implements HttpClientAdapter {}

void main() {
  setUpAll(() => registerFallbackValue(RequestOptions(path: '/')));

  test('attaches token and clears it on 401', () async {
    final store = _FakeStore()..token = 'knox-123';
    final adapter = _MockAdapter();
    var unauthorized = false;
    final dio = buildDio(store: store, onUnauthorized: () => unauthorized = true, baseUrl: 'http://x');
    dio.httpClientAdapter = adapter;

    // First call: 200, assert the Authorization header was attached.
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
      final opts = inv.positionalArguments[0] as RequestOptions;
      expect(opts.headers['Authorization'], 'Token knox-123');
      return ResponseBody.fromString('{}', 200, headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      });
    });
    await dio.get<dynamic>('/me');

    // Second call: 401 -> token cleared + onUnauthorized fired.
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((_) async =>
        ResponseBody.fromString('{}', 401, headers: {
          Headers.contentTypeHeader: [Headers.jsonContentType],
        }));
    await expectLater(dio.get<dynamic>('/me'), throwsA(isA<DioException>()));
    expect(store.token, isNull);
    expect(unauthorized, isTrue);
  });
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test test/auth_interceptor_test.dart`
Expected: FAIL — `token_store.dart`/`api_client.dart` do not exist.

- [ ] **Step 3: Implement the token store + Dio**

Create `app/lib/core/token_store.dart`:

```dart
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Knox token in the platform keystore only (spec 3.2) — never plain prefs.
class TokenStore {
  TokenStore([FlutterSecureStorage? storage])
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
            );

  final FlutterSecureStorage _storage;
  static const _key = 'lamto_auth_token';

  Future<String?> read() => _storage.read(key: _key);
  Future<void> write(String value) => _storage.write(key: _key, value: value);
  Future<void> clear() => _storage.delete(key: _key);
}
```

Create `app/lib/core/api_client.dart`:

```dart
import 'package:dio/dio.dart';
import 'config.dart';
import 'token_store.dart';

/// One interceptor owns auth (spec 6.4): attach the knox token; on any 401
/// clear secure storage and signal the session is lost.
Dio buildDio({
  required TokenStore store,
  required void Function() onUnauthorized,
  String? baseUrl,
}) {
  final dio = Dio(BaseOptions(baseUrl: baseUrl ?? apiBaseUrl));
  dio.interceptors.add(InterceptorsWrapper(
    onRequest: (options, handler) async {
      final token = await store.read();
      if (token != null && token.isNotEmpty) {
        options.headers['Authorization'] = 'Token $token';
        options.extra['had_token'] = true;
      }
      handler.next(options);
    },
    onError: (error, handler) async {
      // Only a 401 on a request that CARRIED a token is a session expiry.
      // A token-less bootstrap GET /me also 401s; firing onUnauthorized there
      // would loop, so gate on had_token.
      if (error.response?.statusCode == 401 &&
          error.requestOptions.extra['had_token'] == true) {
        await store.clear();
        onUnauthorized();
      }
      handler.next(error);
    },
  ));
  return dio;
}
```

- [ ] **Step 4: Run the test**

Run: `cd app && flutter test test/auth_interceptor_test.dart`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/token_store.dart app/lib/core/api_client.dart app/test/auth_interceptor_test.dart
git commit -m "feat(app): secure token store and auth interceptor with 401 clear"
```

---

### Task 4: Problem+json failure mapping + doctrine

Turn `application/problem+json` bodies into a typed `Failure`, and map `code`s to the resident failure doctrine — what happened, whether data was saved, the next safe action (spec §6.4).

**Files:**
- Create: `app/lib/core/failure.dart`
- Test: `app/test/failure_test.dart`

**Interfaces:**
- Produces:
  - `Failure(code, detail, fieldErrors)`; `Failure.fromDio(DioException)`.
  - `String messageForCode(String code, AppLocalizations l10n)` — l10n keys per `code`, generic fallback. (l10n arrives in Task 6; Task 4 keeps a `Map<String,String Function(AppLocalizations)>` and a plain-string fallback so the test runs without l10n.)

- [ ] **Step 1: Write the failing test**

Create `app/test/failure_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/failure.dart';

DioException _dio(int status, Map<String, dynamic> body) {
  final req = RequestOptions(path: '/x');
  return DioException(
    requestOptions: req,
    response: Response(requestOptions: req, statusCode: status, data: body),
    type: DioExceptionType.badResponse,
  );
}

void main() {
  test('parses problem+json code and per-field errors', () {
    final f = Failure.fromDio(_dio(400, {
      'code': 'validation_failed',
      'detail': 'Request validation failed.',
      'errors': {'text': [{'message': 'This field is required.', 'code': 'required'}]},
    }));
    expect(f.code, 'validation_failed');
    expect(f.fieldErrors['text']!.first, 'This field is required.');
  });

  test('maps known codes and falls back generically', () {
    expect(Failure(code: 'occupancy_selection_required').isKnown, isTrue);
    expect(Failure(code: 'weird_unknown').isKnown, isFalse);
    // Network/timeout with no response still yields a usable code.
    final net = Failure.fromDio(DioException(
      requestOptions: RequestOptions(path: '/x'), type: DioExceptionType.connectionTimeout));
    expect(net.code, 'network_error');
  });
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test test/failure_test.dart`
Expected: FAIL — `failure.dart` does not exist.

- [ ] **Step 3: Implement the failure type**

Create `app/lib/core/failure.dart`:

```dart
import 'package:dio/dio.dart';

/// Stable machine codes the resident UI branches on (spec 3.1). Copy is owned
/// by the app (Task 6 l10n); the server never sends display strings.
const knownFailureCodes = {
  'validation_failed',
  'authentication_failed',
  'not_authenticated',
  'permission_denied',
  'not_found',
  'occupancy_selection_required',
  'client_ref_conflict',
  'throttled',
  'network_error',
  'server_error',
};

class Failure {
  Failure({required this.code, this.detail = '', this.fieldErrors = const {}});

  final String code;
  final String detail; // developer English; never shown raw to residents
  final Map<String, List<String>> fieldErrors;

  bool get isKnown => knownFailureCodes.contains(code);

  factory Failure.fromDio(DioException e) {
    final data = e.response?.data;
    if (data is Map && data['code'] is String) {
      final rawErrors = data['errors'];
      final fieldErrors = <String, List<String>>{};
      if (rawErrors is Map) {
        rawErrors.forEach((key, value) {
          if (value is List) {
            fieldErrors['$key'] = value
                .map((item) => item is Map && item['message'] != null
                    ? '${item['message']}'
                    : '$item')
                .toList();
          }
        });
      }
      return Failure(
        code: data['code'] as String,
        detail: data['detail'] is String ? data['detail'] as String : '',
        fieldErrors: fieldErrors,
      );
    }
    final status = e.response?.statusCode;
    if (status != null && status >= 500) return Failure(code: 'server_error');
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return Failure(code: 'network_error');
      default:
        return Failure(code: 'server_error');
    }
  }
}
```

- [ ] **Step 4: Run the test**

Run: `cd app && flutter test test/failure_test.dart`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/failure.dart app/test/failure_test.dart
git commit -m "feat(app): problem+json failure parsing with stable codes"
```

---

### Task 5: Occupancy header injection + occupancy state

Hold the selected occupancy id and inject `X-LamTo-Occupancy` on building-scoped requests (spec §3.4). A client building id is never sent.

**Files:**
- Modify: `app/lib/core/api_client.dart`
- Create: `app/lib/core/occupancy.dart`
- Test: `app/test/occupancy_header_test.dart`

**Interfaces:**
- Produces:
  - `OccupancyHolder` — mutable `int? occupancyId` (a plain object the interceptor reads); persist/load/validate helpers.
  - `isBuildingScopedPath(String path)` — true only for endpoints that require occupancy (clarification #3).
  - `buildDio(...)` gains `required OccupancyHolder occupancy`; interceptor adds `X-LamTo-Occupancy` **only when set AND path is building-scoped**.
  - On occupancy change: clear occupancy-scoped providers/caches (clarification #2).

**Building-scoped path prefixes** (from OpenAPI paths declaring `X-LamTo-Occupancy`):
`/api/v1/locations`, `/api/v1/reports`, `/api/v1/ledger`, `/api/v1/notifications`, `/api/v1/fund` (and nested). Non-scoped: `/api/v1/auth/*`, `/api/v1/me`, `/api/v1/devices` (unless schema later marks them).

- [ ] **Step 1: Write the failing test**

Create `app/test/occupancy_header_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/api_client.dart';
import 'package:lamto/core/occupancy.dart';
import 'package:lamto/core/token_store.dart';
import 'package:mocktail/mocktail.dart';

class _FakeStore implements TokenStore {
  @override
  Future<void> clear() async {}
  @override
  Future<String?> read() async => 'tok';
  @override
  Future<void> write(String value) async {}
}

class _MockAdapter extends Mock implements HttpClientAdapter {}

void main() {
  setUpAll(() => registerFallbackValue(RequestOptions(path: '/')));

  test('injects X-LamTo-Occupancy only on building-scoped paths when set', () async {
    final holder = OccupancyHolder()..occupancyId = 42;
    final adapter = _MockAdapter();
    final dio = buildDio(
      store: _FakeStore(), occupancy: holder, onUnauthorized: () {}, baseUrl: 'http://x');
    dio.httpClientAdapter = adapter;

    String? seen;
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
      seen = (inv.positionalArguments[0] as RequestOptions).headers['X-LamTo-Occupancy']?.toString();
      return ResponseBody.fromString('{}', 200,
          headers: {Headers.contentTypeHeader: [Headers.jsonContentType]});
    });

    // Non-scoped: /me must NOT get the header even when occupancy is set.
    await dio.get<dynamic>('/api/v1/me');
    expect(seen, isNull);

    // Building-scoped: /ledger gets the header.
    await dio.get<dynamic>('/api/v1/ledger');
    expect(seen, '42');

    // When unset, building-scoped also omits header.
    holder.occupancyId = null;
    seen = 'sentinel';
    await dio.get<dynamic>('/api/v1/ledger');
    expect(seen, isNull);
  });

  test('isBuildingScopedPath allowlist', () {
    expect(isBuildingScopedPath('/api/v1/ledger'), isTrue);
    expect(isBuildingScopedPath('/api/v1/reports'), isTrue);
    expect(isBuildingScopedPath('/api/v1/me'), isFalse);
    expect(isBuildingScopedPath('/api/v1/auth/login'), isFalse);
  });
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test test/occupancy_header_test.dart`
Expected: FAIL — `occupancy.dart` missing / `buildDio` has no `occupancy` param.

- [ ] **Step 3: Implement**

Create `app/lib/core/occupancy.dart`:

```dart
/// Path prefixes that declare X-LamTo-Occupancy in the OpenAPI schema.
const buildingScopedPathPrefixes = [
  '/api/v1/locations',
  '/api/v1/reports',
  '/api/v1/ledger',
  '/api/v1/notifications',
  '/api/v1/fund',
];

bool isBuildingScopedPath(String path) {
  final p = path.startsWith('http') ? Uri.parse(path).path : path;
  return buildingScopedPathPrefixes.any((prefix) => p == prefix || p.startsWith('$prefix/'));
}

/// Selected active occupancy id (spec 3.4). Only the occupancy id is ever sent.
/// Persist/load/validate against /me; clear scoped state on change (clarification #2).
class OccupancyHolder {
  int? occupancyId;
}
```

In `app/lib/core/api_client.dart`, add import and `occupancy` parameter; in `onRequest` after token:

```dart
      final occ = occupancy.occupancyId;
      if (occ != null && isBuildingScopedPath(options.path)) {
        options.headers['X-LamTo-Occupancy'] = occ;
      }
```

Update Task-3 test's `buildDio(...)` to pass `occupancy: OccupancyHolder()`.

- [ ] **Step 4: Run the tests**

Run: `cd app && flutter test test/occupancy_header_test.dart test/auth_interceptor_test.dart`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/occupancy.dart app/lib/core/api_client.dart \
        app/test/occupancy_header_test.dart app/test/auth_interceptor_test.dart
git commit -m "feat(app): inject X-LamTo-Occupancy only on building-scoped paths"
```

---

### Task 6: Vietnamese-first localization

ARB-based l10n with Vietnamese as the primary language and per-`code` failure copy (spec §6.2).

**Files:**
- Create: `app/l10n.yaml`, `app/lib/l10n/app_en.arb`, `app/lib/l10n/app_vi.arb`
- Modify: `app/lib/app.dart`, `app/lib/core/failure.dart`
- Test: `app/test/l10n_test.dart`

**Interfaces:**
- Produces: generated `AppLocalizations` (import `package:lamto/l10n/app_localizations.dart`); `failureMessage(Failure, AppLocalizations)` → resident VI copy.

- [ ] **Step 1: Add the l10n config + ARBs**

Create `app/l10n.yaml`:

```yaml
arb-dir: lib/l10n
template-arb-file: app_en.arb
output-localization-file: app_localizations.dart
output-class: AppLocalizations
```

Create `app/lib/l10n/app_en.arb` (template — English keys):

```json
{
  "appTitle": "LamTo",
  "loginTitle": "Sign in",
  "loginIdentifier": "Phone or email",
  "loginPassword": "Password",
  "loginSubmit": "Sign in",
  "occupancyPickerTitle": "Choose your home",
  "errAuthFailed": "The phone/email or password is incorrect. Nothing was submitted. Please try again.",
  "errThrottled": "Too many attempts. Nothing was submitted. Please wait a few minutes and try again.",
  "errOccupancyRequired": "Please choose which home this applies to.",
  "errNetwork": "No connection. Your action was not sent. Check your network and retry.",
  "errServer": "Something went wrong on our side. Your action may not have been saved. Please try again shortly.",
  "errGeneric": "Something went wrong. Please try again.",
  "tabHome": "Home",
  "tabReport": "Report",
  "tabIssues": "Issues",
  "tabLedger": "Ledger",
  "tabAccount": "Account"
}
```

Create `app/lib/l10n/app_vi.arb` (primary — Vietnamese):

```json
{
  "@@locale": "vi",
  "appTitle": "LamTo",
  "loginTitle": "Đăng nhập",
  "loginIdentifier": "Số điện thoại hoặc email",
  "loginPassword": "Mật khẩu",
  "loginSubmit": "Đăng nhập",
  "occupancyPickerTitle": "Chọn căn hộ của bạn",
  "errAuthFailed": "Số điện thoại/email hoặc mật khẩu không đúng. Chưa có gì được gửi đi. Vui lòng thử lại.",
  "errThrottled": "Bạn đã thử quá nhiều lần. Chưa có gì được gửi đi. Vui lòng đợi vài phút rồi thử lại.",
  "errOccupancyRequired": "Vui lòng chọn căn hộ áp dụng.",
  "errNetwork": "Không có kết nối. Thao tác chưa được gửi. Kiểm tra mạng và thử lại.",
  "errServer": "Đã có lỗi từ phía hệ thống. Thao tác có thể chưa được lưu. Vui lòng thử lại sau.",
  "errGeneric": "Đã có lỗi xảy ra. Vui lòng thử lại.",
  "tabHome": "Trang chính",
  "tabReport": "Phản ánh",
  "tabIssues": "Việc của tôi",
  "tabLedger": "Sổ quỹ",
  "tabAccount": "Tài khoản"
}
```

- [ ] **Step 2: Generate + wire localizations**

Run: `cd app && flutter gen-l10n && flutter pub get`
Expected: generates `app/lib/l10n/app_localizations.dart`.

In `app/lib/app.dart`, import and register the delegates, defaulting to Vietnamese:

```dart
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:lamto/l10n/app_localizations.dart';
```

In the `MaterialApp`, add:

```dart
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('vi'),
```

- [ ] **Step 3: Add the failure→copy mapper**

Append to `app/lib/core/failure.dart`:

```dart
import 'package:lamto/l10n/app_localizations.dart';

/// Resident-facing copy per failure code (spec 6.4 doctrine). Never shows raw
/// HTTP jargon or the developer `detail`.
String failureMessage(Failure f, AppLocalizations l10n) {
  switch (f.code) {
    case 'authentication_failed':
    case 'not_authenticated':
      return l10n.errAuthFailed;
    case 'throttled':
      return l10n.errThrottled;
    case 'occupancy_selection_required':
      return l10n.errOccupancyRequired;
    case 'network_error':
      return l10n.errNetwork;
    case 'server_error':
      return l10n.errServer;
    default:
      return l10n.errGeneric;
  }
}
```

- [ ] **Step 4: Write the failing test**

Create `app/test/l10n_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/failure.dart';
import 'package:lamto/l10n/app_localizations.dart';

void main() {
  testWidgets('Vietnamese failure copy is used and mentions save state', (tester) async {
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
    expect(failureMessage(Failure(code: 'throttled'), l10n), contains('Chưa có gì được gửi'));
    expect(l10n.loginSubmit, 'Đăng nhập');
  });
}
```

- [ ] **Step 5: Run the test**

Run: `cd app && flutter test test/l10n_test.dart`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/l10n.yaml app/lib/l10n app/lib/app.dart app/lib/core/failure.dart app/test/l10n_test.dart
git commit -m "feat(app): Vietnamese-first l10n and failure-doctrine copy"
```

---

### Task 7: Session controller + app-start routing

The Riverpod session state, the `GET /me`-driven bootstrap with error taxonomy (clarification #1), occupancy persist/validate (clarification #2), and the root router (spec §6.4).

**Files:**
- Create: `app/lib/features/auth/auth_repository.dart`, `app/lib/features/auth/session_controller.dart`, `app/lib/core/providers.dart`, `app/lib/core/occupancy_store.dart`
- Modify: `app/lib/app.dart`
- Test: `app/test/session_controller_test.dart`, `app/test/auth_repository_contract_test.dart` (manual paths)

**Interfaces:**
- Consumes: `buildDio`, `TokenStore`, `OccupancyHolder`, `Failure`, generated `Me`/`TokenResponse`.
- Produces:
  - `AuthRepository` — `login`, `fetchMe`.
  - `SessionState` sealed: `SessionUnauthenticated`, `SessionAuthenticated(Me me)`, `SessionBootstrapError(Failure failure)` (retryable).
  - Bootstrap: **read secure storage first**; no token → unauthenticated; with token → `GET /me`; only 401/auth codes → unauthenticated (+ clear token); network/timeout/server/schema → `SessionBootstrapError`.
  - Occupancy: load persisted id, validate against `me.occupancies`, clear invalid; on change clear occupancy-scoped providers.
  - Contract tests for every hand-written Dio path (clarification #4) if not using generated API classes for requests.

- [ ] **Step 1: Write the failing test**

Create `app/test/session_controller_test.dart` covering:
- no token in store → `SessionUnauthenticated` (must not call fetchMe)
- token + successful me → `SessionAuthenticated`
- token + 401 → `SessionUnauthenticated` and token cleared
- token + network/timeout DioException → `SessionBootstrapError` with network_error (NOT unauthenticated)
- token + schema/deserialize failure → `SessionBootstrapError`
- persisted occupancy validated: id not in me.occupancies is cleared

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test test/session_controller_test.dart`
Expected: FAIL — the providers/controller don't exist.

- [ ] **Step 3: Implement the repository**

Create `app/lib/features/auth/auth_repository.dart` using Dio + generated `standardSerializers` for deserialize. Document manual paths and add `app/test/auth_repository_contract_test.dart` asserting paths equal OpenAPI:
- `POST /api/v1/auth/login`
- `GET /api/v1/me`

(Or wire generated dart-dio API classes to the same interceptor Dio — prefer that if generation exposes usable services.)

- [ ] **Step 4: Implement providers + controller + occupancy store**

- `OccupancyStore` (shared_preferences): `read(userKey)`, `write(userKey, id)`, `clear(userKey)`.
- `SessionController._bootstrap()`:
  1. `token = await store.read()`; if null/empty → `SessionUnauthenticated`.
  2. try `fetchMe()`; on success validate occupancy, return `SessionAuthenticated`.
  3. on DioException: if 401 or auth failure codes → clear token → `SessionUnauthenticated`; else map `Failure.fromDio` → `SessionBootstrapError`.
  4. on other errors (e.g. TypeError/deserialize) → `SessionBootstrapError(code: schema_error)`.
- `selectOccupancy(id)`: persist, set holder, **invalidate occupancy-scoped providers**.
- Do not map bare catch-all to unauthenticated.

- [ ] **Step 5: Run the test**

Run: `cd app && flutter test test/session_controller_test.dart test/auth_repository_contract_test.dart`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/providers.dart app/lib/core/occupancy_store.dart \
        app/lib/features/auth/ app/test/session_controller_test.dart \
        app/test/auth_repository_contract_test.dart
git commit -m "feat(app): session bootstrap taxonomy and occupancy persist/validate"
```

---

### Task 8: Login, occupancy picker, and the tab shell

The visible foundation: login, the occupancy picker (when `/me` has >1 occupancy), and the adaptive 5-tab shell — routed by session state (spec §6.3, §6.4).

**Files:**
- Create: `app/lib/features/auth/login_screen.dart`, `app/lib/features/auth/occupancy_picker_screen.dart`, `app/lib/features/shell/home_shell.dart`
- Modify: `app/lib/app.dart`
- Test: `app/test/app_routing_test.dart`

**Interfaces:**
- Consumes: `sessionControllerProvider`, `SessionState`, `occupancyHolderProvider`, `failureMessage`, `AppLocalizations`, generated `Me`/`Occupancy`.
- Produces: `LoginScreen`, `OccupancyPickerScreen`, `HomeShell`; `AppRouter` (root `ConsumerWidget`).

- [ ] **Step 1: Write the failing test**

Create `app/test/app_routing_test.dart`:

```dart
import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/app.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/features/auth/auth_repository.dart';
import 'package:lamto/features/auth/session_controller.dart';
import 'package:lamto_api/lamto_api.dart';

class _Repo implements AuthRepository {
  _Repo(this._me);
  final Me? _me;
  @override
  Future<String> login(String i, String p) async => 'tok';
  @override
  Future<Me> fetchMe() async => _me ?? (throw StateError('none'));
}

Me _meWith(int occupancies) => Me((b) {
  final list = ListBuilder<Occupancy>();
  for (var i = 0; i < occupancies; i++) {
    list.add(Occupancy((o) => o
      ..id = i + 1
      ..unitLabel = 'A-${i + 1}'
      ..buildingName = 'Toa A'));
  }
  return b
    ..displayName = 'R'
    ..email = 'r@example.com'
    ..occupancies = list
    ..notificationPreferences = ListBuilder<NotificationPreference>();
});

Future<void> _pump(WidgetTester tester, {required Me? me}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [authRepositoryProvider.overrideWithValue(_Repo(me))],
    child: const LamToApp(),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('no session shows Login', (tester) async {
    await _pump(tester, me: null);
    expect(find.text('Đăng nhập'), findsWidgets);
  });

  testWidgets('multi-occupancy shows the picker', (tester) async {
    await _pump(tester, me: _meWith(2));
    expect(find.text('Chọn căn hộ của bạn'), findsOneWidget);
  });

  testWidgets('single occupancy lands on the tab shell', (tester) async {
    await _pump(tester, me: _meWith(1));
    expect(find.text('Trang chính'), findsWidgets);
  });
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test test/app_routing_test.dart`
Expected: FAIL — the screens/router don't exist.

- [ ] **Step 3: Implement the screens**

Create `app/lib/features/auth/login_screen.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/failure.dart';
import '../../l10n/app_localizations.dart';
import 'session_controller.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _id = TextEditingController();
  final _pw = TextEditingController();
  String? _error;
  bool _busy = false;

  Future<void> _submit(AppLocalizations l10n) async {
    setState(() { _busy = true; _error = null; });
    try {
      await ref.read(sessionControllerProvider.notifier).signIn(_id.text.trim(), _pw.text);
    } on DioException catch (e) {
      setState(() => _error = failureMessage(Failure.fromDio(e), l10n));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.loginTitle)),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: ListView(children: [
          TextField(controller: _id, decoration: InputDecoration(labelText: l10n.loginIdentifier)),
          const SizedBox(height: 12),
          TextField(controller: _pw, obscureText: true, decoration: InputDecoration(labelText: l10n.loginPassword)),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _busy ? null : () => _submit(l10n),
            child: Text(l10n.loginSubmit),
          ),
        ]),
      ),
    );
  }
}
```

Create `app/lib/features/auth/occupancy_picker_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';

class OccupancyPickerScreen extends ConsumerWidget {
  const OccupancyPickerScreen({required this.me, required this.onChosen, super.key});
  final Me me;
  final VoidCallback onChosen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.occupancyPickerTitle)),
      body: ListView(
        children: me.occupancies.map((Occupancy o) {
          return ListTile(
            title: Text('${o.buildingName} · ${o.unitLabel}'),
            onTap: () {
              ref.read(occupancyHolderProvider).occupancyId = o.id;
              onChosen();
            },
          );
        }).toList(),
      ),
    );
  }
}
```

Create `app/lib/features/shell/home_shell.dart` — **platform-adaptive chrome** (clarification #7): Material `NavigationBar` on Android; `CupertinoTabScaffold`/`CupertinoTabBar` on iOS; **same five placeholder bodies**.

```dart
import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import '../../l10n/app_localizations.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  List<Widget> _bodies(AppLocalizations l10n) => [
        for (final label in [l10n.tabHome, l10n.tabReport, l10n.tabIssues, l10n.tabLedger, l10n.tabAccount])
          Center(child: Text(label)),
      ];

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final bodies = _bodies(l10n);
    final isIos = Theme.of(context).platform == TargetPlatform.iOS ||
        defaultTargetPlatform == TargetPlatform.iOS;
    if (isIos) {
      return CupertinoTabScaffold(
        tabBar: CupertinoTabBar(
          currentIndex: _index,
          onTap: (i) => setState(() => _index = i),
          items: [
            BottomNavigationBarItem(icon: const Icon(CupertinoIcons.home), label: l10n.tabHome),
            BottomNavigationBarItem(icon: const Icon(CupertinoIcons.add_circ), label: l10n.tabReport),
            BottomNavigationBarItem(icon: const Icon(CupertinoIcons.list_bullet), label: l10n.tabIssues),
            BottomNavigationBarItem(icon: const Icon(CupertinoIcons.money_dollar), label: l10n.tabLedger),
            BottomNavigationBarItem(icon: const Icon(CupertinoIcons.person), label: l10n.tabAccount),
          ],
        ),
        tabBuilder: (context, index) => CupertinoPageScaffold(
          child: SafeArea(child: bodies[index]),
        ),
      );
    }
    return Scaffold(
      body: bodies[_index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          NavigationDestination(icon: const Icon(Icons.home_outlined), label: l10n.tabHome),
          NavigationDestination(icon: const Icon(Icons.add_circle_outline), label: l10n.tabReport),
          NavigationDestination(icon: const Icon(Icons.list_alt_outlined), label: l10n.tabIssues),
          NavigationDestination(icon: const Icon(Icons.account_balance_outlined), label: l10n.tabLedger),
          NavigationDestination(icon: const Icon(Icons.person_outline), label: l10n.tabAccount),
        ],
      ),
    );
  }
}
```

Add a widget/unit test (or platform override in routing test) that with `debugDefaultTargetPlatformOverride = TargetPlatform.iOS` the shell builds `CupertinoTabBar`, and with Android builds `NavigationBar`.

- [ ] **Step 4: Add the root router**

In `app/lib/app.dart`, replace `home:` with `AppRouter` watching session state. **Do not route AsyncError or SessionBootstrapError to Login** (clarification #1).

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';
import 'core/failure.dart';
import 'core/providers.dart';
import 'features/auth/session_controller.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/occupancy_picker_screen.dart';
import 'features/shell/home_shell.dart';
import 'l10n/app_localizations.dart';
```

```dart
class AppRouter extends ConsumerWidget {
  const AppRouter({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionControllerProvider);
    return switch (session) {
      AsyncData(:final value) => switch (value) {
          SessionUnauthenticated() => const LoginScreen(),
          SessionAuthenticated(:final me) => _routeAuthenticated(ref, me),
          SessionBootstrapError(:final failure) => BootstrapErrorScreen(
              failure: failure,
              onRetry: () => ref.invalidate(sessionControllerProvider),
            ),
        },
      // Transient provider errors also show retry — never Login.
      AsyncError(:final error) => BootstrapErrorScreen(
          failure: error is Failure ? error : Failure(code: 'server_error'),
          onRetry: () => ref.invalidate(sessionControllerProvider),
        ),
      _ => const Scaffold(body: Center(child: CircularProgressIndicator.adaptive())),
    };
  }

  Widget _routeAuthenticated(WidgetRef ref, Me me) {
    final holder = ref.read(occupancyHolderProvider);
    if (me.occupancies.length == 1) {
      // Persist single occupancy selection (via controller helper if available).
      holder.occupancyId = me.occupancies.first.id;
      return const HomeShell();
    }
    if (holder.occupancyId != null &&
        me.occupancies.any((o) => o.id == holder.occupancyId)) {
      return const HomeShell();
    }
    return OccupancyPickerScreen(
      me: me,
      onChosen: () => ref.invalidate(sessionControllerProvider),
    );
  }
}

/// Retryable bootstrap failure UI (clarification #1).
class BootstrapErrorScreen extends StatelessWidget {
  const BootstrapErrorScreen({required this.failure, required this.onRetry, super.key});
  final Failure failure;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(failureMessage(failure, l10n), textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: onRetry, child: Text(l10n.errGeneric /* or dedicated retry key */)),
            ],
          ),
        ),
      ),
    );
  }
}
```

Add ARB keys for retry if needed (`bootstrapRetry`: "Thử lại" / "Retry"). Occupancy picker must call persist + clear scoped providers on selection (via session/occupancy controller).

- [ ] **Step 5: Run the tests**

Run: `cd app && flutter test`
Expected: PASS (all suites — theme, models, interceptors, failure, occupancy, l10n, session, routing).

- [ ] **Step 6: Manual smoke (optional, needs the backend)**

```bash
docker compose up -d     # at repo root; API at /api/v1/
cd app && flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
# Log in with a seeded resident (phone/email + password) -> occupancy pick -> tab shell.
```

- [ ] **Step 7: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/features app/lib/app.dart app/test/app_routing_test.dart
git commit -m "feat(app): login, occupancy picker, and adaptive session-routed tab shell"
```

---

### Task 9: CI job for API drift gate + analyze + test

Wire the local scripts into an actual GitHub Actions workflow (clarification #5).

**Files:**
- Create: `.github/workflows/flutter-app.yml` (or extend an existing workflow)

**Requirements:**
- Job runs on pull_request and push to main/master (and this feature branch pattern).
- Steps: checkout → setup Flutter → setup Node (for openapi-generator) → `cd app && flutter pub get` → `./tool/check_api_generated.sh` → `flutter analyze` → `flutter test`.
- Fail the job if any step fails.

- [ ] **Step 1: Add workflow**

```yaml
name: Flutter resident app
on:
  push:
    paths: ['app/**', 'docs/api/openapi-v1.yaml', '.github/workflows/flutter-app.yml']
  pull_request:
    paths: ['app/**', 'docs/api/openapi-v1.yaml', '.github/workflows/flutter-app.yml']
jobs:
  app:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: app
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          channel: stable
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: flutter pub get
      - run: chmod +x tool/generate_api.sh tool/check_api_generated.sh
      - name: API client drift gate
        run: ./tool/check_api_generated.sh
      - run: flutter analyze
      - run: flutter test
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/flutter-app.yml
git commit -m "ci(app): run API drift gate, flutter analyze, and flutter test"
```

---

## Self-review

### Spec coverage map (Foundation slice of §6)

| Spec | Requirement | Task |
|---|---|---|
| §6.2 | Flutter, Material 3 + adaptive; Riverpod state | Tasks 1, 7, 8 |
| §6.2 | Dart API client generated from committed schema; regenerated + diffed in CI | Tasks 2, 9 |
| §6.2 | Thin repository layer + contract tests for manual paths | Task 7 |
| §6.2 | Vietnamese-first l10n via ARB; copy keyed off `code` | Tasks 4, 6 |
| §6.2 / DESIGN.md | ≥44pt targets, AA tokens, tabular VND, complete dark tokens | Task 1 |
| §3.2 | Token in Keychain/Keystore only | Task 3 |
| §6.4 | One interceptor: attach token; 401 → clear → login | Task 3 |
| §3.4 | `X-LamTo-Occupancy` **only on building-scoped** paths | Task 5 |
| §6.4 | App start: secure storage first; auth vs retryable bootstrap taxonomy | Task 7 |
| §6.4 | Failure doctrine (what happened / saved? / next) from `code`; no HTTP jargon | Tasks 4, 6 |
| §6.3 | Login; Occupancy picker; **platform-adaptive** tab shell | Task 8 |
| Occupancy | Persist/validate against `/me`; clear scoped state on change | Tasks 5, 7, 8 |
| CI | Real workflow: drift gate + analyze + test | Task 9 |
| Repo | Monorepo `app/` decided before scaffold | Repository decision |

### Deferred to the two follow-on §6 plans

- **Reporting:** Report-issue (location picker, ≤5 photos + compression + `client_ref` retry→200 / conflict→409 + local draft), My-issues timeline, rate work.
- **Transparency + Account:** Home (fund block + flows + reports + spending + bell), Ledger list/detail (evidence-level labels rendering), Account (occupancy switcher, notification preferences via `PATCH /me/notification-preferences`, logout/logout-all), Notifications feed + mark-read + deep links, FCM registration (`POST /devices`) + OS permission consent, and the nightly `integration_test` happy path (§6.5). Widget tests for report `client_ref` retry and ledger evidence labels also live there.
- **Rich per-screen visual design** (SF Symbols/Material icons, Dynamic Type polish, empty/error states): apply the `impeccable` skill during those plans.

### Placeholder scan

No `TBD`/`add validation`/`similar to Task N`. Task 1 Step 1 notes the `lamto_api` path dep must be commented until Task 2 generates it (a real ordering constraint, spelled out). Task 8 Step 4's note offers a simpler local-rebuild alternative to the `invalidate` router refresh — a clarification, with complete code given for the chosen path. The generated client's exact class names are pinned by the server's serializer component names (`TokenResponse`, `Me`, `Occupancy`, `Problem`), verified by Task 2's compile test.

### Type consistency

- `buildDio({store, occupancy, onUnauthorized, baseUrl})` — the final signature after Task 5; Tasks 3 and 5 tests and `providers.dart` all call it with `occupancy:`.
- `TokenStore.read/write/clear`, `OccupancyHolder.occupancyId`, `Failure(code, detail, fieldErrors)` / `Failure.fromDio` are used identically across tasks.
- `AuthRepository.login(id,pw)->String` (token) and `fetchMe()->Me` match the `DioAuthRepository` impl and the fakes in Tasks 7–8.
- `SessionState` variants (`SessionUnauthenticated`, `SessionAuthenticated(me)`) and `sessionControllerProvider` are consumed by the router (Task 8) exactly as declared (Task 7).
- Generated model access (`Me.occupancies`, `Occupancy.id/unitLabel/buildingName`, `TokenResponse.token`) matches the server serializers' field names in `snake_case` → dart-dio `camelCase`.
