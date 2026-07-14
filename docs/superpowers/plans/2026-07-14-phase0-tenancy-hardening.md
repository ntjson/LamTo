# Phase 0 Plan 1 — Tenancy Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Building` the enforced tenant key across the LamTo monolith — explicit tenant context, shared selectors, database cross-building constraints, tenant-scoped outbox/notifications/quarantine, phone login, a two-building adversarial suite, and an `onboard_building` command — without changing any P1 behavior.

**Architecture:** Spec is `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md` §2 (tenancy) + §5.4 (sequencing: selector extraction first, behind the full existing suite). Django 5.2 modular monolith; all changes are inside existing apps (`accounts`, `maintenance`, `finance`, `evidence`, `notifications`, `documents`, `web`). This plan is #1 of the Phase 0 series; the anchoring port, resident API, and BQL web gaps are separate later plans.

**Tech Stack:** Django 5.2, PostgreSQL (psycopg3), pytest + pytest-django, existing `lamto.testing.factories` seed world. **Zero new pip dependencies.**

## Global Constraints

- **Test environment (verified working):** every `pytest`/`manage.py` command below assumes this shell setup has been run first:

  ```bash
  docker compose up -d db
  set -a; . ./.env.example; set +a
  export SECRET_KEY=test-secret EVIDENCE_WRITE_SECRET=test-evidence \
         POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
  ```

- **Interpreter:** always `.venv/bin/python` (never bare `python`).
- **Regression gate:** `.venv/bin/python -m pytest src/lamto tests -q` must pass after every task. The six e2e journeys in `tests/e2e/` are blocking.
- Money is integer VND; append-only models (`InsertOnlyModel`, `AppendOnlyModel`) are never weakened.
- Status codes: cross-tenant object access → **404**; missing capability inside own tenant → **403** (spec §2.3).
- No secrets in git. UI copy stays English to match existing templates (Vietnamese is client-owned per spec §3.1).
- Migrations are plain Django migrations (deployment is pre-acceptance; no zero-downtime choreography), but every migration must still apply cleanly on top of existing pilot data.
- Commit after every task with the message given in the task's final step.

---

### Task 1: Extract resident read selectors (behavior-preserving)

**Files:**
- Create: `src/lamto/finance/selectors.py`
- Create: `src/lamto/maintenance/selectors.py`
- Create: `src/lamto/finance/tests/test_selectors.py`
- Modify: `src/lamto/web/views/resident.py` (delete `_resident_reports`, `_published_ledger_qs`, `_verified_fund_entries`, `_period_flows`, `_rateable_work_orders`; import replacements)

**Interfaces:**
- Consumes: existing `lamto.finance.fund._source_verified_q`, `_finalized_posting_q`, models.
- Produces (later tasks and the future API rely on these exact names):
  - `lamto.finance.selectors.published_ledger_entries(building_id) -> QuerySet[PublishedLedgerEntry]`
  - `lamto.finance.selectors.verified_fund_entries(building_id) -> QuerySet[MaintenanceFundEntry]`
  - `lamto.finance.selectors.fund_period_flows(building_id, *, days=30) -> tuple[int, int]`
  - `lamto.maintenance.selectors.resident_reports(user) -> QuerySet[IssueReport]`
  - `lamto.maintenance.selectors.rateable_work_orders(user, report) -> QuerySet[WorkOrder]`

- [ ] **Step 1: Confirm the existing suite is green (refactor baseline)**

Run: `.venv/bin/python -m pytest src/lamto/web/tests src/lamto/finance/tests -q`
Expected: all pass.

- [ ] **Step 2: Write the failing test**

Create `src/lamto/finance/tests/test_selectors.py`:

```python
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from lamto.accounts.models import Building
from lamto.finance.models import MaintenanceFund, MaintenanceFundEntry
from lamto.finance.selectors import fund_period_flows, verified_fund_entries


class FundSelectorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Selector Building")
        cls.fund = MaintenanceFund.objects.create(building=cls.building)

    def _entry(self, entry_type, amount, recorded_at, key):
        return MaintenanceFundEntry.objects.create(
            fund=self.fund,
            entry_type=entry_type,
            amount_vnd=amount,
            source_key=key,
            recorded_at=recorded_at,
        )

    def test_period_flows_windows_and_signs(self):
        now = timezone.now()
        self._entry("OPENING_BALANCE", 1_000_000, now - timedelta(days=5), "k-open")
        self._entry("INFLOW", 200_000, now - timedelta(days=40), "k-old-inflow")
        inflows, outflows = fund_period_flows(self.building.pk, days=30)
        # Unverified entries are excluded entirely by the verified bar.
        verified_pks = set(
            verified_fund_entries(self.building.pk).values_list("pk", flat=True)
        )
        assert all(
            pk in verified_pks
            for pk in MaintenanceFundEntry.objects.filter(
                verification__isnull=False
            ).values_list("pk", flat=True)
        )
        assert isinstance(inflows, int) and isinstance(outflows, int)

    def test_other_building_excluded(self):
        other = Building.objects.create(name="Other Building")
        MaintenanceFund.objects.create(building=other)
        assert verified_fund_entries(other.pk).count() == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_selectors.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.finance.selectors'`

- [ ] **Step 4: Create the selector modules**

Create `src/lamto/finance/selectors.py`:

```python
"""Building-scoped read selectors shared by web templates and the future API.

Selectors are the single query path for tenant-scoped reads (spec 2.3, layer 2).
Every function takes an explicit building_id; ownership-scoped selectors take
the owning user. Bodies are moved verbatim from lamto.web.views.resident.
"""

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.fund import _finalized_posting_q, _source_verified_q
from lamto.finance.models import MaintenanceFundEntry, PublishedLedgerEntry


def published_ledger_entries(building_id):
    """Resident-visible published ledger entries for one building, newest first."""
    return (
        PublishedLedgerEntry.objects.filter(
            case__building_id=building_id,
            snapshot__outbox_event__status=BlockchainOutboxEvent.Status.CONFIRMED,
        )
        .select_related(
            "snapshot",
            "snapshot__outbox_event",
            "work_order",
            "case",
            "proposal",
            "proposal__current_version",
            "payment",
            "payment__verification",
            "payment__verification__membership__user",
        )
        .order_by("-published_at", "-pk")
    )


def verified_fund_entries(building_id):
    """Fund rows held to the same verified/finalized bar as fund_balance(verified_only=True)."""
    return MaintenanceFundEntry.objects.filter(fund__building_id=building_id).filter(
        _source_verified_q() | _finalized_posting_q()
    )


def fund_period_flows(building_id, *, days=30):
    """(inflows, outflows) of verified entries in the trailing period, integer VND."""
    since = timezone.now() - timedelta(days=days)
    fund_entries = verified_fund_entries(building_id).filter(recorded_at__gte=since)
    inflows = (
        fund_entries.filter(
            entry_type__in=[
                MaintenanceFundEntry.EntryType.OPENING_BALANCE,
                MaintenanceFundEntry.EntryType.INFLOW,
            ]
        ).aggregate(total=Sum("amount_vnd"))["total"]
        or 0
    )
    outflows = (
        fund_entries.filter(
            entry_type__in=[
                MaintenanceFundEntry.EntryType.OUTFLOW,
                MaintenanceFundEntry.EntryType.REVERSAL,
                MaintenanceFundEntry.EntryType.REPLACEMENT,
            ]
        ).aggregate(total=Sum("amount_vnd"))["total"]
        or 0
    )
    return int(inflows), int(outflows)
```

Create `src/lamto/maintenance/selectors.py`:

```python
"""Read selectors for resident-owned maintenance records (spec 2.3, layer 2)."""

from lamto.maintenance.models import (
    CaseReport,
    CompletionRating,
    IssueReport,
    WorkOrder,
)
from lamto.maintenance.ratings import ELIGIBLE_STATUSES


def resident_reports(user):
    """Reports the user submitted, newest first (ownership scope)."""
    return (
        IssueReport.objects.filter(reporter=user)
        .select_related("unit", "selected_location")
        .order_by("-created_at", "-pk")
    )


def rateable_work_orders(user, report):
    """Completed work on the report's cases the user has not rated yet."""
    case_ids = CaseReport.objects.filter(report=report).values_list("case_id", flat=True)
    rated = CompletionRating.objects.filter(resident=user).values_list(
        "work_order_id", flat=True
    )
    return WorkOrder.objects.filter(
        case_id__in=case_ids,
        status__in=ELIGIBLE_STATUSES,
    ).exclude(pk__in=rated)
```

- [ ] **Step 5: Rewire `resident.py` to the selectors**

In `src/lamto/web/views/resident.py`:

1. Delete the function definitions `_resident_reports`, `_published_ledger_qs`, `_verified_fund_entries`, `_period_flows`, and `_rateable_work_orders` (keep `_active_occupancy`, `_require_resident`, `_integrity_display`, `_apply_integrity_display` — they change in Task 2).
2. Replace the import block additions/removals at the top:

```python
from lamto.finance.selectors import (
    fund_period_flows,
    published_ledger_entries,
    verified_fund_entries,
)
from lamto.maintenance.selectors import rateable_work_orders, resident_reports
```

Remove now-unused imports: `from datetime import timedelta`, `from django.db.models import Sum`, `from django.utils import timezone`, `from lamto.evidence.models import BlockchainOutboxEvent`, `from lamto.maintenance.ratings import ELIGIBLE_STATUSES`, `CompletionRating` from the maintenance models import, and `_finalized_posting_q` / `_source_verified_q` from the `lamto.finance.fund` import (keep `fund_balance`).
3. Rename call sites throughout the file: `_resident_reports(` → `resident_reports(`, `_published_ledger_qs(` → `published_ledger_entries(`, `_verified_fund_entries(` → `verified_fund_entries(`, `_period_flows(` → `fund_period_flows(`, `_rateable_work_orders(` → `rateable_work_orders(`.

- [ ] **Step 6: Run the new test and the regression baseline**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_selectors.py src/lamto/web/tests -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS (full suite; this is the behavior-preservation proof).

- [ ] **Step 7: Commit**

```bash
git add src/lamto/finance/selectors.py src/lamto/maintenance/selectors.py \
        src/lamto/finance/tests/test_selectors.py src/lamto/web/views/resident.py
git commit -m "refactor: extract building-scoped resident selectors"
```

---

### Task 2: TenantContext and explicit occupancy resolution

**Files:**
- Create: `src/lamto/accounts/tenancy.py`
- Create: `src/lamto/accounts/tests/test_tenancy.py`
- Modify: `src/lamto/web/views/resident.py` (all 8 resident views)
- Modify: `src/lamto/web/forms/resident.py:64-79` (`ResidentReportForm.__init__`)

**Interfaces:**
- Produces (Tasks 3 and 9, plus the future API, rely on these exact names):
  - `lamto.accounts.tenancy.SESSION_OCCUPANCY_KEY: str = "active_occupancy_id"`
  - `lamto.accounts.tenancy.TenantContext` frozen dataclass: `building_id: int`, `actor: str`, `occupancy_id: int | None`, `membership_id: int | None`; classmethods `from_occupancy(occupancy)`, `from_membership(membership)`
  - `lamto.accounts.tenancy.resolve_resident_occupancy(request, *, occupancy_id=None) -> tuple[ResidentOccupancy, list[ResidentOccupancy]]`
- `ResidentReportForm(..., resident=user, occupancy=occupancy)` — new keyword argument.

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/accounts/tests/test_tenancy.py`:

```python
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory, TestCase

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.accounts.tenancy import (
    SESSION_OCCUPANCY_KEY,
    TenantContext,
    resolve_resident_occupancy,
)


class ResolveResidentOccupancyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="resident@example.test", password="x", display_name="R"
        )
        cls.building_a = Building.objects.create(name="Building A")
        cls.building_b = Building.objects.create(name="Building B")
        cls.unit_a = Unit.objects.create(building=cls.building_a, label="A-101")
        cls.unit_b = Unit.objects.create(building=cls.building_b, label="B-202")
        cls.occ_a = ResidentOccupancy.objects.create(user=cls.user, unit=cls.unit_a)

    def _request(self, user):
        request = RequestFactory().get("/")
        request.user = user
        request.session = SessionStore()
        return request

    def test_no_occupancy_denied(self):
        stranger = get_user_model().objects.create_user(
            email="none@example.test", password="x", display_name="N"
        )
        with self.assertRaises(PermissionDenied):
            resolve_resident_occupancy(self._request(stranger))

    def test_sole_occupancy_auto_selected_and_pinned(self):
        request = self._request(self.user)
        occupancy, occupancies = resolve_resident_occupancy(request)
        assert occupancy.pk == self.occ_a.pk
        assert [o.pk for o in occupancies] == [self.occ_a.pk]
        assert request.session[SESSION_OCCUPANCY_KEY] == self.occ_a.pk

    def test_multiple_defaults_to_first_and_session_switches(self):
        occ_b = ResidentOccupancy.objects.create(user=self.user, unit=self.unit_b)
        request = self._request(self.user)
        occupancy, _ = resolve_resident_occupancy(request)
        assert occupancy.pk == self.occ_a.pk
        request.session[SESSION_OCCUPANCY_KEY] = occ_b.pk
        occupancy, _ = resolve_resident_occupancy(request)
        assert occupancy.pk == occ_b.pk

    def test_stale_session_falls_back_and_repins(self):
        occ_b = ResidentOccupancy.objects.create(user=self.user, unit=self.unit_b)
        request = self._request(self.user)
        request.session[SESSION_OCCUPANCY_KEY] = occ_b.pk
        ResidentOccupancy.objects.filter(pk=occ_b.pk).update(active=False)
        occupancy, _ = resolve_resident_occupancy(request)
        assert occupancy.pk == self.occ_a.pk
        assert request.session[SESSION_OCCUPANCY_KEY] == self.occ_a.pk

    def test_explicit_foreign_id_raises_404(self):
        other = get_user_model().objects.create_user(
            email="other@example.test", password="x", display_name="O"
        )
        foreign = ResidentOccupancy.objects.create(user=other, unit=self.unit_b)
        with self.assertRaises(Http404):
            resolve_resident_occupancy(
                self._request(self.user), occupancy_id=foreign.pk
            )

    def test_tenant_context_from_occupancy(self):
        context = TenantContext.from_occupancy(self.occ_a)
        assert context.building_id == self.building_a.pk
        assert context.actor == "resident"
        assert context.occupancy_id == self.occ_a.pk
        assert context.membership_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/accounts/tests/test_tenancy.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.accounts.tenancy'`

- [ ] **Step 3: Implement `tenancy.py`**

Create `src/lamto/accounts/tenancy.py`:

```python
"""Tenant-context resolution (spec 2.3 layer 1, 2.4).

Staff requests already carry their tenant context as the active
OrganizationMembership (lamto.web.staff.resolve_active_membership); the
membership IS the staff context. Resident requests resolve an explicit active
ResidentOccupancy here — never `.first()` by accident. TenantContext is the
frozen carrier handed to selectors by both presentation layers (templates now,
API later).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.http import Http404

from lamto.accounts.models import ResidentOccupancy

SESSION_OCCUPANCY_KEY = "active_occupancy_id"


@dataclass(frozen=True)
class TenantContext:
    building_id: int
    actor: str  # "resident" | "staff"
    occupancy_id: int | None = None
    membership_id: int | None = None

    @classmethod
    def from_occupancy(cls, occupancy) -> "TenantContext":
        return cls(
            building_id=occupancy.unit.building_id,
            actor="resident",
            occupancy_id=occupancy.pk,
        )

    @classmethod
    def from_membership(cls, membership) -> "TenantContext":
        return cls(
            building_id=membership.organization.building_id,
            actor="staff",
            membership_id=membership.pk,
        )


def active_occupancies(user):
    return (
        ResidentOccupancy.objects.select_related("unit__building")
        .filter(user=user, active=True)
        .order_by("pk")
    )


def resolve_resident_occupancy(request, *, occupancy_id=None):
    """Resolve and pin the resident's active occupancy for this request.

    Priority: explicit occupancy_id -> session -> sole/first occupancy.
    An explicit id that is not the caller's own active occupancy raises 404
    (cross-tenant convention); a stale session id silently falls back and
    repins. Raises PermissionDenied when the user has no active occupancy.
    Returns (selected, all_active) so views can render the switcher.
    """
    occupancies = list(active_occupancies(request.user))
    if not occupancies:
        raise PermissionDenied("Active resident occupancy is required.")

    def _find(candidate):
        try:
            cid = int(candidate)
        except (TypeError, ValueError):
            return None
        return next((o for o in occupancies if o.pk == cid), None)

    selected = None
    if occupancy_id is not None:
        selected = _find(occupancy_id)
        if selected is None:
            raise Http404("Occupancy not found.")
    if selected is None:
        session_id = request.session.get(SESSION_OCCUPANCY_KEY)
        if session_id is not None:
            selected = _find(session_id)
    if selected is None:
        selected = occupancies[0]
    if request.session.get(SESSION_OCCUPANCY_KEY) != selected.pk:
        request.session[SESSION_OCCUPANCY_KEY] = selected.pk
    return selected, occupancies
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/accounts/tests/test_tenancy.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Rewire resident views and form**

In `src/lamto/web/views/resident.py`:

1. Delete `_active_occupancy` and `_require_resident`; remove the now-unused `from lamto.accounts.models import ResidentOccupancy` import.
2. Add import: `from lamto.accounts.tenancy import resolve_resident_occupancy`.
3. In each of `home`, `report_create`, `report_list`, `report_detail`, `work_rate`, `ledger_list`, `ledger_detail`: replace the line `occupancy = _require_resident(request.user)` with `occupancy, _occupancies = resolve_resident_occupancy(request)`.
4. In `account`: replace with `occupancy, occupancies = resolve_resident_occupancy(request)` and add `"occupancies": occupancies,` to the render context dict (Task 3's template consumes it).
5. In `report_create`, pass the resolved occupancy into the form:

```python
    form = ResidentReportForm(
        request.POST or None,
        request.FILES or None,
        resident=request.user,
        occupancy=occupancy,
    )
```

In `src/lamto/web/forms/resident.py`, replace `ResidentReportForm.__init__` (currently re-deriving the occupancy with `.first()`):

```python
    def __init__(self, *args, resident=None, occupancy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resident = resident
        self.occupancy = occupancy
        if self.occupancy is not None:
            self.fields["location"].queryset = BuildingLocation.objects.filter(
                building_id=self.occupancy.unit.building_id,
                active=True,
            ).order_by("name")
```

Remove the now-unused `ResidentOccupancy` import from that file if nothing else references it.

If any existing test constructs `ResidentReportForm(resident=...)` directly (rather than posting through the view), pass its occupancy as `occupancy=...` too — the form no longer derives one itself.

- [ ] **Step 6: Run the affected suites**

Run: `.venv/bin/python -m pytest src/lamto/web/tests src/lamto/accounts/tests -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/lamto/accounts/tenancy.py src/lamto/accounts/tests/test_tenancy.py \
        src/lamto/web/views/resident.py src/lamto/web/forms/resident.py
git commit -m "feat: explicit resident occupancy resolution with TenantContext"
```

---

### Task 3: Occupancy switcher in Account

**Files:**
- Modify: `src/lamto/web/views/resident.py` (new view `switch_occupancy`)
- Modify: `src/lamto/web/urls.py` (new route)
- Modify: `src/lamto/web/templates/web/resident/account.html`
- Create: `src/lamto/web/tests/test_occupancy_switch.py`

**Interfaces:**
- Consumes: `resolve_resident_occupancy` from Task 2.
- Produces: route `web:switch-occupancy` (`POST /r/occupancy/`, form fields `occupancy`, optional `next`).

- [ ] **Step 1: Write the failing test**

Create `src/lamto/web/tests/test_occupancy_switch.py`:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.accounts.tenancy import SESSION_OCCUPANCY_KEY


class OccupancySwitchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="switcher@example.test", password="pw", display_name="S"
        )
        cls.building_a = Building.objects.create(name="Switch Building A")
        cls.building_b = Building.objects.create(name="Switch Building B")
        unit_a = Unit.objects.create(building=cls.building_a, label="A-1")
        unit_b = Unit.objects.create(building=cls.building_b, label="B-1")
        cls.occ_a = ResidentOccupancy.objects.create(user=cls.user, unit=unit_a)
        cls.occ_b = ResidentOccupancy.objects.create(user=cls.user, unit=unit_b)

    def setUp(self):
        self.client.force_login(self.user)

    def test_switch_pins_session_and_redirects_home(self):
        response = self.client.post(
            reverse("web:switch-occupancy"), {"occupancy": self.occ_b.pk}
        )
        assert response.status_code == 302
        assert self.client.session[SESSION_OCCUPANCY_KEY] == self.occ_b.pk

    def test_foreign_occupancy_is_404(self):
        other = get_user_model().objects.create_user(
            email="other2@example.test", password="pw", display_name="O"
        )
        foreign = ResidentOccupancy.objects.create(
            user=other, unit=Unit.objects.create(building=self.building_a, label="A-2")
        )
        response = self.client.post(
            reverse("web:switch-occupancy"), {"occupancy": foreign.pk}
        )
        assert response.status_code == 404

    def test_get_not_allowed(self):
        assert self.client.get(reverse("web:switch-occupancy")).status_code == 405

    def test_account_lists_switcher_only_for_multi_occupancy(self):
        response = self.client.get(reverse("web:account"))
        self.assertContains(response, "Switch unit")
        self.assertContains(response, "Switch Building B")

    def test_unsafe_next_is_ignored(self):
        response = self.client.post(
            reverse("web:switch-occupancy"),
            {"occupancy": self.occ_a.pk, "next": "https://evil.example/"},
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("web:resident-home")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_occupancy_switch.py -q`
Expected: FAIL with `NoReverseMatch: Reverse for 'switch-occupancy' not found`

- [ ] **Step 3: Implement view, route, template**

In `src/lamto/web/views/resident.py` add (near `account`), plus `from django.utils.http import url_has_allowed_host_and_scheme` to the imports:

```python
@login_required
@require_http_methods(["POST"])
def switch_occupancy(request):
    occupancy_id = request.POST.get("occupancy")
    if occupancy_id is None:
        raise Http404("occupancy is required")
    resolve_resident_occupancy(request, occupancy_id=occupancy_id)
    next_url = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = ""
    return redirect(next_url or "web:resident-home")
```

In `src/lamto/web/urls.py`, after the `web:account` path, add:

```python
    path("r/occupancy/", resident.switch_occupancy, name="switch-occupancy"),
```

In `src/lamto/web/templates/web/resident/account.html`, insert this section between the first `</section>` (account details) and the "In-app notices" section:

```html
{% if occupancies|length > 1 %}
<section class="panel" aria-labelledby="occupancy-heading">
  <h2 id="occupancy-heading">Active unit</h2>
  <p class="hint">Reports and the ledger show the building of your active unit.</p>
  <form method="post" action="{% url 'web:switch-occupancy' %}" class="stack-form">
    {% csrf_token %}
    <div class="field">
      <label for="occupancy-select">Unit</label>
      <select id="occupancy-select" name="occupancy">
        {% for o in occupancies %}
        <option value="{{ o.pk }}" {% if o.pk == occupancy.pk %}selected{% endif %}>
          {{ o.unit.building.name }} · {{ o.unit.label }}
        </option>
        {% endfor %}
      </select>
    </div>
    <button type="submit" class="button">Switch unit</button>
  </form>
</section>
{% endif %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_occupancy_switch.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/web/views/resident.py src/lamto/web/urls.py \
        src/lamto/web/templates/web/resident/account.html \
        src/lamto/web/tests/test_occupancy_switch.py
git commit -m "feat: resident occupancy switcher in account"
```

---

### Task 4: `User.phone` and phone-or-email login

**Files:**
- Modify: `src/lamto/accounts/models.py:8-14` (`User`)
- Create: `src/lamto/accounts/backends.py`
- Create: migration `src/lamto/accounts/migrations/` (generated `..._user_phone.py`)
- Modify: `src/lamto/config/settings.py` (add `AUTHENTICATION_BACKENDS` next to `AUTH_USER_MODEL`, line ~157)
- Modify: `src/lamto/web/templates/web/resident/login.html:6` (lede copy)
- Create: `src/lamto/accounts/tests/test_phone_auth.py`

**Interfaces:**
- Produces:
  - `User.phone: CharField(max_length=20, unique=True, null=True, blank=True)` — canonical local form `0xxxxxxxxx`.
  - `lamto.accounts.backends.normalize_phone(raw) -> str | None`
  - `lamto.accounts.backends.PhoneOrEmailBackend` — sole entry in `AUTHENTICATION_BACKENDS`.
- Tasks 9–10 and the future API log residents in by phone through the standard Django auth flow; nothing else changes.

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/accounts/tests/test_phone_auth.py`:

```python
from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase

from lamto.accounts.backends import normalize_phone


class NormalizePhoneTests(TestCase):
    def test_accepts_local_and_international_forms(self):
        assert normalize_phone("0901234567") == "0901234567"
        assert normalize_phone("+84 90 123 4567") == "0901234567"
        assert normalize_phone("84901234567") == "0901234567"
        assert normalize_phone("090-123-4567") == "0901234567"

    def test_rejects_non_phones(self):
        assert normalize_phone("") is None
        assert normalize_phone(None) is None
        assert normalize_phone("resident@example.test") is None
        assert normalize_phone("12345") is None


class PhoneOrEmailBackendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="phone-user@example.test", password="pw-secret", display_name="P"
        )
        cls.user.phone = "0901234567"
        cls.user.save(update_fields=["phone"])

    def test_email_login_still_works(self):
        assert authenticate(None, username="phone-user@example.test", password="pw-secret") == self.user

    def test_phone_login_works_with_formatting(self):
        assert authenticate(None, username="+84 901 234 567", password="pw-secret") == self.user

    def test_wrong_password_fails(self):
        assert authenticate(None, username="0901234567", password="nope") is None

    def test_inactive_user_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        assert authenticate(None, username="0901234567", password="pw-secret") is None

    def test_login_view_accepts_phone(self):
        self.client.logout()
        response = self.client.post(
            "/accounts/login/",
            {"username": "0901234567", "password": "pw-secret"},
        )
        assert response.status_code == 302
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/accounts/tests/test_phone_auth.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.accounts.backends'`

- [ ] **Step 3: Implement field, backend, settings, template**

In `src/lamto/accounts/models.py`, add to `User` after `display_name`:

```python
    phone = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text="Canonical local form 0xxxxxxxxx; residents may log in with it.",
    )
```

Create `src/lamto/accounts/backends.py`:

```python
"""Phone-or-email authentication (spec 2.1: residents log in by phone)."""

import re

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

_SEPARATORS = re.compile(r"[\s.\-()]+")
_VN_PHONE = re.compile(r"^0\d{9,10}$")


def normalize_phone(raw):
    """Return the canonical local phone form (0xxxxxxxxx) or None."""
    if not raw:
        return None
    value = _SEPARATORS.sub("", str(raw))
    if value.startswith("+84"):
        value = "0" + value[3:]
    elif value.startswith("84") and len(value) >= 11:
        value = "0" + value[2:]
    if _VN_PHONE.fullmatch(value):
        return value
    return None


class PhoneOrEmailBackend(ModelBackend):
    """Authenticate with email (staff) or Vietnamese phone number (residents)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        phone = normalize_phone(username)
        try:
            if phone is not None:
                user = UserModel.objects.get(phone=phone)
            else:
                user = UserModel.objects.get(email__iexact=username)
        except UserModel.DoesNotExist:
            # Run a hash anyway so lookup misses take the same time.
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
```

In `src/lamto/config/settings.py`, directly under `AUTH_USER_MODEL = "accounts.User"`:

```python
AUTHENTICATION_BACKENDS = ["lamto.accounts.backends.PhoneOrEmailBackend"]
```

In `src/lamto/web/templates/web/resident/login.html`, change the lede line to:

```html
  <p class="lede">Use your account email or phone number, and your password.</p>
```

Generate the migration:

Run: `.venv/bin/python manage.py makemigrations accounts`
Expected: one new migration adding `phone` to `user` (note the generated filename for the commit).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/accounts/tests/test_phone_auth.py -q`
Expected: PASS (7 tests).

Run: `.venv/bin/python -m pytest src/lamto/accounts src/lamto/web/tests -q`
Expected: PASS (login/MFA suites still green with the new backend).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/accounts/models.py src/lamto/accounts/backends.py \
        src/lamto/accounts/migrations/ src/lamto/config/settings.py \
        src/lamto/web/templates/web/resident/login.html \
        src/lamto/accounts/tests/test_phone_auth.py
git commit -m "feat: phone-or-email login with unique User.phone"
```

---

### Task 5: Immutable `building` on `BlockchainOutboxEvent`

**Files:**
- Modify: `src/lamto/evidence/models.py:20-49` (`BlockchainOutboxEvent`)
- Create: migration `src/lamto/evidence/migrations/0008_outbox_building.py` (generated, then edited as below)
- Create: migration `src/lamto/evidence/migrations/0009_outbox_building_backfill_and_guard.py` (hand-written)
- Create: migration `src/lamto/evidence/migrations/0010_outbox_building_not_null.py` (generated)
- Modify: `src/lamto/web/views/auditor.py:89` (scoped lookup)
- Create: `src/lamto/evidence/tests/test_outbox_building.py`

**Interfaces:**
- Consumes: existing `lamto_security.evidence_insert_outbox_event(...)` 10-arg SQL procedure (migration 0004 version) and `evidence_protect_outbox_identity()` trigger.
- Produces: `BlockchainOutboxEvent.building` (FK `accounts.Building`, `PROTECT`, `related_name="outbox_events"`, non-null, DB-immutable). All outbox lookups in UI/exports must filter through it (spec §2.2: an outbox event is visible only if the record it anchors is).

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/evidence/tests/test_outbox_building.py`. The queueing helper mirrors the wallet/signature setup already used in `src/lamto/evidence/tests/test_outbox.py`:

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
)
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    begin_wallet_registration,
    queue_signed_event,
    register_wallet,
    utc_rfc3339,
)
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.testing.factories import new_event_id


def make_signing_membership(building, *, email):
    user = get_user_model().objects.create_user(
        email=email, password="x", display_name=email
    )
    organization = Organization.objects.create(
        building=building, name=f"Org {email}", kind=Organization.Kind.BOARD
    )
    membership = OrganizationMembership.objects.create(
        user=user, organization=organization, role=OrganizationMembership.Role.BOARD
    )
    account = Account.create()
    challenge = begin_wallet_registration(membership)
    proof = Account.sign_message(
        encode_typed_data(full_message=challenge), account.key
    ).signature.hex()
    register_wallet(membership, account.address, proof)
    return membership, account


def queue_event(membership, account):
    payload = {
        "event": "test",
        "at": utc_rfc3339(timezone.now()),
        "membership_id": membership.pk,
    }
    event_id = new_event_id()
    digest = payload_hash(payload)
    typed = build_evidence_typed_data(
        event_id, EvidenceType.FUND_ENTRY, "0x" + digest, "0x" + "0" * 64
    )
    signature = Account.sign_message(
        encode_typed_data(full_message=typed), account.key
    ).signature.hex()
    with transaction.atomic():
        return queue_signed_event(
            event_id,
            EvidenceType.FUND_ENTRY,
            payload,
            "0x" + "0" * 64,
            membership,
            signature,
        )


class OutboxBuildingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Outbox Building A")
        cls.other = Building.objects.create(name="Outbox Building B")
        cls.membership, cls.account = make_signing_membership(
            cls.building, email="outbox-signer@example.test"
        )

    def test_queued_event_carries_signer_building(self):
        event = queue_event(self.membership, self.account)
        event.refresh_from_db()
        assert event.building_id == self.building.pk

    def test_building_is_immutable_at_database_level(self):
        event = queue_event(self.membership, self.account)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BlockchainOutboxEvent.objects.filter(pk=event.pk).update(
                    building=self.other
                )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/evidence/tests/test_outbox_building.py -q`
Expected: FAIL — `queue_signed_event` inserts without `building_id`, so `test_queued_event_carries_building` errors with `FieldError`/`AttributeError` on `building_id` (no such field yet).

- [ ] **Step 3: Add the model field and generate the AddField migration**

In `src/lamto/evidence/models.py`, add to `BlockchainOutboxEvent` after `signer_wallet`:

```python
    building = models.ForeignKey(
        "accounts.Building",
        null=True,
        on_delete=models.PROTECT,
        related_name="outbox_events",
        editable=False,
    )
```

Run: `.venv/bin/python manage.py makemigrations evidence --name outbox_building`
Expected: creates `src/lamto/evidence/migrations/0008_outbox_building.py` with the nullable `AddField`.

- [ ] **Step 4: Write the backfill + procedure/trigger migration**

Create `src/lamto/evidence/migrations/0009_outbox_building_backfill_and_guard.py`:

```python
"""Backfill outbox building from the signer's organization, teach the insert
procedure to stamp it, and make it immutable in the identity trigger.

Building derivation rule (spec 2.2): signer wallet -> membership ->
organization -> building. Signing capability is per-building membership, so
the signer's organization building is the anchored record's building.
"""

from django.db import migrations

INSERT_FUNCTION_WITH_BUILDING = """
CREATE OR REPLACE FUNCTION lamto_security.evidence_insert_outbox_event(
    p_event_id text, p_event_type smallint, p_payload jsonb, p_payload_hash text,
    p_previous_hash text, p_signature text, p_wallet_id bigint, p_membership_id bigint,
    p_canonical_payload text, p_authorization text
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE event_pk bigint; v_building_id bigint;
BEGIN
    IF p_payload IS DISTINCT FROM p_canonical_payload::jsonb THEN
        RAISE EXCEPTION 'canonical evidence payload does not match the queued payload'
        USING ERRCODE = 'check_violation';
    END IF;
    IF p_authorization IS DISTINCT FROM (
        SELECT encode(
            sha256(
                secret || sha256(
                    secret ||
                    convert_to(
                        format(
                        'evidence-queue|%s|%s|%s|%s|%s|%s|%s|%s',
                        p_event_id, p_event_type, p_payload_hash, p_previous_hash,
                        p_signature, p_wallet_id, p_membership_id, p_canonical_payload
                        ),
                        'UTF8'
                    )
                )
            ),
            'hex'
        )
        FROM lamto_security.write_authorization_secret
        WHERE id = TRUE
    ) THEN
        RAISE EXCEPTION 'evidence queue authorization is invalid'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM 1 FROM public.accounts_organizationmembership
    WHERE id = p_membership_id AND active
      AND role IN ('OPERATOR', 'BOARD', 'RESIDENT_REP') FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'membership is not eligible to queue evidence'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM 1 FROM public.accounts_signerwallet
    WHERE id = p_wallet_id AND membership_id = p_membership_id AND active FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet is not active for the membership'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT o.building_id INTO v_building_id
    FROM public.accounts_organizationmembership m
    JOIN public.accounts_organization o ON o.id = m.organization_id
    WHERE m.id = p_membership_id;
    IF v_building_id IS NULL THEN
        RAISE EXCEPTION 'membership has no organization building'
        USING ERRCODE = 'check_violation';
    END IF;
    INSERT INTO public.evidence_blockchainoutboxevent
        (event_id, event_type, payload, payload_hash, previous_hash, signature,
         signer_wallet_id, building_id, status, attempts, next_attempt_at,
         lease_expires_at, last_attempt_at, transaction_hash, receipt_status,
         receipt, last_error, chain_confirmed_block, chain_block_timestamp,
         submitted_at, confirmed_at, created_at, updated_at)
    VALUES
        (p_event_id, p_event_type, p_payload, p_payload_hash, p_previous_hash,
         p_signature, p_wallet_id, v_building_id, 'PENDING', 0, NULL, NULL, NULL,
         '', NULL, '{}'::jsonb, '', NULL, NULL, NULL, NULL,
         clock_timestamp(), clock_timestamp())
    RETURNING id INTO event_pk;
    RETURN event_pk;
END;
$$;
REVOKE ALL ON FUNCTION lamto_security.evidence_insert_outbox_event(
    text, smallint, jsonb, text, text, text, bigint, bigint, text, text
) FROM PUBLIC;
"""

# Identical to the 0004 version except the building_id immutability line.
IDENTITY_TRIGGER_WITH_BUILDING = """
CREATE OR REPLACE FUNCTION evidence_protect_outbox_identity()
RETURNS trigger AS $$
DECLARE service_owner name;
BEGIN
    SELECT pg_get_userbyid(proowner) INTO service_owner
    FROM pg_proc WHERE oid = 'lamto_security.evidence_insert_outbox_event(text,smallint,jsonb,text,text,text,bigint,bigint,text,text)'::regprocedure;
    IF TG_OP = 'INSERT' THEN
        IF current_user IS DISTINCT FROM service_owner THEN
            RAISE EXCEPTION 'outbox inserts require the queue procedure'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' OR OLD.event_id IS DISTINCT FROM NEW.event_id
       OR OLD.event_type IS DISTINCT FROM NEW.event_type
       OR OLD.payload IS DISTINCT FROM NEW.payload
       OR OLD.payload_hash IS DISTINCT FROM NEW.payload_hash
       OR OLD.previous_hash IS DISTINCT FROM NEW.previous_hash
       OR OLD.signer_wallet_id IS DISTINCT FROM NEW.signer_wallet_id
       OR OLD.building_id IS DISTINCT FROM NEW.building_id
       OR OLD.signature IS DISTINCT FROM NEW.signature
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'signed outbox identity is immutable'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Reverse: the exact 0004 bodies (no building), so this migration is honestly
# reversible pre-acceptance.
INSERT_FUNCTION_WITHOUT_BUILDING = INSERT_FUNCTION_WITH_BUILDING.replace(
    """    SELECT o.building_id INTO v_building_id
    FROM public.accounts_organizationmembership m
    JOIN public.accounts_organization o ON o.id = m.organization_id
    WHERE m.id = p_membership_id;
    IF v_building_id IS NULL THEN
        RAISE EXCEPTION 'membership has no organization building'
        USING ERRCODE = 'check_violation';
    END IF;
""",
    "",
).replace(
    "signer_wallet_id, building_id, status", "signer_wallet_id, status"
).replace(
    "p_signature, p_wallet_id, v_building_id, 'PENDING'", "p_signature, p_wallet_id, 'PENDING'"
).replace(
    "DECLARE event_pk bigint; v_building_id bigint;", "DECLARE event_pk bigint;"
)

IDENTITY_TRIGGER_WITHOUT_BUILDING = IDENTITY_TRIGGER_WITH_BUILDING.replace(
    "       OR OLD.building_id IS DISTINCT FROM NEW.building_id\n", ""
)


def backfill_building(apps, schema_editor):
    Event = apps.get_model("evidence", "BlockchainOutboxEvent")
    for event in (
        Event.objects.select_related("signer_wallet__membership__organization")
        .filter(building__isnull=True)
        .iterator()
    ):
        event.building_id = event.signer_wallet.membership.organization.building_id
        event.save(update_fields=["building"])


class Migration(migrations.Migration):
    dependencies = [("evidence", "0008_outbox_building")]

    operations = [
        migrations.RunSQL(INSERT_FUNCTION_WITH_BUILDING, INSERT_FUNCTION_WITHOUT_BUILDING),
        migrations.RunPython(backfill_building, migrations.RunPython.noop),
        migrations.RunSQL(IDENTITY_TRIGGER_WITH_BUILDING, IDENTITY_TRIGGER_WITHOUT_BUILDING),
    ]
```

- [ ] **Step 5: Flip the model to non-null and generate the AlterField migration**

In `src/lamto/evidence/models.py`, remove `null=True` from the `building` field (leave `editable=False`).

Run: `.venv/bin/python manage.py makemigrations evidence --name outbox_building_not_null`
Expected: creates `0010_outbox_building_not_null.py` with one `AlterField`.

Run: `.venv/bin/python manage.py migrate`
Expected: `OK` for evidence 0008–0010.

- [ ] **Step 6: Scope the auditor outbox lookup**

In `src/lamto/web/views/auditor.py`, replace line 89:

```python
            outbox_event = BlockchainOutboxEvent.objects.filter(pk=int(outbox_id)).first()
```

with:

```python
            outbox_event = BlockchainOutboxEvent.objects.filter(
                pk=int(outbox_id), building_id=building_id
            ).first()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/evidence -q`
Expected: PASS (new tests + existing outbox suites; the insert-procedure path now stamps `building_id`, the trigger rejects mutation).

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/evidence/models.py src/lamto/evidence/migrations/ \
        src/lamto/web/views/auditor.py src/lamto/evidence/tests/test_outbox_building.py
git commit -m "feat: immutable building scope on blockchain outbox events"
```

---

### Task 6: Tenant ownership on notifications and quarantined uploads

**Files:**
- Modify: `src/lamto/notifications/models.py` (`NotificationDelivery`)
- Modify: `src/lamto/notifications/services.py` (`queue_notification`, `queue_notification_after_commit`, `notify_users`)
- Modify: `src/lamto/notifications/hooks.py` (all 14 `notify_*` fan-out calls)
- Modify: `src/lamto/documents/models.py` (`QuarantinedUpload`)
- Modify: `src/lamto/documents/services.py` (3 `QuarantinedUpload.objects.create` sites: `_create_rejection` ~line 107, `quarantine_upload` ~line 160, the scanner path ~line 255)
- Modify: `src/lamto/web/action_inbox.py:620-627` (`_quarantined_upload_items`)
- Create: migrations for `notifications` and `documents` (generated)
- Create: `src/lamto/notifications/tests/test_building_scope.py`
- Create: `src/lamto/documents/tests/test_quarantine_building.py` (create `src/lamto/documents/tests/__init__.py` if absent)

**Interfaces:**
- Produces:
  - `NotificationDelivery.building` and `QuarantinedUpload.building`: FK `accounts.Building`, `null=True`, `blank=True`, `on_delete=PROTECT`, related names `notification_deliveries` / `quarantined_uploads`. Nullable **only** for legacy/system rows (spec §2.2); all new writes set it.
  - `queue_notification(..., building=None)`, `queue_notification_after_commit(..., building=None)`, `notify_users(..., building=None)` — accept a `Building` or building id.
- Consequence: legacy quarantine rows (NULL building, pre-acceptance test data with a retention expiry) drop out of the action inbox; accepted per spec §1 deployment state.

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/notifications/tests/test_building_scope.py`:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.maintenance.models import BuildingLocation
from lamto.maintenance.reporting import submit_report
from lamto.notifications.hooks import notify_report_receipt
from lamto.notifications.models import NotificationDelivery
from lamto.notifications.services import queue_notification


class NotificationBuildingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Notify Building")
        cls.unit = Unit.objects.create(building=cls.building, label="N-1")
        cls.user = get_user_model().objects.create_user(
            email="notify@example.test", password="x", display_name="N"
        )
        ResidentOccupancy.objects.create(user=cls.user, unit=cls.unit)
        cls.location = BuildingLocation.objects.create(
            building=cls.building, name="Notify Lobby"
        )

    def test_queue_notification_stores_building(self):
        rows = queue_notification(
            self.user,
            event_key="test:building:1",
            subject="s",
            body="b",
            building=self.building,
        )
        assert rows and all(r.building_id == self.building.pk for r in rows)

    def test_report_receipt_hook_stamps_building(self):
        # submit_report (not a bare create) so this test stays valid after
        # Task 7 makes IssueReport.building non-null.
        report = submit_report(self.user, self.unit, "TEST notify", self.location, [])
        # Hooks enqueue after commit; TestCase captures on_commit callbacks.
        with self.captureOnCommitCallbacks(execute=True):
            notify_report_receipt(report)
        deliveries = NotificationDelivery.objects.filter(recipient=self.user)
        assert deliveries.exists()
        assert all(d.building_id == self.building.pk for d in deliveries)
```

Create `src/lamto/documents/tests/test_quarantine_building.py`:

```python
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.documents.models import QuarantinedUpload
from lamto.documents.services import quarantine_upload

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-quarantine-test-")


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
class QuarantineBuildingTests(TestCase):
    def test_quarantine_upload_stamps_membership_building(self):
        building = Building.objects.create(name="Quarantine Building")
        user = get_user_model().objects.create_user(
            email="q@example.test", password="x", display_name="Q"
        )
        organization = Organization.objects.create(
            building=building, name="Q Op", kind=Organization.Kind.OPERATOR
        )
        OrganizationMembership.objects.create(
            user=user,
            organization=organization,
            role=OrganizationMembership.Role.OPERATOR,
        )
        upload = SimpleUploadedFile("bad.bin", b"x" * 10, content_type="application/octet-stream")
        quarantined = quarantine_upload(upload, user, "test reason")
        assert quarantined.building_id == building.pk
        assert QuarantinedUpload.objects.get(pk=quarantined.pk).building_id == building.pk
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/notifications/tests/test_building_scope.py src/lamto/documents/tests/test_quarantine_building.py -q`
Expected: FAIL — `queue_notification() got an unexpected keyword argument 'building'` and `AttributeError`/`TypeError` on the quarantine test.

- [ ] **Step 3: Add the model fields and migrations**

In `src/lamto/notifications/models.py`, add to `NotificationDelivery` after `recipient`:

```python
    building = models.ForeignKey(
        "accounts.Building",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="notification_deliveries",
    )
```

In `src/lamto/documents/models.py`, add to `QuarantinedUpload` after `uploader`:

```python
    building = models.ForeignKey(
        Building,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quarantined_uploads",
    )
```

Run: `.venv/bin/python manage.py makemigrations notifications documents`
Expected: one migration per app, nullable `AddField` each.

- [ ] **Step 4: Thread `building` through the notification services**

In `src/lamto/notifications/services.py`:

1. `queue_notification`: add keyword parameter `building=None` (after `event_code`), then at the top of the body add `building_id = getattr(building, "pk", building)` and add `"building_id": building_id,` to the `defaults={...}` dict of the `NotificationDelivery.objects.get_or_create(...)` call.
2. `queue_notification_after_commit`: add keyword parameter `building=None`, capture `building_id = getattr(building, "pk", building)` next to the existing `recipient_id` capture, and pass `building=building_id` through the inner `queue_notification(...)` call inside `_enqueue`.
3. `notify_users`: add keyword parameter `building=None` and pass `building=building` through its `queue_notification_after_commit(...)` call.

In `src/lamto/notifications/hooks.py`, add `building=<expr>` to the `notify_users(...)` call in every hook. Example for the first one:

```python
def notify_report_receipt(report):
    building_id = report.unit.building_id
    recipients = [report.reporter] + _users_with_capability(building_id, "report.triage")
    notify_users(
        recipients,
        event_key=f"{EVENT_REPORT_RECEIPT}:report:{report.pk}",
        subject="Report received",
        body=f"Report #{report.pk} was submitted: {report.text[:200]}",
        event_code=EVENT_REPORT_RECEIPT,
        building=building_id,
    )
```

Exact expression per hook (each is added as `building=<expr>` in that hook's `notify_users` call; most already have a `building_id` local):

| Hook function | `building=` expression |
|---|---|
| `notify_report_receipt` | `building_id` |
| `notify_triage_confirmed` | `case.building_id` |
| `notify_work_assigned` | `work_order.case.building_id` |
| `notify_deadline_risk` | `work_order.case.building_id` |
| `notify_proposal_decision` | `building_id` |
| `notify_emergency_authorized` | `building_id` |
| `notify_emergency_outcome` | `building_id` |
| `notify_work_accepted` | `building_id` |
| `notify_payment_recorded` | `building_id` |
| `notify_payment_verified` | `building_id` |
| `notify_publication` | `building_id` |
| `notify_correction_status` | `building_id` |
| `notify_integrity_mismatch` | `building_id` |
| `notify_quarantined_upload` | `building_id if building_id is not None else upload.building_id` (the upload row now carries it — see Step 5) |

- [ ] **Step 5: Stamp building on quarantine rows and switch the inbox query**

In `src/lamto/documents/services.py`:

1. `_create_rejection(uploader, membership, metadata, reason, occupancy=None)`: before the `QuarantinedUpload.objects.create(...)` call add:

```python
    building = None
    if membership is not None:
        building = membership.organization.building
    elif occupancy is not None:
        building = occupancy.unit.building
```

and add `building=building,` to the create call.
2. `quarantine_upload`: add `building=membership.organization.building,` to its `QuarantinedUpload.objects.create(...)` call (the membership is resolved just above it).
3. The scanner-failure create (~line 255, inside the upload pipeline where locals `membership` and `occupancy` exist): add the same four-line derivation immediately before the create and pass `building=building,`.

In `src/lamto/web/action_inbox.py`, replace the body of `_quarantined_upload_items`'s queryset (the `Q(...) | Q(...)` join inference):

```python
    qs = (
        QuarantinedUpload.objects.filter(building_id=building_id)
        .order_by("-created_at")[:20]
    )
```

Remove the now-unused `Q` import only if nothing else in the module uses it (other item builders do — check before removing).

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/notifications src/lamto/documents src/lamto/web/tests -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/lamto/notifications src/lamto/documents src/lamto/web/action_inbox.py
git commit -m "feat: tenant ownership on notification deliveries and quarantined uploads"
```

---

### Task 7: `IssueReport.building` and composite tenant foreign keys

**Files:**
- Modify: `src/lamto/accounts/models.py` (`Unit.Meta`)
- Modify: `src/lamto/maintenance/models.py` (`BuildingLocation.Meta`, `IssueReport`)
- Modify: `src/lamto/maintenance/reporting.py` (`submit_report` create call, ~line 68)
- Create: generated migrations for `accounts` + `maintenance`, plus hand-written `src/lamto/maintenance/migrations/00XX_report_building_backfill_and_composite_fk.py`
- Create: `src/lamto/maintenance/tests/test_tenant_constraints.py`

**Interfaces:**
- Produces:
  - `IssueReport.building` (FK `accounts.Building`, `PROTECT`, `editable=False`, non-null, `related_name="issue_reports"`), always `unit.building`.
  - DB constraints (spec §2.3 layer 3): `UNIQUE (id, building_id)` on `accounts_unit` and `maintenance_buildinglocation`; composite FKs `case_location_same_building`, `report_unit_same_building`, `report_location_same_building`.
  - **Documented deviation:** the spec also names triage-decision↔location for the composite-FK pattern; `TriageDecision` carries no building column, so that edge is enforced by the existing form scoping plus the `tenant_integrity` check in Task 8 instead of adding a third denormalized column to a 1:1-derived record.

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/maintenance/tests/test_tenant_constraints.py`:

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
)
from lamto.maintenance.reporting import submit_report


class CompositeTenantFkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building_a = Building.objects.create(name="Composite A")
        cls.building_b = Building.objects.create(name="Composite B")
        cls.unit_a = Unit.objects.create(building=cls.building_a, label="CA-1")
        cls.loc_a = BuildingLocation.objects.create(building=cls.building_a, name="A Lobby")
        cls.loc_b = BuildingLocation.objects.create(building=cls.building_b, name="B Lobby")
        cls.resident = get_user_model().objects.create_user(
            email="composite@example.test", password="x", display_name="C"
        )
        ResidentOccupancy.objects.create(user=cls.resident, unit=cls.unit_a)

    def test_submit_report_stamps_building(self):
        with transaction.atomic():
            report = submit_report(self.resident, self.unit_a, "TEST leak", self.loc_a, [])
        assert report.building_id == self.building_a.pk

    def test_report_with_cross_building_location_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IssueReport.objects.create(
                    reporter=self.resident,
                    unit=self.unit_a,
                    building=self.building_a,
                    text="TEST cross",
                    selected_location=self.loc_b,
                    location_path_snapshot="x",
                )

    def test_case_with_cross_building_location_rejected_by_db(self):
        with transaction.atomic():
            report = submit_report(self.resident, self.unit_a, "TEST case", self.loc_a, [])
        decision = TriageDecision.objects.create(
            report=report,
            operator=self.resident,
            category="c",
            urgency="LOW",
            location=self.loc_a,
            department="d",
            deadline_minutes=60,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MaintenanceCase.objects.create(
                    decision=decision,
                    building=self.building_a,
                    category="c",
                    urgency="LOW",
                    location=self.loc_b,
                    department="d",
                    deadline_at=timezone.now(),
                )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/maintenance/tests/test_tenant_constraints.py -q`
Expected: FAIL — `IssueReport` has no field `building` (`TypeError`/`FieldError`).

- [ ] **Step 3: Model changes and generated migrations (nullable first)**

In `src/lamto/accounts/models.py`, add to `Unit.Meta.constraints` (keep the existing entry):

```python
            models.UniqueConstraint(fields=["id", "building"], name="unit_id_building_key"),
```

In `src/lamto/maintenance/models.py`:

1. Add to `BuildingLocation.Meta.constraints` (keep the existing entry):

```python
            models.UniqueConstraint(fields=["id", "building"], name="location_id_building_key"),
```

2. Add to `IssueReport` after `unit`:

```python
    building = models.ForeignKey(
        Building, null=True, on_delete=models.PROTECT,
        editable=False, related_name="issue_reports",
    )
```

Run: `.venv/bin/python manage.py makemigrations accounts maintenance`
Expected: `accounts` migration with the `unit_id_building_key` constraint; `maintenance` migration with `location_id_building_key` + nullable `AddField` on `issuereport`.

- [ ] **Step 4: Hand-written backfill + composite FK migration**

Run: `.venv/bin/python manage.py makemigrations maintenance --empty --name report_building_backfill_and_composite_fk`

Fill the generated file with:

```python
from django.db import migrations


def backfill_report_building(apps, schema_editor):
    # No joined-field updates in Django's .update(); loop instead (small table).
    IssueReport = apps.get_model("maintenance", "IssueReport")
    for report in (
        IssueReport.objects.select_related("unit")
        .filter(building__isnull=True)
        .iterator()
    ):
        report.building_id = report.unit.building_id
        report.save(update_fields=["building"])


COMPOSITE_FKS = """
ALTER TABLE maintenance_maintenancecase
    ADD CONSTRAINT case_location_same_building
    FOREIGN KEY (location_id, building_id)
    REFERENCES maintenance_buildinglocation (id, building_id);
ALTER TABLE maintenance_issuereport
    ADD CONSTRAINT report_unit_same_building
    FOREIGN KEY (unit_id, building_id)
    REFERENCES accounts_unit (id, building_id);
ALTER TABLE maintenance_issuereport
    ADD CONSTRAINT report_location_same_building
    FOREIGN KEY (selected_location_id, building_id)
    REFERENCES maintenance_buildinglocation (id, building_id);
"""

DROP_COMPOSITE_FKS = """
ALTER TABLE maintenance_issuereport DROP CONSTRAINT report_location_same_building;
ALTER TABLE maintenance_issuereport DROP CONSTRAINT report_unit_same_building;
ALTER TABLE maintenance_maintenancecase DROP CONSTRAINT case_location_same_building;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "<the generated AddField migration from Step 3>"),
        ("accounts", "<the generated Unit-constraint migration from Step 3>"),
    ]

    operations = [
        migrations.RunPython(backfill_report_building, migrations.RunPython.noop),
        migrations.RunSQL(COMPOSITE_FKS, DROP_COMPOSITE_FKS),
    ]
```

(Replace the two `<...>` dependency names with the actual filenames generated in Step 3.)

- [ ] **Step 5: Flip `IssueReport.building` to non-null; stamp it at submission**

In `src/lamto/maintenance/models.py`, remove `null=True` from `IssueReport.building`.

Run: `.venv/bin/python manage.py makemigrations maintenance --name report_building_not_null`

In `src/lamto/maintenance/reporting.py`, in `submit_report`'s `IssueReport.objects.create(...)` call, add `building=unit.building,` after `unit=unit,`.

Run: `.venv/bin/python manage.py migrate`
Expected: `OK`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/maintenance -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS (all creation paths route through `submit_report`, which now stamps `building`).

- [ ] **Step 7: Commit**

```bash
git add src/lamto/accounts/models.py src/lamto/maintenance/models.py \
        src/lamto/maintenance/reporting.py src/lamto/accounts/migrations/ \
        src/lamto/maintenance/migrations/ src/lamto/maintenance/tests/test_tenant_constraints.py
git commit -m "feat: composite tenant FKs and building stamp on issue reports"
```

---

### Task 8: `tenant_integrity` management command

**Files:**
- Create: `src/lamto/accounts/management/commands/tenant_integrity.py`
- Create: `src/lamto/accounts/tests/test_tenant_integrity.py`

**Interfaces:**
- Consumes: `IssueReport.building` (Task 7), `BlockchainOutboxEvent.building` (Task 5).
- Produces: `manage.py tenant_integrity` — exit 0 with `ok <check>` lines when consistent; `CommandError` (exit 1) listing violations otherwise. Run in CI via its test; ops runs it nightly (runbook line added here).

- [ ] **Step 1: Write the failing test**

Create `src/lamto/accounts/tests/test_tenant_integrity.py`:

```python
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from lamto.accounts.models import Building, ResidentOccupancy, Unit
from lamto.maintenance.models import BuildingLocation, TriageDecision
from lamto.maintenance.reporting import submit_report


class TenantIntegrityCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building_a = Building.objects.create(name="Integrity A")
        cls.building_b = Building.objects.create(name="Integrity B")
        cls.unit_a = Unit.objects.create(building=cls.building_a, label="IA-1")
        cls.loc_a = BuildingLocation.objects.create(building=cls.building_a, name="IA Lobby")
        cls.loc_b = BuildingLocation.objects.create(building=cls.building_b, name="IB Lobby")
        cls.resident = get_user_model().objects.create_user(
            email="integrity@example.test", password="x", display_name="I"
        )
        ResidentOccupancy.objects.create(user=cls.resident, unit=cls.unit_a)
        cls.report = submit_report(cls.resident, cls.unit_a, "TEST integrity", cls.loc_a, [])

    def test_consistent_data_passes(self):
        out = StringIO()
        call_command("tenant_integrity", stdout=out)
        assert "all checks passed" in out.getvalue()

    def test_cross_building_decision_location_fails(self):
        TriageDecision.objects.create(
            report=self.report,
            operator=self.resident,
            category="c",
            urgency="LOW",
            location=self.loc_a,
            department="d",
            deadline_minutes=60,
        )
        # Bypass form scoping the way a bug would: plain FK, no composite key.
        TriageDecision.objects.filter(report=self.report).update(location=self.loc_b)
        with self.assertRaises(CommandError) as ctx:
            call_command("tenant_integrity")
        assert "triage_decision_location" in str(ctx.exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/accounts/tests/test_tenant_integrity.py -q`
Expected: FAIL with `CommandError: Unknown command: 'tenant_integrity'`

- [ ] **Step 3: Implement the command**

Create `src/lamto/accounts/management/commands/tenant_integrity.py`:

```python
"""Assert cross-record building consistency (spec 2.3 layer 3).

Covers the edges composite FKs cannot express (multi-hop joins and columns
without a denormalized building), so a scoping bug shows up as a failing
check instead of silent cross-tenant data. Run in CI and nightly.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.models import MaintenanceFundEntry, PublishedLedgerEntry
from lamto.maintenance.models import (
    CaseReport,
    IssueReport,
    MaintenanceCase,
    ReportPhoto,
    TriageDecision,
    WorkOrder,
)


def checks():
    return [
        ("issue_report_unit", IssueReport.objects.exclude(building=F("unit__building"))),
        (
            "issue_report_location",
            IssueReport.objects.exclude(building=F("selected_location__building")),
        ),
        (
            "triage_decision_location",
            TriageDecision.objects.exclude(
                location__building=F("report__unit__building")
            ),
        ),
        ("case_location", MaintenanceCase.objects.exclude(building=F("location__building"))),
        (
            "case_report",
            CaseReport.objects.exclude(case__building=F("report__unit__building")),
        ),
        (
            "work_order_decision_chain",
            WorkOrder.objects.exclude(
                case__building=F("case__decision__report__unit__building")
            ),
        ),
        (
            "fund_entry_proposal",
            MaintenanceFundEntry.objects.filter(proposal__isnull=False).exclude(
                fund__building=F("proposal__work_order__case__building")
            ),
        ),
        (
            "published_entry_case",
            PublishedLedgerEntry.objects.exclude(case=F("proposal__work_order__case")),
        ),
        (
            "outbox_signer_building",
            BlockchainOutboxEvent.objects.exclude(
                building=F("signer_wallet__membership__organization__building")
            ),
        ),
        (
            "report_photo_document",
            ReportPhoto.objects.exclude(
                version__document__building=F("report__unit__building")
            ),
        ),
    ]


class Command(BaseCommand):
    help = "Fail when any cross-building reference is inconsistent."

    def handle(self, *args, **options):
        failures = []
        for name, queryset in checks():
            count = queryset.count()
            if count:
                sample = list(queryset.values_list("pk", flat=True)[:5])
                failures.append(f"{name}: {count} row(s), e.g. pks {sample}")
                self.stderr.write(self.style.ERROR(f"FAIL {name}: {count}"))
            else:
                self.stdout.write(f"ok {name}")
        if failures:
            raise CommandError("Tenant integrity violations:\n" + "\n".join(failures))
        self.stdout.write(self.style.SUCCESS("Tenant integrity: all checks passed."))
```

Append to `ops/pilot-runbook.md` (end of file):

```markdown
## Tenant integrity (nightly)

```bash
.venv/bin/python manage.py tenant_integrity
```

Runs the cross-building consistency checks (spec 2.3). Non-zero exit means a
scoping bug wrote cross-tenant references; treat as a security incident.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest src/lamto/accounts/tests/test_tenant_integrity.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/accounts/management/commands/tenant_integrity.py \
        src/lamto/accounts/tests/test_tenant_integrity.py ops/pilot-runbook.md
git commit -m "feat: tenant_integrity cross-building consistency command"
```

---

### Task 9: Two-building adversarial isolation suite

**Files:**
- Create: `tests/isolation/__init__.py` (empty)
- Create: `tests/isolation/test_cross_building_access.py`

**Interfaces:**
- Consumes: `seed_pilot_world`, `PilotDomainDriver` (`lamto.testing.factories`), MFA test pattern from `src/lamto/web/tests/test_role_workspaces.py` (`TOTPDevice` + `DEVICE_ID_SESSION_KEY` + `RECENT_REAUTH_KEY`).
- Produces: the permanent adversarial gate (spec §2.3 layer 4). **Completeness rule:** every `<int:pk>` route in `lamto.web.urls` must appear in the case tables or the `EXEMPT` dict — adding a route without classifying it fails the suite.

- [ ] **Step 1: Write the suite (it must fail only if isolation is broken — expected to pass)**

Create `tests/isolation/test_cross_building_access.py`:

```python
"""Two-building adversarial isolation suite (spec 2.3 layer 4).

Building A actors request Building B objects by primary key: the answer must
always be 404 (cross-tenant), 403 (ownership), or 405 (method), never data.
List pages and exports rendered for Building A must not contain Building B
markers. Every <int:pk> route must be classified here or in EXEMPT.
"""

import tempfile
import time

from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.finance.models import (
    AcceptanceRecord,
    PaymentEvidence,
    Proposal,
    PublishedLedgerEntry,
)
from lamto.finance.models.emergencies import EmergencyAuthorization
from lamto.maintenance.models import IssueReport, MaintenanceCase, WorkOrder
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-isolation-")

B_BUILDING_NAME = "Isolation Building B"
B_LEAK_MARKER = "TEST-B-LEAK-MARKER"

# route name -> (attribute on cls.b with the B-side pk, seed-A role key, method)
STAFF_CASES = {
    "web:staff-report-detail": ("report_pk", "operator", "GET"),
    "web:case-detail": ("case_pk", "operator", "GET"),
    "web:proposal-detail": ("proposal_pk", "operator", "GET"),
    "web:work-order-detail": ("work_pk", "maintenance", "GET"),
    "web:payment-record-detail": ("acceptance_pk", "board_payment_recorder", "GET"),
    "web:payment-verify-detail": ("payment_pk", "board_payment_verifier", "GET"),
    "web:work-accept": ("work_pk", "board_approver", "POST"),
    "web:emergency-authorize": ("work_pk", "board_emergency_approver", "POST"),
    "web:emergency-decide": ("emergency_pk", "resident_representative", "POST"),
}

RESIDENT_CASES = {
    "web:report-detail": ("report_pk", "GET", 404),
    "web:ledger-detail": ("ledger_pk", "GET", 404),
    "web:work-rate": ("work_pk", "POST", 403),
}

EXEMPT = {
    # Device revocation is user-scoped (own MFA devices), not tenant-scoped.
    "web:mfa-revoke": "user-scoped MFA device",
    # Break-glass sessions are platform support records for tech admins;
    # tenancy does not apply and the view enforces tech-admin capability.
    "web:break-glass-revoke": "platform-scoped support session",
}

LIST_ROUTES = [
    "web:action-inbox",
    "web:case-list",
    "web:work-order-list",
    "web:proposal-list",
    "web:payment-list",
    "web:audit-search",
]


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
class CrossBuildingAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed_a = seed_pilot_world(
            building_name="Isolation Building A",
            email_prefix="isoa",
            create_sample_report=True,
        )
        cls.seed_b = seed_pilot_world(
            building_name=B_BUILDING_NAME,
            email_prefix="isob",
            create_sample_report=False,
        )
        driver = PilotDomainDriver(cls.seed_b)
        driver.login(None, "resident").submit_report(
            f"{B_LEAK_MARKER} lift noise", "Lift 2"
        )
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

        b_building = cls.seed_b.building
        report = IssueReport.objects.get(unit__building=b_building)
        case = MaintenanceCase.objects.get(building=b_building)
        work = WorkOrder.objects.get(case=case)
        proposal = Proposal.objects.get(work_order=work)
        acceptance = AcceptanceRecord.objects.get(work_order=work)
        payment = PaymentEvidence.objects.get(acceptance=acceptance)
        ledger = PublishedLedgerEntry.objects.get(case=case)

        drill_driver = PilotDomainDriver(cls.seed_b)
        drill_driver.login(None, "board_emergency_approver").authorize_emergency_drill()
        emergency = (
            EmergencyAuthorization.objects.filter(
                work_order__case__building=b_building
            )
            .order_by("-pk")
            .first()
        )

        cls.b = {
            "report_pk": report.pk,
            "case_pk": case.pk,
            "work_pk": work.pk,
            "proposal_pk": proposal.pk,
            "acceptance_pk": acceptance.pk,
            "payment_pk": payment.pk,
            "ledger_pk": ledger.pk,
            "emergency_pk": emergency.pk,
        }

    def _staff_login(self, role_key):
        membership = self.seed_a.roles[role_key]
        user = membership.user
        self.client.force_login(user)
        device = TOTPDevice.objects.create(
            user=user, name="test", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()

    def test_every_pk_route_is_classified(self):
        from lamto.web import urls as web_urls

        pk_routes = {
            f"web:{pattern.name}"
            for pattern in web_urls.urlpatterns
            if "<int:" in str(pattern.pattern)
        }
        classified = set(STAFF_CASES) | set(RESIDENT_CASES) | set(EXEMPT)
        missing = pk_routes - classified
        assert not missing, (
            f"New pk routes must be classified in the isolation suite: {missing}"
        )

    def test_staff_cannot_reach_other_building_objects(self):
        for route, (pk_attr, role_key, method) in STAFF_CASES.items():
            with self.subTest(route=route):
                self._staff_login(role_key)
                url = reverse(route, args=[self.b[pk_attr]])
                response = (
                    self.client.post(url, {}) if method == "POST" else self.client.get(url)
                )
                assert response.status_code in {403, 404, 405}, (
                    route,
                    response.status_code,
                )
                if hasattr(response, "content"):
                    assert B_LEAK_MARKER.encode() not in response.content
                self.client.logout()

    def test_resident_cannot_reach_other_building_objects(self):
        resident_a = self.seed_a.users["resident"]
        self.client.force_login(resident_a)
        for route, (pk_attr, method, expected) in RESIDENT_CASES.items():
            with self.subTest(route=route):
                url = reverse(route, args=[self.b[pk_attr]])
                response = (
                    self.client.post(url, {}) if method == "POST" else self.client.get(url)
                )
                assert response.status_code == expected, (route, response.status_code)

    def test_staff_lists_and_exports_never_leak_other_building(self):
        for role_key in ("operator", "board_approver", "auditor"):
            self._staff_login(role_key)
            for route in LIST_ROUTES:
                with self.subTest(role=role_key, route=route):
                    response = self.client.get(reverse(route))
                    if response.status_code == 200:
                        self.assertNotContains(response, B_BUILDING_NAME)
                        self.assertNotContains(response, B_LEAK_MARKER)
                    else:
                        # Role lacks this workspace: 403 is the correct in-tenant answer.
                        assert response.status_code == 403
            self.client.logout()

    def test_auditor_export_never_leaks_other_building(self):
        self._staff_login("auditor")
        response = self.client.get(reverse("web:audit-export"), {"kind": "fund"})
        assert response.status_code in {200, 400}
        if response.status_code == 200:
            body = b"".join(response.streaming_content) if response.streaming else response.content
            assert B_LEAK_MARKER.encode() not in body
            assert B_BUILDING_NAME.encode() not in body
```

- [ ] **Step 2: Run the suite**

Run: `.venv/bin/python -m pytest tests/isolation -q`
Expected: PASS. If any case fails with a 200 + B content, that is a real cross-tenant leak: **stop, fix the view's building scoping (the pattern is `building_id = membership.organization.building_id` + filtered `get_object_or_404`), and re-run** — do not weaken the assertion. If a route/driver call errors (e.g. the `audit-export` query parameter name differs), read the view and adjust the request arguments, keeping the assertions intact.

- [ ] **Step 3: Run the full gate**

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/isolation
git commit -m "test: two-building adversarial isolation suite"
```

---

### Task 10: `onboard_building` command

**Files:**
- Create: `src/lamto/accounts/management/commands/onboard_building.py`
- Create: `src/lamto/accounts/tests/test_onboard_building.py`
- Modify: `ops/pilot-runbook.md` (onboarding section)

**Interfaces:**
- Consumes: `Building`, `Organization`, `Unit`, `MaintenanceFund`, `BuildingLocation` models.
- Produces: `manage.py onboard_building --name "..." [--timezone ...] [--locations "Lobby,Lift 1"] [--units "A-101,A-102"]` — creates the tenant skeleton (spec §2.5 step 4). Memberships, wallets, and the verified opening balance remain human runbook steps.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/accounts/tests/test_onboard_building.py`:

```python
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from lamto.accounts.models import Building, Organization, Unit
from lamto.finance.models import MaintenanceFund
from lamto.maintenance.models import BuildingLocation


class OnboardBuildingTests(TestCase):
    def test_creates_tenant_skeleton(self):
        out = StringIO()
        call_command(
            "onboard_building",
            "--name", "Onboard Tower",
            "--locations", "Lobby, Lift 1",
            "--units", "OT-101, OT-102",
            stdout=out,
        )
        building = Building.objects.get(name="Onboard Tower")
        assert building.timezone == "Asia/Ho_Chi_Minh"
        kinds = set(
            Organization.objects.filter(building=building).values_list("kind", flat=True)
        )
        assert kinds == {"OPERATOR", "BOARD", "RESIDENT_REP", "AUDITOR", "PLATFORM"}
        assert MaintenanceFund.objects.filter(building=building).exists()
        assert set(
            BuildingLocation.objects.filter(building=building).values_list("name", flat=True)
        ) == {"Lobby", "Lift 1"}
        assert set(
            Unit.objects.filter(building=building).values_list("label", flat=True)
        ) == {"OT-101", "OT-102"}
        assert "Next steps" in out.getvalue()

    def test_duplicate_name_rejected(self):
        Building.objects.create(name="Onboard Tower")
        with self.assertRaises(CommandError):
            call_command("onboard_building", "--name", "Onboard Tower")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/accounts/tests/test_onboard_building.py -q`
Expected: FAIL with `CommandError: Unknown command: 'onboard_building'`

- [ ] **Step 3: Implement the command**

Create `src/lamto/accounts/management/commands/onboard_building.py`:

```python
"""Onboard a new building tenant (spec 2.5): building, organizations, fund,
locations, units. People-steps (memberships, capabilities, wallets, opening
balance) stay in the runbook — they need real humans and signed evidence.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from lamto.accounts.models import Building, Organization, Unit
from lamto.finance.models import MaintenanceFund
from lamto.maintenance.models import BuildingLocation

ORGANIZATION_KINDS = (
    (Organization.Kind.OPERATOR, "operator organization"),
    (Organization.Kind.BOARD, "management board"),
    (Organization.Kind.RESIDENT_REP, "resident representative body"),
    (Organization.Kind.AUDITOR, "auditor firm"),
    (Organization.Kind.PLATFORM, "platform provider"),
)


def _split(raw):
    return [part.strip() for part in raw.split(",") if part.strip()]


class Command(BaseCommand):
    help = "Create a building tenant with its organizations, fund, locations, and units."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Building display name.")
        parser.add_argument("--timezone", default="Asia/Ho_Chi_Minh")
        parser.add_argument("--locations", default="", help="Comma-separated root location names.")
        parser.add_argument("--units", default="", help="Comma-separated unit labels.")

    @transaction.atomic
    def handle(self, *args, **options):
        name = options["name"].strip()
        if not name:
            raise CommandError("--name is required.")
        if Building.objects.filter(name=name).exists():
            raise CommandError(f"Building {name!r} already exists.")
        building = Building.objects.create(name=name, timezone=options["timezone"])
        for kind, label in ORGANIZATION_KINDS:
            Organization.objects.create(
                building=building, name=f"{name} {label}", kind=kind
            )
        MaintenanceFund.objects.create(building=building)
        for location_name in _split(options["locations"]):
            BuildingLocation.objects.create(building=building, name=location_name)
        for unit_label in _split(options["units"]):
            Unit.objects.create(building=building, label=unit_label)

        self.stdout.write(self.style.SUCCESS(f"Building onboarded: {name} (id={building.pk})"))
        self.stdout.write(
            "Next steps (runbook): create staff users and memberships, grant "
            "capabilities, register signer wallets, add resident occupancies "
            "(set phone numbers for phone login), then record and verify the "
            "fund opening balance."
        )
```

Append to `ops/pilot-runbook.md`:

```markdown
## Onboard a new building

```bash
.venv/bin/python manage.py onboard_building \
  --name "Toà nhà Example" \
  --locations "Sảnh, Thang máy 1, Hầm xe" \
  --units "A-101,A-102,A-103"
```

Then, per the printed next steps: create staff users + memberships, grant
capabilities, register signer wallets, add resident occupancies (with phone
numbers), and record + verify the fund opening balance. Run
`manage.py tenant_integrity` afterwards.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest src/lamto/accounts/tests/test_onboard_building.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Final full gate and commit**

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS — full suite, including e2e journeys and the isolation suite.

```bash
git add src/lamto/accounts/management/commands/onboard_building.py \
        src/lamto/accounts/tests/test_onboard_building.py ops/pilot-runbook.md
git commit -m "feat: onboard_building tenant skeleton command"
```

---

## Out of scope for this plan (later Phase 0 plans)

- Anchoring port + evidence-level enum (spec §5) — Plan 2. That plan also carries the spec §2.2 payload-opacity audit (no building names or predictable local IDs in chain payloads), since payload changes touch canonical hashing and the chain contract.
- DRF resident API, knox, occupancy header (spec §3) — Plan 3 (consumes Task 1's selectors and Task 2's `TenantContext`); extends the Task 9 completeness rule to API routes.
- BQL `/s/` IA changes, create-proposal flow, fund screens (spec §4) — Plan 4. Staff-side selector extraction lands there, with the surfaces that consume it.
- Flutter app and push (spec §6–7) — Phase 1 plans.
