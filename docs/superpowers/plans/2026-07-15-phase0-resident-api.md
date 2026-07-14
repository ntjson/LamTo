# Phase 0 Plan 3: Resident API (DRF + knox) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Phase 0 resident-API slice of spec §3 — DRF + knox plumbing, RFC 9457 problem+json errors, server-validated `X-LamTo-Occupancy` context, `POST /auth/login|logout|logout-all`, `GET /me`, read-only `GET /ledger`, `GET /ledger/{id}`, `GET /fund/summary`, a committed OpenAPI schema with a drift gate, and the two-building adversarial walk extended over every API route.

**Architecture:** A new `lamto.api` Django app mounted at `/api/v1/` in the same monolith. The API is resident-only (staff keep the MFA'd `/s/` web surface, untouched). Both presentation layers call the shared building-scoped selectors in `lamto.finance.selectors` — this plan deepens that layer with one extraction (`ledger_entry_proof`) so the web template and the API serialize the same assembly. Tenant context comes from the validated occupancy header per spec §3.4; a client-supplied building ID is never accepted.

**Tech Stack:** Django 5.2, djangorestframework ≥3.16, django-rest-knox ≥5.0, drf-spectacular ≥0.28 (has built-in knox auth-scheme support since 0.27.2), pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md` §3 (all), §2.3 layers 1–2 and 4, §2.4, §5.4 gate 2. Plans 1 (tenancy) and 2 (anchoring port + evidence levels) are implemented; this plan builds on `TenantContext`/`active_occupancies` (`accounts/tenancy.py`), `published_ledger_entries`/`fund_period_flows` (`finance/selectors.py`), and `EvidenceLevel`/`evidence_level()` (`evidence/models.py`).

## Design decisions (documented deviations & interpretations)

1. **The OpenAPI "CI drift check" is an always-running pytest module.** This repo has no CI workflow files; Plan 2 realized the "disabled-mode CI job" the same way. `src/lamto/api/tests/test_openapi.py` regenerates the schema and fails on any diff against the committed `docs/api/openapi-v1.yaml`.
2. **Login requires an active resident occupancy (403 otherwise).** Spec §3.1 makes the surface resident-only; refusing tokens to occupancy-less users (staff) makes §3.2's revocation rule total — every token belongs to a user who had an active occupancy at issuance, so "deactivating the last active occupancy deletes all their knox tokens" covers all tokens.
3. **Token cap uses custom eviction, not knox's `TOKEN_LIMIT_PER_USER`.** Knox's built-in limit *rejects* the 6th login with 403; spec §3.2 says "oldest evicted at login". The login view deletes oldest tokens beyond 4 before creating the new one. `TOKEN_LIMIT_PER_USER` stays unset.
4. **Endpoint paths have no trailing slash** (`/api/v1/auth/login`), matching the spec §3.3 table literally. The web surface keeps its trailing-slash convention; the two never mix.
5. **`/me` also requires ≥1 active occupancy (403 otherwise).** Consistent with decision 2; a valid token whose user has since lost all occupancies (e.g. bulk `update()` that bypassed the revocation signal) gets 403, never data.
6. **`GET /fund/summary` uses the fixed 30-day trailing window** the resident web home already uses (`fund_period_flows(days=30)`). No period parameter until a client needs one (YAGNI).

## Global Constraints

Copied from the spec; every task implicitly includes these.

- P1 invariants unchanged: append-only financial records, integer VND, separation of duties, publication gates, no secrets in git, tenant isolation.
- Resident-only surface: staff get no API in Phase 0/1 (spec §3.1).
- Status codes: cross-tenant object access → **404** (existence not revealed); missing capability within the caller's own tenant → **403** (spec §2.3).
- Errors: RFC 9457 `application/problem+json` + stable machine `code` field; `detail` is developer English; no stack traces or internal identifiers in responses (spec §3.1).
- Pagination: DRF cursor pagination, default page size 20, cursor links only (spec §3.1).
- knox per-device tokens: TTL 30 days, sliding refresh on use, cap 5 per user with oldest evicted at login; logout deletes the calling token; logout-all deletes all; deactivation deletes server-side; no JWT, no OAuth, no resident MFA (spec §3.2).
- Login throttling reuses the existing `AuthThrottleBucket` (account|IP keyed) (spec §3.2).
- A client-supplied building ID is never trusted or accepted; unit and building always derive from the validated occupancy (spec §3.4).
- Review-time check: no payment-provider dependency may enter `pyproject.toml` (spec §5.3).
- Schema file committed; regenerate-and-fail-on-diff gate (spec §3.1, §5.4).
- The six e2e journeys (`tests/e2e/`) stay green (spec §5.4).

**Test environment (verified in Plans 1–2):**

```bash
docker compose up -d db
set -a; . ./.env.example; set +a
export SECRET_KEY=test-secret EVIDENCE_WRITE_SECRET=test-evidence \
       POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
# Run tests with: .venv/bin/python -m pytest <path> -q
# manage.py lives at the repo root.
```

## File Structure

```
pyproject.toml                                  # modify: +djangorestframework, +django-rest-knox, +drf-spectacular
src/lamto/config/settings.py                    # modify: INSTALLED_APPS, REST_FRAMEWORK, REST_KNOX, SPECTACULAR_SETTINGS
src/lamto/config/urls.py                        # modify: mount api/v1/
src/lamto/api/__init__.py                       # create: empty
src/lamto/api/apps.py                           # create: ApiConfig (ready() wires signals)
src/lamto/api/problems.py                       # create: problem+json handler + OccupancySelectionRequired
src/lamto/api/occupancy.py                      # create: resolve_api_occupancy (spec 3.4)
src/lamto/api/serializers.py                    # create: request/response serializers
src/lamto/api/views.py                          # create: auth, me, ledger, fund views
src/lamto/api/urls.py                           # create: app_name="api", the 7 routes
src/lamto/api/signals.py                        # create: token revocation on deactivation
src/lamto/api/tests/__init__.py                 # create: empty
src/lamto/api/tests/test_problems.py            # create: handler unit tests
src/lamto/api/tests/test_auth.py                # create: login/logout/lifecycle tests
src/lamto/api/tests/test_me.py                  # create: /me tests
src/lamto/api/tests/test_fund.py                # create: fund summary + occupancy-header tests
src/lamto/api/tests/test_ledger.py              # create: ledger list/detail tests
src/lamto/api/tests/test_openapi.py             # create: schema drift gate
src/lamto/finance/selectors.py                  # modify: +ledger_entry_proof
src/lamto/web/views/resident.py                 # modify: ledger_detail consumes ledger_entry_proof
docs/api/openapi-v1.yaml                        # create: generated, committed schema
tests/isolation/test_cross_building_access.py   # modify: API walk + completeness rule
```

---

### Task 1: API plumbing — dependencies, settings, app skeleton, problem+json handler

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/lamto/config/settings.py`
- Modify: `src/lamto/config/urls.py`
- Create: `src/lamto/api/__init__.py`, `src/lamto/api/apps.py`, `src/lamto/api/urls.py`, `src/lamto/api/problems.py`
- Create: `src/lamto/api/tests/__init__.py`
- Test: `src/lamto/api/tests/test_problems.py`

**Interfaces:**
- Consumes: nothing new (settings layout as-is).
- Produces: `lamto.api.problems.problem_exception_handler(exc, context)` (DRF exception handler), `lamto.api.problems.OccupancySelectionRequired` (APIException, 422, code `occupancy_selection_required`), `lamto.api.problems.PROBLEM_CONTENT_TYPE = "application/problem+json"`; URL namespace `api` mounted at `/api/v1/`; settings keys `REST_FRAMEWORK`, `REST_KNOX`, `SPECTACULAR_SETTINGS`. Later tasks append routes to `lamto/api/urls.py`'s `urlpatterns`.

- [ ] **Step 1: Add the three dependencies to `pyproject.toml`**

In the `[project] dependencies` list, after the line `"eth-account>=0.13,<1",` insert:

```toml
  "djangorestframework>=3.16,<4",
  "django-rest-knox>=5.0,<6",
  "drf-spectacular>=0.28,<1",
```

(No payment-provider dependency enters this file — spec §5.3 review-time check.)

- [ ] **Step 2: Install**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: `Successfully installed ... djangorestframework-3.16.x django-rest-knox-5.x.x drf-spectacular-0.28.x ...` (plus transitive PyYAML/uritemplate/jsonschema/inflection).

- [ ] **Step 3: Create the app skeleton**

Create `src/lamto/api/__init__.py` and `src/lamto/api/tests/__init__.py` (both empty).

Create `src/lamto/api/apps.py`:

```python
from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lamto.api"

    def ready(self):
        from lamto.api import signals  # noqa: F401  (token-revocation receivers)
```

Create `src/lamto/api/signals.py` as a placeholder module so `ready()` imports cleanly (Task 2 fills it):

```python
"""Server-side knox token revocation (spec 3.2). Receivers arrive with the auth task."""
```

Create `src/lamto/api/urls.py`:

```python
"""Resident API v1 (spec 3). Staff get no API in Phase 0/1."""

from django.urls import path

app_name = "api"

urlpatterns: list = []
```

(`path` is imported now because every later task uses it; the linter pass at the end of this task tolerates the unused import — if your linter does not, add routes first in Task 2 and drop the import here.)

- [ ] **Step 4: Wire settings**

In `src/lamto/config/settings.py`:

a) At the top, after `import os`, add:

```python
from datetime import timedelta
```

b) In `INSTALLED_APPS`, after `'lamto.notifications',` add:

```python
    'rest_framework',
    'knox',
    'drf_spectacular',
    'lamto.api',
```

c) At the end of the file (after the `PILOT_ALLOW_FIXTURES` block) append:

```python
# --- Resident API (spec 3): DRF + knox tokens + OpenAPI schema ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["knox.auth.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "lamto.api.problems.problem_exception_handler",
}

REST_KNOX = {
    "TOKEN_TTL": timedelta(days=30),  # spec 3.2: TTL 30 days
    "AUTO_REFRESH": True,  # spec 3.2: sliding refresh on use
}

SPECTACULAR_SETTINGS = {
    "TITLE": "LamTo Resident API",
    "VERSION": "v1",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}
```

- [ ] **Step 5: Mount the API in `src/lamto/config/urls.py`**

Replace the `urlpatterns` list with:

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        SecureLoginView.as_view(template_name="web/resident/login.html"),
        name="login",
    ),
    path(
        "accounts/logout/",
        secure_logout,
        name="logout",
    ),
    path("api/v1/", include("lamto.api.urls")),
    path("", include("lamto.web.urls")),
]
```

(Only the `path("api/v1/", ...)` line is new.)

- [ ] **Step 6: Write the failing handler tests**

Create `src/lamto/api/tests/test_problems.py`:

```python
"""problem+json exception handler unit tests (spec 3.1)."""

from django.http import Http404
from django.test import SimpleTestCase
from rest_framework import exceptions

from lamto.api.problems import (
    PROBLEM_CONTENT_TYPE,
    OccupancySelectionRequired,
    problem_exception_handler,
)


class ProblemHandlerTests(SimpleTestCase):
    def _handle(self, exc):
        return problem_exception_handler(exc, {"view": None, "request": None})

    def test_validation_error_carries_per_field_codes(self):
        response = self._handle(
            exceptions.ValidationError({"month": ["month requires a year."]})
        )
        assert response.status_code == 400
        assert response.content_type == PROBLEM_CONTENT_TYPE
        assert response.data["code"] == "validation_failed"
        assert response.data["status"] == 400
        assert response.data["type"] == "about:blank"
        assert response.data["title"]
        field_error = response.data["errors"]["month"][0]
        assert field_error["message"] == "month requires a year."
        assert field_error["code"] == "invalid"

    def test_http404_maps_to_not_found(self):
        response = self._handle(Http404("hidden"))
        assert response.status_code == 404
        assert response.data["code"] == "not_found"
        # Existence is not revealed and no internal identifiers leak.
        assert "hidden" not in str(response.data)

    def test_not_authenticated_code(self):
        response = self._handle(exceptions.NotAuthenticated())
        assert response.status_code == 401
        assert response.data["code"] == "not_authenticated"

    def test_permission_denied_code(self):
        response = self._handle(exceptions.PermissionDenied())
        assert response.status_code == 403
        assert response.data["code"] == "permission_denied"

    def test_throttled_code(self):
        response = self._handle(exceptions.Throttled())
        assert response.status_code == 429
        assert response.data["code"] == "throttled"

    def test_occupancy_selection_required_is_422(self):
        response = self._handle(OccupancySelectionRequired())
        assert response.status_code == 422
        assert response.data["code"] == "occupancy_selection_required"

    def test_unhandled_exception_returns_none(self):
        assert self._handle(RuntimeError("boom")) is None
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_problems.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lamto.api.problems'`

- [ ] **Step 8: Implement the handler**

Create `src/lamto/api/problems.py`:

```python
"""RFC 9457 problem+json errors with stable machine codes (spec 3.1).

`detail` is developer English; the Flutter client owns all Vietnamese
user-facing copy keyed off `code`. Never include stack traces or internal
identifiers in responses.
"""

from http import HTTPStatus

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler

PROBLEM_CONTENT_TYPE = "application/problem+json"


class OccupancySelectionRequired(exceptions.APIException):
    """Multiple active occupancies and no X-LamTo-Occupancy header (spec 3.4)."""

    status_code = 422
    default_detail = (
        "Multiple active occupancies; select one with the X-LamTo-Occupancy header."
    )
    default_code = "occupancy_selection_required"


# Most specific classes first: the first isinstance() match wins.
_EXCEPTION_CODES = (
    (OccupancySelectionRequired, "occupancy_selection_required"),
    (exceptions.NotAuthenticated, "not_authenticated"),
    (exceptions.AuthenticationFailed, "authentication_failed"),
    (exceptions.PermissionDenied, "permission_denied"),
    (exceptions.NotFound, "not_found"),
    (exceptions.MethodNotAllowed, "method_not_allowed"),
    (exceptions.Throttled, "throttled"),
    (exceptions.ParseError, "validation_failed"),
    (exceptions.UnsupportedMediaType, "validation_failed"),
    (exceptions.ValidationError, "validation_failed"),
    (Http404, "not_found"),
    (DjangoPermissionDenied, "permission_denied"),
)


def _field_errors(detail):
    """Preserve DRF's per-field error structure while exposing machine codes."""
    if isinstance(detail, dict):
        return {key: _field_errors(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_field_errors(item) for item in detail]
    return {"message": str(detail), "code": getattr(detail, "code", "invalid")}


def problem_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        # Not an API exception: let Django's standard 500 path handle it.
        return None
    code = next(
        (code for klass, code in _EXCEPTION_CODES if isinstance(exc, klass)), "error"
    )
    problem = {
        "type": "about:blank",
        "title": HTTPStatus(response.status_code).phrase,
        "status": response.status_code,
        "code": code,
    }
    if isinstance(exc, exceptions.ValidationError):
        problem["detail"] = "Request validation failed."
        problem["errors"] = _field_errors(exc.detail)
    elif isinstance(exc, exceptions.APIException):
        problem["detail"] = str(exc.detail)
    elif isinstance(exc, Http404):
        problem["detail"] = "Not found."
    else:  # django.core.exceptions.PermissionDenied
        problem["detail"] = "Permission denied."
    response.data = problem
    # DRF keeps an explicitly set content_type through finalize_response.
    response.content_type = PROBLEM_CONTENT_TYPE
    return response
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_problems.py -q`
Expected: `7 passed`

- [ ] **Step 10: Apply knox migrations and sanity-check the project**

Run (with the test environment sourced):

```bash
.venv/bin/python manage.py migrate knox
.venv/bin/python manage.py check
```

Expected: knox migrations apply (`Applying knox.0001_initial... OK` etc.); `System check identified no issues (0 silenced).`

- [ ] **Step 11: Confirm nothing else broke**

Run: `.venv/bin/python -m pytest src/lamto/config src/lamto/accounts -q`
Expected: all pass (settings import unchanged for existing consumers).

- [ ] **Step 12: Commit**

```bash
git add pyproject.toml src/lamto/config/settings.py src/lamto/config/urls.py src/lamto/api
git commit -m "feat: resident API plumbing — DRF, knox, problem+json errors"
```

---

### Task 2: Auth endpoints — login, logout, logout-all, token lifecycle

**Files:**
- Create: `src/lamto/api/serializers.py`, `src/lamto/api/views.py`
- Modify: `src/lamto/api/urls.py`, `src/lamto/api/signals.py`
- Test: `src/lamto/api/tests/test_auth.py`

**Interfaces:**
- Consumes: `lamto.accounts.security.assert_not_throttled(account, ip)` / `record_auth_failure(account, ip, kind="login")` / `reset_auth_throttle(account, ip)` / `client_ip(request)`; `lamto.accounts.tenancy.active_occupancies(user)`; `knox.models.AuthToken` (`AuthToken.objects.create(user=user) -> (instance, token_string)`; `instance.expiry`, `instance.created`); `lamto.api.problems` from Task 1. The `PhoneOrEmailBackend` already accepts phone or email as `username`.
- Produces: routes `api:auth-login`, `api:auth-logout`, `api:auth-logout-all`; `LoginSerializer` (fields `identifier`, `password`), `TokenResponseSerializer` (fields `token`, `expiry`); `lamto.api.views.TOKEN_CAP_PER_USER = 5`; signal receivers that delete a user's knox tokens on user deactivation or last-active-occupancy deactivation.

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/api/tests/test_auth.py`:

```python
"""Resident API auth lifecycle (spec 3.2)."""

import json
from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from knox.models import AuthToken

from lamto.accounts.models import AuthThrottleBucket, Building, ResidentOccupancy, Unit

PASSWORD = "resident-pass-123"


def problem(response):
    """Parse a problem+json body (Client.json() rejects the media type)."""
    return json.loads(response.content)


class ApiAuthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.resident = User.objects.create_user(
            email="api-resident@example.com",
            password=PASSWORD,
            display_name="API Resident",
            phone="0912345678",
        )
        building = Building.objects.create(name="API Auth Building")
        cls.unit = Unit.objects.create(building=building, label="A-101")
        cls.occupancy = ResidentOccupancy.objects.create(
            user=cls.resident, unit=cls.unit, active=True
        )
        cls.staff = User.objects.create_user(
            email="api-staff@example.com",
            password=PASSWORD,
            display_name="API Staff",
        )

    def _login(self, identifier, password=PASSWORD):
        return self.client.post(
            reverse("api:auth-login"),
            {"identifier": identifier, "password": password},
            content_type="application/json",
        )

    def _token(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return token

    def test_login_with_email_returns_token_and_30_day_expiry(self):
        response = self._login("api-resident@example.com")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["token"]
        expiry = datetime.fromisoformat(body["expiry"])
        remaining = expiry - timezone.now()
        assert 29 <= remaining.days <= 30
        assert AuthToken.objects.filter(user=self.resident).count() == 1

    def test_login_with_phone_in_any_accepted_form(self):
        for identifier in ("0912345678", "+84 912 345 678"):
            with self.subTest(identifier=identifier):
                response = self._login(identifier)
                assert response.status_code == 200, response.content

    def test_login_wrong_password_is_401_problem_and_recorded(self):
        response = self._login("api-resident@example.com", password="wrong")
        assert response.status_code == 401
        assert response["Content-Type"].startswith("application/problem+json")
        assert problem(response)["code"] == "authentication_failed"
        assert AuthThrottleBucket.objects.count() == 1

    def test_login_locked_after_max_failures(self):
        for _ in range(5):
            self._login("api-resident@example.com", password="wrong")
        response = self._login("api-resident@example.com")  # correct password
        assert response.status_code == 429
        assert problem(response)["code"] == "throttled"

    def test_login_missing_fields_is_validation_failed(self):
        response = self.client.post(
            reverse("api:auth-login"), {}, content_type="application/json"
        )
        assert response.status_code == 400
        body = problem(response)
        assert body["code"] == "validation_failed"
        assert "identifier" in body["errors"]
        assert "password" in body["errors"]

    def test_login_without_active_occupancy_is_403(self):
        response = self._login("api-staff@example.com")
        assert response.status_code == 403
        assert problem(response)["code"] == "permission_denied"
        assert not AuthToken.objects.filter(user=self.staff).exists()

    def test_inactive_user_cannot_login(self):
        self.resident.is_active = False
        self.resident.save()
        response = self._login("api-resident@example.com")
        assert response.status_code == 401

    def test_token_cap_evicts_oldest(self):
        for _ in range(5):
            assert self._login("api-resident@example.com").status_code == 200
        first_pk = (
            AuthToken.objects.filter(user=self.resident).order_by("created").first().pk
        )
        assert self._login("api-resident@example.com").status_code == 200
        remaining = AuthToken.objects.filter(user=self.resident)
        assert remaining.count() == 5
        assert not remaining.filter(pk=first_pk).exists()

    def test_logout_deletes_only_the_calling_token(self):
        token = self._login("api-resident@example.com").json()["token"]
        other = self._login("api-resident@example.com").json()["token"]
        response = self.client.post(
            reverse("api:auth-logout"),
            headers={"authorization": f"Token {token}"},
        )
        assert response.status_code == 204
        assert AuthToken.objects.filter(user=self.resident).count() == 1
        # The deleted token no longer authenticates.
        again = self.client.post(
            reverse("api:auth-logout"),
            headers={"authorization": f"Token {token}"},
        )
        assert again.status_code == 401
        assert problem(again)["code"] == "authentication_failed"
        # The surviving token still works.
        assert (
            self.client.post(
                reverse("api:auth-logout-all"),
                headers={"authorization": f"Token {other}"},
            ).status_code
            == 204
        )

    def test_logout_all_deletes_every_token(self):
        token = self._login("api-resident@example.com").json()["token"]
        self._login("api-resident@example.com")
        response = self.client.post(
            reverse("api:auth-logout-all"),
            headers={"authorization": f"Token {token}"},
        )
        assert response.status_code == 204
        assert AuthToken.objects.filter(user=self.resident).count() == 0

    def test_deactivating_user_deletes_tokens(self):
        self._token()
        self._token()
        self.resident.is_active = False
        self.resident.save()
        assert AuthToken.objects.filter(user=self.resident).count() == 0

    def test_deactivating_last_occupancy_deletes_tokens(self):
        self._token()
        self.occupancy.active = False
        self.occupancy.save()
        assert AuthToken.objects.filter(user=self.resident).count() == 0

    def test_deactivating_one_of_two_occupancies_keeps_tokens(self):
        second = ResidentOccupancy.objects.create(
            user=self.resident, unit=self.unit, active=True
        )
        self._token()
        second.active = False
        second.save()
        assert AuthToken.objects.filter(user=self.resident).count() == 1

    def test_token_of_inactive_user_is_rejected_regardless(self):
        token = self._token()
        # Bypass the signal deliberately (bulk update): auth must still reject.
        get_user_model().objects.filter(pk=self.resident.pk).update(is_active=False)
        response = self.client.post(
            reverse("api:auth-logout"),
            headers={"authorization": f"Token {token}"},
        )
        assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_auth.py -q`
Expected: FAIL — `NoReverseMatch: 'auth-login' not found` (and/or import errors).

- [ ] **Step 3: Implement serializers**

Create `src/lamto/api/serializers.py`:

```python
"""Resident API serializers (spec 3). Later tasks append to this module."""

from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="Email or Vietnamese phone number.")
    # trim_whitespace=False: passwords may legitimately contain spaces.
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class TokenResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    expiry = serializers.DateTimeField()
```

- [ ] **Step 4: Implement the views**

Create `src/lamto/api/views.py`:

```python
"""Resident API views (spec 3). Resident-only; staff stay on the /s/ web surface."""

from django.contrib.auth import authenticate
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from drf_spectacular.utils import extend_schema
from knox.models import AuthToken
from knox.views import LogoutAllView as KnoxLogoutAllView
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import exceptions, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from lamto.accounts.security import (
    assert_not_throttled,
    client_ip,
    record_auth_failure,
    reset_auth_throttle,
)
from lamto.accounts.tenancy import active_occupancies
from lamto.api.serializers import LoginSerializer, TokenResponseSerializer

TOKEN_CAP_PER_USER = 5  # spec 3.2: 5 concurrent tokens; oldest evicted at login


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=LoginSerializer, responses={200: TokenResponseSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        ip = client_ip(request)
        try:
            assert_not_throttled(identifier, ip)
        except DjangoPermissionDenied:
            raise exceptions.Throttled(
                detail="Too many authentication attempts. Try again later."
            )
        user = authenticate(
            request,
            username=identifier,
            password=serializer.validated_data["password"],
        )
        if user is None:
            record_auth_failure(identifier, ip, kind="login")
            raise exceptions.AuthenticationFailed("Invalid credentials.")
        if not active_occupancies(user).exists():
            # Resident-only surface (spec 3.1); staff keep the MFA'd web flows.
            raise exceptions.PermissionDenied(
                "An active resident occupancy is required."
            )
        reset_auth_throttle(identifier, ip)
        stale = list(AuthToken.objects.filter(user=user).order_by("-created"))[
            TOKEN_CAP_PER_USER - 1 :
        ]
        for old_token in stale:
            old_token.delete()
        instance, token = AuthToken.objects.create(user=user)
        return Response(
            TokenResponseSerializer({"token": token, "expiry": instance.expiry}).data
        )


class LogoutView(KnoxLogoutView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request, format=None):
        return super().post(request, format)


class LogoutAllView(KnoxLogoutAllView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request, format=None):
        return super().post(request, format)
```

- [ ] **Step 5: Implement the revocation signals**

Replace the content of `src/lamto/api/signals.py` with:

```python
"""Server-side knox token revocation (spec 3.2).

Deactivating a user, or their last active occupancy, deletes all their knox
tokens. `.save()` paths are covered here; bulk `queryset.update()` bypasses
signals, so authentication itself also rejects inactive users (knox checks
`is_active`) and every occupancy-scoped endpoint re-validates active
occupancies per request.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from knox.models import AuthToken

from lamto.accounts.models import ResidentOccupancy


@receiver(
    post_save,
    sender=settings.AUTH_USER_MODEL,
    dispatch_uid="api.revoke_tokens_inactive_user",
)
def revoke_tokens_for_inactive_user(sender, instance, **kwargs):
    if not instance.is_active:
        AuthToken.objects.filter(user=instance).delete()


@receiver(
    post_save,
    sender=ResidentOccupancy,
    dispatch_uid="api.revoke_tokens_last_occupancy",
)
def revoke_tokens_without_active_occupancy(sender, instance, **kwargs):
    if instance.active:
        return
    if not ResidentOccupancy.objects.filter(
        user_id=instance.user_id, active=True
    ).exists():
        AuthToken.objects.filter(user_id=instance.user_id).delete()
```

- [ ] **Step 6: Register the routes**

In `src/lamto/api/urls.py`, replace the `urlpatterns` assignment with:

```python
from lamto.api import views

urlpatterns = [
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/logout-all", views.LogoutAllView.as_view(), name="auth-logout-all"),
]
```

(The `from lamto.api import views` import goes below `from django.urls import path`.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_auth.py -q`
Expected: `14 passed`

- [ ] **Step 8: Commit**

```bash
git add src/lamto/api
git commit -m "feat: resident API auth with device-token lifecycle"
```

---

### Task 3: Occupancy header resolution + `GET /me`

**Files:**
- Create: `src/lamto/api/occupancy.py`
- Modify: `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Test: `src/lamto/api/tests/test_me.py`

**Interfaces:**
- Consumes: `lamto.accounts.tenancy.active_occupancies(user)` and `TenantContext.from_occupancy(occupancy)`; `lamto.api.problems.OccupancySelectionRequired`.
- Produces: `lamto.api.occupancy.resolve_api_occupancy(request) -> tuple[ResidentOccupancy, TenantContext]` and `lamto.api.occupancy.OCCUPANCY_HEADER = "X-LamTo-Occupancy"` (Task 5's views call this); route `api:me`; `MeSerializer` (fields `display_name`, `email`, `phone`, `occupancies[{id, unit_label, building_name}]`, `notification_preferences[{event_code, email_enabled}]`).

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/api/tests/test_me.py`:

```python
"""GET /me — profile, active occupancies, notification prefs (spec 3.3)."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from knox.models import AuthToken

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.notifications.models import NotificationPreference


class MeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.resident = User.objects.create_user(
            email="me-resident@example.com",
            password="resident-pass-123",
            display_name="Me Resident",
            phone="0987654321",
        )
        building_a = Building.objects.create(name="Building Alpha")
        building_b = Building.objects.create(name="Building Beta")
        cls.occupancy_a = ResidentOccupancy.objects.create(
            user=cls.resident,
            unit=Unit.objects.create(building=building_a, label="A-101"),
            active=True,
        )
        cls.occupancy_b = ResidentOccupancy.objects.create(
            user=cls.resident,
            unit=Unit.objects.create(building=building_b, label="B-202"),
            active=True,
        )
        NotificationPreference.objects.create(
            user=cls.resident, event_code="ledger.published", email_enabled=False
        )

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    def test_me_returns_profile_occupancies_and_prefs(self):
        response = self.client.get(reverse("api:me"), headers=self._auth())
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["display_name"] == "Me Resident"
        assert body["email"] == "me-resident@example.com"
        assert body["phone"] == "0987654321"
        occupancies = {o["id"]: o for o in body["occupancies"]}
        assert set(occupancies) == {self.occupancy_a.pk, self.occupancy_b.pk}
        assert occupancies[self.occupancy_a.pk]["unit_label"] == "A-101"
        assert occupancies[self.occupancy_a.pk]["building_name"] == "Building Alpha"
        assert body["notification_preferences"] == [
            {"event_code": "ledger.published", "email_enabled": False}
        ]

    def test_me_requires_token(self):
        response = self.client.get(reverse("api:me"))
        assert response.status_code == 401
        assert response["Content-Type"].startswith("application/problem+json")
        assert json.loads(response.content)["code"] == "not_authenticated"

    def test_me_without_active_occupancy_is_403(self):
        staff = get_user_model().objects.create_user(
            email="me-staff@example.com",
            password="resident-pass-123",
            display_name="Me Staff",
        )
        response = self.client.get(reverse("api:me"), headers=self._auth(staff))
        assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_me.py -q`
Expected: FAIL — `NoReverseMatch: 'me' not found`

- [ ] **Step 3: Implement occupancy resolution**

Create `src/lamto/api/occupancy.py`:

```python
"""X-LamTo-Occupancy resolution (spec 3.4).

The server validates the header against the caller's own active occupancies
and derives unit + building from the validated occupancy. A client-supplied
building ID is never trusted or accepted. Sole active occupancy -> auto-
selected when the header is absent. Multiple and no header -> 422. An ID that
is not the caller's active occupancy -> 404 (existence not revealed).
"""

from rest_framework import exceptions

from lamto.accounts.tenancy import TenantContext, active_occupancies
from lamto.api.problems import OccupancySelectionRequired

OCCUPANCY_HEADER = "X-LamTo-Occupancy"


def resolve_api_occupancy(request):
    """Return (occupancy, TenantContext) for the authenticated resident."""
    occupancies = list(active_occupancies(request.user))
    if not occupancies:
        raise exceptions.PermissionDenied("An active resident occupancy is required.")
    raw = request.headers.get(OCCUPANCY_HEADER)
    if raw is None:
        if len(occupancies) > 1:
            raise OccupancySelectionRequired()
        selected = occupancies[0]
    else:
        try:
            wanted = int(raw)
        except (TypeError, ValueError):
            raise exceptions.NotFound("Occupancy not found.")
        selected = next((o for o in occupancies if o.pk == wanted), None)
        if selected is None:
            raise exceptions.NotFound("Occupancy not found.")
    return selected, TenantContext.from_occupancy(selected)
```

- [ ] **Step 4: Append the serializers**

Append to `src/lamto/api/serializers.py`:

```python
class OccupancySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    unit_label = serializers.CharField()
    building_name = serializers.CharField()


class NotificationPreferenceSerializer(serializers.Serializer):
    event_code = serializers.CharField()
    email_enabled = serializers.BooleanField()


class MeSerializer(serializers.Serializer):
    display_name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField(allow_null=True)
    occupancies = OccupancySerializer(many=True)
    notification_preferences = NotificationPreferenceSerializer(many=True)
```

- [ ] **Step 5: Append the view**

Append to `src/lamto/api/views.py` (and extend the serializers import line to
`from lamto.api.serializers import LoginSerializer, MeSerializer, TokenResponseSerializer`):

```python
class MeView(APIView):
    @extend_schema(responses={200: MeSerializer})
    def get(self, request):
        occupancies = list(active_occupancies(request.user))
        if not occupancies:
            raise exceptions.PermissionDenied(
                "An active resident occupancy is required."
            )
        preferences = list(
            request.user.notification_preferences.order_by("event_code").values(
                "event_code", "email_enabled"
            )
        )
        data = {
            "display_name": request.user.display_name,
            "email": request.user.email,
            "phone": request.user.phone,
            "occupancies": [
                {
                    "id": occupancy.pk,
                    "unit_label": occupancy.unit.label,
                    "building_name": occupancy.unit.building.name,
                }
                for occupancy in occupancies
            ],
            "notification_preferences": preferences,
        }
        return Response(MeSerializer(data).data)
```

- [ ] **Step 6: Register the route**

In `src/lamto/api/urls.py`, append to `urlpatterns`:

```python
    path("me", views.MeView.as_view(), name="me"),
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_me.py src/lamto/api/tests/test_auth.py -q`
Expected: `17 passed`

- [ ] **Step 8: Commit**

```bash
git add src/lamto/api
git commit -m "feat: occupancy header resolution and /me endpoint"
```

---

### Task 4: Shared ledger proof selector (behavior-preserving refactor)

The web `ledger_detail` view assembles the proof data (payload, redacted docs, corrections, transaction IDs, evidence level) inline. The API must serve the same assembly, so it moves into `lamto.finance.selectors` — spec §3.1: both presentation layers call the shared selectors; no template view is rewritten to consume the API. Behavior guard: the existing web test suite.

**Files:**
- Modify: `src/lamto/finance/selectors.py`
- Modify: `src/lamto/web/views/resident.py`

**Interfaces:**
- Consumes: `lamto.evidence.models.evidence_level(status)`; `PublishedLedgerEntry` relations (`snapshot`, `proposal.current_version`, `payment.verification`, `payment.proof_redacted`, `work_order.acceptance`, `corrections`).
- Produces: `lamto.finance.selectors.ledger_entry_proof(entry) -> dict` with keys:
  - `payload: dict` — `snapshot.resident_payload` (or `{}`)
  - `proposed_amount: int | None`
  - `verification: PaymentVerification | None` (model instance)
  - `redacted_docs: list[dict]` — `{label, filename, sha256}`
  - `corrections: list[Correction]` — resident-visible model instances
  - `events: list[BlockchainOutboxEvent]` — snapshot, verification, payment events (non-None only)
  - `transaction_ids: list[str]` — non-empty hashes from `events`
  - `emergency: dict | None`
  - `evidence_level: str` — `EvidenceLevel` value for the snapshot's outbox event

- [ ] **Step 1: Add the selector**

In `src/lamto/finance/selectors.py`, change the evidence import line from
`from lamto.evidence.models import SETTLED_STATUSES` to
`from lamto.evidence.models import SETTLED_STATUSES, evidence_level`, then append:

```python
def ledger_entry_proof(entry):
    """Detail assembly for one published entry, shared by the resident web
    template and the API (spec 3.1: one query path, one set of gates).
    """
    payload = entry.snapshot.resident_payload or {}
    version = entry.proposal.current_version
    verification = getattr(entry.payment, "verification", None)
    redacted_docs = []
    acceptance = getattr(entry.work_order, "acceptance", None)
    if acceptance is not None:
        for label, version_obj in (
            ("Invoice (redacted)", acceptance.invoice_redacted),
            ("Acceptance report (redacted)", acceptance.acceptance_redacted),
        ):
            if version_obj is not None:
                redacted_docs.append(
                    {
                        "label": label,
                        "filename": version_obj.filename,
                        "sha256": version_obj.sha256,
                    }
                )
    proof_redacted = entry.payment.proof_redacted
    if proof_redacted is not None:
        redacted_docs.append(
            {
                "label": "Payment proof (redacted)",
                "filename": proof_redacted.filename,
                "sha256": proof_redacted.sha256,
            }
        )
    events = [
        event
        for event in (
            entry.snapshot.outbox_event,
            getattr(verification, "outbox_event", None) if verification else None,
            entry.payment.outbox_event,
        )
        if event is not None
    ]
    return {
        "payload": payload,
        "proposed_amount": (
            version.amount_vnd
            if version is not None
            else payload.get("proposed_amount_vnd")
        ),
        "verification": verification,
        "redacted_docs": redacted_docs,
        "corrections": [
            correction
            for correction in entry.corrections.all()
            if correction.is_resident_visible
        ],
        "events": events,
        "transaction_ids": [
            event.transaction_hash for event in events if event.transaction_hash
        ],
        "emergency": payload.get("emergency"),
        "evidence_level": evidence_level(entry.snapshot.outbox_event.status),
    }
```

- [ ] **Step 2: Consume it in the web view**

In `src/lamto/web/views/resident.py`:

a) Change the imports: the evidence import line becomes
`from lamto.evidence.models import EvidenceLevel` (drop `evidence_level` — now used via the selector), and the selectors import gains `ledger_entry_proof`:

```python
from lamto.finance.selectors import (
    fund_period_flows,
    ledger_entry_proof,
    published_ledger_entries,
    verified_fund_entries,
)
```

b) Replace the body of `ledger_detail` (keep the decorators and signature) with:

```python
@login_required
@require_GET
def ledger_detail(request, pk):
    occupancy, _occupancies = resolve_resident_occupancy(request)
    tenant = TenantContext.from_occupancy(occupancy)
    entry = (
        published_ledger_entries(tenant.building_id)
        .filter(pk=pk)
        .first()
    )
    if entry is None:
        raise Http404("Published ledger entry not found.")
    detail = ledger_entry_proof(entry)
    payload = detail["payload"]
    integrity = _integrity_display(entry)
    anchoring = _evidence_level_display(detail["evidence_level"])
    return render(
        request,
        "web/resident/ledger_detail.html",
        {
            "entry": entry,
            "payload": payload,
            "proposed_amount": detail["proposed_amount"],
            "approvals": payload.get("approvals") or {},
            "verification": detail["verification"],
            "redacted_docs": detail["redacted_docs"],
            "corrections": detail["corrections"],
            "transaction_ids": detail["transaction_ids"],
            "emergency": detail["emergency"],
            "integrity_label": integrity["label"],
            "integrity_class": integrity["css_class"],
            "integrity_icon": integrity["icon"],
            "integrity_alert": integrity["alert"],
            "integrity_status": entry.effective_integrity_status,
            "evidence_level": detail["evidence_level"],
            "anchoring_label": anchoring["label"],
            "anchoring_class": anchoring["css_class"],
            "anchoring_icon": anchoring["icon"],
            "occupancy": occupancy,
            "nav_active": "ledger",
        },
    )
```

Every context key and value is identical to the previous inline version — this is a pure extraction.

- [ ] **Step 3: Run the behavior guards**

Run: `.venv/bin/python -m pytest src/lamto/web src/lamto/finance tests/isolation -q`
Expected: all pass (identical counts to before this task — no behavior change). If anything fails, the extraction changed behavior: stop and fix the selector, not the tests.

- [ ] **Step 4: Commit**

```bash
git add src/lamto/finance/selectors.py src/lamto/web/views/resident.py
git commit -m "refactor: shared ledger proof selector for web and API"
```

---

### Task 5: Read-only ledger + fund summary endpoints

**Files:**
- Modify: `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Test: `src/lamto/api/tests/test_fund.py`, `src/lamto/api/tests/test_ledger.py`

**Interfaces:**
- Consumes: `resolve_api_occupancy` (Task 3), `ledger_entry_proof` (Task 4), `published_ledger_entries(building_id)`, `fund_period_flows(building_id)` (`lamto.finance.selectors`), `fund_balance(building_id, verified_only=True)` (`lamto.finance.fund`), `evidence_level(status)` (`lamto.evidence.models`).
- Produces: routes `api:ledger-list` (`GET /api/v1/ledger`), `api:ledger-detail` (`GET /api/v1/ledger/<int:pk>`), `api:fund-summary` (`GET /api/v1/fund/summary`); serializers `LedgerEntryListSerializer`, `LedgerEntryDetailSerializer`, `FundSummarySerializer`, `LedgerFilterSerializer`; `LedgerCursorPagination` (page size 20, ordering `("-published_at", "-pk")`).

- [ ] **Step 1: Write the failing fund tests**

Create `src/lamto/api/tests/test_fund.py`:

```python
"""GET /fund/summary + X-LamTo-Occupancy context rules (spec 3.3, 3.4)."""

import json
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.finance.fund import fund_balance
from lamto.testing.factories import seed_pilot_world

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-api-fund-")


def problem(response):
    return json.loads(response.content)


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class FundSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="API Fund Building",
            email_prefix="apif",
            create_sample_report=False,
        )
        cls.resident = cls.seed.users["resident"]
        cls.occupancy = ResidentOccupancy.objects.get(user=cls.resident, active=True)
        # A second building with no fund rows, for multi-occupancy cases.
        cls.other_building = Building.objects.create(name="API Fund Building Two")
        cls.other_unit = Unit.objects.create(building=cls.other_building, label="C-303")
        # A stranger whose occupancy id must never resolve for cls.resident.
        stranger = get_user_model().objects.create_user(
            email="apif-stranger@example.com",
            password="resident-pass-123",
            display_name="Stranger",
        )
        cls.stranger_occupancy = ResidentOccupancy.objects.create(
            user=stranger, unit=cls.other_unit, active=True
        )

    def _auth(self):
        _instance, token = AuthToken.objects.create(user=self.resident)
        return {"authorization": f"Token {token}"}

    def test_sole_occupancy_auto_selected(self):
        response = self.client.get(reverse("api:fund-summary"), headers=self._auth())
        assert response.status_code == 200, response.content
        body = response.json()
        expected = fund_balance(self.seed.building.pk, verified_only=True)
        assert expected > 0
        assert body["balance_vnd"] == expected
        assert body["period_days"] == 30
        assert body["period_inflows_vnd"] >= 0
        assert body["period_outflows_vnd"] >= 0

    def test_multiple_occupancies_without_header_is_422(self):
        second = ResidentOccupancy.objects.create(
            user=self.resident, unit=self.other_unit, active=True
        )
        response = self.client.get(reverse("api:fund-summary"), headers=self._auth())
        assert response.status_code == 422
        assert problem(response)["code"] == "occupancy_selection_required"
        # With the header, each occupancy resolves to its own building.
        chosen = self.client.get(
            reverse("api:fund-summary"),
            headers={**self._auth(), "x-lamto-occupancy": str(second.pk)},
        )
        assert chosen.status_code == 200
        assert chosen.json()["balance_vnd"] == 0  # second building has no fund rows

    def test_foreign_occupancy_header_is_404(self):
        response = self.client.get(
            reverse("api:fund-summary"),
            headers={**self._auth(), "x-lamto-occupancy": str(self.stranger_occupancy.pk)},
        )
        assert response.status_code == 404
        assert problem(response)["code"] == "not_found"

    def test_garbage_occupancy_header_is_404(self):
        response = self.client.get(
            reverse("api:fund-summary"),
            headers={**self._auth(), "x-lamto-occupancy": "abc"},
        )
        assert response.status_code == 404

    def test_inactive_own_occupancy_header_is_404(self):
        extra = ResidentOccupancy.objects.create(
            user=self.resident, unit=self.other_unit, active=True
        )
        ResidentOccupancy.objects.filter(pk=extra.pk).update(active=False)
        response = self.client.get(
            reverse("api:fund-summary"),
            headers={**self._auth(), "x-lamto-occupancy": str(extra.pk)},
        )
        assert response.status_code == 404
```

- [ ] **Step 2: Write the failing ledger tests**

Create `src/lamto/api/tests/test_ledger.py`. The publication choreography is copied from the proven recipe in `tests/isolation/test_cross_building_access.py`:

```python
"""GET /ledger and /ledger/{id} — published entries with proof (spec 3.3)."""

import json
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.evidence.models import BlockchainOutboxEvent, EvidenceLevel
from lamto.finance.models import PublishedLedgerEntry
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-api-ledger-")


def problem(response):
    return json.loads(response.content)


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class LedgerApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="API Ledger Building",
            email_prefix="apil",
            create_sample_report=False,
        )
        driver = PilotDomainDriver(cls.seed)
        driver.login(None, "resident").submit_report("Lobby lamp flickers", "Lift 2")
        driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        driver.login(None, "operator").submit_signed_proposal()
        driver.login(None, "board_approver").approve_proposal()
        driver.login(None, "resident_representative").coapprove_proposal()
        driver.login(None, "maintenance").complete_assigned_work()
        driver.login(None, "board_payment_recorder").accept_and_record_payment()
        driver.login(None, "board_payment_verifier").verify_payment()
        driver.confirm_all_chain_events()
        driver.login(None, "eligible_publisher").sign_publication_snapshot()
        driver.confirm_all_chain_events()
        cls.entry = PublishedLedgerEntry.objects.get(
            case__building=cls.seed.building
        )

    def _auth(self):
        _instance, token = AuthToken.objects.create(
            user=self.seed.users["resident"]
        )
        return {"authorization": f"Token {token}"}

    def test_list_returns_published_entry_with_cursor_shape(self):
        response = self.client.get(reverse("api:ledger-list"), headers=self._auth())
        assert response.status_code == 200, response.content
        body = response.json()
        assert set(body) == {"next", "previous", "results"}
        assert len(body["results"]) == 1
        row = body["results"][0]
        assert row["id"] == self.entry.pk
        assert row["contractor_name"] == self.entry.contractor_name
        assert row["actual_cost_vnd"] == self.entry.actual_cost_vnd
        assert row["published_at"]
        assert row["evidence_level"] == EvidenceLevel.CHAIN_CONFIRMED
        assert row["integrity_status"] == self.entry.effective_integrity_status

    def test_list_period_filters(self):
        year = self.entry.published_at.year
        auth = self._auth()
        hit = self.client.get(
            reverse("api:ledger-list"),
            {"year": year, "month": self.entry.published_at.month},
            headers=auth,
        )
        assert len(hit.json()["results"]) == 1
        miss = self.client.get(
            reverse("api:ledger-list"), {"year": year - 1}, headers=auth
        )
        assert miss.json()["results"] == []

    def test_month_without_year_is_validation_failed(self):
        response = self.client.get(
            reverse("api:ledger-list"), {"month": 5}, headers=self._auth()
        )
        assert response.status_code == 400
        body = problem(response)
        assert body["code"] == "validation_failed"
        assert "month" in body["errors"]

    def test_detail_returns_payload_and_proof(self):
        response = self.client.get(
            reverse("api:ledger-detail", args=[self.entry.pk]), headers=self._auth()
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["id"] == self.entry.pk
        assert body["contractor_name"] == self.entry.contractor_name
        assert body["actual_cost_vnd"] == self.entry.actual_cost_vnd
        assert body["proposed_amount_vnd"] is not None
        assert "report_id" in body["payload"]
        assert body["verification"]["decision"] == "VERIFIED"
        assert body["verification"]["verified_by"]
        assert body["redacted_documents"], "redacted document hashes must be exposed"
        for doc in body["redacted_documents"]:
            assert set(doc) == {"label", "filename", "sha256"}
            assert len(doc["sha256"]) == 64
        assert body["corrections"] == []
        proof = body["proof"]
        assert proof["evidence_level"] == EvidenceLevel.CHAIN_CONFIRMED
        assert proof["anchoring_backend"] == "besu"
        assert proof["payload_hash"] == self.entry.snapshot.resident_payload_hash
        assert proof["events"], "outbox events must be listed in the proof"
        for event in proof["events"]:
            assert event["event_id"].startswith("0x")
            assert event["status"] == BlockchainOutboxEvent.Status.CONFIRMED
            assert event["evidence_level"] == EvidenceLevel.CHAIN_CONFIRMED

    def test_detail_unknown_pk_is_404_problem(self):
        response = self.client.get(
            reverse("api:ledger-detail", args=[999999]), headers=self._auth()
        )
        assert response.status_code == 404
        assert problem(response)["code"] == "not_found"

    def test_unsettled_entry_is_invisible(self):
        BlockchainOutboxEvent.objects.filter(
            pk=self.entry.snapshot.outbox_event_id
        ).update(status=BlockchainOutboxEvent.Status.PENDING)
        auth = self._auth()
        assert (
            self.client.get(reverse("api:ledger-list"), headers=auth).json()["results"]
            == []
        )
        assert (
            self.client.get(
                reverse("api:ledger-detail", args=[self.entry.pk]), headers=auth
            ).status_code
            == 404
        )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_fund.py src/lamto/api/tests/test_ledger.py -q`
Expected: FAIL — `NoReverseMatch: 'fund-summary' not found` / `'ledger-list' not found`

- [ ] **Step 4: Append the serializers**

Append to `src/lamto/api/serializers.py`:

```python
class LedgerFilterSerializer(serializers.Serializer):
    year = serializers.IntegerField(required=False, min_value=2000, max_value=2100)
    month = serializers.IntegerField(required=False, min_value=1, max_value=12)

    def validate(self, data):
        if "month" in data and "year" not in data:
            raise serializers.ValidationError({"month": "month requires a year."})
        return data


class LedgerEntryListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    contractor_name = serializers.CharField()
    actual_cost_vnd = serializers.IntegerField()
    published_at = serializers.DateTimeField()
    integrity_status = serializers.CharField(source="effective_integrity_status")
    evidence_level = serializers.SerializerMethodField()

    def get_evidence_level(self, entry) -> str:
        from lamto.evidence.models import evidence_level

        return evidence_level(entry.snapshot.outbox_event.status)


class VerificationSerializer(serializers.Serializer):
    decision = serializers.CharField()
    verified_by = serializers.CharField()
    verified_at = serializers.DateTimeField()


class RedactedDocumentSerializer(serializers.Serializer):
    label = serializers.CharField()
    filename = serializers.CharField()
    sha256 = serializers.CharField()


class CorrectionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    reason = serializers.CharField()


class ProofEventSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    event_type = serializers.IntegerField()
    status = serializers.CharField()
    evidence_level = serializers.CharField()
    transaction_hash = serializers.CharField(allow_blank=True)


class ProofSerializer(serializers.Serializer):
    evidence_level = serializers.CharField()
    anchoring_backend = serializers.CharField(allow_blank=True)
    payload_hash = serializers.CharField()
    events = ProofEventSerializer(many=True)


class LedgerEntryDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    contractor_name = serializers.CharField()
    actual_cost_vnd = serializers.IntegerField()
    published_at = serializers.DateTimeField()
    proposed_amount_vnd = serializers.IntegerField(allow_null=True)
    integrity_status = serializers.CharField()
    payload = serializers.JSONField()
    verification = VerificationSerializer(allow_null=True)
    redacted_documents = RedactedDocumentSerializer(many=True)
    corrections = CorrectionSerializer(many=True)
    proof = ProofSerializer()


class FundSummarySerializer(serializers.Serializer):
    balance_vnd = serializers.IntegerField()
    period_days = serializers.IntegerField()
    period_inflows_vnd = serializers.IntegerField()
    period_outflows_vnd = serializers.IntegerField()
```

- [ ] **Step 5: Append the views**

In `src/lamto/api/views.py`:

a) Extend the imports:

```python
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import exceptions, generics, pagination, permissions

from lamto.api.occupancy import resolve_api_occupancy
from lamto.api.serializers import (
    FundSummarySerializer,
    LedgerEntryDetailSerializer,
    LedgerEntryListSerializer,
    LedgerFilterSerializer,
    LoginSerializer,
    MeSerializer,
    TokenResponseSerializer,
)
from lamto.evidence.models import evidence_level
from lamto.finance.fund import fund_balance
from lamto.finance.selectors import (
    fund_period_flows,
    ledger_entry_proof,
    published_ledger_entries,
)
```

(These replace the narrower import lines from Tasks 2–3; keep the accounts imports as-is.)

b) Append the views:

```python
class LedgerCursorPagination(pagination.CursorPagination):
    page_size = 20  # spec 3.1
    ordering = ("-published_at", "-pk")


@extend_schema_view(
    get=extend_schema(parameters=[LedgerFilterSerializer]),
)
class LedgerListView(generics.ListAPIView):
    serializer_class = LedgerEntryListSerializer
    pagination_class = LedgerCursorPagination

    def get_queryset(self):
        filters = LedgerFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        _occupancy, tenant = resolve_api_occupancy(self.request)
        entries = published_ledger_entries(tenant.building_id)
        year = filters.validated_data.get("year")
        month = filters.validated_data.get("month")
        if year is not None:
            entries = entries.filter(published_at__year=year)
        if month is not None:
            entries = entries.filter(published_at__month=month)
        return entries


class LedgerDetailView(APIView):
    @extend_schema(responses={200: LedgerEntryDetailSerializer})
    def get(self, request, pk):
        _occupancy, tenant = resolve_api_occupancy(request)
        entry = published_ledger_entries(tenant.building_id).filter(pk=pk).first()
        if entry is None:
            raise exceptions.NotFound("Published ledger entry not found.")
        detail = ledger_entry_proof(entry)
        verification = detail["verification"]
        data = {
            "id": entry.pk,
            "contractor_name": entry.contractor_name,
            "actual_cost_vnd": entry.actual_cost_vnd,
            "published_at": entry.published_at,
            "proposed_amount_vnd": detail["proposed_amount"],
            "integrity_status": entry.effective_integrity_status,
            "payload": detail["payload"],
            "verification": (
                {
                    "decision": verification.decision,
                    "verified_by": verification.membership.user.display_name,
                    "verified_at": verification.verified_at,
                }
                if verification is not None
                else None
            ),
            "redacted_documents": detail["redacted_docs"],
            "corrections": [
                {
                    "id": correction.pk,
                    "status": correction.status,
                    "reason": correction.reason,
                }
                for correction in detail["corrections"]
            ],
            "proof": {
                "evidence_level": detail["evidence_level"],
                "anchoring_backend": entry.snapshot.anchoring_backend,
                "payload_hash": entry.snapshot.resident_payload_hash,
                "events": [
                    {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "status": event.status,
                        "evidence_level": evidence_level(event.status),
                        "transaction_hash": event.transaction_hash,
                    }
                    for event in detail["events"]
                ],
            },
        }
        return Response(LedgerEntryDetailSerializer(data).data)


class FundSummaryView(APIView):
    @extend_schema(responses={200: FundSummarySerializer})
    def get(self, request):
        _occupancy, tenant = resolve_api_occupancy(request)
        inflows, outflows = fund_period_flows(tenant.building_id)
        data = {
            "balance_vnd": fund_balance(tenant.building_id, verified_only=True),
            "period_days": 30,
            "period_inflows_vnd": inflows,
            "period_outflows_vnd": outflows,
        }
        return Response(FundSummarySerializer(data).data)
```

- [ ] **Step 6: Register the routes**

In `src/lamto/api/urls.py`, append to `urlpatterns`:

```python
    path("ledger", views.LedgerListView.as_view(), name="ledger-list"),
    path("ledger/<int:pk>", views.LedgerDetailView.as_view(), name="ledger-detail"),
    path("fund/summary", views.FundSummaryView.as_view(), name="fund-summary"),
]
```

(Replace the closing bracket — final `urlpatterns` has all 7 routes.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/api -q`
Expected: all pass (problems 7 + auth 14 + me 3 + fund 5 + ledger 6 = `35 passed`).

- [ ] **Step 8: Commit**

```bash
git add src/lamto/api
git commit -m "feat: read-only ledger and fund summary API"
```

---

### Task 6: Committed OpenAPI schema + drift gate

**Files:**
- Create: `docs/api/openapi-v1.yaml` (generated)
- Test: `src/lamto/api/tests/test_openapi.py`

**Interfaces:**
- Consumes: all routes/serializers from Tasks 1–5; `SPECTACULAR_SETTINGS` from Task 1. drf-spectacular ≥0.27.2 ships the knox auth extension, so `knox.auth.TokenAuthentication` produces a security scheme without custom code.
- Produces: the committed schema file; regeneration command documented in the test's failure message.

- [ ] **Step 1: Write the failing drift test**

Create `src/lamto/api/tests/test_openapi.py`:

```python
"""OpenAPI drift gate (spec 3.1, 5.4): regenerate and fail on any diff."""

import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase

SCHEMA_PATH = (
    Path(settings.BASE_DIR).parent.parent / "docs" / "api" / "openapi-v1.yaml"
)
REGENERATE = "python manage.py spectacular --file docs/api/openapi-v1.yaml"


class OpenApiDriftTests(SimpleTestCase):
    def test_committed_schema_matches_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_path = Path(tmp) / "openapi-v1.yaml"
            call_command(
                "spectacular",
                "--file",
                str(generated_path),
                "--validate",
                "--fail-on-warn",
            )
            generated = generated_path.read_text()
        assert SCHEMA_PATH.exists(), f"schema file missing; run: {REGENERATE}"
        assert generated == SCHEMA_PATH.read_text(), (
            f"docs/api/openapi-v1.yaml is stale; regenerate with: {REGENERATE}"
        )

    def test_schema_covers_every_api_route(self):
        content = SCHEMA_PATH.read_text()
        for route in (
            "/api/v1/auth/login",
            "/api/v1/auth/logout",
            "/api/v1/auth/logout-all",
            "/api/v1/me",
            "/api/v1/ledger",
            "/api/v1/fund/summary",
        ):
            assert route in content, f"{route} missing from committed schema"
        # spectacular names the <int:pk> parameter {id} when it can infer a
        # model, {pk} otherwise; either spelling proves the route is present.
        assert (
            "/api/v1/ledger/{id}" in content or "/api/v1/ledger/{pk}" in content
        ), "ledger detail route missing from committed schema"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py -q`
Expected: FAIL — `schema file missing; run: python manage.py spectacular ...`
If instead the `call_command` itself fails with warnings (`--fail-on-warn`), that is a real finding: an endpoint is missing its `@extend_schema` annotation — fix the view, do not drop the flag.

- [ ] **Step 3: Generate and commit the schema**

Run (with the test environment sourced):

```bash
mkdir -p docs/api
.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn
```

Expected: the command exits 0 and writes `docs/api/openapi-v1.yaml`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add docs/api/openapi-v1.yaml src/lamto/api/tests/test_openapi.py
git commit -m "feat: committed OpenAPI schema with drift gate"
```

---

### Task 7: Adversarial isolation walk over API routes + full-suite gate

Spec §2.3 layer 4: the two-building suite walks every registered URL (web **and** API); new endpoints are added to the walk automatically via the URL registry (the completeness test).

**Files:**
- Modify: `tests/isolation/test_cross_building_access.py`

**Interfaces:**
- Consumes: everything shipped in Tasks 1–6; existing `seed_a`/`seed_b`/`cls.b` fixtures in the isolation suite; `knox.models.AuthToken`.
- Produces: `API_RESIDENT_CASES` classification map; the completeness rule extended over `lamto.api.urls`.

- [ ] **Step 1: Extend the classification tables**

In `tests/isolation/test_cross_building_access.py`, after the `RESIDENT_CASES` dict, add:

```python
# API routes (spec 2.3 layer 4 covers web and API identically).
API_RESIDENT_CASES = {
    "api:ledger-detail": ("ledger_pk", "GET", 404),
}

API_LIST_ROUTES = ["api:ledger-list", "api:fund-summary"]
```

- [ ] **Step 2: Extend the completeness rule**

Replace the body of `test_every_pk_route_is_classified` with:

```python
    def test_every_pk_route_is_classified(self):
        from lamto.api import urls as api_urls
        from lamto.web import urls as web_urls

        pk_routes = {
            f"web:{pattern.name}"
            for pattern in web_urls.urlpatterns
            if "<int:" in str(pattern.pattern)
        } | {
            f"api:{pattern.name}"
            for pattern in api_urls.urlpatterns
            if "<int:" in str(pattern.pattern)
        }
        classified = (
            set(STAFF_CASES)
            | set(RESIDENT_CASES)
            | set(API_RESIDENT_CASES)
            | set(EXEMPT)
        )
        missing = pk_routes - classified
        assert not missing, (
            f"New pk routes must be classified in the isolation suite: {missing}"
        )
```

- [ ] **Step 3: Add the API walk tests**

Add these methods to `CrossBuildingAccessTests` (after `test_resident_cannot_reach_other_building_objects`):

```python
    def _api_auth(self, user):
        from knox.models import AuthToken

        _instance, token = AuthToken.objects.create(user=user)
        return {"authorization": f"Token {token}"}

    def test_api_resident_cannot_reach_other_building_objects(self):
        auth = self._api_auth(self.seed_a.users["resident"])
        for route, (pk_attr, method, expected) in API_RESIDENT_CASES.items():
            with self.subTest(route=route):
                url = reverse(route, args=[self.b[pk_attr]])
                assert method == "GET"
                response = self.client.get(url, headers=auth)
                # Design §2.3: cross-tenant object access is 404, never data.
                assert response.status_code == expected, (route, response.status_code)
                assert B_LEAK_MARKER.encode() not in response.content

    def test_api_rejects_foreign_occupancy_header(self):
        from lamto.accounts.models import ResidentOccupancy

        auth = self._api_auth(self.seed_a.users["resident"])
        b_occupancy = ResidentOccupancy.objects.get(
            user=self.seed_b.users["resident"], active=True
        )
        for route in API_LIST_ROUTES:
            with self.subTest(route=route):
                response = self.client.get(
                    reverse(route),
                    headers={**auth, "x-lamto-occupancy": str(b_occupancy.pk)},
                )
                assert response.status_code == 404, (route, response.status_code)
                assert B_LEAK_MARKER.encode() not in response.content

    def test_api_lists_never_leak_other_building(self):
        auth = self._api_auth(self.seed_a.users["resident"])
        response = self.client.get(reverse("api:ledger-list"), headers=auth)
        assert response.status_code == 200
        listed_ids = [row["id"] for row in response.json()["results"]]
        assert self.b["ledger_pk"] not in listed_ids
        assert B_LEAK_MARKER.encode() not in response.content
        assert B_BUILDING_NAME.encode() not in response.content
```

- [ ] **Step 4: Run the isolation suite**

Run: `.venv/bin/python -m pytest tests/isolation -q`
Expected: all pass (previous count + 3 new tests).

- [ ] **Step 5: Run the full suite (P1 regression gate, spec §5.4)**

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: everything passes, including the six e2e journeys and the disabled-mode journey. This is the plan's exit gate — investigate any failure before committing.

- [ ] **Step 6: Commit**

```bash
git add tests/isolation/test_cross_building_access.py
git commit -m "test: adversarial isolation walk covers API routes"
```

---

## Spec coverage map

| Spec requirement | Where |
|---|---|
| §3.1 DRF at `/api/v1/`, URL-path versioning | Task 1 (mount), Task 2–5 (routes) |
| §3.1 resident-only surface | Design decisions 2 & 5; Task 2 login gate; Task 3 `/me` gate |
| §3.1 both layers call shared selectors | Task 4 extraction; Task 5 views consume selectors only |
| §3.1 problem+json + stable `code` (incl. `occupancy_selection_required`, `validation_failed` per-field) | Task 1 handler + tests; wire-level assertions in Tasks 2/3/5 |
| §3.1 cursor pagination, page 20, cursor links only | Task 5 `LedgerCursorPagination` + list-shape test |
| §3.1 committed OpenAPI schema, CI regenerate-and-diff | Task 6 |
| §3.2 knox login (phone or email), TTL 30d sliding | Task 1 `REST_KNOX`; Task 2 login + expiry test |
| §3.2 logout / logout-all | Task 2 |
| §3.2 deactivation deletes tokens; inactive auth rejected | Task 2 signals + tests (incl. bulk-update bypass test) |
| §3.2 device cap 5, oldest evicted | Task 2 (design decision 3) |
| §3.2 login throttling via `AuthThrottleBucket` | Task 2 (`assert_not_throttled`/`record_auth_failure`/`reset_auth_throttle`) |
| §3.3 `/auth/*`, `/me`, `/ledger`, `/ledger/{id}`, `/fund/summary` (Phase 0 slice) | Tasks 2, 3, 5 |
| §3.3 ledger detail: plain-language payload + proof (evidence level, hashes, event IDs, chain status) | Task 5 detail serializer + test |
| §3.4 occupancy header rules (auto-select / 422 / 404, building never client-supplied) | Task 3 `resolve_api_occupancy`; Task 5 fund tests; Task 7 foreign-header walk |
| §2.3 layer 4: adversarial walk covers API; completeness via URL registry | Task 7 |
| §2.3 status-code convention 404/403 | Task 3/5 tests, Task 7 walk |
| §5.1 evidence levels in API responses, no `verified` boolean | Task 5 serializers carry the enum verbatim |
| §5.3 no payment-provider dependency | Task 1 Step 1 note |
| §5.4 six e2e journeys stay green; OpenAPI drift gate permanent | Task 7 Step 5; Task 6 test module |

## Out of scope (deferred per spec)

- **Phase 1 API slice:** `POST /reports` (+ `client_ref` idempotency, 409 `client_ref_conflict`), `/reports/*`, `/locations`, `/devices`, `/notifications`, ratings, photo upload/download paths (spec §3.3, §3.5, §3.6).
- **Staff API** — explicitly never in Phase 0/1.
- **Vietnamese copy** — the client owns user-facing copy keyed off `code`; API `detail` stays developer English.
- **Dart client generation** — happens in the Flutter app repo's CI against the committed schema.
- **problem+json for non-DRF 500s** — Django's default 500 path is unchanged; the client's generic error path covers it.
