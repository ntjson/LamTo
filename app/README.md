# LamTo resident app

Vietnamese-first Flutter client (iOS + Android) for apartment maintenance
accountability. Talks to the Phase 1 resident API under `docs/api/openapi-v1.yaml`.

## Local run

```bash
# repo root — DB + object storage
docker compose up -d

# API (separate terminal; needs project .env — see .env.example)
.venv/bin/python manage.py migrate
PILOT_ALLOW_FIXTURES=1 .venv/bin/python manage.py seed_pilot --fixture
.venv/bin/python manage.py runserver 0.0.0.0:8000

cd app
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

Android emulators reach the host at `10.0.2.2`; iOS simulators and Linux desktop
use `http://127.0.0.1:8000`.

Firebase platform config (`google-services.json` / `GoogleService-Info.plist`) is
**not** committed. Without it, push degrades to a no-op (see
[`docs/ops/push-smoke-checklist.md`](../docs/ops/push-smoke-checklist.md)).

## Unit / widget tests

```bash
cd app
flutter analyze
flutter test
```

## Nightly integration test (spec §6.5)

Requires a running, seeded backend and a device/emulator (or Linux desktop):

```bash
# repo root
docker compose up -d
# seed the pilot world (creates the resident login used below)
PILOT_ALLOW_FIXTURES=1 .venv/bin/python manage.py seed_pilot --fixture
.venv/bin/python manage.py runserver 0.0.0.0:8000

cd app
flutter test integration_test/app_test.dart \
  --dart-define=API_BASE_URL=http://10.0.2.2:8000 \
  --dart-define=INTEGRATION_IDENTIFIER=pilot-resident@pilot.lamto.test \
  --dart-define=INTEGRATION_PASSWORD=pilot-test-secret
```

Pilot fixture credentials come from `src/lamto/testing/factories.py`
(`PILOT_PASSWORD` / `pilot-resident@pilot.lamto.test`). Never use them outside
non-production seeds.

| Target | `API_BASE_URL` |
|--------|----------------|
| Android emulator | `http://10.0.2.2:8000` |
| iOS simulator / Linux desktop / host | `http://127.0.0.1:8000` |

Scheduled CI: [`.github/workflows/flutter-nightly.yml`](../.github/workflows/flutter-nightly.yml)
brings up compose, seeds the pilot world, and runs this happy path.

Compile-only check (no device):

```bash
cd app && flutter analyze integration_test lib
```

## Real-device push smoke

Manual checklist (permission, register, refresh, tap routing, logout deregister):
[`docs/ops/push-smoke-checklist.md`](../docs/ops/push-smoke-checklist.md).
