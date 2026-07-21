# Stage 2: Request Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give resident requests the full A/B/C/D outcome lifecycle (info-request loop, decline with reason, direct handling with progress updates, proposal) on the report/case pair, make ratings binary, and delete `WorkOrder` — the case becomes the work container.

**Architecture:** Additive model groundwork first (statuses, `InfoRequest`, `is_private`, `missing_information`), then outcomes A/B as report-level services, then a mechanical finance re-anchor (`Proposal`/`AcceptanceRecord` from WorkOrder → case), then the case-work cutover that deletes WorkOrder (progress updates, completion, binary rating, 14-day close), and finally e2e/app alignment. Resident-visible status lives on `IssueReport`; the `MaintenanceCase` is the Management-side work container created at triage confirmation.

**Tech Stack:** Django 5 + pytest-django + Postgres 17 (docker compose), OpenAPI YAML at `docs/api/openapi-v1.yaml` + dart-dio client regen (`app/tool/generate_api.sh`), Flutter app.

**Spec:** `docs/superpowers/specs/2026-07-21-two-role-rebuild-design.md` §2 (+§7 stage 2).

## Global Constraints

- Report status machine (spec §2, verbatim): `SUBMITTED → IN_REVIEW → NEEDS_INFO → (DECLINED | IN_PROGRESS | PROPOSED) → COMPLETED → CLOSED`.
- One open `InfoRequest` per report at a time. No chat, no escalation, no disputes, no appeals.
- Rating is binary Satisfied / Not satisfied + optional comment, one per reporter per case; a report closes when its reporter rates or 14 days after completion, whichever comes first (`RATING_WINDOW_DAYS = 14`).
- `is_private` requests: outcomes A/B/C only (proposal creation refuses), excluded from duplicate candidates.
- AI stays suggest-only; `missing_information` is a new **required** key in the provider response contract (list of strings, may be empty).
- "Department" is relabeled **"Management queue"** in user-facing copy only; the model field name `department` stays.
- Test environment (once per shell): `docker compose up -d && set -a; . ./.env; set +a && export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner`. Module tests `uv run pytest src/lamto/<app> -q`; full suite `uv run pytest src/lamto tests -q`. Stale test DB: `docker exec lamto-db-1 psql -U lamto_bootstrap -d postgres -c "DROP DATABASE IF EXISTS test_lamto;"`.
- No data preservation; new migrations via `makemigrations` only, never edit existing ones.
- Flutter app changes in this stage are the minimal compatibility patch (rating shape + status strings + regenerated client); the full UX build-out is stage 4.

---

### Task 1: Lifecycle model groundwork (statuses, InfoRequest, is_private, missing_information)

**Files:**
- Modify: `src/lamto/maintenance/models.py` (IssueReport.Status ~line 50, decline/private fields, `MaintenanceCase.completed_at/closed_at` ~line 148, new `InfoRequest` model after `CaseReport`), `src/lamto/maintenance/ai.py` (RESPONSE_KEYS ~line 29, `_validate_response` ~line 78, suggestion create + job completion status writes in `_process_claimed_job`/`_manual`), `src/lamto/maintenance/candidates.py` (exclude private), plus every file the Step 6 grep finds using `Status.OPEN`/`Status.RESOLVED`.
- Test: `src/lamto/maintenance/tests/test_lifecycle_models.py` (new), existing `test_ai.py`-style triage tests (find via `grep -rln "_validate_response\|RESPONSE_KEYS" src/lamto/maintenance/tests`).
- Create (generated): maintenance migration.

**Interfaces:**
- Consumes: existing models.
- Produces: `IssueReport.Status` with 8 values (below) and default `SUBMITTED`; fields `IssueReport.is_private: bool`, `declined_reason: str`, `declined_by: User|None`, `declined_at: datetime|None`; `MaintenanceCase.completed_at/closed_at: datetime|None`; `InfoRequest(report, message, created_by, created_at, reply_text, resolved_at)` with related_name `info_requests`; `TriageSuggestion.missing_information: list[str]`. All later tasks use exactly these names.

- [ ] **Step 1: Write the failing model tests**

```python
# src/lamto/maintenance/tests/test_lifecycle_models.py
from django.db import IntegrityError
from django.test import TestCase

from lamto.accounts.models import Building, Unit, User
from lamto.maintenance.models import BuildingLocation, InfoRequest, IssueReport


def _report(**kwargs):
    building = Building.objects.create(name=kwargs.pop("bname", "B1"))
    unit = Unit.objects.create(building=building, label="A-101")
    location = BuildingLocation.objects.create(building=building, name="Lobby")
    reporter = User.objects.create_user(
        email=kwargs.pop("email", "r@x.vn"), password="pw", display_name="R"
    )
    return IssueReport.objects.create(
        reporter=reporter,
        unit=unit,
        text="Broken light",
        selected_location=location,
        location_path_snapshot="B1 / Lobby",
        **kwargs,
    )


class LifecycleModelTests(TestCase):
    def test_new_report_defaults(self):
        report = _report()
        self.assertEqual(report.status, IssueReport.Status.SUBMITTED)
        self.assertFalse(report.is_private)
        self.assertEqual(report.declined_reason, "")
        self.assertIsNone(report.declined_at)

    def test_status_values(self):
        self.assertEqual(
            set(IssueReport.Status.values),
            {"SUBMITTED", "IN_REVIEW", "NEEDS_INFO", "DECLINED",
             "IN_PROGRESS", "PROPOSED", "COMPLETED", "CLOSED"},
        )

    def test_one_open_info_request_per_report(self):
        report = _report()
        manager = User.objects.create_user(email="m@x.vn", password="pw", display_name="M")
        InfoRequest.objects.create(report=report, message="Which floor?", created_by=manager)
        with self.assertRaises(IntegrityError):
            InfoRequest.objects.create(report=report, message="Photo?", created_by=manager)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest src/lamto/maintenance/tests/test_lifecycle_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'InfoRequest'`.

- [ ] **Step 3: Model changes**

`IssueReport.Status` becomes:

```python
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        IN_REVIEW = "IN_REVIEW", "In review"
        NEEDS_INFO = "NEEDS_INFO", "Needs information"
        DECLINED = "DECLINED", "Declined"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        PROPOSED = "PROPOSED", "Proposed"
        COMPLETED = "COMPLETED", "Completed"
        CLOSED = "CLOSED", "Closed"
```

with `default=Status.SUBMITTED`. Add to `IssueReport`:

```python
    is_private = models.BooleanField(default=False)
    declined_reason = models.TextField(blank=True)
    declined_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="declined_reports",
    )
    declined_at = models.DateTimeField(null=True, blank=True)
```

Add to `MaintenanceCase`:

```python
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
```

Add to `TriageSuggestion`: `missing_information = models.JSONField(default=list)`.

New model after `CaseReport`:

```python
class InfoRequest(models.Model):
    """Outcome A: one simple information-request loop per report at a time."""

    report = models.ForeignKey(IssueReport, on_delete=models.PROTECT, related_name="info_requests")
    message = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    reply_text = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["report"],
                condition=models.Q(resolved_at__isnull=True),
                name="one_open_info_request_per_report",
            )
        ]
```

- [ ] **Step 4: AI contract — `missing_information`**

`src/lamto/maintenance/ai.py`: add `"missing_information"` to `RESPONSE_KEYS`. In `_validate_response`, after the `deadline_minutes` check:

```python
    missing = payload["missing_information"]
    if type(missing) is not list or any(not _valid_string(item) for item in missing):
        raise TriageValidationError("response missing_information is invalid")
```

Where the `TriageSuggestion` is created in `_process_claimed_job`, add `missing_information=payload["missing_information"],`. In the same function, after the job is marked SUCCEEDED, and in `_manual` after NEEDS_MANUAL, move the report into review:

```python
    IssueReport.objects.filter(
        pk=job.report_id, status=IssueReport.Status.SUBMITTED
    ).update(status=IssueReport.Status.IN_REVIEW)
```

(import `IssueReport` at top; in `_manual` the job's report id is `job.report_id`). Update the AI tests' mock payload fixtures to include `"missing_information": []` (find them: `grep -rln "duplicate_report_ids" src/lamto/maintenance/tests`), and add one test asserting a non-list `missing_information` routes to NEEDS_MANUAL.

- [ ] **Step 5: Private exclusion from duplicates**

`src/lamto/maintenance/candidates.py::find_duplicate_candidates` — add `.exclude(is_private=True)` (or `is_private=False` filter) to the candidate queryset.

- [ ] **Step 6: Old-status sweep**

Run: `grep -rn "Status.OPEN\|Status.RESOLVED\|\"OPEN\"\|\"RESOLVED\"" src/lamto tests app/lib --include="*.py" --include="*.dart" | grep -v __pycache__ | grep -v migrations`
For every Python hit: `OPEN` (meaning "awaiting handling") → the check that fits the site (`status in {SUBMITTED, IN_REVIEW, NEEDS_INFO}` for "still open" gates; the attach-photo gate in `reporting.py` must also allow `NEEDS_INFO` so replies can add photos); `RESOLVED` → `COMPLETED`/`CLOSED` per site meaning. Dart hits are display-only mappings — extend the app's status label map with the new strings (Vietnamese labels reuse existing terms; exact copy is stage 4's problem, fallback to the raw code is acceptable this stage). The task is incomplete while the grep returns unconverted logic.

- [ ] **Step 7: Migration + green**

```bash
uv run python manage.py makemigrations maintenance
uv run pytest src/lamto/maintenance -q     # all passed
uv run pytest src/lamto tests -q            # all passed
```

- [ ] **Step 8: Commit** — `git commit -am "feat(maintenance): request lifecycle model groundwork"`

---

### Task 2: Outcomes A & B — info-request loop and decline

**Files:**
- Create: `src/lamto/maintenance/cases.py`
- Modify: `src/lamto/notifications/hooks.py` (add `notify_info_requested(info_request)`, `notify_report_declined(report)` following the existing hook pattern — recipients `[report.reporter]`, notification kind strings `"info_requested"`, `"report_declined"`; check the existing `NotificationDelivery` kind field length), `src/lamto/web/views/requests.py` (`report_detail` actions), `src/lamto/web/forms/staff.py` (two new forms), staff template for report detail (`grep -rn "report_detail" src/lamto/web/templates` to locate), `src/lamto/web/action_inbox.py` (new `_review_queue_items`), `src/lamto/api/views.py` + `serializers.py` + `urls.py` (info-reply endpoint; `is_private` on report creation; decline/info fields in timeline), `src/lamto/maintenance/selectors.py` (`resident_report_timeline` gains `declined_reason`, `open_info_request`), `docs/api/openapi-v1.yaml`.
- Test: `src/lamto/maintenance/tests/test_outcomes_ab.py` (new), plus web/api test files per hits.

**Interfaces:**
- Consumes: Task 1 models.
- Produces (exact signatures, used by web + API):
  - `request_information(report, manager, message) -> InfoRequest` — guards: manager is Management for the report's building (`require_management`), report status not in `{DECLINED, COMPLETED, CLOSED}`, no open info request; sets report `NEEDS_INFO`; audits `"request.info_requested"`; notifies reporter.
  - `reply_information(resident, report, text) -> InfoRequest` — guards: resident is `report.reporter`, an open info request exists; sets `reply_text`, `resolved_at=now`, report → `IN_REVIEW`; audits with occupancy metadata like `report.submit` does; notifies nothing (management sees the review queue).
  - `decline_report(report, manager, reason) -> IssueReport` — guards as request_information plus non-empty reason; sets `DECLINED` + the three decline fields; if the report belongs to a case whose other reports are all terminal, closes the case (`active=False`, `closed_at=now`); audits `"request.declined"`; notifies reporter.

- [ ] **Step 1: Write failing service tests**

```python
# src/lamto/maintenance/tests/test_outcomes_ab.py
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.maintenance.cases import decline_report, reply_information, request_information
from lamto.maintenance.models import BuildingLocation, InfoRequest, IssueReport


class OutcomeABTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="B1")
        cls.unit = Unit.objects.create(building=cls.building, label="A-101")
        cls.location = BuildingLocation.objects.create(building=cls.building, name="Lobby")
        cls.resident = User.objects.create_user(email="r@x.vn", password="pw", display_name="R")
        ResidentOccupancy.objects.create(user=cls.resident, unit=cls.unit)
        cls.manager = User.objects.create_user(email="m@x.vn", password="pw", display_name="M")
        ManagementMembership.objects.create(user=cls.manager, building=cls.building)

    def _report(self):
        return IssueReport.objects.create(
            reporter=self.resident, unit=self.unit, text="Leak",
            selected_location=self.location, location_path_snapshot="B1 / Lobby",
            status=IssueReport.Status.IN_REVIEW,
        )

    def test_info_loop_roundtrip(self):
        report = self._report()
        info = request_information(report, self.manager, "Which tap?")
        report.refresh_from_db()
        self.assertEqual(report.status, IssueReport.Status.NEEDS_INFO)
        reply_information(self.resident, report, "Kitchen tap")
        report.refresh_from_db()
        info.refresh_from_db()
        self.assertEqual(report.status, IssueReport.Status.IN_REVIEW)
        self.assertEqual(info.reply_text, "Kitchen tap")
        self.assertIsNotNone(info.resolved_at)

    def test_second_open_info_request_rejected(self):
        report = self._report()
        request_information(report, self.manager, "Which tap?")
        with self.assertRaises(ValidationError):
            request_information(report, self.manager, "And which floor?")

    def test_reply_requires_reporter(self):
        report = self._report()
        request_information(report, self.manager, "Which tap?")
        stranger = User.objects.create_user(email="s@x.vn", password="pw", display_name="S")
        with self.assertRaises(PermissionDenied):
            reply_information(stranger, report, "hi")

    def test_decline_records_reason_and_notifies_state(self):
        report = self._report()
        decline_report(report, self.manager, "Duplicate of an already fixed issue")
        report.refresh_from_db()
        self.assertEqual(report.status, IssueReport.Status.DECLINED)
        self.assertEqual(report.declined_reason, "Duplicate of an already fixed issue")
        self.assertEqual(report.declined_by_id, self.manager.pk)
        self.assertIsNotNone(report.declined_at)

    def test_decline_requires_reason_and_management(self):
        report = self._report()
        with self.assertRaises(ValidationError):
            decline_report(report, self.manager, "   ")
        with self.assertRaises(PermissionDenied):
            decline_report(report, self.resident, "reason")

    def test_terminal_report_cannot_get_info_request(self):
        report = self._report()
        decline_report(report, self.manager, "No.")
        with self.assertRaises(ValidationError):
            request_information(report, self.manager, "Too late?")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest src/lamto/maintenance/tests/test_outcomes_ab.py -q` → `ModuleNotFoundError: No module named 'lamto.maintenance.cases'`.

- [ ] **Step 3: Implement `src/lamto/maintenance/cases.py`**

```python
"""Request-outcome services on the report/case pair (spec §2, outcomes A–D)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.accounts.models import ResidentOccupancy
from lamto.accounts.services import require_management
from lamto.audit.services import record_audit

from .models import CaseReport, InfoRequest, IssueReport

TERMINAL_STATUSES = frozenset(
    {IssueReport.Status.DECLINED, IssueReport.Status.COMPLETED, IssueReport.Status.CLOSED}
)
RATING_WINDOW_DAYS = 14


def _locked_report(report):
    report = (
        IssueReport.objects.select_for_update()
        .select_related("unit")
        .filter(pk=getattr(report, "pk", None))
        .first()
    )
    if report is None:
        raise ValidationError("Report is required.")
    return report


@transaction.atomic
def request_information(report, manager, message) -> InfoRequest:
    report = _locked_report(report)
    membership = require_management(manager, report.unit.building_id)
    if report.status in TERMINAL_STATUSES:
        raise ValidationError("Closed or declined requests cannot ask for information.")
    if not (message or "").strip():
        raise ValidationError("An information request needs a message.")
    if InfoRequest.objects.filter(report=report, resolved_at__isnull=True).exists():
        raise ValidationError("An information request is already open for this report.")
    info = InfoRequest.objects.create(
        report=report, message=message.strip(), created_by=manager
    )
    report.status = IssueReport.Status.NEEDS_INFO
    report.save(update_fields=["status"])
    record_audit(
        actor=manager, membership=membership, action="request.info_requested",
        target_type="InfoRequest", target_id=str(info.pk), result="accepted",
        metadata={"report_id": report.pk},
    )
    try:
        from lamto.notifications.hooks import notify_info_requested

        notify_info_requested(info)
    except Exception:
        pass
    return info


@transaction.atomic
def reply_information(resident, report, text) -> InfoRequest:
    report = _locked_report(report)
    if report.reporter_id != getattr(resident, "pk", None):
        raise PermissionDenied("Only the reporter may reply to an information request.")
    info = (
        InfoRequest.objects.select_for_update()
        .filter(report=report, resolved_at__isnull=True)
        .first()
    )
    if info is None:
        raise ValidationError("No open information request for this report.")
    if not (text or "").strip():
        raise ValidationError("A reply needs text (photos may be attached separately).")
    occupancy = ResidentOccupancy.objects.filter(
        user=resident, active=True, unit__building_id=report.unit.building_id
    ).first()
    if occupancy is None:
        raise PermissionDenied("Active occupancy in the building is required.")
    info.reply_text = text.strip()
    info.resolved_at = timezone.now()
    info.save(update_fields=["reply_text", "resolved_at"])
    report.status = IssueReport.Status.IN_REVIEW
    report.save(update_fields=["status"])
    record_audit(
        actor=resident, membership=None, action="request.info_replied",
        target_type="InfoRequest", target_id=str(info.pk), result="accepted",
        metadata={"report_id": report.pk, "occupancy_id": occupancy.pk},
    )
    return info


@transaction.atomic
def decline_report(report, manager, reason) -> IssueReport:
    report = _locked_report(report)
    membership = require_management(manager, report.unit.building_id)
    if report.status in TERMINAL_STATUSES:
        raise ValidationError("This request is already closed.")
    if not (reason or "").strip():
        raise ValidationError("Declining a request requires a reason the resident can read.")
    now = timezone.now()
    report.status = IssueReport.Status.DECLINED
    report.declined_reason = reason.strip()
    report.declined_by = manager
    report.declined_at = now
    report.save(update_fields=["status", "declined_reason", "declined_by", "declined_at"])
    for link in CaseReport.objects.filter(report=report).select_related("case"):
        case = link.case
        open_siblings = (
            CaseReport.objects.filter(case=case)
            .exclude(report=report)
            .exclude(report__status__in=TERMINAL_STATUSES)
            .exists()
        )
        if not open_siblings and case.active:
            case.active = False
            case.closed_at = now
            case.save(update_fields=["active", "closed_at"])
    record_audit(
        actor=manager, membership=membership, action="request.declined",
        target_type="IssueReport", target_id=str(report.pk), result="accepted",
        metadata={"reason_length": len(report.declined_reason)},
    )
    try:
        from lamto.notifications.hooks import notify_report_declined

        notify_report_declined(report)
    except Exception:
        pass
    return report
```

Note: `record_audit`'s resident branch whitelists specific actions — add `"request.info_replied"` to the allowed resident actions in `src/lamto/audit/services.py` (same pattern as `report.submit`).

- [ ] **Step 4: Run service tests** — `uv run pytest src/lamto/maintenance/tests/test_outcomes_ab.py -q` → all passed.

- [ ] **Step 5: Notification hooks** — add to `src/lamto/notifications/hooks.py`, following the exact structure of `notify_report_receipt`:

```python
def notify_info_requested(info_request):
    report = info_request.report
    _deliver([report.reporter], "info_requested", {
        "report_id": report.pk, "message": info_request.message,
    })


def notify_report_declined(report):
    _deliver([report.reporter], "report_declined", {
        "report_id": report.pk, "reason": report.declined_reason,
    })
```

(Adapt `_deliver` to whatever the existing hooks call — read two existing hooks and copy their delivery mechanics exactly.)

- [ ] **Step 6: Web actions** — `src/lamto/web/forms/staff.py`:

```python
class InfoRequestForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea, label=_("What information is missing?"))


class DeclineReportForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea, label=_("Reason shown to the resident"))
```

`requests.report_detail`: handle `action == "request_info"` → `request_information(report, request.user, form.cleaned_data["message"])`; `action == "decline"` → `decline_report(...)`; wrap in `try/except ValidationError` with `messages.error`, redirect back to the report. Template: render the two forms when the report is not terminal, show `declined_reason` when declined, show the open info request + reply when present, and display `suggestion.missing_information` + `confidence_percent` in the AI block; relabel the visible "Department" strings to "Management queue" here and in the case templates.

- [ ] **Step 7: Inbox review queue** — `src/lamto/web/action_inbox.py`:

```python
def _review_queue_items(building_id: int) -> list[ActionItem]:
    items = []
    reports = (
        IssueReport.objects.filter(
            building_id=building_id, status=IssueReport.Status.IN_REVIEW,
            triage_decision__isnull=True,
        )
        .order_by("created_at")[:20]
    )
    for report in reports:
        items.append(ActionItem(
            key=f"review-report-{report.pk}",
            label=f"Review request #{report.pk}",
            url_name="web:staff-report-detail", url_kwargs={"pk": report.pk},
            group="triage",
        ))
    return items
```

(Match `ActionItem`'s actual constructor — read the dataclass at the top of the file and mirror `_manual_triage_items`' construction exactly.) Register it in `action_items_for` after `_manual_triage_items`.

- [ ] **Step 8: API** — in `src/lamto/api/`:
  - `serializers.py`: report-create serializer gains `is_private = serializers.BooleanField(required=False, default=False)` (pass through to `submit_report` — add the `is_private=False` parameter to `reporting.submit_report` and set it on the created report); new `InfoReplySerializer` (`text = CharField()`).
  - `views.py`: `class ReportInfoReplyView(APIView)` — POST resolves the report exactly like `ReportDetailView` scopes it (reporter-only), calls `reply_information`, returns `{"report_id": ..., "status": report.status}` with 200; Django `ValidationError` → DRF `ValidationError`, `PermissionDenied` → DRF `PermissionDenied` (mirror `WorkRatingView`'s except blocks).
  - `urls.py`: `path("reports/<int:pk>/info-reply", views.ReportInfoReplyView.as_view(), name="report-info-reply")`.
  - `selectors.resident_report_timeline`: add `"declined_reason": report.declined_reason or None`, `"is_private": report.is_private`, and `"open_info_request": {"id": i.pk, "message": i.message, "created_at": i.created_at} if i else None` (query the open one).
  - `docs/api/openapi-v1.yaml`: add the `info-reply` path, the `is_private` request property, and the new report status enum values + timeline fields, matching the YAML's existing style.
- [ ] **Step 9: Green** — `uv run pytest src/lamto/maintenance src/lamto/api src/lamto/web -q` → all passed; then `uv run pytest src/lamto tests -q` → all passed.
- [ ] **Step 10: Commit** — `git commit -am "feat: outcomes A/B — info-request loop and decline with reason"`

---

### Task 3: Re-anchor proposals and acceptance to the case

**Files:**
- Modify: `src/lamto/finance/models/proposals.py` (`Proposal.work_order` OneToOne → `case = models.OneToOneField(MaintenanceCase, on_delete=models.PROTECT, related_name="proposal")`), `src/lamto/finance/models/execution.py` (`AcceptanceRecord.work_order` → `case = models.OneToOneField(MaintenanceCase, ..., related_name="acceptance")`; drop the `WorkOrder` import), `src/lamto/finance/proposals.py` (`create_proposal(case, creator_membership)`; the report-status write below), `src/lamto/finance/acceptance.py`, `src/lamto/finance/payments.py`, `src/lamto/finance/publication.py`, `src/lamto/finance/integrity.py`, `src/lamto/finance/selectors.py`, `src/lamto/web/views/proposals.py` + `requests.py` + `payments.py`, `src/lamto/web/urls.py` (`s/work/<pk>/propose/` → `s/cases/<int:pk>/propose/`; `s/work/<pk>/accept/` → `s/cases/<int:pk>/accept/`), `src/lamto/web/action_inbox.py` (`_proposal_create_candidates`, `_work_acceptance_items` re-query on cases), `src/lamto/maintenance/models.py` (move the `verification_label` property from WorkOrder to `MaintenanceCase`, same body).
- Test: all `src/lamto/finance/tests/*`, affected web tests.
- Create (generated): finance migration.

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `create_proposal(case, creator_membership) -> Proposal` which also moves every linked non-terminal report to `PROPOSED` and **refuses private requests**; `accept_work(case, ...)` (same remaining signature as today's `accept_work` but first arg is the case); `acceptance.case` / `proposal.case` relations; `MaintenanceCase.verification_label`.

- [ ] **Step 1: Swap the two FK fields** as listed; `uv run python manage.py makemigrations finance`.
- [ ] **Step 2: Mechanical reference sweep.**

Run: `grep -rn "work_order" src/lamto/finance src/lamto/web --include="*.py" | grep -v __pycache__ | grep -v migrations`
Every hit converts `X.work_order` → `X.case`, `work_order.case.building_id` → `case.building_id`, `work_order__case__` lookups → `case__`. In evidence payload builders (`build_proposal_evidence_payload`, `build_payment_evidence_payload`, the acceptance payload builder, publication payload), the `work_order_id`-style payload field becomes `case_id` — recompute every hard-coded payload/hash expectation in tests from the new builders; never paste stale hashes.
- [ ] **Step 3: Outcome D gate in `create_proposal`** — after resolving the locked case and membership, add:

```python
    links = CaseReport.objects.filter(case=locked_case).select_related("report")
    if any(link.report.is_private for link in links):
        raise ValidationError("Private requests cannot become community proposals.")
```

and after the proposal is created:

```python
    IssueReport.objects.filter(
        case_reports__case=locked_case
    ).exclude(status__in=TERMINAL_STATUSES).update(status=IssueReport.Status.PROPOSED)
```

(import `CaseReport`, `IssueReport` from `lamto.maintenance.models` and `TERMINAL_STATUSES` from `lamto.maintenance.cases`).
- [ ] **Step 4: Web moves** — `proposal_create` view takes a case pk; `case_detail` links to it; acceptance form posts to the case route; work-order references in these views/templates → case.
- [ ] **Step 5: Green** — `uv run pytest src/lamto/finance src/lamto/web src/lamto/maintenance -q` then full `uv run pytest src/lamto tests -q` → all passed.
- [ ] **Step 6: Commit** — `git commit -am "refactor(finance)!: anchor proposals and acceptance on the case"`

---

### Task 4: Case work tracking — progress, completion, binary rating, delete WorkOrder

**Files:**
- Modify: `src/lamto/maintenance/models.py` (`WorkUpdate.work_order` → `case = models.ForeignKey(MaintenanceCase, on_delete=models.PROTECT, related_name="updates")`; `CompletionRating`: `work_order` → `case = models.ForeignKey(MaintenanceCase, ..., related_name="completion_ratings")`, `score` → `satisfied = models.BooleanField()`, unique constraint → `fields=["resident", "case"], name="completion_rating_once_per_resident_case"`, drop the score-range check; delete the `WorkOrder` class), `src/lamto/maintenance/cases.py` (add the four services below), `src/lamto/maintenance/ratings.py` (rewrite below), `src/lamto/maintenance/selectors.py` (`resident_report_timeline` — replace the `work_orders` block with case progress + rating state; `rateable_work_orders` → `rateable_cases(user, report)`), `src/lamto/notifications/hooks.py` (delete `notify_work_assigned`; `notify_deadline_risk` takes a case; delete `notify_work_rateable` (completion hook replaces); add `notify_progress_update(update)`, `notify_case_completed(case)` — recipients: the linked reporters), `src/lamto/web/action_inbox.py` (delete `_assigned_work_items`; `_deadline_risk_items` queries active cases past/near `deadline_at`; add `_in_progress_case_items` listing active in-progress cases), `src/lamto/web/views/requests.py` (case actions: start work, publish progress, complete), `src/lamto/web/forms/staff.py` (delete `CreateWorkOrderForm`, `CompleteWorkOrderForm`; add `ProgressUpdateForm` reusing `CompleteWorkOrderForm`'s evidence-upload mechanics), `src/lamto/web/urls.py` (delete the three `s/work/` routes), `src/lamto/web/staff.py` (drop the "Work" nav item), `src/lamto/api/views.py`/`serializers.py`/`urls.py` (rating endpoint swap below), `src/lamto/audit/services.py` (resident action whitelist: `"work.rate"` target `"CompletionRating"` stays valid — keep), `docs/api/openapi-v1.yaml`.
- Delete: `src/lamto/maintenance/workorders.py`, `src/lamto/web/views/work.py`, `src/lamto/web/templates/web/staff/work_order_detail.html`, `src/lamto/maintenance/tests/test_workorders.py`.
- Create: `src/lamto/maintenance/management/commands/close_completed_cases.py`, `src/lamto/maintenance/tests/test_case_work.py`.
- Create (generated): maintenance migration.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces (in `lamto.maintenance.cases`):
  - `start_case_work(case, manager) -> MaintenanceCase` — outcome C/D work start; guards: management, case active + not completed; linked non-terminal reports → `IN_PROGRESS`; audit `"case.work_started"`.
  - `publish_progress(case, manager, cause, result, before_versions=(), after_versions=()) -> WorkUpdate` — guards: management, case active + not completed, non-empty cause/result; evidence versions validated same-building via the `_evidence_versions` logic lifted from `workorders.py`; audit `"case.progress_published"`; notify reporters.
  - `complete_case_work(case, manager, cause, result, before_versions=(), after_versions=()) -> MaintenanceCase` — publishes a final `WorkUpdate` (same validation), sets `completed_at=now`, linked non-terminal reports → `COMPLETED`; audit `"case.work_completed"`; notify reporters (rating invitation).
  - `close_expired_completed_cases(now=None) -> int` — every case with `completed_at <= now - timedelta(days=RATING_WINDOW_DAYS)` and `closed_at IS NULL`: linked `COMPLETED` reports → `CLOSED`, case `active=False, closed_at=now`; returns count.
  - In `lamto.maintenance.ratings`: `rate_completed_case(resident, case, satisfied, comment="") -> CompletionRating` — guards copied from today's `rate_completed_work` (reporter-of-case + active occupancy + once), eligibility `case.completed_at IS NOT NULL`; `satisfied` must be `bool`; after saving, the rater's own report(s) in the case → `CLOSED`; if every linked report is terminal, close the case (`active=False, closed_at=now`).

- [ ] **Step 1: Write failing tests for the case-work services**

```python
# src/lamto/maintenance/tests/test_case_work.py
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.maintenance.cases import (
    close_expired_completed_cases, complete_case_work, publish_progress, start_case_work,
)
from lamto.maintenance.models import (
    BuildingLocation, CaseReport, IssueReport, MaintenanceCase, TriageDecision,
)
from lamto.maintenance.ratings import rate_completed_case


class CaseWorkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="B1")
        cls.unit = Unit.objects.create(building=cls.building, label="A-101")
        cls.location = BuildingLocation.objects.create(building=cls.building, name="Lobby")
        cls.resident = User.objects.create_user(email="r@x.vn", password="pw", display_name="R")
        ResidentOccupancy.objects.create(user=cls.resident, unit=cls.unit)
        cls.manager = User.objects.create_user(email="m@x.vn", password="pw", display_name="M")
        ManagementMembership.objects.create(user=cls.manager, building=cls.building)

    def _case(self):
        report = IssueReport.objects.create(
            reporter=self.resident, unit=self.unit, text="Leak",
            selected_location=self.location, location_path_snapshot="B1 / Lobby",
            status=IssueReport.Status.IN_REVIEW,
        )
        decision = TriageDecision.objects.create(
            report=report, operator=self.manager, category="Plumbing", urgency="HIGH",
            location=self.location, department="Water", deadline_minutes=1440,
        )
        case = MaintenanceCase.objects.create(
            decision=decision, building=self.building, category="Plumbing",
            urgency="HIGH", location=self.location, department="Water",
            deadline_at=timezone.now() + timedelta(days=1),
        )
        CaseReport.objects.create(case=case, report=report, grouped_by=self.manager)
        return case, report

    def test_c_path_start_progress_complete_rate(self):
        case, report = self._case()
        start_case_work(case, self.manager)
        report.refresh_from_db()
        self.assertEqual(report.status, IssueReport.Status.IN_PROGRESS)

        publish_progress(case, self.manager, "Opened wall", "Found burst pipe")
        self.assertEqual(case.updates.count(), 1)

        complete_case_work(case, self.manager, "Replaced pipe", "Water restored")
        case.refresh_from_db()
        report.refresh_from_db()
        self.assertIsNotNone(case.completed_at)
        self.assertEqual(report.status, IssueReport.Status.COMPLETED)

        rating = rate_completed_case(self.resident, case, satisfied=True, comment="OK")
        self.assertTrue(rating.satisfied)
        report.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(report.status, IssueReport.Status.CLOSED)
        self.assertIsNotNone(case.closed_at)

    def test_cannot_rate_before_completion(self):
        case, _ = self._case()
        start_case_work(case, self.manager)
        with self.assertRaises(ValidationError):
            rate_completed_case(self.resident, case, satisfied=False)

    def test_fourteen_day_auto_close(self):
        case, report = self._case()
        start_case_work(case, self.manager)
        complete_case_work(case, self.manager, "Done", "Done")
        MaintenanceCase.objects.filter(pk=case.pk).update(
            completed_at=timezone.now() - timedelta(days=15)
        )
        closed = close_expired_completed_cases()
        self.assertEqual(closed, 1)
        report.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(report.status, IssueReport.Status.CLOSED)
        self.assertIsNotNone(case.closed_at)

    def test_progress_requires_active_uncompleted_case(self):
        case, _ = self._case()
        start_case_work(case, self.manager)
        complete_case_work(case, self.manager, "Done", "Done")
        with self.assertRaises(ValidationError):
            publish_progress(case, self.manager, "More", "Work")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest src/lamto/maintenance/tests/test_case_work.py -q` → ImportError on the new service names.
- [ ] **Step 3: Model migration** (WorkUpdate/CompletionRating re-parent, WorkOrder delete): make the field changes listed in Files, delete the `WorkOrder` class, run `uv run python manage.py makemigrations maintenance`. If `makemigrations` orders the WorkOrder deletion before the FK re-targets and fails, split into two migrations (first re-target, then delete) — both generated, never hand-ordered SQL.
- [ ] **Step 4: Implement the services** in `cases.py` per the Interfaces block. Lift `_evidence_versions` verbatim from `workorders.py` before deleting the file (it validates building + uploader on evidence `DocumentVersion`s and creates `WorkUpdateEvidence` rows with BEFORE/AFTER kinds — keep behavior identical). The shared "write one update" helper:

```python
def _append_update(case, manager, membership, cause, result, before_versions, after_versions):
    if not (cause or "").strip() or not (result or "").strip():
        raise ValidationError("Progress updates need both a cause and a result.")
    update = WorkUpdate.objects.create(case=case, cause=cause.strip(), result=result.strip())
    _evidence_versions(update, before_versions, WorkUpdateEvidence.Kind.BEFORE,
                       case.building_id, manager)
    _evidence_versions(update, after_versions, WorkUpdateEvidence.Kind.AFTER,
                       case.building_id, manager)
    return update
```

(adjust `_evidence_versions`'s parameter order to whatever the lifted code actually takes — keep its internals unchanged). `rate_completed_case` in `ratings.py` mirrors today's `rate_completed_work` guards with the interface changes listed above.
- [ ] **Step 5: The close command** — `src/lamto/maintenance/management/commands/close_completed_cases.py`:

```python
from django.core.management.base import BaseCommand

from lamto.maintenance.cases import close_expired_completed_cases


class Command(BaseCommand):
    help = "Close completed cases whose 14-day rating window has passed."

    def handle(self, *args, **options):
        closed = close_expired_completed_cases()
        self.stdout.write(self.style.SUCCESS(f"Closed {closed} case(s)."))
```

- [ ] **Step 6: Delete the work-order layer** — `git rm src/lamto/maintenance/workorders.py src/lamto/web/views/work.py src/lamto/web/templates/web/staff/work_order_detail.html src/lamto/maintenance/tests/test_workorders.py`; strip the three `s/work/` routes, the nav item, the forms, and the inbox builders as listed in Files; rework `_deadline_risk_items` to query `MaintenanceCase.objects.filter(building_id=..., active=True, completed_at__isnull=True, deadline_at__lt=...)`.
- [ ] **Step 7: Web case actions** — `requests.case_detail` gains POST actions `start_work` / `publish_progress` / `complete_work` calling the three services (ProgressUpdateForm carries cause/result + before/after uploads exactly like the deleted CompleteWorkOrderForm did); the template shows the update timeline (already-existing `_list` partials) and the case's ratings.
- [ ] **Step 8: API rating swap** — in `api/`: replace `WorkRatingView` with:

```python
class CaseRatingView(APIView):
    @extend_schema(
        request=CaseRatingSerializer,
        responses={201: CaseRatingResultSerializer, **problem_responses(400, 401, 403, 404)},
    )
    def post(self, request, pk):
        case = (
            MaintenanceCase.objects.filter(
                pk=pk, case_reports__report__reporter=request.user
            ).distinct().first()
        )
        if case is None:
            raise exceptions.NotFound("Case not found.")
        serializer = CaseRatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rating = rate_completed_case(
                request.user, case,
                serializer.validated_data["satisfied"],
                serializer.validated_data.get("comment", ""),
            )
        except DjangoValidationError as error:
            raise exceptions.ValidationError(error.messages)
        except DjangoPermissionDenied:
            raise exceptions.PermissionDenied("Only residents who reported this case may rate the work.")
        return Response(
            CaseRatingResultSerializer(
                {"id": rating.pk, "case_id": case.pk, "satisfied": rating.satisfied}
            ).data,
            status=201,
        )
```

with `CaseRatingSerializer` (`satisfied = BooleanField()`, `comment = CharField(required=False, allow_blank=True, max_length=500)`) and `CaseRatingResultSerializer` (`id`, `case_id`, `satisfied`). Route: replace `work/<int:pk>/rating` with `path("cases/<int:pk>/rating", views.CaseRatingView.as_view(), name="case-rating")`. Rework `resident_report_timeline`'s `work_orders` block into:

```python
        updates = [
            {"id": u.pk, "cause": u.cause, "result": u.result, "created_at": u.created_at}
            for u in case.updates.order_by("pk")
        ]
        cases.append({
            "id": case.pk, "category": case.category, "urgency": case.urgency,
            "deadline_at": case.deadline_at, "active": case.active,
            "completed_at": case.completed_at, "closed_at": case.closed_at,
            "updates": updates,
            "can_rate": case.completed_at is not None and case.pk not in rated_ids,
        })
```

(`rated_ids` now collected from `CompletionRating...values_list("case_id", flat=True)`). Update `docs/api/openapi-v1.yaml` accordingly (new path, removed path, timeline schema).
- [ ] **Step 9: Sweep and green** —

Run: `grep -rn "WorkOrder\|work_order" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations`
Expected: zero hits (fix any stragglers — factories/e2e hits belong to Task 5; if the driver still references work orders, the full-suite gate below is deferred to Task 5 and ONLY the module gate applies here).
Run: `uv run pytest src/lamto/maintenance src/lamto/finance src/lamto/web src/lamto/api -q` → all passed.
- [ ] **Step 10: Commit** — `git commit -am "feat(maintenance)!: case work tracking with binary rating; delete WorkOrder"`

---

### Task 5: e2e drivers, Flutter compatibility patch, verification

**Files:**
- Modify: `src/lamto/testing/factories.py` (`PilotDomainDriver`: work-order choreography → `start_case_work`/`publish_progress`/`complete_case_work`/`rate_completed_case`; proposal/acceptance calls take the case), `tests/e2e/*` scenarios, `tests/isolation/*` if flagged.
- Modify (app): regenerate `app/packages/lamto_api` via `app/tool/generate_api.sh`; patch the rating screen (score widget → Satisfied / Not satisfied toggle posting `satisfied`), the API call site for the renamed `cases/<pk>/rating` endpoint, and the status label map for the 8 report statuses; update affected widget/unit tests.
- Docs: none this stage (PRODUCT.md etc. is stage 4).

**Interfaces:**
- Consumes: everything above.
- Produces: green full backend suite + green Flutter suite.

- [ ] **Step 1: Driver rework** — replace every `create_work_order`/`start_work_order`/`complete_work_order`/`rate_completed_work` call in `factories.py` and e2e scenarios with the case-work services; the happy-path e2e now runs: submit → triage confirm → (start → progress → complete → rate) and the proposal path: submit → triage confirm → proposal on case → publish → acceptance on case → payment → publication.
- [ ] **Step 2: Backend full green** — `uv run pytest src/lamto tests -q` → all passed.
- [ ] **Step 3: Regenerate the Dart client** — `bash app/tool/generate_api.sh` (needs java or docker), then `bash app/tool/check_api_generated.sh` if it verifies drift.
- [ ] **Step 4: App patch** — find the rating call site: `grep -rn "rating\|WorkRating" app/lib --include="*.dart" | head`; swap to the `CaseRating` client method with `satisfied: bool`; replace the 1–5 score widget with two choice buttons (Satisfied / Not satisfied) preserving the existing form styling; extend the status label map (Task 1 Step 6 already listed the Dart hits). Run `cd app && flutter analyze && flutter test` → green.
- [ ] **Step 5: Final sweeps**

```bash
grep -rn "WorkOrder\|work_order" src/lamto tests app/lib --include="*.py" --include="*.dart" | grep -v __pycache__ | grep -v migrations   # zero hits
grep -rn "score" src/lamto/maintenance src/lamto/api --include="*.py" | grep -v __pycache__ | grep -v migrations                          # zero rating-score hits
```

- [ ] **Step 6: Fresh-DB migration check** — `docker exec lamto-db-1 psql -U lamto_bootstrap -d postgres -c "DROP DATABASE IF EXISTS lamto;" -c "CREATE DATABASE lamto OWNER lamto_owner;" && uv run python manage.py migrate` → clean.
- [ ] **Step 7: Commit** — `git commit -am "feat!: stage 2 complete — request lifecycle on the case, app compatibility patch"`

---

## Self-review notes (already applied)

- Outcome C/D report statuses are driven by explicit service calls (`start_case_work`, `create_proposal`), not signals — matches the codebase's explicit-service style.
- Late-grouped duplicates (`triage.group_report`) adopt case state lazily: `group_report` gains one line setting the new report's status to the case's dominant phase (`IN_PROGRESS` if started, `PROPOSED` if a proposal exists, else `IN_REVIEW`) — add this line + a test in Task 4 Step 7's web work (it lives in `triage.py`).
- Acceptance/payment inbox items keep working across Tasks 3–4 because acceptance re-anchors in Task 3 before WorkOrder dies in Task 4.
- The provider AI contract gains a required `missing_information` key — the external AI service (AI_TRIAGE_URL) must be updated in lockstep; NEEDS_MANUAL fallback covers a non-compliant provider, so a stale provider degrades to manual triage rather than breaking.
