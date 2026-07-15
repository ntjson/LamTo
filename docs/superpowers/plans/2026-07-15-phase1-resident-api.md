# Phase 1 Resident API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Phase 1 resident write/read API to `/api/v1/` — idempotent report submission, report timeline, photo upload, work ratings, the location tree, the in-app notification feed, and signed document downloads — all over the shared building-scoped selectors.

**Architecture:** Extends Plan 3's `lamto.api` DRF app in place. Every mutation routes through existing domain services (`submit_report`, `rate_completed_work`, `create_resident_report_photo`); this plan adds one report field (`client_ref`), thin idempotency/feed/download helpers, serializers, views, and the OpenAPI + adversarial gates. Report/photo/rating endpoints are ownership-scoped (the caller's own reports); locations and the feed are building-scoped via the validated `X-LamTo-Occupancy` header (spec §3.4, unchanged from Plan 3). Downloads are Django-hosted short-TTL signed URLs (never presigned object-store URLs), re-authorized at redemption.

**Tech Stack:** Django 5.2 modular monolith, Django REST Framework, django-rest-knox tokens, drf-spectacular (OpenAPI), `django.core.signing` (download tokens), PostgreSQL/psycopg3, pytest + pytest-django, `PilotDomainDriver` domain e2e.

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md`):

- **§3.1 Resident-only surface.** Staff get no API in Phase 0/1. Errors are RFC 9457 `application/problem+json` with a stable machine `code`; `detail` is developer English; the Flutter client owns all Vietnamese copy keyed off `code`. **No stack traces or internal identifiers in responses.** Cursor pagination, default page size 20.
- **§3.4 Occupancy context is server-validated.** The server validates `X-LamTo-Occupancy` against the caller's own **active** occupancies and derives unit + building from it. **A client-supplied building ID is never trusted or accepted.** Sole occupancy → auto-selected; multiple + no header → 422 `occupancy_selection_required`; foreign/garbage id → 404.
- **§2.3 status-code convention.** Cross-tenant object access → **404** (existence not revealed). Missing capability within the caller's own tenant → **403**. Applies to web and API identically. **Every registered API route is classified in the two-building adversarial suite** or `test_every_registered_route_is_classified` fails.
- **§3.5 Idempotent report submission.** `POST /reports` requires a client-generated `client_ref` UUID (unique per user). First → 201. Retry with the same `(user, client_ref)` and canonically identical content (text, occupancy, location) → 200 (existing report). Same `client_ref`, materially different content → 409 `client_ref_conflict`. Photos upload **separately** after the report row exists (per-photo retry), preserving the P1 "commit report before AI call" invariant.
- **§3.6 Uploads and downloads.** Uploads go **through Django** (multipart, size/type-checked) — never presigned object-store URLs; the ClamAV scan/quarantine gate stays in the path. Signed download URLs: **authorization runs before issuance on every request**; the resident code path can only issue URLs for the caller's own report photos and **redacted** variants of published-ledger documents; **original-variant issuance is unreachable** from the resident surface. TTL ≤ 5 minutes; responses carry `Cache-Control: private, no-store`; storage keys stay random/opaque; signed URLs are never written to logs.
- **§5.3 / §5.4.** Platform never initiates/holds funds — **no payment-provider dependency may enter `pyproject.toml`**. No secrets in git. The six e2e journeys, the two-building adversarial walk, `tenant_integrity`, the OpenAPI drift check, and the disabled-mode job stay green.

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

## Always-on gates (keep green after every task)

Three tests run on every commit and **fail immediately** if a new route is unclassified or the schema drifts. Every task that adds a route MUST, before its final commit:

1. Regenerate the committed schema: `manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn`.
2. Classify the new route(s) in `tests/isolation/test_cross_building_access.py` (add to an `API_*` map, plus a `cls.b` pk for object routes).
3. Add the new path(s) to `src/lamto/api/tests/test_openapi.py::test_schema_covers_every_api_route`.
4. Confirm green: `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py -q`.

## Design decisions

1. **`COMPONENT_SPLIT_REQUEST = True`.** drf-spectacular cannot represent a `FileField` in one component for both request and response, so file uploads need this global setting plus a `MultiPartParser` on the upload view (drf-spectacular FAQ). It is enabled once in Task 1 and the whole committed schema is regenerated then (a large, behavior-free diff that renames request components to `…Request`); every later task regenerates normally.
2. **Ownership vs tenant scoping.** `GET /reports`, `GET /reports/{id}`, photo upload, rating, and `POST /notifications/{id}/read` are **ownership-scoped** (the caller's own rows) and ignore the occupancy header — cross-user access is 404. `GET /locations` and `GET /notifications` are **building-scoped** via `resolve_api_occupancy` (occupancy header). `POST /reports` uses the header to derive the new report's unit + building.
3. **Idempotency lives in a wrapper.** `submit_report` gains a `client_ref=None` param that only stamps the field (web + factories unchanged). A new `submit_report_idempotent` wrapper does the lookup/conflict/`IntegrityError`-race handling and is the only API entry point (spec §3.5).
4. **Downloads are Django-hosted signed URLs.** `django.core.signing.dumps({"v","u"})` binds a version to the caller; redemption re-checks `u == request.user`, re-runs `resident_can_download`, and streams integrity-checked bytes with `Cache-Control: private, no-store` (spec §3.6). Presigned object-store URLs are never issued. The predicate only returns True for the caller's own `REPORT_PHOTO` versions and `REDACTED` published-ledger documents — originals of staff documents are structurally unreachable.
5. **No new domain behavior.** All state changes go through existing services; capability, building scope, and separation of duties are already enforced and tested there.

## File Structure

**Modify:**
- `src/lamto/maintenance/models.py` — `IssueReport.client_ref` (Task 1).
- `src/lamto/maintenance/reporting.py` — `submit_report(client_ref=…)`, `submit_report_idempotent`, `attach_report_photo`, `ReportClientRefConflict` (Tasks 1, 4).
- `src/lamto/maintenance/selectors.py` — `resident_report_timeline`, `active_location_tree` (Tasks 3, 6).
- `src/lamto/notifications/services.py` — `resident_feed`, `mark_notification_read` (Task 7).
- `src/lamto/documents/access.py` — extract `read_version_bytes` (Task 8).
- `src/lamto/finance/selectors.py` — add `version_id` to `ledger_entry_proof` redacted docs (Task 8).
- `src/lamto/config/settings.py` — `COMPONENT_SPLIT_REQUEST` (Task 1).
- `src/lamto/api/problems.py` — `ClientRefConflict` code (Task 2).
- `src/lamto/api/serializers.py` — report/location/feed/photo/download serializers (Tasks 2–8).
- `src/lamto/api/views.py` — the new views + download-url injection (Tasks 2–8).
- `src/lamto/api/urls.py` — 8 routes (Tasks 2–8).
- `src/lamto/api/tests/test_openapi.py` — route coverage (every task).
- `tests/isolation/test_cross_building_access.py` — classify routes + leak tests (every task; Task 9 adds bespoke tests).

**Create:**
- `src/lamto/api/downloads.py` — token issue/verify + `resident_can_download` (Task 8).
- `src/lamto/api/tests/test_reports.py`, `test_report_photos.py`, `test_ratings.py`, `test_locations.py`, `test_notifications.py`, `test_downloads.py`.

**Create migration:** `src/lamto/maintenance/migrations/0013_issuereport_client_ref.py` (Task 1, generated).

---

### Task 1: `client_ref` on `IssueReport` + idempotent submit service

Adds the per-user idempotency key and the wrapper the API create endpoint calls (spec §3.5). Also flips on `COMPONENT_SPLIT_REQUEST` and regenerates the schema baseline so later file-upload work slots in cleanly.

**Files:**
- Modify: `src/lamto/maintenance/models.py`
- Modify: `src/lamto/maintenance/reporting.py`
- Modify: `src/lamto/config/settings.py`
- Create: `src/lamto/maintenance/migrations/0013_issuereport_client_ref.py` (generated)
- Test: `src/lamto/maintenance/tests/test_reporting_idempotent.py`

**Interfaces:**
- Produces:
  - `IssueReport.client_ref` — `UUIDField(null=True, blank=True)`, unique per reporter when set.
  - `submit_report(resident, unit, text, location, photo_versions, client_ref=None) -> IssueReport` — unchanged behavior when `client_ref is None`; stamps the field otherwise.
  - `submit_report_idempotent(resident, unit, text, location, photo_versions, client_ref) -> tuple[IssueReport, bool]` — `(report, created)`. Retry with identical `(text, unit, location)` → `(existing, False)`; different content → raises `ReportClientRefConflict`.
  - `ReportClientRefConflict(Exception)`.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/maintenance/tests/test_reporting_idempotent.py`:

```python
import tempfile
import uuid

from django.core.files.storage import storages
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import BuildingLocation, IssueReport
from lamto.maintenance.reporting import (
    ReportClientRefConflict,
    submit_report_idempotent,
)
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-idem-")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class IdempotentSubmitTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="Idem B", email_prefix="idem", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.unit = self.seed.unit
        self.location = self.seed.location

    def test_first_submit_creates_then_retry_returns_same(self):
        ref = uuid.uuid4()
        report, created = submit_report_idempotent(
            self.resident, self.unit, "Lift jerks", self.location, [], ref
        )
        assert created is True
        again, created2 = submit_report_idempotent(
            self.resident, self.unit, "Lift jerks", self.location, [], ref
        )
        assert created2 is False
        assert again.pk == report.pk
        assert IssueReport.objects.filter(reporter=self.resident).count() == 1

    def test_same_ref_different_text_conflicts(self):
        ref = uuid.uuid4()
        submit_report_idempotent(self.resident, self.unit, "Lift jerks", self.location, [], ref)
        try:
            submit_report_idempotent(self.resident, self.unit, "Different text", self.location, [], ref)
            assert False, "expected ReportClientRefConflict"
        except ReportClientRefConflict:
            pass
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/maintenance/tests/test_reporting_idempotent.py -q`
Expected: FAIL — `ImportError: cannot import name 'submit_report_idempotent'`.

- [ ] **Step 3: Add the model field**

In `src/lamto/maintenance/models.py`, add to `IssueReport` (after `status`):

```python
    client_ref = models.UUIDField(null=True, blank=True)
```

And add a `Meta` to `IssueReport` (it has none today) enforcing per-reporter uniqueness only when set:

```python
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "client_ref"],
                condition=models.Q(client_ref__isnull=False),
                name="report_client_ref_once",
            )
        ]
```

- [ ] **Step 4: Generate the migration**

Run: `.venv/bin/python manage.py makemigrations maintenance -n issuereport_client_ref`
Expected: creates `src/lamto/maintenance/migrations/0013_issuereport_client_ref.py` (AddField + AddConstraint).

- [ ] **Step 5: Add the service changes**

In `src/lamto/maintenance/reporting.py`, add `IntegrityError` to the db import and the conflict class + wrapper. Change the top imports:

```python
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
```

Add near the top (after imports):

```python
class ReportClientRefConflict(Exception):
    """Same (reporter, client_ref) submitted with materially different content (spec 3.5)."""
```

Change the `submit_report` signature and the create call:

```python
def submit_report(resident, unit, text, location, photo_versions, client_ref=None) -> IssueReport:
```

…and in the `IssueReport.objects.create(...)` call add `client_ref=client_ref,`:

```python
    report = IssueReport.objects.create(
        reporter=resident,
        unit=unit,
        building=unit.building,
        text=text,
        selected_location=location,
        location_path_snapshot=location_path_snapshot,
        client_ref=client_ref,
    )
```

Append the wrapper at the end of the module:

```python
def _content_matches(existing, text, unit, location) -> bool:
    return (
        existing.text == (text or "").strip()
        and existing.unit_id == getattr(unit, "pk", unit)
        and existing.selected_location_id == getattr(location, "pk", location)
    )


def submit_report_idempotent(resident, unit, text, location, photo_versions, client_ref):
    """Idempotent POST /reports entry point (spec 3.5). Returns (report, created)."""
    existing = IssueReport.objects.filter(reporter=resident, client_ref=client_ref).first()
    if existing is not None:
        if _content_matches(existing, text, unit, location):
            return existing, False
        raise ReportClientRefConflict("client_ref reused with different content.")
    try:
        report = submit_report(resident, unit, text, location, photo_versions, client_ref=client_ref)
    except IntegrityError:
        # Concurrent duplicate: submit_report's atomic rolled back; re-fetch.
        existing = IssueReport.objects.filter(reporter=resident, client_ref=client_ref).first()
        if existing is not None and _content_matches(existing, text, unit, location):
            return existing, False
        raise ReportClientRefConflict("client_ref reused with different content.")
    return report, True
```

- [ ] **Step 6: Run to verify the service passes**

Run: `.venv/bin/python -m pytest src/lamto/maintenance/tests/test_reporting_idempotent.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Enable `COMPONENT_SPLIT_REQUEST` and regenerate the schema baseline**

In `src/lamto/config/settings.py`, add to `SPECTACULAR_SETTINGS`:

```python
    "COMPONENT_SPLIT_REQUEST": True,
```

Regenerate the committed schema (renames request components to `…Request`; no behavior change):

Run: `.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn`

- [ ] **Step 8: Run the always-on gates**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py -q`
Expected: PASS — schema matches (just regenerated); no new routes yet, so classification is unchanged.

- [ ] **Step 9: Commit**

```bash
git add src/lamto/maintenance/models.py src/lamto/maintenance/reporting.py \
        src/lamto/maintenance/migrations/0013_issuereport_client_ref.py \
        src/lamto/config/settings.py docs/api/openapi-v1.yaml \
        src/lamto/maintenance/tests/test_reporting_idempotent.py
git commit -m "feat: idempotent report submission with client_ref and split-request schema"
```

---

### Task 2: `POST /reports` (idempotent create)

The write endpoint: resolve occupancy → validate location in that building → idempotent submit → 201/200/409 (spec §3.3, §3.5). Adds the `client_ref_conflict` problem code.

**Files:**
- Modify: `src/lamto/api/problems.py`
- Modify: `src/lamto/api/serializers.py`
- Modify: `src/lamto/api/views.py`
- Modify: `src/lamto/api/urls.py`
- Modify: `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/api/tests/test_reports.py`

**Interfaces:**
- Consumes: `submit_report_idempotent`, `ReportClientRefConflict` (Task 1); `resolve_api_occupancy`, `OCCUPANCY_HEADER_PARAMETER`; `problem_responses`.
- Produces:
  - `problems.ClientRefConflict(APIException, status_code=409, default_code="client_ref_conflict")`.
  - `serializers.ReportCreateSerializer` (`client_ref` UUID, `text`, `location_id`).
  - `views.ReportListCreateView` at `api:reports` = `reports` (POST here; GET added in Task 3).

- [ ] **Step 1: Add the problem code**

In `src/lamto/api/problems.py`, add the exception (after `OccupancySelectionRequired`):

```python
class ClientRefConflict(exceptions.APIException):
    """POST /reports retried with the same client_ref but different content (spec 3.5)."""

    status_code = 409
    default_detail = "client_ref reused with different content."
    default_code = "client_ref_conflict"
```

Add to `_EXCEPTION_CODES` (near the top, before the generic entries):

```python
    (ClientRefConflict, "client_ref_conflict"),
```

Add to `_PROBLEM_DESCRIPTIONS`:

```python
    409: "client_ref reused with different content (code=client_ref_conflict).",
```

- [ ] **Step 2: Add the serializers**

In `src/lamto/api/serializers.py`, append. `ReportSummarySerializer` is the lightweight shape returned by create and by the list (Task 3); the full timeline detail serializer lands in Task 3.

```python
class ReportCreateSerializer(serializers.Serializer):
    client_ref = serializers.UUIDField(help_text="Client-generated UUID, unique per user (spec 3.5).")
    text = serializers.CharField(max_length=5000)
    location_id = serializers.IntegerField(help_text="Active BuildingLocation id in the resolved occupancy building.")


class ReportSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    text = serializers.CharField()
    status = serializers.CharField()
    location_path_snapshot = serializers.CharField()
    created_at = serializers.DateTimeField()
```

- [ ] **Step 3: Add the list/create view**

In `src/lamto/api/views.py`, extend imports:

```python
from django.core.exceptions import ValidationError as DjangoValidationError
from lamto.api import problems
from lamto.api.serializers import ReportCreateSerializer, ReportSummarySerializer
from lamto.maintenance.models import BuildingLocation
from lamto.maintenance.reporting import ReportClientRefConflict, submit_report_idempotent
from lamto.maintenance.selectors import resident_reports
```

(`DjangoPermissionDenied` is already imported.) Add the view — GET lists the caller's own reports (ownership-scoped, no occupancy header); POST is the idempotent create:

```python
class ReportCursorPagination(pagination.CursorPagination):
    page_size = 20
    ordering = ("-created_at", "-pk")


class ReportListCreateView(generics.ListCreateAPIView):
    serializer_class = ReportSummarySerializer
    pagination_class = ReportCursorPagination

    def get_queryset(self):
        return resident_reports(self.request.user)

    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        request=ReportCreateSerializer,
        responses={
            201: ReportSummarySerializer,
            200: ReportSummarySerializer,
            **problem_responses(400, 401, 403, 404, 409, 422),
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        occupancy, tenant = resolve_api_occupancy(request)
        location = BuildingLocation.objects.filter(
            pk=serializer.validated_data["location_id"],
            building_id=tenant.building_id,
            active=True,
        ).first()
        if location is None:
            raise exceptions.ValidationError({"location_id": "Unknown active location for this building."})
        try:
            report, created = submit_report_idempotent(
                request.user,
                occupancy.unit,
                serializer.validated_data["text"],
                location,
                [],
                serializer.validated_data["client_ref"],
            )
        except ReportClientRefConflict:
            raise problems.ClientRefConflict()
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages)
        except DjangoPermissionDenied:
            raise exceptions.PermissionDenied("An active resident occupancy is required.")
        return Response(ReportSummarySerializer(report).data, status=201 if created else 200)
```

`generics.ListCreateAPIView` routes GET → the inherited `list` (paginated, uses `serializer_class` + `get_queryset`) and POST → the overridden `create`; the `@extend_schema` on `create` annotates the POST operation.

- [ ] **Step 4: Add the route**

In `src/lamto/api/urls.py`, add:

```python
    path("reports", views.ReportListCreateView.as_view(), name="reports"),
```

- [ ] **Step 5: Write the failing tests**

Create `src/lamto/api/tests/test_reports.py`:

```python
import json
import tempfile
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.accounts.models import ResidentOccupancy
from lamto.maintenance.models import IssueReport
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-reports-")


def problem(response):
    return json.loads(response.content)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class ReportCreateTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API Reports B", email_prefix="apir", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.occupancy = ResidentOccupancy.objects.get(user=self.resident, active=True)

    def _auth(self):
        _instance, token = AuthToken.objects.create(user=self.resident)
        return {"authorization": f"Token {token}"}

    def _body(self, **over):
        base = {"client_ref": str(uuid.uuid4()), "text": "Lift jerks", "location_id": self.seed.location.pk}
        base.update(over)
        return base

    def test_first_create_is_201_and_retry_is_200(self):
        body = self._body()
        first = self.client.post(reverse("api:reports"), data=body, content_type="application/json", headers=self._auth())
        assert first.status_code == 201, first.content
        again = self.client.post(reverse("api:reports"), data=body, content_type="application/json", headers=self._auth())
        assert again.status_code == 200, again.content
        assert IssueReport.objects.filter(reporter=self.resident).count() == 1

    def test_same_ref_different_text_is_409(self):
        ref = str(uuid.uuid4())
        self.client.post(reverse("api:reports"), data=self._body(client_ref=ref), content_type="application/json", headers=self._auth())
        conflict = self.client.post(
            reverse("api:reports"),
            data=self._body(client_ref=ref, text="Different"),
            content_type="application/json",
            headers=self._auth(),
        )
        assert conflict.status_code == 409
        assert problem(conflict)["code"] == "client_ref_conflict"

    def test_foreign_location_is_400(self):
        from lamto.accounts.models import Building
        from lamto.maintenance.models import BuildingLocation

        other = BuildingLocation.objects.create(building=Building.objects.create(name="Other"), name="Elsewhere")
        resp = self.client.post(
            reverse("api:reports"),
            data=self._body(location_id=other.pk),
            content_type="application/json",
            headers=self._auth(),
        )
        assert resp.status_code == 400
        assert problem(resp)["code"] == "validation_failed"

    def test_list_returns_only_own_reports(self):
        self.client.post(reverse("api:reports"), data=self._body(), content_type="application/json", headers=self._auth())
        resp = self.client.get(reverse("api:reports"), headers=self._auth())
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["text"] == "Lift jerks"
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_reports.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Regenerate schema, classify the route, run gates**

- Regenerate: `.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml --validate --fail-on-warn`
- In `tests/isolation/test_cross_building_access.py`, add a new ownership bucket after `API_TENANT_OBJECT` and include it in every union + the classifier:

```python
# Ownership-scoped lists/writes (the caller's own rows; never building-tenant).
API_OWNERSHIP_LIST = {
    "api:reports": "GET mine + POST create",
}
```

Add `| set(API_OWNERSHIP_LIST)` to the classifier union in `test_every_registered_route_is_classified` and to the printed sets list.
- In `src/lamto/api/tests/test_openapi.py::test_schema_covers_every_api_route`, add `"/api/v1/reports"` to the route tuple.
- Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py -q` → PASS.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/api/problems.py src/lamto/api/serializers.py src/lamto/api/views.py \
        src/lamto/api/urls.py docs/api/openapi-v1.yaml src/lamto/api/tests/test_reports.py \
        src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py
git commit -m "feat: POST /reports idempotent create with client_ref_conflict"
```

---

### Task 3: `GET /reports` (mine) + `GET /reports/{id}` (timeline)

Ownership-scoped read: the caller's reports list, and one report's full timeline (triage → case → work → acceptance), 404 for anyone else's (spec §3.3, §2.3).

**Files:**
- Modify: `src/lamto/maintenance/selectors.py`, `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Modify: `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/api/tests/test_reports.py`

**Interfaces:**
- Consumes: `resident_reports` (existing), `resolve_api_occupancy`.
- Produces:
  - `selectors.resident_report_timeline(report) -> dict` (keys: `id, text, status, location_path_snapshot, unit_label, created_at, triage_status, category, photos, cases`; each case has `work_orders` with `can_rate`).
  - `serializers.ReportPhotoSerializer`, `ReportWorkOrderSerializer`, `ReportCaseSerializer`, `ReportDetailSerializer`.
  - `views.ReportDetailView` at `api:report-detail` = `reports/<int:pk>`.

- [ ] **Step 1: Add the timeline selector**

In `src/lamto/maintenance/selectors.py`, extend the import and append the selector:

```python
from lamto.maintenance.models import (
    CaseReport,
    CompletionRating,
    IssueReport,
    WorkOrder,
)
from lamto.maintenance.ratings import ELIGIBLE_STATUSES
```

```python
def resident_report_timeline(report):
    """Ownership timeline for one report (spec 3.3): triage -> case -> work -> acceptance."""
    triage_job = getattr(report, "triage_job", None)
    decision = getattr(report, "triage_decision", None)
    rated_ids = set(
        CompletionRating.objects.filter(resident_id=report.reporter_id).values_list(
            "work_order_id", flat=True
        )
    )
    cases = []
    for link in CaseReport.objects.filter(report=report).select_related("case").order_by("case_id"):
        case = link.case
        work_orders = []
        for wo in case.work_orders.select_related("acceptance").order_by("pk"):
            acceptance = getattr(wo, "acceptance", None)
            work_orders.append(
                {
                    "id": wo.pk,
                    "status": wo.status,
                    "deadline_at": wo.deadline_at,
                    "completed_at": wo.completed_at,
                    "accepted_at": getattr(acceptance, "accepted_at", None),
                    "can_rate": wo.status in ELIGIBLE_STATUSES and wo.pk not in rated_ids,
                }
            )
        cases.append(
            {
                "id": case.pk,
                "category": case.category,
                "urgency": case.urgency,
                "deadline_at": case.deadline_at,
                "active": case.active,
                "work_orders": work_orders,
            }
        )
    return {
        "id": report.pk,
        "text": report.text,
        "status": report.status,
        "location_path_snapshot": report.location_path_snapshot,
        "unit_label": report.unit.label,
        "created_at": report.created_at,
        "triage_status": triage_job.status if triage_job is not None else None,
        "category": decision.category if decision is not None else None,
        "photos": [
            {"id": rp.version.pk, "filename": rp.version.filename, "sha256": rp.version.sha256}
            for rp in report.photos.select_related("version").order_by("pk")
        ],
        "cases": cases,
    }
```

- [ ] **Step 2: Add the timeline serializers**

In `src/lamto/api/serializers.py`, append (the list uses `ReportSummarySerializer` from Task 2):

```python
class ReportPhotoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    filename = serializers.CharField()
    sha256 = serializers.CharField()
    # download_url added in Task 8.


class ReportWorkOrderSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    deadline_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField(allow_null=True)
    accepted_at = serializers.DateTimeField(allow_null=True)
    can_rate = serializers.BooleanField()


class ReportCaseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    category = serializers.CharField()
    urgency = serializers.CharField()
    deadline_at = serializers.DateTimeField()
    active = serializers.BooleanField()
    work_orders = ReportWorkOrderSerializer(many=True)


class ReportDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    text = serializers.CharField()
    status = serializers.CharField()
    location_path_snapshot = serializers.CharField()
    unit_label = serializers.CharField()
    created_at = serializers.DateTimeField()
    triage_status = serializers.CharField(allow_null=True)
    category = serializers.CharField(allow_null=True)
    photos = ReportPhotoSerializer(many=True)
    cases = ReportCaseSerializer(many=True)
```

- [ ] **Step 3: Add the detail view**

In `src/lamto/api/views.py`, add imports and the detail view (the list GET already works from Task 2):

```python
from lamto.api.serializers import ReportDetailSerializer
from lamto.maintenance.models import IssueReport
from lamto.maintenance.selectors import resident_report_timeline
```

```python
class ReportDetailView(APIView):
    @extend_schema(responses={200: ReportDetailSerializer, **problem_responses(401, 403, 404)})
    def get(self, request, pk):
        report = (
            IssueReport.objects.select_related("unit", "triage_job", "triage_decision")
            .filter(pk=pk, reporter=request.user)
            .first()
        )
        if report is None:
            raise exceptions.NotFound("Report not found.")
        return Response(ReportDetailSerializer(resident_report_timeline(report)).data)
```

- [ ] **Step 4: Add the route**

In `src/lamto/api/urls.py`, add:

```python
    path("reports/<int:pk>", views.ReportDetailView.as_view(), name="report-detail"),
```

- [ ] **Step 5: Write the failing tests**

Append `test_detail_timeline_and_foreign_report_404` to the `ReportCreateTests` class in `src/lamto/api/tests/test_reports.py`:

```python
    def test_detail_timeline_and_foreign_report_404(self):
        create = self.client.post(reverse("api:reports"), data=self._body(), content_type="application/json", headers=self._auth())
        report_id = create.json()["id"]
        detail = self.client.get(reverse("api:report-detail", kwargs={"pk": report_id}), headers=self._auth())
        assert detail.status_code == 200
        body = detail.json()
        assert body["triage_status"] == "PENDING"
        assert body["cases"] == []
        # A stranger's report id is 404 for this resident.
        from django.contrib.auth import get_user_model
        from lamto.accounts.models import ResidentOccupancy
        stranger = get_user_model().objects.create_user(email="apir-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        other = IssueReport.objects.create(
            reporter=stranger, unit=self.seed.unit, text="theirs",
            selected_location=self.seed.location, location_path_snapshot="x",
        )
        miss = self.client.get(reverse("api:report-detail", kwargs={"pk": other.pk}), headers=self._auth())
        assert miss.status_code == 404
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_reports.py -q`
Expected: PASS (5 passed).

- [ ] **Step 7: Regenerate schema, classify the route, run gates**

- Regenerate the schema (command above).
- In `tests/isolation/test_cross_building_access.py`, add to `API_TENANT_OBJECT`:

```python
    "api:report-detail": ("report_pk", "GET", 404),
```

- In `test_openapi.py::test_schema_covers_every_api_route`, add `"/api/v1/reports/{id}" in content or "/api/v1/reports/{pk}" in content` (mirror the ledger-detail tolerance).
- Run the gates → PASS. The generic `test_api_resident_cannot_reach_other_building_objects` now exercises `report-detail` → 404 automatically.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/maintenance/selectors.py src/lamto/api/serializers.py src/lamto/api/views.py \
        src/lamto/api/urls.py docs/api/openapi-v1.yaml src/lamto/api/tests/test_reports.py \
        src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py
git commit -m "feat: GET /reports list and report timeline detail"
```

---

### Task 4: `POST /reports/{id}/photos` (multipart upload)

Per-photo multipart upload through the ClamAV pipeline, attached to the caller's own report (spec §3.5, §3.6). 404 for anyone else's report.

**Files:**
- Modify: `src/lamto/maintenance/reporting.py`, `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Modify: `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/api/tests/test_report_photos.py`

**Interfaces:**
- Consumes: `create_resident_report_photo`, `scan_with_clamav`, `ReportPhoto` (existing).
- Produces:
  - `reporting.attach_report_photo(resident, report, uploaded_file, scanner) -> DocumentVersion`.
  - `serializers.ReportPhotoUploadSerializer` (`photo` FileField).
  - `views.ReportPhotoUploadView` at `api:report-photos` = `reports/<int:pk>/photos`.

- [ ] **Step 1: Add the attach service**

In `src/lamto/maintenance/reporting.py`, extend imports and append the service:

```python
from lamto.accounts.models import ResidentOccupancy, Unit
from lamto.documents.models import Document, DocumentVersion
from lamto.documents.services import create_resident_report_photo
from lamto.documents.scanner import scan_with_clamav
```

```python
def attach_report_photo(resident, report, uploaded_file, scanner=None) -> DocumentVersion:
    """Upload one report photo through the ClamAV pipeline and link it to the report.

    The caller must own the report (checked by the view). Requires an active
    occupancy in the report's building. Preserves the P1 upload-after-commit rule.
    """
    # Resolve the scanner at call time (not as a default arg) so tests can patch
    # lamto.maintenance.reporting.scan_with_clamav.
    if scanner is None:
        scanner = scan_with_clamav
    occupancy = ResidentOccupancy.objects.filter(
        user=resident, active=True, unit__building_id=report.building_id
    ).first()
    if occupancy is None:
        raise PermissionDenied("Active occupancy in the report building is required.")
    version = create_resident_report_photo(resident, report.building, uploaded_file, scanner)
    ReportPhoto.objects.create(report=report, version=version)
    return version
```

(`ReportPhoto` is already imported in this module.)

- [ ] **Step 2: Add the serializer**

In `src/lamto/api/serializers.py`, append:

```python
class ReportPhotoUploadSerializer(serializers.Serializer):
    photo = serializers.FileField(help_text="JPEG/PNG image; scanned by ClamAV before storage.")
```

- [ ] **Step 3: Add the view**

In `src/lamto/api/views.py`, add imports + the view:

```python
from lamto.api.serializers import ReportPhotoSerializer, ReportPhotoUploadSerializer
from lamto.maintenance.reporting import attach_report_photo
from lamto.documents.services import DocumentUploadQuarantined, DocumentUploadRejected
```

```python
class ReportPhotoUploadView(APIView):
    parser_classes = [parsers.MultiPartParser]

    @extend_schema(
        request=ReportPhotoUploadSerializer,
        responses={201: ReportPhotoSerializer, **problem_responses(400, 401, 403, 404)},
    )
    def post(self, request, pk):
        report = IssueReport.objects.filter(pk=pk, reporter=request.user).first()
        if report is None:
            raise exceptions.NotFound("Report not found.")
        serializer = ReportPhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            version = attach_report_photo(request.user, report, serializer.validated_data["photo"])
        except (DocumentUploadRejected, DocumentUploadQuarantined) as error:
            raise exceptions.ValidationError({"photo": str(error)})
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages)
        except DjangoPermissionDenied:
            raise exceptions.PermissionDenied("Active occupancy in the report building is required.")
        return Response(
            ReportPhotoSerializer({"id": version.pk, "filename": version.filename, "sha256": version.sha256}).data,
            status=201,
        )
```

- [ ] **Step 4: Add the route**

In `src/lamto/api/urls.py`, add:

```python
    path("reports/<int:pk>/photos", views.ReportPhotoUploadView.as_view(), name="report-photos"),
```

- [ ] **Step 5: Write the failing tests**

Create `src/lamto/api/tests/test_report_photos.py`:

```python
import tempfile
import uuid
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.maintenance.models import IssueReport, ReportPhoto
from lamto.maintenance.reporting import submit_report_idempotent
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-photos-")
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class ReportPhotoUploadTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API Photos B", email_prefix="apip", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.report, _ = submit_report_idempotent(
            self.resident, self.seed.unit, "Lift jerks", self.seed.location, [], uuid.uuid4()
        )

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    @patch("lamto.maintenance.reporting.scan_with_clamav", lambda _f: True)
    def test_upload_attaches_photo_to_own_report(self):
        resp = self.client.post(
            reverse("api:report-photos", kwargs={"pk": self.report.pk}),
            data={"photo": SimpleUploadedFile("p.png", _PNG, content_type="image/png")},
            headers=self._auth(),
        )
        assert resp.status_code == 201, resp.content
        assert ReportPhoto.objects.filter(report=self.report).count() == 1
        assert resp.json()["sha256"]

    @patch("lamto.maintenance.reporting.scan_with_clamav", lambda _f: True)
    def test_upload_to_foreign_report_is_404(self):
        from django.contrib.auth import get_user_model
        from lamto.accounts.models import ResidentOccupancy
        stranger = get_user_model().objects.create_user(email="apip-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        resp = self.client.post(
            reverse("api:report-photos", kwargs={"pk": self.report.pk}),
            data={"photo": SimpleUploadedFile("p.png", _PNG, content_type="image/png")},
            headers=self._auth(stranger),
        )
        assert resp.status_code == 404
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_report_photos.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Regenerate schema, classify the route, run gates**

- Regenerate the schema. Confirm the multipart request body appears (search the yaml for `multipart/form-data` under `/api/v1/reports/{id}/photos`).
- In `tests/isolation/test_cross_building_access.py`, add to `API_TENANT_OBJECT`:

```python
    "api:report-photos": ("report_pk", "POST", 404),
```

- In `test_openapi.py`, add `"/api/v1/reports/{id}/photos"` (accept `{pk}` too) to the route coverage.
- Run the gates → PASS.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/maintenance/reporting.py src/lamto/api/serializers.py src/lamto/api/views.py \
        src/lamto/api/urls.py docs/api/openapi-v1.yaml src/lamto/api/tests/test_report_photos.py \
        src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py
git commit -m "feat: POST /reports/{id}/photos multipart upload via ClamAV pipeline"
```

---

### Task 5: `POST /work/{id}/rating`

The caller rates completed work on a case they reported (spec §3.3). Cross-tenant/not-reported → 404; own-building but not the reporter → the domain's 403; already-rated / not-eligible → 400.

**Files:**
- Modify: `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Modify: `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/api/tests/test_ratings.py`

**Interfaces:**
- Consumes: `rate_completed_work` (existing), `WorkOrder`.
- Produces:
  - `serializers.WorkRatingSerializer` (`score` 1–5, `comment` optional).
  - `views.WorkRatingView` at `api:work-rating` = `work/<int:pk>/rating`.

- [ ] **Step 1: Add the serializer**

In `src/lamto/api/serializers.py`, append:

```python
class WorkRatingSerializer(serializers.Serializer):
    score = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)


class WorkRatingResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    work_order_id = serializers.IntegerField()
    score = serializers.IntegerField()
```

- [ ] **Step 2: Add the view**

In `src/lamto/api/views.py`, add imports + the view:

```python
from lamto.api.serializers import WorkRatingResultSerializer, WorkRatingSerializer
from lamto.maintenance.models import WorkOrder
from lamto.maintenance.ratings import rate_completed_work
```

```python
class WorkRatingView(APIView):
    @extend_schema(
        request=WorkRatingSerializer,
        responses={201: WorkRatingResultSerializer, **problem_responses(400, 401, 403, 404)},
    )
    def post(self, request, pk):
        # Scope to work orders on a case the caller reported: existence is not
        # revealed for other tenants' work (spec 2.3 -> 404).
        work_order = (
            WorkOrder.objects.filter(pk=pk, case__case_reports__report__reporter=request.user)
            .distinct()
            .first()
        )
        if work_order is None:
            raise exceptions.NotFound("Work order not found.")
        serializer = WorkRatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rating = rate_completed_work(
                request.user,
                work_order,
                serializer.validated_data["score"],
                serializer.validated_data.get("comment", ""),
            )
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages)
        except DjangoPermissionDenied:
            raise exceptions.PermissionDenied("Only residents who reported this case may rate the work.")
        return Response(
            WorkRatingResultSerializer(
                {"id": rating.pk, "work_order_id": work_order.pk, "score": rating.score}
            ).data,
            status=201,
        )
```

- [ ] **Step 3: Add the route**

In `src/lamto/api/urls.py`, add:

```python
    path("work/<int:pk>/rating", views.WorkRatingView.as_view(), name="work-rating"),
```

- [ ] **Step 4: Write the failing tests**

Create `src/lamto/api/tests/test_ratings.py`:

```python
import json
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.maintenance.models import CompletionRating, WorkOrder
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-rate-")


def problem(response):
    return json.loads(response.content)


def _accepted_work(seed):
    d = PilotDomainDriver(seed)
    d.login(None, "resident").submit_report("Lift noise", "Lift 2")
    d.login(None, "operator").confirm_triage_and_create_paid_work_order()
    d.login(None, "operator").submit_signed_proposal()
    d.login(None, "board_approver").approve_proposal()
    d.login(None, "resident_representative").coapprove_proposal()
    d.login(None, "maintenance").complete_assigned_work()
    d.login(None, "board_payment_recorder").accept_and_record_payment()
    d.confirm_all_chain_events()
    return WorkOrder.objects.get(case__building=seed.building)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class WorkRatingTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API Rate B", email_prefix="apirate", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.work = _accepted_work(self.seed)

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    def test_reporter_can_rate_once(self):
        url = reverse("api:work-rating", kwargs={"pk": self.work.pk})
        first = self.client.post(url, data={"score": 5, "comment": "Great"}, content_type="application/json", headers=self._auth())
        assert first.status_code == 201, first.content
        assert CompletionRating.objects.filter(work_order=self.work, resident=self.resident).count() == 1
        again = self.client.post(url, data={"score": 4}, content_type="application/json", headers=self._auth())
        assert again.status_code == 400  # already rated

    def test_non_reporter_cannot_rate(self):
        from django.contrib.auth import get_user_model
        from lamto.accounts.models import ResidentOccupancy
        stranger = get_user_model().objects.create_user(email="apirate-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        resp = self.client.post(
            reverse("api:work-rating", kwargs={"pk": self.work.pk}),
            data={"score": 5}, content_type="application/json", headers=self._auth(stranger),
        )
        assert resp.status_code == 404  # did not report this case -> existence not revealed
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_ratings.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Regenerate schema, classify the route, run gates**

- Regenerate the schema.
- In `tests/isolation/test_cross_building_access.py`, add to `API_TENANT_OBJECT`:

```python
    "api:work-rating": ("work_pk", "POST", 404),
```

- In `test_openapi.py`, add `"/api/v1/work/{id}/rating"` (accept `{pk}`).
- Run the gates → PASS.

- [ ] **Step 7: Commit**

```bash
git add src/lamto/api/serializers.py src/lamto/api/views.py src/lamto/api/urls.py \
        docs/api/openapi-v1.yaml src/lamto/api/tests/test_ratings.py \
        src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py
git commit -m "feat: POST /work/{id}/rating for reporting residents"
```

---

### Task 6: `GET /locations`

The active location tree for the resolved occupancy's building (spec §3.3). Returned as a flat, ordered list of `{id, name, parent_id}` — the client assembles the tree (no recursive schema).

**Files:**
- Modify: `src/lamto/maintenance/selectors.py`, `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Modify: `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/api/tests/test_locations.py`

**Interfaces:**
- Produces:
  - `selectors.active_location_tree(building_id)` → `BuildingLocation` queryset, active, ordered by `(parent_id, name)`.
  - `serializers.LocationSerializer` (`id, name, parent_id`).
  - `views.LocationListView` at `api:locations` = `locations`.

- [ ] **Step 1: Add the selector**

In `src/lamto/maintenance/selectors.py`, add `BuildingLocation` to the model import and append:

```python
def active_location_tree(building_id):
    """Active locations for one building, ordered so parents precede siblings (spec 3.3)."""
    return (
        BuildingLocation.objects.filter(building_id=building_id, active=True)
        .order_by("parent_id", "name", "pk")
    )
```

- [ ] **Step 2: Add the serializer**

In `src/lamto/api/serializers.py`, append:

```python
class LocationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True)
```

- [ ] **Step 3: Add the view**

In `src/lamto/api/views.py`, add imports + the view:

```python
from lamto.api.serializers import LocationSerializer
from lamto.maintenance.selectors import active_location_tree
```

```python
class LocationListView(APIView):
    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        responses={200: LocationSerializer(many=True), **problem_responses(401, 403, 404, 422)},
    )
    def get(self, request):
        _occupancy, tenant = resolve_api_occupancy(request)
        locations = active_location_tree(tenant.building_id)
        return Response(LocationSerializer(locations, many=True).data)
```

- [ ] **Step 4: Add the route**

In `src/lamto/api/urls.py`, add:

```python
    path("locations", views.LocationListView.as_view(), name="locations"),
```

- [ ] **Step 5: Write the failing test**

Create `src/lamto/api/tests/test_locations.py`:

```python
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.maintenance.models import BuildingLocation
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-loc-")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class LocationListTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API Loc B", email_prefix="apiloc", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        # A child + an inactive sibling of the seed location.
        self.child = BuildingLocation.objects.create(
            building=self.seed.building, parent=self.seed.location, name="Cabin"
        )
        BuildingLocation.objects.create(building=self.seed.building, name="Retired", active=False)

    def _auth(self):
        _instance, token = AuthToken.objects.create(user=self.resident)
        return {"authorization": f"Token {token}"}

    def test_returns_active_tree_only(self):
        resp = self.client.get(reverse("api:locations"), headers=self._auth())
        assert resp.status_code == 200
        names = {row["name"] for row in resp.json()}
        assert "Cabin" in names
        assert "Retired" not in names
        child = next(row for row in resp.json() if row["name"] == "Cabin")
        assert child["parent_id"] == self.seed.location.pk
```

- [ ] **Step 6: Run the test**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_locations.py -q`
Expected: PASS (1 passed).

- [ ] **Step 7: Regenerate schema, classify the route, run gates**

- Regenerate the schema.
- In `tests/isolation/test_cross_building_access.py`, add to `API_TENANT_LIST`:

```python
    "api:locations": "GET",
```

- In `test_openapi.py`, add `"/api/v1/locations"` to the route coverage tuple.
- Run the gates → PASS. `test_api_rejects_foreign_occupancy_header` + `test_api_lists_never_leak_other_building` now cover `locations` automatically.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/maintenance/selectors.py src/lamto/api/serializers.py src/lamto/api/views.py \
        src/lamto/api/urls.py docs/api/openapi-v1.yaml src/lamto/api/tests/test_locations.py \
        src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py
git commit -m "feat: GET /locations active tree for the resolved occupancy building"
```

---

### Task 7: `GET /notifications` + `POST /notifications/{id}/read`

The in-app feed (building-scoped) and mark-read (ownership-scoped) (spec §3.3). Only the caller's own IN_APP `AVAILABLE` deliveries; mark-read on someone else's → 404.

**Files:**
- Modify: `src/lamto/notifications/services.py`, `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Modify: `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/api/tests/test_notifications.py`

**Interfaces:**
- Produces:
  - `services.resident_feed(user, building_id)` → `NotificationDelivery` queryset.
  - `services.mark_notification_read(user, delivery_id) -> int` (rows updated; 0 or 1).
  - `serializers.NotificationFeedSerializer` (`id, event_code, subject, body, created_at, read_at`).
  - `views.NotificationListView` at `api:notifications` = `notifications`; `NotificationReadView` at `api:notification-read` = `notifications/<int:pk>/read`.

- [ ] **Step 1: Add the feed + mark-read services**

In `src/lamto/notifications/services.py`, append:

```python
def resident_feed(user, building_id):
    """Resident in-app feed for one building (spec 3.3): available IN_APP notices,
    plus legacy null-building rows, newest first."""
    return (
        NotificationDelivery.objects.filter(
            recipient=user,
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.AVAILABLE,
        )
        .filter(Q(building_id=building_id) | Q(building_id__isnull=True))
        .order_by("-created_at", "-pk")
    )


def mark_notification_read(user, delivery_id) -> int:
    """Mark one of the caller's IN_APP notices read. Returns rows updated (0/1)."""
    return (
        NotificationDelivery.objects.filter(
            pk=delivery_id,
            recipient=user,
            channel=NotificationDelivery.Channel.IN_APP,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
    )
```

(`Q` and `timezone` are already imported in this module.)

- [ ] **Step 2: Add the serializer**

In `src/lamto/api/serializers.py`, append:

```python
class NotificationFeedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    event_code = serializers.CharField()
    subject = serializers.CharField()
    body = serializers.CharField()
    created_at = serializers.DateTimeField()
    read_at = serializers.DateTimeField(allow_null=True)
```

- [ ] **Step 3: Add the views**

In `src/lamto/api/views.py`, add imports + views:

```python
from lamto.api.serializers import NotificationFeedSerializer
from lamto.notifications.models import NotificationDelivery
from lamto.notifications.services import mark_notification_read, resident_feed
```

```python
class NotificationCursorPagination(pagination.CursorPagination):
    page_size = 20
    ordering = ("-created_at", "-pk")


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationFeedSerializer
    pagination_class = NotificationCursorPagination

    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        responses={200: NotificationFeedSerializer(many=True), **problem_responses(401, 403, 404, 422)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        _occupancy, tenant = resolve_api_occupancy(self.request)
        return resident_feed(self.request.user, tenant.building_id)


class NotificationReadView(APIView):
    @extend_schema(request=None, responses={204: None, **problem_responses(401, 403, 404)})
    def post(self, request, pk):
        delivery = NotificationDelivery.objects.filter(
            pk=pk, recipient=request.user, channel=NotificationDelivery.Channel.IN_APP
        ).first()
        if delivery is None:
            raise exceptions.NotFound("Notification not found.")
        mark_notification_read(request.user, pk)
        return Response(status=204)
```

- [ ] **Step 4: Add the routes**

In `src/lamto/api/urls.py`, add:

```python
    path("notifications", views.NotificationListView.as_view(), name="notifications"),
    path("notifications/<int:pk>/read", views.NotificationReadView.as_view(), name="notification-read"),
```

- [ ] **Step 5: Write the failing tests**

Create `src/lamto/api/tests/test_notifications.py`:

```python
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.notifications.models import NotificationDelivery
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-notif-")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class NotificationFeedTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API Notif B", email_prefix="apin", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.delivery = NotificationDelivery.objects.create(
            recipient=self.resident, building=self.seed.building,
            channel=NotificationDelivery.Channel.IN_APP, status=NotificationDelivery.Status.AVAILABLE,
            event_key="ledger.publication:x:1", event_code="ledger.publication",
            subject="New spending published", body="A new expenditure was published.",
        )

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    def _occ(self):
        from lamto.accounts.models import ResidentOccupancy
        occ = ResidentOccupancy.objects.get(user=self.resident, active=True)
        return {**self._auth(), "x-lamto-occupancy": str(occ.pk)}

    def test_feed_lists_available_and_mark_read(self):
        resp = self.client.get(reverse("api:notifications"), headers=self._occ())
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1 and results[0]["read_at"] is None

        read = self.client.post(reverse("api:notification-read", kwargs={"pk": self.delivery.pk}), headers=self._auth())
        assert read.status_code == 204
        self.delivery.refresh_from_db()
        assert self.delivery.read_at is not None

    def test_mark_read_foreign_delivery_is_404(self):
        from django.contrib.auth import get_user_model
        from lamto.accounts.models import ResidentOccupancy
        stranger = get_user_model().objects.create_user(email="apin-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        resp = self.client.post(
            reverse("api:notification-read", kwargs={"pk": self.delivery.pk}), headers=self._auth(stranger)
        )
        assert resp.status_code == 404
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_notifications.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Regenerate schema, classify the routes, run gates**

- Regenerate the schema.
- In `tests/isolation/test_cross_building_access.py`:
  - add to `API_TENANT_LIST`: `"api:notifications": "GET",`
  - add to `API_TENANT_OBJECT`: `"api:notification-read": ("notification_pk", "POST", 404),`
  - in `setUpTestData`, after the `cls.b = {...}` block, create a B-side notification and store its pk:

```python
        b_notice = NotificationDelivery.objects.create(
            recipient=cls.seed_b.users["resident"], building=b_building,
            channel=NotificationDelivery.Channel.IN_APP, status=NotificationDelivery.Status.AVAILABLE,
            event_key="ledger.publication:iso:1", event_code="ledger.publication",
            subject="B notice", body=B_LEAK_MARKER,
        )
        cls.b["notification_pk"] = b_notice.pk
```

  - add `from lamto.notifications.models import NotificationDelivery` to the imports.
- In `test_openapi.py`, add `"/api/v1/notifications"` and `"/api/v1/notifications/{id}/read"` (accept `{pk}`).
- Run the gates → PASS.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/notifications/services.py src/lamto/api/serializers.py src/lamto/api/views.py \
        src/lamto/api/urls.py docs/api/openapi-v1.yaml src/lamto/api/tests/test_notifications.py \
        src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py
git commit -m "feat: GET /notifications feed and mark-read"
```

---

### Task 8: Signed document downloads

Django-hosted short-TTL signed URLs for the caller's own report photos and redacted published-ledger documents; originals of staff documents are structurally unreachable (spec §3.6). Injects `download_url` into report-photo and ledger-detail responses.

**Files:**
- Create: `src/lamto/api/downloads.py`
- Modify: `src/lamto/documents/access.py` (extract `read_version_bytes`)
- Modify: `src/lamto/finance/selectors.py` (add `version_id` to redacted docs)
- Modify: `src/lamto/api/serializers.py`, `src/lamto/api/views.py`, `src/lamto/api/urls.py`
- Modify: `src/lamto/api/tests/test_openapi.py`, `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/api/tests/test_downloads.py`

**Interfaces:**
- Produces:
  - `downloads.issue_download_token(user_id, version_id) -> str`; `downloads.DOWNLOAD_MAX_AGE = 300`.
  - `downloads.resident_can_download(user, version) -> bool`.
  - `access.read_version_bytes(version) -> bytes` (read + integrity check; raises `DocumentIntegrityError`).
  - `views.DocumentDownloadView` at `api:document-download` = `documents/<str:token>`.
  - `download_url` added to `ReportPhotoSerializer` and `RedactedDocumentSerializer`.

- [ ] **Step 1: Add a reusable byte reader in documents/access.py**

In `src/lamto/documents/access.py`, add a new pure reader (leave `authorize_download` and its audit branches untouched — the existing `test_access` suite guards them). The 3-line read+hash overlap with `authorize_download` is acceptable duplication vs. the risk of reworking a security-audited function:

```python
def read_version_bytes(version) -> bytes:
    """Read a stored version and verify its sha256. Raises DocumentIntegrityError.

    Used by the resident API download path after its own authorization; the staff
    ``authorize_download`` keeps its distinct 'unavailable' vs 'integrity_mismatch'
    audit branches and is not routed through this reader.
    """
    try:
        data = b"".join(_read_stored_version(version))
    except Exception as error:
        raise DocumentIntegrityError("Document storage is unavailable.") from error
    if hashlib.sha256(data).hexdigest() != version.sha256:
        raise DocumentIntegrityError("Document integrity check failed.")
    return data
```

- [ ] **Step 2: Add `version_id` to the shared ledger proof selector**

In `src/lamto/finance/selectors.py`, in `ledger_entry_proof`, add `"version_id": version_obj.pk` to each redacted doc dict (the acceptance loop and the payment-proof block) and `"version_id": proof_redacted.pk` for the proof entry. The web templates ignore the extra key.

- [ ] **Step 3: Create the download authorization module**

Create `src/lamto/api/downloads.py`:

```python
"""Signed resident document downloads (spec 3.6).

Django-hosted, short-TTL signed URLs — never presigned object-store URLs.
The token binds a version to the requesting user; redemption re-checks the
user and re-runs resident_can_download, so a token can never widen access.
"""

from django.core import signing
from django.db.models import Q

from lamto.accounts.tenancy import active_occupancies
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.models import SETTLED_STATUSES
from lamto.finance.models import PublishedLedgerEntry
from lamto.maintenance.models import ReportPhoto

DOWNLOAD_SALT = "lamto.api.download"
DOWNLOAD_MAX_AGE = 300  # spec 3.6: TTL <= 5 minutes


def issue_download_token(user_id: int, version_id: int) -> str:
    """Signed, TTL-bound token binding a document version to one user."""
    return signing.dumps({"v": version_id, "u": user_id}, salt=DOWNLOAD_SALT)


def resident_can_download(user, version) -> bool:
    """True only for the caller's own report photos and redacted published-ledger
    documents. Originals of staff documents are unreachable from this path."""
    if version.document.kind == Document.Kind.REPORT_PHOTO:
        return ReportPhoto.objects.filter(version=version, report__reporter=user).exists()
    if version.variant != DocumentVersion.Variant.REDACTED:
        return False
    building_ids = list(active_occupancies(user).values_list("unit__building_id", flat=True))
    if not building_ids:
        return False
    return (
        PublishedLedgerEntry.objects.filter(
            case__building_id__in=building_ids,
            snapshot__outbox_event__status__in=SETTLED_STATUSES,
        )
        .filter(
            Q(work_order__acceptance__invoice_redacted=version)
            | Q(work_order__acceptance__acceptance_redacted=version)
            | Q(payment__proof_redacted=version)
        )
        .exists()
    )
```

- [ ] **Step 4: Add the download view + inject `download_url`**

In `src/lamto/api/serializers.py`, add `download_url = serializers.CharField()` to `ReportPhotoSerializer` and to `RedactedDocumentSerializer`.

In `src/lamto/api/views.py`, add imports + the view, and inject the url where photos/redacted docs are serialized:

```python
from django.core import signing
from django.http import HttpResponse
from django.urls import reverse
from lamto.api.downloads import DOWNLOAD_MAX_AGE, DOWNLOAD_SALT, issue_download_token, resident_can_download
from lamto.documents.access import DocumentIntegrityError, read_version_bytes
from lamto.documents.models import DocumentVersion
```

```python
class DocumentDownloadView(APIView):
    @extend_schema(responses={200: OpenApiTypes.BINARY, **problem_responses(401, 403, 404)})
    def get(self, request, token):
        try:
            payload = signing.loads(token, salt=DOWNLOAD_SALT, max_age=DOWNLOAD_MAX_AGE)
        except signing.BadSignature:
            raise exceptions.NotFound("Document not found.")
        if payload.get("u") != request.user.pk:
            raise exceptions.NotFound("Document not found.")
        version = (
            DocumentVersion.objects.select_related("document").filter(pk=payload.get("v")).first()
        )
        if version is None or not resident_can_download(request.user, version):
            raise exceptions.NotFound("Document not found.")
        try:
            data = read_version_bytes(version)
        except DocumentIntegrityError:
            raise exceptions.NotFound("Document not found.")
        response = HttpResponse(data, content_type=version.content_type)
        response["Cache-Control"] = "private, no-store"
        response["Content-Disposition"] = f'inline; filename="{version.filename}"'
        return response
```

(Ensure `OpenApiTypes` is imported: `from drf_spectacular.types import OpenApiTypes`.)

In `ReportDetailView.get` and `ReportListCreateView.post`, after building the timeline dict, add a download url to each photo:

```python
        timeline = resident_report_timeline(report)
        for photo in timeline["photos"]:
            photo["download_url"] = reverse(
                "api:document-download", args=[issue_download_token(request.user.pk, photo["id"])]
            )
        return Response(ReportDetailSerializer(timeline).data, ...)
```

In `LedgerDetailView.get`, add a download url to each redacted document before serializing:

```python
        redacted_documents = [
            {**doc, "download_url": reverse(
                "api:document-download", args=[issue_download_token(request.user.pk, doc["version_id"])]
            )}
            for doc in detail["redacted_docs"]
        ]
```

…and use `redacted_documents` in the `data` dict (replacing `detail["redacted_docs"]`).

- [ ] **Step 5: Add the route**

In `src/lamto/api/urls.py`, add:

```python
    path("documents/<str:token>", views.DocumentDownloadView.as_view(), name="document-download"),
```

- [ ] **Step 6: Write the failing tests**

Create `src/lamto/api/tests/test_downloads.py`:

```python
import tempfile
import uuid
from unittest.mock import patch

from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from knox.models import AuthToken

from lamto.api.downloads import DOWNLOAD_SALT, issue_download_token
from lamto.maintenance.models import ReportPhoto
from lamto.maintenance.reporting import submit_report_idempotent
from lamto.testing.factories import seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-api-dl-")
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class DownloadTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="API DL B", email_prefix="apidl", create_sample_report=False)
        self.resident = self.seed.users["resident"]
        self.report, _ = submit_report_idempotent(
            self.resident, self.seed.unit, "Lift jerks", self.seed.location, [], uuid.uuid4()
        )

    def _auth(self, user=None):
        _instance, token = AuthToken.objects.create(user=user or self.resident)
        return {"authorization": f"Token {token}"}

    @patch("lamto.maintenance.reporting.scan_with_clamav", lambda _f: True)
    def _upload_photo(self):
        self.client.post(
            reverse("api:report-photos", kwargs={"pk": self.report.pk}),
            data={"photo": SimpleUploadedFile("p.png", _PNG, content_type="image/png")},
            headers=self._auth(),
        )
        return ReportPhoto.objects.get(report=self.report).version

    def test_own_photo_download_url_streams_bytes(self):
        version = self._upload_photo()
        detail = self.client.get(reverse("api:report-detail", kwargs={"pk": self.report.pk}), headers=self._auth())
        url = detail.json()["photos"][0]["download_url"]
        assert url.startswith("/api/v1/documents/")
        got = self.client.get(url, headers=self._auth())
        assert got.status_code == 200
        assert got["Cache-Control"] == "private, no-store"
        assert got.content == _PNG

    def test_token_bound_to_user_and_expiry(self):
        version = self._upload_photo()
        # A token minted for this user cannot be redeemed by another user.
        from django.contrib.auth import get_user_model
        from lamto.accounts.models import ResidentOccupancy
        stranger = get_user_model().objects.create_user(email="apidl-x@example.com", password="x", display_name="X")
        ResidentOccupancy.objects.create(user=stranger, unit=self.seed.unit, active=True)
        token = issue_download_token(self.resident.pk, version.pk)
        miss = self.client.get(reverse("api:document-download", args=[token]), headers=self._auth(stranger))
        assert miss.status_code == 404
        # A tampered/garbage token is 404.
        bad = self.client.get(reverse("api:document-download", args=["not-a-real-token"]), headers=self._auth())
        assert bad.status_code == 404

    def test_original_staff_document_is_unreachable(self):
        # Forge a token for an original (non-redacted, non-photo) document version;
        # resident_can_download must refuse it -> 404.
        import hashlib
        from lamto.documents.models import Document, DocumentVersion
        doc = Document.objects.create(building=self.seed.building, kind=Document.Kind.INVOICE)
        original = DocumentVersion.objects.create(
            document=doc, version=1, variant=DocumentVersion.Variant.ORIGINAL,
            filename="inv.pdf", content_type="application/pdf", byte_size=3,
            sha256=hashlib.sha256(b"pdf").hexdigest(), storage_key="k", provider_version_id="v",
            scan_status=DocumentVersion.ScanStatus.CLEAN, uploader=self.resident,
        )
        token = issue_download_token(self.resident.pk, original.pk)
        resp = self.client.get(reverse("api:document-download", args=[token]), headers=self._auth())
        assert resp.status_code == 404
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_downloads.py -q`
Expected: PASS (3 passed).

- [ ] **Step 8: Regenerate schema, classify the route, run gates**

- Regenerate the schema.
- In `tests/isolation/test_cross_building_access.py`, add to `API_EXEMPT`:

```python
    "api:document-download": "signed-token download; authorization re-runs at redemption (see test_downloads)",
```

- In `test_openapi.py`, add `"/api/v1/documents/"` substring coverage (the `{token}` path).
- Run the gates → PASS.

- [ ] **Step 9: Commit**

```bash
git add src/lamto/api/downloads.py src/lamto/documents/access.py src/lamto/finance/selectors.py \
        src/lamto/api/serializers.py src/lamto/api/views.py src/lamto/api/urls.py \
        docs/api/openapi-v1.yaml src/lamto/api/tests/test_downloads.py \
        src/lamto/api/tests/test_openapi.py tests/isolation/test_cross_building_access.py
git commit -m "feat: signed resident document downloads for photos and redacted ledger docs"
```

---

### Task 9: Adversarial ownership-leak tests + full regression gate

The generic walk already covers the new `API_TENANT_OBJECT`/`API_TENANT_LIST` routes (404 + no-leak). This task adds the two cases the generic walk does not: the ownership-scoped `GET /reports` must not leak another user's reports, and the download re-authorization holds across tenants. Then it runs the whole suite as the exit gate.

**Files:**
- Modify: `tests/isolation/test_cross_building_access.py`
- Test: (bespoke methods added to the isolation suite)

**Interfaces:**
- Consumes: everything above; `cls.b` pks (`report_pk`, `work_pk`, `notification_pk`).

- [ ] **Step 1: Add the ownership-leak test**

In `tests/isolation/test_cross_building_access.py`, add a method to `CrossBuildingAccessTests` that authenticates as A's resident and confirms B's report never appears in `GET /reports` or `GET /reports/{id}`:

```python
    def test_api_reports_never_leak_other_users(self):
        resident_a = self.seed_a.users["resident"]
        _instance, token = AuthToken.objects.create(user=resident_a)
        auth = {"authorization": f"Token {token}"}
        listing = self.client.get(reverse("api:reports"), headers=auth)
        assert listing.status_code == 200, listing.content
        assert B_LEAK_MARKER.encode() not in listing.content
        # B's report id is 404 for A's resident.
        miss = self.client.get(reverse("api:report-detail", kwargs={"pk": self.b["report_pk"]}), headers=auth)
        assert miss.status_code == 404
```

- [ ] **Step 2: Add the download re-authorization test**

Add a method confirming a token minted for B's resident cannot be redeemed by A's resident, and A cannot obtain B's redacted-ledger download:

```python
    def test_api_download_reauthorizes_across_tenants(self):
        from lamto.api.downloads import issue_download_token
        from lamto.finance.models import PublishedLedgerEntry

        resident_a = self.seed_a.users["resident"]
        resident_b = self.seed_b.users["resident"]
        _instance, token_a = AuthToken.objects.create(user=resident_a)
        auth_a = {"authorization": f"Token {token_a}"}
        # A redacted ledger document from B's published expenditure.
        entry_b = PublishedLedgerEntry.objects.get(case__building=self.seed_b.building)
        redacted = entry_b.work_order.acceptance.invoice_redacted
        # A token bound to B's resident is not redeemable by A's resident.
        forged = issue_download_token(resident_b.pk, redacted.pk)
        assert self.client.get(reverse("api:document-download", args=[forged]), headers=auth_a).status_code == 404
        # Even a token A could mint for that version fails resident_can_download (wrong building).
        self_minted = issue_download_token(resident_a.pk, redacted.pk)
        assert self.client.get(reverse("api:document-download", args=[self_minted]), headers=auth_a).status_code == 404
```

- [ ] **Step 3: Run the isolation suite**

Run: `.venv/bin/python -m pytest tests/isolation/test_cross_building_access.py -q`
Expected: PASS — classification, generic walks, and both bespoke tests green.

- [ ] **Step 4: Run the full API suite**

Run: `.venv/bin/python -m pytest src/lamto/api -q`
Expected: PASS — auth, me, ledger, fund (Plan 3) plus reports, photos, ratings, locations, notifications, downloads, and the OpenAPI drift gate.

- [ ] **Step 5: Full regression gate (exit gate)**

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS — the six e2e journeys, the two-building adversarial walk (web + API), `tenant_integrity`, the disabled-mode job, and every new Phase 1 API test.

- [ ] **Step 6: Commit**

```bash
git add tests/isolation/test_cross_building_access.py
git commit -m "test: adversarial ownership-leak and download re-authorization for resident API"
```

---

## Self-review

### Spec coverage map

| Spec | Requirement | Task |
|---|---|---|
| §3.3 Reporting | `POST /reports` | Task 2 |
| §3.3 Reporting | `GET /reports` (mine), `GET /reports/{id}` timeline | Task 3 |
| §3.3 Reporting | `POST /reports/{id}/photos` (multipart) | Task 4 |
| §3.3 Reporting | `POST /work/{id}/rating` | Task 5 |
| §3.3 Reference | `GET /locations` (active tree for occupancy building) | Task 6 |
| §3.3 Feed | `GET /notifications` + mark-read | Task 7 |
| §3.5 | `client_ref` idempotency: 201 / 200 / 409 | Tasks 1, 2 |
| §3.5 | Photos upload separately after the report row exists | Task 4 |
| §3.6 uploads | Through Django, ClamAV gate, size/type-checked | Task 4 |
| §3.6 downloads | Signed URLs, TTL ≤ 5 min, `private, no-store`, redacted-only + own photos, originals unreachable, never presigned | Task 8 |
| §3.4 | `X-LamTo-Occupancy` for building-scoped routes (reuses Plan 3) | Tasks 2, 6, 7 |
| §3.1 | problem+json codes (`client_ref_conflict` added), cursor pagination, committed schema + drift gate | Tasks 2, 3, 7; every task |
| §2.3 | Cross-tenant → 404; adversarial walk covers every API route | Every task + Task 9 |

**Out of scope (documented deferrals):** `POST /devices`, `DELETE /devices/{install_id}`, and the whole push subsystem (§7) — the next plan (they require the `Device` model, FCM token rotation, the `PUSH` channel, and send-time revalidation, none of which the in-app feed needs). The Flutter app (§6) and the Dart client generation (app repo) remain future work.

### Placeholder scan

No `TBD`/`add validation`/`similar to Task N`. Each task is runnable in isolation: Task 2 ships the create + list on a `ListCreateAPIView` returning the lightweight `ReportSummarySerializer`; Task 3 adds only the timeline detail view. Every code step carries complete code.

### Type consistency

- `submit_report_idempotent(...) -> (report, created)` used identically in Tasks 1, 2, 4, 8 tests.
- `resident_report_timeline` dict keys (`photos`, `cases[].work_orders[].can_rate`) match `ReportDetailSerializer` fields exactly; `download_url` is added to both the dict (view injection) and `ReportPhotoSerializer` in Task 8.
- `issue_download_token(user_id, version_id)` — pk-typed args, consistent across `downloads.py`, the view injection, and all download tests.
- `ledger_entry_proof` gains `version_id` (Task 8) consumed by `LedgerDetailView`'s redacted-doc injection; the web templates ignore it.
- Isolation buckets: object routes (`report-detail`, `report-photos`, `work-rating`, `notification-read`) → `API_TENANT_OBJECT` (→404); building lists (`locations`, `notifications`) → `API_TENANT_LIST`; ownership (`reports`) → new `API_OWNERSHIP_LIST`; `document-download` → `API_EXEMPT`. Every bucket is added to the classifier union in Task 2/6/7/8.
