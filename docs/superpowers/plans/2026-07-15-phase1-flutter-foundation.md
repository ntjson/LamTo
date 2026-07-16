# Flutter Resident App — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Flutter resident app's foundation (spec §6): a platform-adaptive Material 3 scaffold, a Dart API client generated from the committed OpenAPI schema, the single auth/occupancy HTTP interceptor, problem-json failure mapping, Vietnamese-first l10n, the `GET /me`-driven app-start routing, and the Login + Occupancy-picker screens.

**Architecture:** A new `app/` Flutter project in this monorepo. The `dart-dio` generator turns `docs/api/openapi-v1.yaml` into a committed, CI-diffed typed model + serializer package (`app/packages/lamto_api`); thin repositories issue requests through one interceptor-configured `Dio` (attach knox token, inject `X-LamTo-Occupancy`, map `application/problem+json`, clear the token on 401) and deserialize responses with the generated `standardSerializers`. Riverpod 3 holds session/occupancy state; a root `ConsumerWidget` routes on the async session state. This plan delivers login → occupancy pick → an empty tab shell; the feature screens land in the two follow-on plans (see Scope Check).

**Tech Stack:** Flutter (Material 3 + `.adaptive`), Dart 3, `flutter_riverpod` ^3, `dio` ^5, `flutter_secure_storage` ^9, `built_value`/`built_collection` (generated client), `openapi-generator-cli` v7 (dart-dio), Flutter `gen-l10n` (ARB), `flutter_test` + `mocktail`.

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

ThemeData lamToTheme(Brightness brightness) {
  final scheme = ColorScheme.fromSeed(
    seedColor: LamToColors.primary,
    brightness: brightness,
    primary: LamToColors.primary,
    onPrimary: LamToColors.onPrimary,
    error: LamToColors.error,
    surface: LamToColors.surface,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: brightness == Brightness.light ? LamToColors.bg : null,
    // Money uses tabular figures (DESIGN.md); enable app-wide feature.
    textTheme: const TextTheme().apply(fontFamilyFallback: const ['Roboto']),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(),
      filled: true,
      fillColor: LamToColors.surface,
    ),
  );
}
```

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
  - `OccupancyHolder` — mutable `int? occupancyId` (a plain object the interceptor reads).
  - `buildDio(...)` gains a `required OccupancyHolder occupancy` param; the interceptor adds `X-LamTo-Occupancy` when set.

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

  test('injects X-LamTo-Occupancy only when set', () async {
    final holder = OccupancyHolder();
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

    await dio.get<dynamic>('/ledger');
    expect(seen, isNull);
    holder.occupancyId = 42;
    await dio.get<dynamic>('/ledger');
    expect(seen, '42');
  });
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test test/occupancy_header_test.dart`
Expected: FAIL — `occupancy.dart` missing / `buildDio` has no `occupancy` param.

- [ ] **Step 3: Implement**

Create `app/lib/core/occupancy.dart`:

```dart
/// The resident's selected active occupancy id, injected as X-LamTo-Occupancy
/// (spec 3.4). Only the occupancy id is ever sent; never a building id.
class OccupancyHolder {
  int? occupancyId;
}
```

In `app/lib/core/api_client.dart`, add the import and the `occupancy` parameter, and set the header in `onRequest`:

```dart
import 'occupancy.dart';
```

Change the signature to `Dio buildDio({required TokenStore store, required OccupancyHolder occupancy, required void Function() onUnauthorized, String? baseUrl})` and inside `onRequest`, after attaching the token:

```dart
      final occ = occupancy.occupancyId;
      if (occ != null) {
        options.headers['X-LamTo-Occupancy'] = occ;
      }
```

Update the Task-3 test's `buildDio(...)` call to pass `occupancy: OccupancyHolder()`.

- [ ] **Step 4: Run the tests**

Run: `cd app && flutter test test/occupancy_header_test.dart test/auth_interceptor_test.dart`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/occupancy.dart app/lib/core/api_client.dart \
        app/test/occupancy_header_test.dart app/test/auth_interceptor_test.dart
git commit -m "feat(app): inject X-LamTo-Occupancy header from occupancy state"
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

The Riverpod session state, the `GET /me`-driven bootstrap, and the root router (spec §6.4).

**Files:**
- Create: `app/lib/features/auth/auth_repository.dart`, `app/lib/features/auth/session_controller.dart`, `app/lib/core/providers.dart`
- Modify: `app/lib/app.dart`
- Test: `app/test/session_controller_test.dart`

**Interfaces:**
- Consumes: `buildDio`, `TokenStore`, `OccupancyHolder`, `Failure`, generated `Me`/`TokenResponse`.
- Produces:
  - `AuthRepository` — `Future<String> login(String identifier, String password)` (returns token), `Future<Me> fetchMe()`.
  - `SessionState` sealed: `SessionUnauthenticated`, `SessionAuthenticated(Me me)`.
  - `sessionControllerProvider` (`AsyncNotifierProvider<SessionController, SessionState>`) with `bootstrap()`, `signIn(id,pw)`, `signOut()`.
  - `providers.dart`: `tokenStoreProvider`, `occupancyHolderProvider`, `dioProvider`, `authRepositoryProvider`.

- [ ] **Step 1: Write the failing test**

Create `app/test/session_controller_test.dart`:

```dart
import 'package:built_collection/built_collection.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/features/auth/auth_repository.dart';
import 'package:lamto/features/auth/session_controller.dart';
import 'package:lamto_api/lamto_api.dart';

class _FakeRepo implements AuthRepository {
  _FakeRepo({this.me});
  Me? me;
  @override
  Future<String> login(String identifier, String password) async => 'tok';
  @override
  Future<Me> fetchMe() async {
    if (me == null) throw StateError('no session');
    return me!;
  }
}

Me _me() => Me((b) => b
  ..displayName = 'Resident'
  ..email = 'r@example.com'
  ..occupancies = ListBuilder<Occupancy>()
  ..notificationPreferences = ListBuilder<NotificationPreference>());

void main() {
  test('bootstrap with no session -> unauthenticated', () async {
    final container = ProviderContainer(overrides: [
      authRepositoryProvider.overrideWithValue(_FakeRepo()),
    ]);
    addTearDown(container.dispose);
    final state = await container.read(sessionControllerProvider.future);
    expect(state, isA<SessionUnauthenticated>());
  });

  test('bootstrap with a session -> authenticated', () async {
    final container = ProviderContainer(overrides: [
      authRepositoryProvider.overrideWithValue(_FakeRepo(me: _me())),
    ]);
    addTearDown(container.dispose);
    final state = await container.read(sessionControllerProvider.future);
    expect(state, isA<SessionAuthenticated>());
  });
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && flutter test test/session_controller_test.dart`
Expected: FAIL — the providers/controller don't exist.

- [ ] **Step 3: Implement the repository**

Create `app/lib/features/auth/auth_repository.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:lamto_api/lamto_api.dart';

abstract class AuthRepository {
  Future<String> login(String identifier, String password);
  Future<Me> fetchMe();
}

class DioAuthRepository implements AuthRepository {
  DioAuthRepository(this._dio);
  final Dio _dio;

  @override
  Future<String> login(String identifier, String password) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/api/v1/auth/login',
      data: {'identifier': identifier, 'password': password},
    );
    final token = standardSerializers.deserializeWith(TokenResponse.serializer, res.data!)!;
    return token.token;
  }

  @override
  Future<Me> fetchMe() async {
    final res = await _dio.get<Map<String, dynamic>>('/api/v1/me');
    return standardSerializers.deserializeWith(Me.serializer, res.data!)!;
  }
}
```

- [ ] **Step 4: Implement the providers + controller**

Create `app/lib/core/providers.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'api_client.dart';
import 'occupancy.dart';
import 'token_store.dart';
import '../features/auth/auth_repository.dart';
import '../features/auth/session_controller.dart';

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());
final occupancyHolderProvider = Provider<OccupancyHolder>((ref) => OccupancyHolder());

final dioProvider = Provider<Dio>((ref) {
  return buildDio(
    store: ref.watch(tokenStoreProvider),
    occupancy: ref.watch(occupancyHolderProvider),
    // A 401 on a token-carrying request means the session expired: re-bootstrap
    // so the router falls back to Login (the interceptor already cleared the token).
    onUnauthorized: () => ref.invalidate(sessionControllerProvider),
  );
});

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => DioAuthRepository(ref.watch(dioProvider)),
);
```

Create `app/lib/features/auth/session_controller.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';
import '../../core/providers.dart';
import '../../core/token_store.dart';
import 'auth_repository.dart';

sealed class SessionState {
  const SessionState();
}

class SessionUnauthenticated extends SessionState {
  const SessionUnauthenticated();
}

class SessionAuthenticated extends SessionState {
  const SessionAuthenticated(this.me);
  final Me me;
}

class SessionController extends AsyncNotifier<SessionState> {
  AuthRepository get _repo => ref.read(authRepositoryProvider);
  TokenStore get _store => ref.read(tokenStoreProvider);

  @override
  Future<SessionState> build() => _bootstrap();

  Future<SessionState> _bootstrap() async {
    try {
      final me = await _repo.fetchMe();
      return SessionAuthenticated(me);
    } catch (_) {
      return const SessionUnauthenticated();
    }
  }

  Future<void> signIn(String identifier, String password) async {
    final token = await _repo.login(identifier, password);
    await _store.write(token);
    state = AsyncData(SessionAuthenticated(await _repo.fetchMe()));
  }

  Future<void> signOut() async {
    await _store.clear();
    state = const AsyncData(SessionUnauthenticated());
  }
}

final sessionControllerProvider =
    AsyncNotifierProvider<SessionController, SessionState>(SessionController.new);
```

- [ ] **Step 5: Run the test**

Run: `cd app && flutter test test/session_controller_test.dart`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
cd /home/nts/src/LamTo
git add app/lib/core/providers.dart app/lib/features/auth/auth_repository.dart \
        app/lib/features/auth/session_controller.dart app/test/session_controller_test.dart
git commit -m "feat(app): session controller and GET /me bootstrap"
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

Create `app/lib/features/shell/home_shell.dart` (adaptive tab scaffold; tab bodies are placeholders filled by the follow-on plans):

```dart
import 'package:flutter/material.dart';
import '../../l10n/app_localizations.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;
  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final tabs = [l10n.tabHome, l10n.tabReport, l10n.tabIssues, l10n.tabLedger, l10n.tabAccount];
    return Scaffold(
      body: Center(child: Text(tabs[_index])),
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

- [ ] **Step 4: Add the root router**

In `app/lib/app.dart`, replace the `home:` with an `AppRouter` that watches session state. Add the imports and the widget:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';
import 'core/providers.dart';
import 'features/auth/session_controller.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/occupancy_picker_screen.dart';
import 'features/shell/home_shell.dart';
```

Set `home: const AppRouter()` and append:

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
          _ => const LoginScreen(),
        },
      AsyncError() => const LoginScreen(),
      _ => const Scaffold(body: Center(child: CircularProgressIndicator.adaptive())),
    };
  }

  Widget _routeAuthenticated(WidgetRef ref, Me me) {
    final holder = ref.read(occupancyHolderProvider);
    if (me.occupancies.length == 1) {
      holder.occupancyId = me.occupancies.first.id;
      return const HomeShell();
    }
    if (holder.occupancyId != null) return const HomeShell();
    return OccupancyPickerScreen(
      me: me,
      // Re-runs _routeAuthenticated, which now sees holder.occupancyId != null
      // and returns HomeShell. Re-fetching /me once on selection is acceptable.
      onChosen: () => ref.invalidate(sessionControllerProvider),
    );
  }
}
```

`LamToApp` stays a `StatelessWidget`; `MaterialApp.home` is `const AppRouter()` (a `ConsumerWidget`). `onChosen` runs on tap (not during build), so invalidating the provider there is safe.

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
git commit -m "feat(app): login, occupancy picker, and session-routed tab shell"
```

---

## Self-review

### Spec coverage map (Foundation slice of §6)

| Spec | Requirement | Task |
|---|---|---|
| §6.2 | Flutter, Material 3 + adaptive; Riverpod state | Tasks 1, 7, 8 |
| §6.2 | Dart API client generated from committed schema; regenerated + diffed in CI | Task 2 |
| §6.2 | Thin repository layer | Task 7 (`AuthRepository` over generated models + `standardSerializers`) |
| §6.2 | Vietnamese-first l10n via ARB; copy keyed off `code` | Tasks 4, 6 |
| §6.2 / DESIGN.md | ≥44pt targets, AA tokens, one primary action, system font scaling | Tasks 1 (theme/48px buttons), 8 |
| §3.2 | Token in Keychain/Keystore only | Task 3 |
| §6.4 | One interceptor: attach token; 401 → clear → login | Task 3 |
| §3.4 | `X-LamTo-Occupancy` injection; only the occupancy id sent | Task 5 |
| §6.4 | App start `GET /me` decides route | Task 7 |
| §6.4 | Failure doctrine (what happened / saved? / next) from `code`; no HTTP jargon | Tasks 4, 6 |
| §6.3 | Login screen; Occupancy picker; tab scaffold (Home·Report·Issues·Ledger·Account) | Task 8 |

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
