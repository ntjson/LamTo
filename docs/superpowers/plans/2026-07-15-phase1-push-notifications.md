# Push Notifications (FCM) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the backend push-notification subsystem (spec §7) — a device registry with `/devices` endpoints, a `PUSH` delivery channel that fans out to FCM with send-time revalidation and provider-error classification, payload minimization, publication aggregation, resident consent, and ops visibility.

**Architecture:** Extends the existing `lamto.notifications` durable-queue pipeline in place. `PUSH` becomes a third `NotificationDelivery.Channel` beside `IN_APP` and `EMAIL`, inheriting the same queue/claim/retry/preference machinery; the worker fans each `PUSH` delivery out to the recipient's active `Device` rows via `firebase-admin`. Push carries **no sensitive content** — a fixed generic Vietnamese title/body plus an allowlisted deep-link reference; the authenticated API re-authorizes every follow-up fetch, so a push can never widen access. The in-app feed and staff inbox remain authoritative; push is best-effort.

**Tech Stack:** Django 5.2 modular monolith, `firebase-admin` (FCM), django-rest-knox tokens, DRF + drf-spectacular, PostgreSQL/psycopg3, pytest + pytest-django.

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md`):

- **§7.1 Provider.** FCM only, via `firebase-admin` with a service-account credential from environment/secret (**never in git**). **No second provider, no push abstraction layer.** Zalo ZNS is a noted later option, not built.
- **§7.2 Device hygiene.** Possession of a current FCM token proves control of the device: an incoming registration whose `fcm_token` is already attached to a different user/install deactivates the old binding and reattaches to the registering `(user, install_id)`. Logout deactivates that install's `Device`. Auth tokens and FCM tokens are **separate records; an FCM token is never an auth credential.** Stale rows die on first `UNREGISTERED` response or via inactivity cleanup (unseen 180 days → deactivated).
- **§7.3 Delivery.** **Send-time revalidation:** immediately before sending, the worker re-checks the user is active and still holds an active occupancy in the delivery's `building`; otherwise no tenant-specific push. **Provider errors:** terminal (`UNREGISTERED`, invalid/mismatched token) → immediately deactivate the `Device`, no retry; transient (unavailable/internal/quota) → capped exponential backoff, then marked failed while the in-app feed still holds the item. **Aggregation:** ledger-publication pushes within a short window collapse (FCM `collapse_key`) with a per-user daily cap per category.
- **§7.4 Events + payload minimization.** Resident-relevant events only: report received/triaged, report grouped into a case, work completed (rate prompt), published ledger entry, published correction. **No staff push in Phase 1.** Payloads carry **no sensitive content** (no amounts, names, or report text) — generic Vietnamese title/body + deep-link reference (`type` + `id`) + delivery ID. **Deep links resolve through an allowlisted type→route map** (report, case, ledger entry, notifications feed); anything else is ignored. A push can never grant access; the app always re-fetches through the authenticated API.
- **§7.5 Consent.** Two independent layers: OS permission (client-side) and in-app per-category preferences extending `NotificationPreference` with the push channel, managed from Account. Defaults once OS permission exists: report updates on, ledger publications on.
- **§7.6 Ops.** Push failure counts and dead-token cleanup age join `/s/ops/health/`.
- **§5.3 / §5.4.** No payment-provider dependency in `pyproject.toml`. No secrets in git. The six e2e journeys, the two-building adversarial walk (web + API), `tenant_integrity`, the OpenAPI drift check, and the disabled-mode job stay green.

## Verified test environment

`manage.py` is at the repo root. Postgres via compose; settings read `.env.example` plus test overrides:

```bash
docker compose up -d db
set -a; . ./.env.example; set +a
export SECRET_KEY=test-secret EVIDENCE_WRITE_SECRET=test-evidence \
       POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
# run tests:  .venv/bin/python -m pytest <path> -q
# regenerate the committed OpenAPI schema:
#   .venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn
```

Push is off unless `PUSH_ENABLED` is truthy **and** `FIREBASE_CREDENTIALS` is set. Tests exercise the pipeline with `@override_settings(PUSH_ENABLED=True)` and by patching `lamto.notifications.services.send_push` — no real FCM credential or network is used.

## Always-on gates (keep green after every task)

`src/lamto/api/tests/test_openapi.py` (drift + route coverage) and `tests/isolation/test_cross_building_access.py` (`test_every_registered_route_is_classified`) run on every commit. The task that adds `/devices` routes MUST, before its final commit: regenerate the committed schema, classify the new route names in an `API_*` map, add the paths to `test_schema_covers_every_api_route`, and confirm `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py -q` is green.

## Design decisions

1. **No push abstraction layer (§7.1).** `notifications/push.py` calls `firebase_admin.messaging.send` directly. One thin `send_push(...)` function + a `classify_push_error(...)` helper; the worker owns the retry/deactivation policy. Firebase app init is lazy and memoized.
2. **`PUSH` deliveries are created only where they can succeed.** `queue_notification` adds the `PUSH` channel for a recipient only when `PUSH_ENABLED`, the event is in `RESIDENT_PUSH_EVENT_CODES`, the recipient's push preference is on, and the recipient has ≥1 active `Device`. This keeps the queue free of rows for staff (no devices) and residents without the app — while the worker's send-time revalidation is the authoritative second gate (§7.3).
3. **Payload minimization is server-owned copy (§7.4), the one exception to "server sends no display strings."** The OS renders a push before the app runs, so the server sends a fixed generic Vietnamese title/body per event code (`PUSH_COPY`) — never the delivery's sensitive `subject`/`body`. The deep link is `{type, id}` from an allowlist; unknown entities fall back to the notifications feed.
4. **Token reassignment is deliberate cross-user write (§7.2).** `register_device` deactivates any *other* active `Device` holding the incoming `fcm_token` before upserting the caller's `(user, install_id)` — possession of the token proves control. `fcm_token` is unique **among active rows** (partial constraint) so a deactivated row may retain its stale token.
5. **Aggregation via `collapse_key` + a daily cap (§7.3).** Publication pushes share a per-building `collapse_key` (the device shows one) and are suppressed past `PUSH_DAILY_CAP_PER_CATEGORY` sends per user per category per day. No windowed "N new" counting — YAGNI beyond the collapse + cap the spec names.
6. **Daily-cap calendar day uses project `TIME_ZONE` (`Asia/Ho_Chi_Minh`).** `_daily_push_cap_reached` bounds "today" with `timezone.localdate()` (Django `USE_TZ=True` + `TIME_ZONE`), not UTC `timezone.now().date()`. Documented in Task 6.
7. **Suppressed deliveries are not true FCM successes.** Worker still marks non-retryable suppressions as `SENT` (queue must not retry; in-app remains authoritative) but sets a structured `last_error` prefix `suppressed:<reason>` (`recipient_ineligible`, `no_active_devices`, `daily_cap`). Ops/metrics count **true FCM success** only as `PUSH`+`SENT` with empty/`last_error` not starting with `suppressed:`; suppressed counts are exposed separately (`push_suppressed`).
8. **Logout ↔ Device deactivation coupling (§7.2).** `DELETE /devices/{install_id}` remains the explicit deactivation primitive. Additionally: (a) `POST /api/v1/auth/logout` accepts optional header `X-Install-Id` (or JSON body `install_id`); when present for the authenticated user, deactivates that install's Device in the same request as knox token revocation — so a successful mobile logout cannot silently leave that install push-active if the client sends the install id; (b) `POST /api/v1/auth/logout-all` deactivates **all** of the user's active Devices; (c) **Flutter client contract (follow-up):** push-capable installs MUST send `X-Install-Id` on logout (and SHOULD also call `DELETE /devices/{install_id}` as defense-in-depth). Web logout without install_id does not touch Devices (no FCM install). Tests cover logout-with-header deactivates; logout-without leaves device active.
9. **Stale-device cleanup is invocable, not dead code.** Management command `deactivate_stale_devices` (`--days`, default 180) plus a worker processor batch that calls `deactivate_stale_devices` on the regular worker cycle (same pattern as other ops processors). Ops health exposes `dead_devices` count **and** `stale_device_max_inactive_days` (max whole days since `last_seen_at` among inactive devices, or 0 if none) so ops can see age, not only total inactive count.
10. **Concurrent token reassignment is race-hardened.** `register_device` deactivates other holders under `transaction.atomic` + `select_for_update()` on conflicting active token rows, then upserts; on partial-unique `IntegrityError` for `device_active_fcm_token_once`, retry once after re-deactivating. Race-oriented test exercises concurrent registrations of the same token (Postgres) or forces the constraint path so two active rows with the same token cannot remain.
11. **Terminal FCM classification covers all invalid/unregistered/mismatched cases in pinned `firebase-admin>=6,<8`.** `classify_push_error` treats as terminal: `messaging.UnregisteredError`, `messaging.SenderIdMismatchError`, and `messaging.InvalidArgumentError` when the message indicates an invalid/unregistered registration token (plus any `code`/`http_response` patterns the pinned version surfaces for dead tokens). Transient: quota, unavailable, internal, third-party auth, network. Unknown exceptions default to transient (retry then fail).

## File Structure

**Create:**
- `src/lamto/notifications/devices.py` — `register_device`, `deactivate_device`, `deactivate_stale_devices` (race-hardened).
- `src/lamto/notifications/push.py` — `send_push`, `classify_push_error`, `build_push_payload`, `PUSH_COPY`, `DEEP_LINK_TYPES`.
- `src/lamto/notifications/management/commands/deactivate_stale_devices.py` — scheduled/ops entry for inactivity cleanup.
- `src/lamto/notifications/tests/test_devices.py`, `test_push_channel.py`, `test_push_worker.py`, `test_push_payload.py`.
- `src/lamto/api/tests/test_devices.py`.
- Migrations: `0003_device.py` (Task 1), `0004_push_channel_and_preference.py` (Task 3).

**Modify:**
- `src/lamto/notifications/models.py` — `Device`, `Channel.PUSH`, `NotificationPreference.push_enabled`.
- `src/lamto/notifications/services.py` — `DEFAULT_CHANNELS`, `push_enabled_for`, `RESIDENT_PUSH_EVENT_CODES`, `EVENT_WORK_COMPLETED`, queue gating, `_process_push_delivery` (suppressed: prefixes), `MAX_PUSH_ATTEMPTS`, daily cap via `localdate()`.
- `src/lamto/notifications/hooks.py` — `notify_work_rateable`, residents on `notify_correction_status`.
- `src/lamto/finance/acceptance.py` — call `notify_work_rateable`.
- `src/lamto/config/settings.py`, `.env.example` — FCM config.
- `src/lamto/config/worker.py` — processor for `deactivate_stale_devices`.
- `pyproject.toml` — `firebase-admin`.
- `src/lamto/api/{serializers,views,urls}.py` — `/devices`; logout/logout-all Device coupling.
- `src/lamto/web/forms/staff.py` — push preference toggles.
- `src/lamto/api/views.py` (`MeView`), `src/lamto/api/serializers.py` — `push_enabled` in `/me` prefs.
- `src/lamto/web/views/health.py`, the ops-health template — push metrics (success vs suppressed, dead count + max inactive age).
- `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py` — classify `/devices`.

---

### Task 1: `Device` model + registry service

The per-install device registry and the rotation/reassignment rules (spec §7.2). Pure data + service; no API yet.

**Files:**
- Modify: `src/lamto/notifications/models.py`
- Create: `src/lamto/notifications/devices.py`
- Create: `src/lamto/notifications/migrations/0003_device.py` (generated)
- Test: `src/lamto/notifications/tests/test_devices.py`

**Interfaces:**
- Produces:
  - `Device(user, install_id, fcm_token, platform, app_version, active, last_seen_at, created_at)`; `Device.Platform` = `IOS`/`ANDROID`. Unique `(user, install_id)`; unique `fcm_token` among active rows.
  - `register_device(user, install_id, fcm_token, platform, app_version="") -> Device` — race-hardened reassignment (select_for_update + IntegrityError retry) then upserts `(user, install_id)` active.
  - `deactivate_device(user, install_id) -> int` (rows updated).
  - `deactivate_stale_devices(days=180) -> int`.

- [x] **Step 1: Write the failing test**

Create `src/lamto/notifications/tests/test_devices.py`:

```python
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from lamto.notifications.devices import (
    deactivate_device,
    deactivate_stale_devices,
    register_device,
)
from lamto.notifications.models import Device


class DeviceRegistryTests(TestCase):
    def setUp(self):
        self.user_a = get_user_model().objects.create_user(email="a@example.test", password="x", display_name="A")
        self.user_b = get_user_model().objects.create_user(email="b@example.test", password="x", display_name="B")

    def test_upsert_by_user_install(self):
        install = str(uuid.uuid4())
        d1 = register_device(self.user_a, install, "tok-1", Device.Platform.ANDROID)
        d2 = register_device(self.user_a, install, "tok-2", Device.Platform.ANDROID, app_version="1.1")
        assert d1.pk == d2.pk  # same (user, install) row
        d2.refresh_from_db()
        assert d2.fcm_token == "tok-2" and d2.active is True and d2.app_version == "1.1"
        assert Device.objects.filter(user=self.user_a).count() == 1

    def test_token_reassignment_deactivates_old_binding(self):
        install_a = str(uuid.uuid4())
        install_b = str(uuid.uuid4())
        register_device(self.user_a, install_a, "shared-tok", Device.Platform.IOS)
        # Possession of the token proves control: it reattaches to user_b's install.
        register_device(self.user_b, install_b, "shared-tok", Device.Platform.IOS)
        old = Device.objects.get(user=self.user_a, install_id=install_a)
        new = Device.objects.get(user=self.user_b, install_id=install_b)
        assert old.active is False
        assert new.active is True and new.fcm_token == "shared-tok"
        assert Device.objects.filter(fcm_token="shared-tok", active=True).count() == 1

    def test_deactivate_device_and_stale_cleanup(self):
        from datetime import timedelta
        from django.utils import timezone

        install = str(uuid.uuid4())
        register_device(self.user_a, install, "tok-x", Device.Platform.ANDROID)
        assert deactivate_device(self.user_a, install) == 1
        assert Device.objects.get(user=self.user_a, install_id=install).active is False

        install2 = str(uuid.uuid4())
        d = register_device(self.user_a, install2, "tok-y", Device.Platform.ANDROID)
        Device.objects.filter(pk=d.pk).update(last_seen_at=timezone.now() - timedelta(days=200))
        assert deactivate_stale_devices(days=180) == 1
        assert Device.objects.get(pk=d.pk).active is False

    def test_concurrent_token_reassignment_leaves_one_active(self):
        """Race around active-token partial unique: only one active holder remains."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from django.db import connection

        install_a = str(uuid.uuid4())
        install_b = str(uuid.uuid4())
        token = f"race-tok-{uuid.uuid4()}"

        def _register(user, install):
            # Fresh connection per thread (Django TestCase).
            connection.close()
            try:
                return register_device(user, install, token, Device.Platform.ANDROID)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_register, self.user_a, install_a),
                pool.submit(_register, self.user_b, install_b),
            ]
            for f in as_completed(futures):
                f.result()  # must not raise IntegrityError to the caller

        active = list(Device.objects.filter(fcm_token=token, active=True))
        assert len(active) == 1
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_devices.py -q`
Expected: FAIL — `ImportError: cannot import name 'register_device'`.

- [x] **Step 3: Add the model**

In `src/lamto/notifications/models.py`, append:

```python
class Device(models.Model):
    """A resident's push-capable install (spec 7.2). fcm_token is unique among
    active rows; possession of a token proves control (see register_device)."""

    class Platform(models.TextChoices):
        IOS = "IOS", "iOS"
        ANDROID = "ANDROID", "Android"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    install_id = models.CharField(max_length=64)
    fcm_token = models.CharField(max_length=512)
    platform = models.CharField(max_length=16, choices=Platform.choices)
    app_version = models.CharField(max_length=32, blank=True)
    active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "install_id"], name="device_user_install_once"),
            models.UniqueConstraint(
                fields=["fcm_token"], condition=models.Q(active=True), name="device_active_fcm_token_once"
            ),
        ]
        indexes = [models.Index(fields=["user", "active"], name="device_user_active_idx")]
```

- [x] **Step 4: Generate the migration**

Run: `.venv/bin/python manage.py makemigrations notifications -n device`
Expected: creates `src/lamto/notifications/migrations/0003_device.py`.

- [x] **Step 5: Add the registry service**

Create `src/lamto/notifications/devices.py`:

```python
"""Push device registry with token rotation/reassignment (spec 7.2)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Device


@transaction.atomic
def register_device(user, install_id, fcm_token, platform, app_version="") -> Device:
    """Upsert the caller's (user, install_id) device, reassigning the token away
    from any other active device that currently holds it.

    Race-hardened: locks conflicting active token holders with select_for_update,
    then upserts. On partial-unique IntegrityError (device_active_fcm_token_once),
    re-deactivates and retries once.
    """
    from django.db import IntegrityError

    def _deactivate_other_holders():
        list(
            Device.objects.select_for_update()
            .filter(fcm_token=fcm_token, active=True)
            .exclude(user=user, install_id=install_id)
        )
        Device.objects.filter(fcm_token=fcm_token, active=True).exclude(
            user=user, install_id=install_id
        ).update(active=False)

    def _upsert():
        device, _ = Device.objects.update_or_create(
            user=user,
            install_id=install_id,
            defaults={
                "fcm_token": fcm_token,
                "platform": platform,
                "app_version": app_version,
                "active": True,
                "last_seen_at": timezone.now(),
            },
        )
        return device

    _deactivate_other_holders()
    try:
        return _upsert()
    except IntegrityError:
        _deactivate_other_holders()
        return _upsert()


def deactivate_device(user, install_id) -> int:
    """Deactivate one install's device (logout / explicit DELETE). Returns rows updated."""
    return Device.objects.filter(user=user, install_id=install_id, active=True).update(active=False)


def deactivate_user_devices(user) -> int:
    """Deactivate all active devices for a user (logout-all). Returns rows updated."""
    return Device.objects.filter(user=user, active=True).update(active=False)


def deactivate_stale_devices(days: int = 180) -> int:
    """Deactivate devices unseen for `days` (inactivity cleanup, spec 7.2)."""
    cutoff = timezone.now() - timedelta(days=days)
    return Device.objects.filter(active=True, last_seen_at__lt=cutoff).update(active=False)
```

Also create `src/lamto/notifications/management/commands/deactivate_stale_devices.py`:

```python
from django.core.management.base import BaseCommand

from lamto.notifications.devices import deactivate_stale_devices


class Command(BaseCommand):
    help = "Deactivate push devices unseen for N days (default 180; spec 7.2)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=180)

    def handle(self, *args, **options):
        n = deactivate_stale_devices(days=options["days"])
        self.stdout.write(self.style.SUCCESS(f"deactivated={n}"))
```

Wire a worker processor in `src/lamto/config/worker.py` (append to PROCESSORS):

```python
def process_stale_devices_batch(*, days: int = 180) -> ProcessorResult:
    name = "stale_devices"
    try:
        from lamto.notifications.devices import deactivate_stale_devices

        n = deactivate_stale_devices(days=days)
        return ProcessorResult(name=name, ok=True, count=n, detail=f"deactivated={n}")
    except Exception as exc:
        logger.exception("worker processor %s failed", name)
        return ProcessorResult(name=name, ok=False, detail=str(exc))
```

- [x] **Step 6: Run to verify it passes**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_devices.py -q`
Expected: PASS (4 passed, including race test on Postgres).

- [x] **Step 7: Commit**

```bash
git add src/lamto/notifications/models.py src/lamto/notifications/devices.py \
        src/lamto/notifications/migrations/0003_device.py src/lamto/notifications/tests/test_devices.py \
        src/lamto/notifications/management/commands/deactivate_stale_devices.py \
        src/lamto/config/worker.py
git commit -m "feat: push device registry with token rotation and reassignment"
```

---

### Task 2: `POST /devices` + `DELETE /devices/{install_id}` + logout coupling

Resident API endpoints to register/upsert and deactivate the calling install's device (spec §7.2). User-scoped (knox auth); no tenant context. Also couple knox logout to Device deactivation so a successful mobile logout cannot silently leave the install push-active.

**Files:**
- Modify: `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Modify: `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/api/tests/test_devices.py` (and logout coverage in same file or `test_auth.py`)

**Interfaces:**
- Consumes: `register_device`, `deactivate_device`, `deactivate_user_devices` (Task 1).
- Produces:
  - `serializers.DeviceRegisterSerializer` (`install_id`, `fcm_token`, `platform`, `app_version`), `DeviceSerializer` (`install_id`, `platform`, `active`).
  - `views.DeviceRegisterView` at `api:devices` = `devices` (POST); `DeviceDeleteView` at `api:device-delete` = `devices/<str:install_id>` (DELETE).
  - `LogoutView.post`: after super, if `X-Install-Id` header or body `install_id` present → `deactivate_device(user, install_id)`.
  - `LogoutAllView.post`: after super → `deactivate_user_devices(user)`.

- [x] **Step 1: Add the serializers**

In `src/lamto/api/serializers.py`, append:

```python
class DeviceRegisterSerializer(serializers.Serializer):
    install_id = serializers.CharField(max_length=64, help_text="Stable per-install client UUID (spec 7.2).")
    fcm_token = serializers.CharField(max_length=512)
    platform = serializers.ChoiceField(choices=["IOS", "ANDROID"])
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")


class DeviceSerializer(serializers.Serializer):
    install_id = serializers.CharField()
    platform = serializers.CharField()
    active = serializers.BooleanField()
```

- [x] **Step 2: Add the views**

In `src/lamto/api/views.py`, add imports + the views:

```python
from rest_framework import status as drf_status
from lamto.api.serializers import DeviceRegisterSerializer, DeviceSerializer
from lamto.notifications.devices import deactivate_device, register_device
```

```python
class DeviceRegisterView(APIView):
    @extend_schema(
        request=DeviceRegisterSerializer,
        responses={200: DeviceSerializer, **problem_responses(400, 401)},
    )
    def post(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = register_device(
            request.user,
            serializer.validated_data["install_id"],
            serializer.validated_data["fcm_token"],
            serializer.validated_data["platform"],
            serializer.validated_data.get("app_version", ""),
        )
        return Response(
            DeviceSerializer({"install_id": device.install_id, "platform": device.platform, "active": device.active}).data
        )


class DeviceDeleteView(APIView):
    @extend_schema(request=None, responses={204: None, **problem_responses(401)})
    def delete(self, request, install_id):
        deactivate_device(request.user, install_id)
        return Response(status=drf_status.HTTP_204_NO_CONTENT)
```

- [x] **Step 3: Add the routes**

In `src/lamto/api/urls.py`, add:

```python
    path("devices", views.DeviceRegisterView.as_view(), name="devices"),
    path("devices/<str:install_id>", views.DeviceDeleteView.as_view(), name="device-delete"),
```

- [x] **Step 4: Write the failing tests**

Create `src/lamto/api/tests/test_devices.py`:

```python
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from knox.models import AuthToken

from lamto.notifications.models import Device


class DeviceApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="d@example.test", password="x", display_name="D")

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.user)
        return {"authorization": f"Token {token}"}

    def test_register_and_delete(self):
        install = str(uuid.uuid4())
        resp = self.client.post(
            reverse("api:devices"),
            data={"install_id": install, "fcm_token": "tok-1", "platform": "ANDROID", "app_version": "1.0"},
            content_type="application/json",
            headers=self._auth(),
        )
        assert resp.status_code == 200, resp.content
        assert Device.objects.filter(user=self.user, install_id=install, active=True).count() == 1

        gone = self.client.delete(reverse("api:device-delete", args=[install]), headers=self._auth())
        assert gone.status_code == 204
        assert Device.objects.get(user=self.user, install_id=install).active is False

    def test_registration_reassigns_token_from_other_user(self):
        other = get_user_model().objects.create_user(email="o@example.test", password="x", display_name="O")
        Device.objects.create(
            user=other, install_id="o-install", fcm_token="shared", platform="IOS",
            active=True, last_seen_at=timezone.now(),
        )
        resp = self.client.post(
            reverse("api:devices"),
            data={"install_id": str(uuid.uuid4()), "fcm_token": "shared", "platform": "IOS"},
            content_type="application/json",
            headers=self._auth(),
        )
        assert resp.status_code == 200
        assert Device.objects.get(user=other, install_id="o-install").active is False

    def test_logout_with_install_id_deactivates_device(self):
        install = str(uuid.uuid4())
        Device.objects.create(
            user=self.user, install_id=install, fcm_token="logout-tok",
            platform="ANDROID", active=True, last_seen_at=timezone.now(),
        )
        resp = self.client.post(
            reverse("api:auth-logout"),
            headers={**self._auth(), "x-install-id": install},
        )
        assert resp.status_code == 204
        assert Device.objects.get(user=self.user, install_id=install).active is False

    def test_logout_without_install_id_leaves_device_active(self):
        install = str(uuid.uuid4())
        Device.objects.create(
            user=self.user, install_id=install, fcm_token="keep-tok",
            platform="ANDROID", active=True, last_seen_at=timezone.now(),
        )
        resp = self.client.post(reverse("api:auth-logout"), headers=self._auth())
        assert resp.status_code == 204
        assert Device.objects.get(user=self.user, install_id=install).active is True
```

Also update `LogoutView` / `LogoutAllView` in `src/lamto/api/views.py`:

```python
class LogoutView(KnoxLogoutView):
    authentication_classes = [ResidentTokenAuthentication]

    @extend_schema(
        request=None,
        responses={204: None, **problem_responses(401)},
    )
    def post(self, request, format=None):
        install_id = request.headers.get("X-Install-Id") or request.data.get("install_id")
        response = super().post(request, format)
        if install_id:
            from lamto.notifications.devices import deactivate_device

            deactivate_device(request.user, str(install_id))
        return response


class LogoutAllView(KnoxLogoutAllView):
    authentication_classes = [ResidentTokenAuthentication]

    @extend_schema(
        request=None,
        responses={204: None, **problem_responses(401)},
    )
    def post(self, request, format=None):
        response = super().post(request, format)
        from lamto.notifications.devices import deactivate_user_devices

        deactivate_user_devices(request.user)
        return response
```

- [x] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_devices.py -q`
Expected: PASS (4 passed).

- [x] **Step 6: Regenerate schema, classify the routes, run gates**

- Regenerate: `.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn`
- In `tests/isolation/test_cross_building_access.py`, add to `API_AUTHENTICATED_GLOBAL` (device rows are user-scoped, not tenant-scoped):

```python
    "api:devices": "POST register/upsert FCM device",
    "api:device-delete": "DELETE deactivate this install's device",
```

- In `src/lamto/api/tests/test_openapi.py::test_schema_covers_every_api_route`, add `"/api/v1/devices"` and (accepting `{install_id}`) `"/api/v1/devices/{install_id}"`.
- Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py -q` → PASS.

- [x] **Step 7: Commit**

```bash
git add src/lamto/api/serializers.py src/lamto/api/views.py src/lamto/api/urls.py \
        docs/api/openapi-v1.yaml src/lamto/api/tests/test_devices.py \
        src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py
git commit -m "feat: POST /devices and DELETE /devices/{install_id}"
```

---

### Task 3: `PUSH` channel + push preference + queue gating

Add the third channel, the per-category push preference, and the queue-time rule that only creates `PUSH` rows for eligible residents-with-devices (spec §7.3, §7.5).

**Files:**
- Modify: `src/lamto/notifications/models.py`, `src/lamto/notifications/services.py`
- Create: `src/lamto/notifications/migrations/0004_push_channel_and_preference.py` (generated)
- Test: `src/lamto/notifications/tests/test_push_channel.py`

**Interfaces:**
- Consumes: `Device` (Task 1).
- Produces:
  - `NotificationDelivery.Channel.PUSH`; `NotificationPreference.push_enabled` (default True).
  - `services.EVENT_WORK_COMPLETED = "work.completed"`, `services.RESIDENT_PUSH_EVENT_CODES`, `services.push_enabled_for(user, event_code) -> bool`.
  - `DEFAULT_CHANNELS` gains `PUSH`; `queue_notification` gates it per recipient.

- [x] **Step 1: Write the failing test**

Create `src/lamto/notifications/tests/test_push_channel.py`:

```python
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.notifications.devices import register_device
from lamto.notifications.models import Device, NotificationDelivery, NotificationPreference
from lamto.notifications.services import EVENT_PUBLICATION, EVENT_PAYMENT_RECORDED, queue_notification


@override_settings(PUSH_ENABLED=True)
class PushQueueGatingTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Push B")
        self.unit = Unit.objects.create(building=self.building, label="A-1")
        self.resident = get_user_model().objects.create_user(email="r@example.test", password="x", display_name="R")
        ResidentOccupancy.objects.create(user=self.resident, unit=self.unit, active=True)

    def _push_rows(self):
        return NotificationDelivery.objects.filter(recipient=self.resident, channel=NotificationDelivery.Channel.PUSH)

    def test_push_row_created_only_with_active_device(self):
        # No device yet -> no PUSH row.
        queue_notification(self.resident, f"{EVENT_PUBLICATION}:entry:1", "s", "b", event_code=EVENT_PUBLICATION, building=self.building)
        assert self._push_rows().count() == 0
        # Register a device -> PUSH row is created for a resident-push event.
        register_device(self.resident, str(uuid.uuid4()), "tok", Device.Platform.ANDROID)
        queue_notification(self.resident, f"{EVENT_PUBLICATION}:entry:2", "s", "b", event_code=EVENT_PUBLICATION, building=self.building)
        assert self._push_rows().count() == 1

    def test_non_resident_event_gets_no_push(self):
        register_device(self.resident, str(uuid.uuid4()), "tok", Device.Platform.ANDROID)
        queue_notification(self.resident, f"{EVENT_PAYMENT_RECORDED}:payment:1", "s", "b", event_code=EVENT_PAYMENT_RECORDED, building=self.building)
        assert self._push_rows().count() == 0

    def test_push_preference_off_suppresses(self):
        register_device(self.resident, str(uuid.uuid4()), "tok", Device.Platform.ANDROID)
        NotificationPreference.objects.create(user=self.resident, event_code=EVENT_PUBLICATION, push_enabled=False)
        queue_notification(self.resident, f"{EVENT_PUBLICATION}:entry:3", "s", "b", event_code=EVENT_PUBLICATION, building=self.building)
        assert self._push_rows().count() == 0
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_channel.py -q`
Expected: FAIL — `Channel.PUSH`/`push_enabled` do not exist.

- [x] **Step 3: Add the model changes**

In `src/lamto/notifications/models.py`, add `PUSH` to `NotificationDelivery.Channel`:

```python
    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "In-app"
        EMAIL = "EMAIL", "Email"
        PUSH = "PUSH", "Push"
```

Add `push_enabled` to `NotificationPreference` (after `email_enabled`):

```python
    push_enabled = models.BooleanField(default=True)
```

- [x] **Step 4: Generate the migration**

Run: `.venv/bin/python manage.py makemigrations notifications -n push_channel_and_preference`
Expected: creates `0004_push_channel_and_preference.py` (AlterField channel choices + AddField push_enabled).

- [x] **Step 5: Add the queue gating**

In `src/lamto/notifications/services.py`:

Add the new event code beside the others:

```python
EVENT_WORK_COMPLETED = "work.completed"
```

Add it to `PREFERENCE_EVENT_CHOICES` so it gets a consent toggle (§7.5), after the triage entry:

```python
    (EVENT_WORK_COMPLETED, "Work completed (rate prompt)"),
```

Add the resident push set + preference helper (after `PREFERENCE_EVENT_CHOICES`):

```python
# Resident-relevant push events only (spec 7.4). No staff push in Phase 1.
RESIDENT_PUSH_EVENT_CODES = frozenset(
    {
        EVENT_REPORT_RECEIPT,
        EVENT_TRIAGE_STATUS,
        EVENT_WORK_COMPLETED,
        EVENT_PUBLICATION,
        EVENT_CORRECTION_STATUS,
    }
)


def push_enabled_for(user, event_code: str) -> bool:
    pref = NotificationPreference.objects.filter(user=user, event_code=event_code).first()
    if pref is None:
        return True  # default on once OS permission exists (spec 7.5)
    return bool(pref.push_enabled)
```

Add `PUSH` to `DEFAULT_CHANNELS`:

```python
DEFAULT_CHANNELS = (
    NotificationDelivery.Channel.IN_APP,
    NotificationDelivery.Channel.EMAIL,
    NotificationDelivery.Channel.PUSH,
)
```

In `queue_notification`, add a `PUSH` gate inside the channel loop (mirroring the `EMAIL` gate), before the `get_or_create`:

```python
        if channel == NotificationDelivery.Channel.PUSH:
            from django.conf import settings
            from lamto.notifications.models import Device

            code = event_code or _event_code_from_key(event_key)
            if not getattr(settings, "PUSH_ENABLED", False):
                continue
            if code not in RESIDENT_PUSH_EVENT_CODES:
                continue
            if not push_enabled_for(recipient, code):
                continue
            if not Device.objects.filter(user=recipient, active=True).exists():
                continue
```

- [x] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_channel.py -q`
Expected: PASS (3 passed).

- [x] **Step 7: Commit**

```bash
git add src/lamto/notifications/models.py src/lamto/notifications/services.py \
        src/lamto/notifications/migrations/0004_push_channel_and_preference.py \
        src/lamto/notifications/tests/test_push_channel.py
git commit -m "feat: PUSH notification channel with device-gated queueing and push preference"
```

---

### Task 4: firebase-admin sender, config, and payload minimization

The FCM dependency + config, the thin `send_push`, error classification, and the minimized-payload builder (spec §7.1, §7.4).

**Files:**
- Modify: `pyproject.toml`, `src/lamto/config/settings.py`, `.env.example`
- Create: `src/lamto/notifications/push.py`
- Test: `src/lamto/notifications/tests/test_push_payload.py`

**Interfaces:**
- Produces:
  - `push.send_push(token, *, title, body, data, collapse_key=None) -> str` (message id).
  - `push.classify_push_error(exc) -> "terminal" | "transient"`.
  - `push.build_push_payload(delivery) -> (title, body, data)` — `data = {"type", "id", "delivery_id"}`, allowlisted type, no sensitive content.
  - `push.PUSH_COPY`, `push.DEEP_LINK_TYPES`.
- Settings: `FIREBASE_CREDENTIALS`, `PUSH_ENABLED`, `PUSH_DAILY_CAP_PER_CATEGORY`.

- [x] **Step 1: Add the dependency**

In `pyproject.toml`, add to `dependencies` (a push provider — permitted; §5.3 forbids only payment providers):

```toml
  "firebase-admin>=6,<8",
```

Install it: `.venv/bin/pip install "firebase-admin>=6,<8"`

- [x] **Step 2: Add settings + env**

In `src/lamto/config/settings.py`, after the notification/anchoring block, add:

```python
# --- Push notifications (spec 7): FCM via firebase-admin ---
# Path to a service-account JSON; never committed. Push is off unless both are set.
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS", "")
PUSH_ENABLED = (
    os.getenv("PUSH_ENABLED", "").lower() in {"1", "true", "yes"} and bool(FIREBASE_CREDENTIALS)
)
PUSH_DAILY_CAP_PER_CATEGORY = int(os.getenv("PUSH_DAILY_CAP_PER_CATEGORY", "10"))
```

In `.env.example`, add:

```
# Push notifications (FCM). Leave FIREBASE_CREDENTIALS empty to keep push off.
FIREBASE_CREDENTIALS=
PUSH_ENABLED=
PUSH_DAILY_CAP_PER_CATEGORY=10
```

- [x] **Step 3: Write the failing test**

Create `src/lamto/notifications/tests/test_push_payload.py`:

```python
from django.test import TestCase

from lamto.notifications.models import NotificationDelivery
from lamto.notifications.push import build_push_payload
from lamto.notifications.services import EVENT_PUBLICATION, EVENT_PAYMENT_RECORDED


class PushPayloadTests(TestCase):
    def _delivery(self, event_key, event_code, body):
        return NotificationDelivery(
            event_key=event_key, event_code=event_code, subject="secret subject",
            body=body, channel=NotificationDelivery.Channel.PUSH,
        )

    def test_publication_payload_is_minimized_and_deep_linked(self):
        d = self._delivery(f"{EVENT_PUBLICATION}:entry:42", EVENT_PUBLICATION, "Spending of 9999999 VND published")
        title, body, data = build_push_payload(d)
        assert "9999999" not in title and "9999999" not in body  # no sensitive content
        assert data["type"] == "ledger" and data["id"] == "42"
        assert "delivery_id" in data

    def test_unknown_entity_falls_back_to_feed(self):
        d = self._delivery(f"{EVENT_PAYMENT_RECORDED}:payment:7", EVENT_PAYMENT_RECORDED, "x")
        _title, _body, data = build_push_payload(d)
        assert data["type"] == "notifications"  # payment is not an allowlisted resident deep link
```

- [x] **Step 4: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_payload.py -q`
Expected: FAIL — no module `lamto.notifications.push`.

- [x] **Step 5: Add the push module**

Create `src/lamto/notifications/push.py`:

```python
"""FCM sender + payload minimization (spec 7.1, 7.4). No abstraction layer:
firebase_admin.messaging is called directly."""

from django.conf import settings

from .services import (
    EVENT_CORRECTION_STATUS,
    EVENT_PUBLICATION,
    EVENT_REPORT_RECEIPT,
    EVENT_TRIAGE_STATUS,
    EVENT_WORK_COMPLETED,
    _event_code_from_key,
)

# Fixed generic Vietnamese copy shown by the OS before the app runs (spec 7.4);
# never the delivery's sensitive subject/body.
PUSH_COPY = {
    EVENT_REPORT_RECEIPT: ("Đã nhận phản ánh", "Phản ánh của bạn đã được ghi nhận."),
    EVENT_TRIAGE_STATUS: ("Phản ánh đã được phân loại", "Phản ánh của bạn đã được mở thành yêu cầu xử lý."),
    EVENT_WORK_COMPLETED: ("Công việc đã hoàn thành", "Vui lòng đánh giá công việc đã thực hiện."),
    EVENT_PUBLICATION: ("Khoản chi mới được công bố", "Có khoản chi mới trong sổ quỹ tòa nhà."),
    EVENT_CORRECTION_STATUS: ("Có điều chỉnh mới", "Một điều chỉnh đã được công bố trong sổ quỹ."),
}
_DEFAULT_COPY = ("Thông báo mới", "Bạn có một thông báo mới.")

# Allowlisted entity segment (from event_key) -> app deep-link route type.
DEEP_LINK_TYPES = {"report": "report", "case": "case", "entry": "ledger", "correction": "ledger"}

_firebase_app = None


def _ensure_app():
    global _firebase_app
    if _firebase_app is None:
        import firebase_admin
        from firebase_admin import credentials

        _firebase_app = firebase_admin.initialize_app(
            credentials.Certificate(settings.FIREBASE_CREDENTIALS)
        )
    return _firebase_app


def send_push(token, *, title, body, data, collapse_key=None) -> str:
    """Send one FCM message; returns the provider message id. Raises firebase
    messaging errors, classified by classify_push_error."""
    from firebase_admin import messaging

    _ensure_app()
    message = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in data.items()},
        android=messaging.AndroidConfig(collapse_key=collapse_key) if collapse_key else None,
        apns=(
            messaging.APNSConfig(headers={"apns-collapse-id": collapse_key})
            if collapse_key
            else None
        ),
    )
    return messaging.send(message)


def classify_push_error(exc) -> str:
    """Terminal (dead token -> deactivate device) vs transient (retry) (spec 7.3).

    Terminal covers all invalid/unregistered/mismatched-token cases exposed by
    pinned firebase-admin>=6,<8: UnregisteredError, SenderIdMismatchError, and
    InvalidArgumentError for bad registration tokens. Everything else is transient.
    """
    from firebase_admin import messaging

    if isinstance(exc, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
        return "terminal"
    if isinstance(exc, messaging.InvalidArgumentError):
        msg = str(exc).lower()
        if any(
            needle in msg
            for needle in (
                "registration token",
                "not a valid fcm",
                "invalid registration",
                "requested entity was not found",
            )
        ):
            return "terminal"
    return "transient"


def _parse_reference(event_key: str):
    parts = event_key.split(":")
    if len(parts) >= 3:
        return parts[1], parts[2]
    return None, None


def build_push_payload(delivery):
    """Generic Vietnamese title/body + allowlisted deep link + delivery id (spec 7.4)."""
    code = delivery.event_code or _event_code_from_key(delivery.event_key)
    title, body = PUSH_COPY.get(code, _DEFAULT_COPY)
    entity, entity_id = _parse_reference(delivery.event_key)
    link_type = DEEP_LINK_TYPES.get(entity, "notifications")
    data = {"type": link_type, "id": entity_id or "", "delivery_id": str(delivery.pk)}
    return title, body, data
```

- [x] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_payload.py -q`
Expected: PASS (2 passed).

- [x] **Step 7: Commit**

```bash
git add pyproject.toml src/lamto/config/settings.py .env.example \
        src/lamto/notifications/push.py src/lamto/notifications/tests/test_push_payload.py
git commit -m "feat: FCM sender, config, and minimized push payload builder"
```

---

### Task 5: Worker PUSH fan-out with send-time revalidation and error classification

The worker processes `PUSH` deliveries: revalidate the recipient, fan out to active devices, deactivate dead tokens, back off on transient errors (spec §7.3).

**Files:**
- Modify: `src/lamto/notifications/services.py`
- Test: `src/lamto/notifications/tests/test_push_worker.py`

**Interfaces:**
- Consumes: `Device` (Task 1), `send_push`, `classify_push_error`, `build_push_payload` (Task 4), `active_occupancies`.
- Produces: `MAX_PUSH_ATTEMPTS`; `process_delivery` routes `PUSH` to `_process_push_delivery`.

- [x] **Step 1: Write the failing test**

Create `src/lamto/notifications/tests/test_push_worker.py`:

```python
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.notifications.devices import register_device
from lamto.notifications.models import Device, NotificationDelivery
from lamto.notifications.services import EVENT_PUBLICATION, process_delivery


def _make_resident(building, unit, email):
    user = get_user_model().objects.create_user(email=email, password="x", display_name="R")
    ResidentOccupancy.objects.create(user=user, unit=unit, active=True)
    return user


def _push_delivery(user, building):
    return NotificationDelivery.objects.create(
        recipient=user, building=building, channel=NotificationDelivery.Channel.PUSH,
        status=NotificationDelivery.Status.PENDING, event_key=f"{EVENT_PUBLICATION}:entry:1",
        event_code=EVENT_PUBLICATION, subject="s", body="b",
    )


@override_settings(PUSH_ENABLED=True)
class PushWorkerTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Worker B")
        self.unit = Unit.objects.create(building=self.building, label="A-1")
        self.resident = _make_resident(self.building, self.unit, "wr@example.test")
        register_device(self.resident, str(uuid.uuid4()), "tok-1", Device.Platform.ANDROID)

    @patch("lamto.notifications.services.send_push", return_value="msg-1")
    def test_sends_and_marks_sent(self, send):
        delivery = _push_delivery(self.resident, self.building)
        result = process_delivery(delivery)
        assert result.status == NotificationDelivery.Status.SENT
        assert send.call_count == 1

    @patch("lamto.notifications.services.send_push")
    def test_terminal_error_deactivates_device(self, send):
        from firebase_admin import messaging

        send.side_effect = messaging.UnregisteredError("gone")
        delivery = _push_delivery(self.resident, self.building)
        process_delivery(delivery)
        assert Device.objects.filter(user=self.resident, active=True).count() == 0

    @patch("lamto.notifications.services.send_push", return_value="msg-1")
    def test_revalidation_suppresses_when_occupancy_gone(self, send):
        ResidentOccupancy.objects.filter(user=self.resident).update(active=False)
        delivery = _push_delivery(self.resident, self.building)
        result = process_delivery(delivery)
        assert send.call_count == 0
        assert result.status == NotificationDelivery.Status.SENT  # non-retryable; in-app authoritative
        assert result.last_error.startswith("suppressed:")  # not a true FCM success
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_worker.py -q`
Expected: FAIL — `process_delivery` has no PUSH branch (`send_push` not imported in services).

- [x] **Step 3: Add the worker branch**

In `src/lamto/notifications/services.py`, add the constant near `MAX_EMAIL_ATTEMPTS`:

```python
MAX_PUSH_ATTEMPTS = 5
```

In `process_delivery`, after the `IN_APP` branch and before the `# EMAIL` block, add:

```python
        if locked.channel == NotificationDelivery.Channel.PUSH:
            return _process_push_delivery(locked)
```

Append the push processor + revalidation helper at the end of the module:

```python
def _recipient_can_receive_push(delivery) -> bool:
    """Send-time revalidation (spec 7.3): user active + active occupancy in building."""
    from lamto.accounts.tenancy import active_occupancies

    user = delivery.recipient
    if not getattr(user, "is_active", False):
        return False
    if delivery.building_id is None:
        return True
    return active_occupancies(user).filter(unit__building_id=delivery.building_id).exists()


# Structured suppress markers: do not count as true FCM success in ops metrics.
PUSH_SUPPRESSED_PREFIX = "suppressed:"


def _process_push_delivery(delivery):
    from lamto.notifications.models import Device
    from lamto.notifications.push import build_push_payload, classify_push_error, send_push

    now = timezone.now()
    if not _recipient_can_receive_push(delivery):
        delivery.status = NotificationDelivery.Status.SENT  # non-retryable; in-app feed holds it
        delivery.last_error = f"{PUSH_SUPPRESSED_PREFIX}recipient_ineligible"
        delivery.save(update_fields=["status", "last_error", "updated_at"])
        return delivery

    devices = list(Device.objects.filter(user=delivery.recipient, active=True))
    if not devices:
        delivery.status = NotificationDelivery.Status.SENT
        delivery.last_error = f"{PUSH_SUPPRESSED_PREFIX}no_active_devices"
        delivery.save(update_fields=["status", "last_error", "updated_at"])
        return delivery

    title, body, data = build_push_payload(delivery)
    collapse_key = None  # set for aggregated categories in Task 6
    any_transient = False
    last_error = ""
    for device in devices:
        try:
            send_push(device.fcm_token, title=title, body=body, data=data, collapse_key=collapse_key)
        except Exception as exc:  # noqa: BLE001 - provider errors are classified below
            if classify_push_error(exc) == "terminal":
                Device.objects.filter(pk=device.pk).update(active=False)
            else:
                any_transient = True
                last_error = str(exc)[:2000]

    delivery.attempts += 1
    if any_transient:
        delivery.last_error = last_error
        if delivery.attempts >= MAX_PUSH_ATTEMPTS:
            delivery.status = NotificationDelivery.Status.FAILED
            delivery.next_retry_at = None
        else:
            delivery.status = NotificationDelivery.Status.FAILED
            backoff = BASE_BACKOFF_SECONDS * (2 ** min(delivery.attempts - 1, 6))
            delivery.next_retry_at = now + timedelta(seconds=backoff)
    else:
        delivery.status = NotificationDelivery.Status.SENT
        delivery.last_error = ""
        delivery.next_retry_at = None
    delivery.save(update_fields=["status", "attempts", "last_error", "next_retry_at", "updated_at"])
    return delivery
```

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_worker.py -q`
Expected: PASS (3 passed).

- [x] **Step 5: Update the worker command help text**

In `src/lamto/notifications/management/commands/process_notifications.py`, change the help string to `"Process due in-app, email, and push notification deliveries."` (behavior already covers PUSH via `process_due_notifications`).

- [x] **Step 6: Commit**

```bash
git add src/lamto/notifications/services.py \
        src/lamto/notifications/management/commands/process_notifications.py \
        src/lamto/notifications/tests/test_push_worker.py
git commit -m "feat: PUSH worker fan-out with send-time revalidation and error classification"
```

---

### Task 6: Publication aggregation (collapse + daily cap)

Ledger-publication pushes collapse on-device and are capped per user per day so a bulk-publication day does not spam residents (spec §7.3).

**Files:**
- Modify: `src/lamto/notifications/services.py`
- Test: `src/lamto/notifications/tests/test_push_worker.py`

**Interfaces:**
- Consumes: `PUSH_DAILY_CAP_PER_CATEGORY` (settings), `_process_push_delivery`.
- Produces: `_collapse_key(delivery)`, `_daily_push_cap_reached(delivery)`.

- [x] **Step 1: Write the failing test**

Append to `src/lamto/notifications/tests/test_push_worker.py`:

```python
    @override_settings(PUSH_ENABLED=True, PUSH_DAILY_CAP_PER_CATEGORY=2)
    @patch("lamto.notifications.services.send_push", return_value="msg-1")
    def test_publication_collapse_key_and_daily_cap(self, send):
        from lamto.notifications.services import _collapse_key

        d1 = _push_delivery(self.resident, self.building)
        process_delivery(d1)
        assert send.call_args.kwargs["collapse_key"] == _collapse_key(d1)
        assert _collapse_key(d1) == f"pub:{self.building.pk}"

        # Two already sent today (cap=2): the third is suppressed without a send.
        NotificationDelivery.objects.create(
            recipient=self.resident, building=self.building, channel=NotificationDelivery.Channel.PUSH,
            status=NotificationDelivery.Status.SENT, event_key=f"{EVENT_PUBLICATION}:entry:9",
            event_code=EVENT_PUBLICATION, subject="s", body="b",
        )
        send.reset_mock()
        d3 = _push_delivery(self.resident, self.building)
        result = process_delivery(d3)
        assert send.call_count == 0
        assert result.status == NotificationDelivery.Status.SENT
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_worker.py::PushWorkerTests::test_publication_collapse_key_and_daily_cap -q`
Expected: FAIL — `_collapse_key` does not exist / collapse_key is None.

- [x] **Step 3: Add collapse + cap**

In `src/lamto/notifications/services.py`, add the helpers before `_process_push_delivery`:

```python
# Categories that collapse on-device and are daily-capped (spec 7.3).
_AGGREGATED_PUSH_CODES = frozenset({EVENT_PUBLICATION})


def _collapse_key(delivery):
    code = delivery.event_code or _event_code_from_key(delivery.event_key)
    if code == EVENT_PUBLICATION and delivery.building_id is not None:
        return f"pub:{delivery.building_id}"
    return None


def _daily_push_cap_reached(delivery) -> bool:
    from django.conf import settings

    code = delivery.event_code or _event_code_from_key(delivery.event_key)
    if code not in _AGGREGATED_PUSH_CODES:
        return False
    cap = getattr(settings, "PUSH_DAILY_CAP_PER_CATEGORY", 10)
    today = timezone.localdate()  # settings.TIME_ZONE = Asia/Ho_Chi_Minh
    sent_today = NotificationDelivery.objects.filter(
        recipient=delivery.recipient,
        channel=NotificationDelivery.Channel.PUSH,
        event_code=code,
        status=NotificationDelivery.Status.SENT,
        last_error="",  # true FCM success only; suppressions do not consume cap
        updated_at__date=today,
    ).count()
    return sent_today >= cap
```

In `_process_push_delivery`, replace `collapse_key = None  # set for aggregated categories in Task 6` with the cap check + real collapse key (place right after the `devices` no-active-devices guard):

```python
    if _daily_push_cap_reached(delivery):
        delivery.status = NotificationDelivery.Status.SENT  # capped; in-app feed holds it
        delivery.last_error = f"{PUSH_SUPPRESSED_PREFIX}daily_cap"
        delivery.save(update_fields=["status", "last_error", "updated_at"])
        return delivery

    title, body, data = build_push_payload(delivery)
    collapse_key = _collapse_key(delivery)
```

(Remove the now-duplicate `title, body, data = build_push_payload(delivery)` / `collapse_key = None` lines that preceded the loop.)

Daily-cap "today" uses project timezone (`TIME_ZONE = Asia/Ho_Chi_Minh`); replace the date filter:

```python
def _daily_push_cap_reached(delivery) -> bool:
    from django.conf import settings

    code = delivery.event_code or _event_code_from_key(delivery.event_key)
    if code not in _AGGREGATED_PUSH_CODES:
        return False
    cap = getattr(settings, "PUSH_DAILY_CAP_PER_CATEGORY", 10)
    today = timezone.localdate()  # Asia/Ho_Chi_Minh calendar day (settings.TIME_ZONE)
    # Count only true FCM successes (empty last_error), not suppressions.
    sent_today = NotificationDelivery.objects.filter(
        recipient=delivery.recipient,
        channel=NotificationDelivery.Channel.PUSH,
        event_code=code,
        status=NotificationDelivery.Status.SENT,
        last_error="",
        updated_at__date=today,
    ).count()
    return sent_today >= cap
```

In the daily-cap test, assert `result.last_error.startswith("suppressed:")` and that true-success cap ignores suppressed rows.

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_worker.py -q`
Expected: PASS (4+ passed).

- [x] **Step 5: Commit**

```bash
git add src/lamto/notifications/services.py src/lamto/notifications/tests/test_push_worker.py
git commit -m "feat: publication push collapse key and per-user daily cap"
```

---

### Task 7: Resident event wiring (rate prompt + published correction)

Two of the five §7.4 resident events do not currently reach residents. Wire them so their deliveries (and thus PUSH) target the reporting residents / building residents.

**Files:**
- Modify: `src/lamto/notifications/hooks.py`, `src/lamto/finance/acceptance.py`
- Test: `src/lamto/notifications/tests/test_push_channel.py`

**Interfaces:**
- Consumes: `EVENT_WORK_COMPLETED`, `EVENT_CORRECTION_STATUS`, `notify_users`.
- Produces: `hooks.notify_work_rateable(record)`; `notify_correction_status` includes building residents when the correction is resident-visible.

- [x] **Step 1: Write the failing test**

Append to `src/lamto/notifications/tests/test_push_channel.py`:

```python
    def test_work_rateable_notifies_reporting_resident(self):
        from lamto.notifications.hooks import notify_work_rateable
        from lamto.notifications.services import EVENT_WORK_COMPLETED
        from lamto.testing.factories import PilotDomainDriver, seed_pilot_world
        from lamto.maintenance.models import WorkOrder
        import tempfile
        from django.test import override_settings

        with override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tempfile.mkdtemp()}},
                "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tempfile.mkdtemp()}},
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            }
        ):
            seed = seed_pilot_world(building_name="Rate B", email_prefix="rate", create_sample_report=False)
            d = PilotDomainDriver(seed)
            d.login(None, "resident").submit_report("Lift noise", "Lift 2")
            d.login(None, "operator").confirm_triage_and_create_paid_work_order()
            d.login(None, "operator").submit_signed_proposal()
            d.login(None, "board_approver").approve_proposal()
            d.login(None, "resident_representative").coapprove_proposal()
            d.login(None, "maintenance").complete_assigned_work()
            d.login(None, "board_payment_recorder").accept_and_record_payment()
            d.confirm_all_chain_events()
            work = WorkOrder.objects.get(case__building=seed.building)
            from lamto.finance.models import AcceptanceRecord
            record = AcceptanceRecord.objects.get(work_order=work)
            # notify_users queues via transaction.on_commit; fire it in-test.
            with self.captureOnCommitCallbacks(execute=True):
                notify_work_rateable(record)
            assert NotificationDelivery.objects.filter(
                recipient=seed.users["resident"], event_code=EVENT_WORK_COMPLETED,
            ).exists()
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest "src/lamto/notifications/tests/test_push_channel.py::PushQueueGatingTests::test_work_rateable_notifies_reporting_resident" -q`
Expected: FAIL — `notify_work_rateable` does not exist.

- [x] **Step 3: Add the rate-prompt hook**

In `src/lamto/notifications/hooks.py`, extend the services import with `EVENT_WORK_COMPLETED` and append:

```python
def notify_work_rateable(record):
    """Prompt the reporting residents to rate completed work (spec 7.4)."""
    from lamto.maintenance.models import CaseReport

    work_order = record.work_order
    building_id = work_order.case.building_id
    residents = [
        link.report.reporter
        for link in CaseReport.objects.filter(case=work_order.case).select_related("report__reporter")
    ]
    notify_users(
        residents,
        event_key=f"{EVENT_WORK_COMPLETED}:work:{work_order.pk}",
        subject="Work completed",
        body=f"Work order #{work_order.pk} is complete — please rate it.",
        event_code=EVENT_WORK_COMPLETED,
        building=building_id,
    )
```

- [x] **Step 4: Call it from acceptance**

In `src/lamto/finance/acceptance.py`, at the existing `notify_work_accepted(record)` call site (inside the `transaction.on_commit`/post-commit block near line 286), add right after it:

```python
        from lamto.notifications.hooks import notify_work_rateable

        notify_work_rateable(record)
```

- [x] **Step 5: Include residents on published corrections**

In `src/lamto/notifications/hooks.py`, update `notify_correction_status` to add building residents when the correction is resident-visible:

```python
def notify_correction_status(correction, status_label: str):
    building_id = correction.original_entry.case.building_id
    recipients = (
        [correction.operator.user]
        + _users_with_capability(building_id, "correction.approve")
        + _users_with_capability(building_id, "correction.create")
    )
    if getattr(correction, "is_resident_visible", False):
        from lamto.accounts.models import ResidentOccupancy

        recipients += [
            o.user
            for o in ResidentOccupancy.objects.filter(
                unit__building_id=building_id, active=True
            ).select_related("user")
        ]
    notify_users(
        recipients,
        event_key=f"{EVENT_CORRECTION_STATUS}:correction:{correction.pk}:{status_label}",
        subject=f"Correction {status_label}",
        body=f"Correction #{correction.pk} is now {status_label}.",
        event_code=EVENT_CORRECTION_STATUS,
        building=building_id,
    )
```

- [x] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_push_channel.py -q`
Expected: PASS (4 passed).

- [x] **Step 7: Run the finance acceptance suite (guard the call-site change)**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_acceptance.py -q`
Expected: PASS — the extra notification hook does not alter acceptance behavior.

- [x] **Step 8: Commit**

```bash
git add src/lamto/notifications/hooks.py src/lamto/finance/acceptance.py \
        src/lamto/notifications/tests/test_push_channel.py
git commit -m "feat: resident rate-prompt and published-correction notifications"
```

---

### Task 8: Consent preferences + ops health

Resident push preferences on the Account page (§7.5), `push_enabled` surfaced in `/me`, and push metrics on `/s/ops/health/` (§7.6).

**Files:**
- Modify: `src/lamto/web/forms/staff.py`
- Modify: `src/lamto/api/serializers.py`, `src/lamto/api/views.py` (MeView)
- Modify: `src/lamto/web/views/health.py`, the ops-health template
- Test: `src/lamto/web/tests/test_push_preferences.py`, `src/lamto/api/tests/test_me.py`

**Interfaces:**
- Consumes: `RESIDENT_PUSH_EVENT_CODES`, `NotificationPreference.push_enabled`.
- Produces: `NotificationPreferenceForm` push toggles; `/me` prefs include `push_enabled`; ops-health `push_failures`, `push_sent_success`, `push_suppressed`, `dead_devices`, `stale_device_max_inactive_days`.

- [x] **Step 1: Add push toggles to the preference form**

In `src/lamto/web/forms/staff.py`, in `NotificationPreferenceForm.__init__`, after building the `email_{code}` fields, add push fields for the resident-push categories, and load their current values:

```python
        from lamto.notifications.services import RESIDENT_PUSH_EVENT_CODES

        push_prefs = {
            p.event_code: p.push_enabled
            for p in NotificationPreference.objects.filter(user=user)
        }
        for code, label in PREFERENCE_EVENT_CHOICES:
            if code not in RESIDENT_PUSH_EVENT_CODES:
                continue
            self.fields[f"push_{code}"] = forms.BooleanField(
                label=f"Push: {label}", required=False, initial=push_prefs.get(code, True)
            )
```

In `NotificationPreferenceForm.save`, persist `push_enabled` alongside `email_enabled` (update the existing `update_or_create` loop):

```python
        from lamto.notifications.services import RESIDENT_PUSH_EVENT_CODES

        for code, _label in PREFERENCE_EVENT_CHOICES:
            defaults = {"email_enabled": bool(self.cleaned_data.get(f"email_{code}"))}
            if code in RESIDENT_PUSH_EVENT_CODES and f"push_{code}" in self.fields:
                defaults["push_enabled"] = bool(self.cleaned_data.get(f"push_{code}"))
            NotificationPreference.objects.update_or_create(
                user=self.user, event_code=code, defaults=defaults
            )
```

- [x] **Step 2: Surface `push_enabled` in `/me`**

In `src/lamto/api/serializers.py`, add `push_enabled` to `NotificationPreferenceSerializer`:

```python
class NotificationPreferenceSerializer(serializers.Serializer):
    event_code = serializers.CharField()
    email_enabled = serializers.BooleanField()
    push_enabled = serializers.BooleanField()
```

In `src/lamto/api/views.py`, in `MeView.get`, include `push_enabled` in the preferences values list:

```python
        preferences = list(
            request.user.notification_preferences.order_by("event_code").values(
                "event_code", "email_enabled", "push_enabled"
            )
        )
```

- [x] **Step 3: Add push metrics to ops health**

In `src/lamto/web/views/health.py`, where `notification_failures` is computed, add push-specific counts and a dead-device count:

```python
    from django.db.models import Max
    from django.db.models.functions import Now
    from lamto.notifications.models import Device
    from lamto.notifications.services import PUSH_SUPPRESSED_PREFIX

    push_qs = NotificationDelivery.objects.filter(channel=NotificationDelivery.Channel.PUSH)
    push_failures = push_qs.filter(
        status__in=[NotificationDelivery.Status.FAILED, NotificationDelivery.Status.DEAD],
    ).count()
    push_sent_success = push_qs.filter(
        status=NotificationDelivery.Status.SENT, last_error=""
    ).count()
    push_suppressed = push_qs.filter(
        status=NotificationDelivery.Status.SENT, last_error__startswith=PUSH_SUPPRESSED_PREFIX
    ).count()
    dead_devices = Device.objects.filter(active=False).count()
    # Max whole days since last_seen_at among inactive devices (age signal, not only count).
    oldest = (
        Device.objects.filter(active=False)
        .order_by("last_seen_at")
        .values_list("last_seen_at", flat=True)
        .first()
    )
    if oldest is None:
        stale_device_max_inactive_days = 0
    else:
        stale_device_max_inactive_days = max(0, (timezone.now() - oldest).days)
```

Add `push_failures`, `push_sent_success`, `push_suppressed`, `dead_devices`, and `stale_device_max_inactive_days` to the ops-health context/template:

```html
      <div><dt>Push failures</dt><dd>{{ push_failures }}</dd></div>
      <div><dt>Push sent (FCM success)</dt><dd>{{ push_sent_success }}</dd></div>
      <div><dt>Push suppressed (not FCM success)</dt><dd>{{ push_suppressed }}</dd></div>
      <div><dt>Inactive devices (dead tokens)</dt><dd>{{ dead_devices }}</dd></div>
      <div><dt>Stale device max inactive age (days)</dt><dd>{{ stale_device_max_inactive_days }}</dd></div>
```

(Find the ops-health template referenced by `ops_health` — it renders the existing `notification_failures` metric in a `<dl>`; add the rows there.)

- [x] **Step 4: Write the tests**

Create `src/lamto/web/tests/test_push_preferences.py`:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase

from lamto.notifications.models import NotificationPreference
from lamto.notifications.services import EVENT_PUBLICATION
from lamto.web.forms.staff import NotificationPreferenceForm


class PushPreferenceFormTests(TestCase):
    def test_saves_push_enabled_flag(self):
        user = get_user_model().objects.create_user(email="p@example.test", password="x", display_name="P")
        form = NotificationPreferenceForm(
            data={f"push_{EVENT_PUBLICATION}": "", f"email_{EVENT_PUBLICATION}": "on"},
            user=user,
        )
        assert form.is_valid(), form.errors
        form.save()
        pref = NotificationPreference.objects.get(user=user, event_code=EVENT_PUBLICATION)
        assert pref.push_enabled is False and pref.email_enabled is True
```

Append to `src/lamto/api/tests/test_me.py` a check that `/me` prefs include `push_enabled`:

```python
    def test_me_preferences_include_push_enabled(self):
        from lamto.notifications.models import NotificationPreference
        from lamto.notifications.services import EVENT_PUBLICATION

        NotificationPreference.objects.create(
            user=self.resident, event_code=EVENT_PUBLICATION, email_enabled=True, push_enabled=False
        )
        response = self.client.get(reverse("api:me"), headers=self._auth())
        assert response.status_code == 200
        prefs = {p["event_code"]: p for p in response.json()["notification_preferences"]}
        assert prefs[EVENT_PUBLICATION]["push_enabled"] is False
```

(Reuse the `test_me.py` class's existing `setUp`/`_auth`; if the resident attribute is named differently there, match it.)

- [x] **Step 5: Run the tests + regenerate schema (MeSerializer changed)**

- Regenerate: `.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn`
- Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_push_preferences.py src/lamto/api/tests/test_me.py src/lamto/api/tests/test_openapi.py -q`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/lamto/web/forms/staff.py src/lamto/api/serializers.py src/lamto/api/views.py \
        src/lamto/web/views/health.py docs/api/openapi-v1.yaml \
        src/lamto/web/tests/test_push_preferences.py src/lamto/api/tests/test_me.py
# plus the ops-health template edited in Step 3
git add src/lamto/web/templates/web/staff/
git commit -m "feat: resident push preferences and ops-health push metrics"
```

- [x] **Step 7: Full regression gate (exit gate)**

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS — the six e2e journeys, the two-building adversarial walk (web + API), `tenant_integrity`, the disabled-mode job, and every new push test. (With `PUSH_ENABLED` unset in the default test env, no `PUSH` rows are created, so existing suites are unaffected.)

---

## Self-review

### Spec coverage map

| Spec | Requirement | Task |
|---|---|---|
| §7.1 | FCM only via firebase-admin; credential from env, never in git; no abstraction layer | Task 4 |
| §7.2 | `Device` model (user, install_id, fcm_token, platform, app_version, active, last_seen_at) | Task 1 |
| §7.2 | Registration upsert by (user, install_id); token reassignment; logout deactivates install | Tasks 1, 2 |
| §7.2 | Inactivity cleanup (180 days) | Task 1 (`deactivate_stale_devices`) |
| §7.2 | Auth tokens and FCM tokens are separate records | Devices are their own model; knox untouched |
| §3.3 / §7.2 | `POST /devices`, `DELETE /devices/{install_id}` | Task 2 |
| §7.3 | `PUSH` third channel inheriting queue/claim/retry/preference | Tasks 3, 5 |
| §7.3 | Send-time revalidation (user active + occupancy in building) | Task 5 |
| §7.3 | Terminal (deactivate device) vs transient (backoff) error classification | Tasks 4, 5 |
| §7.3 | Idempotency/dedupe: payload carries delivery id | Task 4 (`data.delivery_id`) |
| §7.3 | Aggregation: collapse_key + per-user daily cap for publications | Task 6 |
| §7.4 | Resident events only; no staff push | Task 3 gating (`RESIDENT_PUSH_EVENT_CODES`) + Task 5 revalidation |
| §7.4 | Five resident events (receipt/triage/rate-prompt/publication/correction) | Tasks 3 (3 existing) + 7 (2 wired) |
| §7.4 | Payload minimization: generic VI title/body, allowlisted deep link, no sensitive content | Task 4 |
| §7.5 | In-app per-category push preferences on Account; defaults on | Tasks 3, 8 |
| §7.6 | Push failure counts + dead-token cleanup on ops health | Task 8 |
| §5.3 | firebase-admin is a push provider, not a payment provider | Task 4 (allowed) |

### Placeholder scan

No `TBD`/`add validation`/`similar to Task N`. Task 5 leaves a `collapse_key = None  # set for aggregated categories in Task 6` line that Task 6 explicitly replaces with named code — a spelled-out substitution, not a placeholder. Task 8 Step 3 tells the implementer to locate the ops-health template rows next to the existing `notification_failures` metric (the exact `<dl>` the current view already renders).

### Type consistency

- `register_device(user, install_id, fcm_token, platform, app_version="")` / `deactivate_device(user, install_id)` identical across Tasks 1, 2, 5.
- `Device.Platform` values `"IOS"`/`"ANDROID"` match the `DeviceRegisterSerializer` choices (Task 2).
- `send_push(token, *, title, body, data, collapse_key=None)` — the worker (Task 5/6) calls it with exactly those kwargs; tests patch `lamto.notifications.services.send_push`.
- `RESIDENT_PUSH_EVENT_CODES` (Task 3) is consumed by Task 3 gating, Task 4 `PUSH_COPY` keys, and Task 8 preference form — same event-code constants throughout (`EVENT_WORK_COMPLETED` added in Task 3, used in Tasks 4, 7).
- `build_push_payload(delivery) -> (title, body, data)` and `classify_push_error(exc) -> str` signatures match their Task 5 call sites.

## Out of scope (documented deferrals)

- **The Flutter client** (§6): OS permission prompt, `flutter_secure_storage`, FCM token-refresh re-registration, deep-link routing, duplicate-tolerant navigation. This plan delivers only the backend + `/devices` API the app will call. Flutter logout MUST send `X-Install-Id` (see design decision 8).
- **Resident API endpoint to *write* push/email preferences.** **Shipped:** `PATCH /api/v1/me/notification-preferences` updates `email_enabled` / `push_enabled` per event code (Flutter Account can call it). `/me` remains the read surface; web Account form still works. Flutter client UI wiring remains out of scope.
- **Windowed "N new" summary copy.** Aggregation uses `collapse_key` (device shows one) + a daily cap, per §7.3; counting exact "3 khoản chi mới" is deferred (YAGNI beyond the spec's collapse + cap).
- **Zalo ZNS / a second provider** (§7.1 explicitly not built).

## Deviations

- Follow-up: shipped `PATCH /me/notification-preferences`, OpenAPI X-Install-Id, seeded ops metric tests, durable `push_sent_device_ids` partial-retry.
- All-terminal FCM fan-out marks `suppressed:all_tokens_terminal` (not empty last_error SENT) so ops success/daily cap stay honest.
- Correction residents notified from `finalize_correction_publication` (visibility only then), not only decide-time hook list change.
- `InvalidArgumentError` imported from `firebase_admin.exceptions` (not messaging) for firebase-admin 7.5.
- Race test uses TransactionTestCase (threads + append-only triggers).

