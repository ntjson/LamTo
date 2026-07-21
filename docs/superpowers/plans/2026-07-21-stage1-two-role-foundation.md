# Stage 1: Two-Role Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the six staff roles into one building-scoped Management role, delete the role-only workflows (approvals, emergencies, corrections) and surfaces (role workspaces, resident web PWA, break-glass), and leave one Management web workspace + the untouched resident Flutter app, with the full test suite green.

**Architecture:** Expand→cutover→contract. Task 1 adds `ManagementMembership` + `require_management` alongside the old model. Tasks 2–4 delete the three leaf role-workflows while everything else stays green. Tasks 5–10 are a **cutover wave** (audit → accounts wallets → maintenance → finance → documents/notifications → factories/e2e): each task leaves its own module's tests green, but the FULL suite is red inside the wave and green again at Task 10. Tasks 11–12 rebuild the web shell as Management-only. Task 13 contracts: deletes the old role models. Task 14 is final verification.

**Tech Stack:** Django 5 + pytest-django + Postgres 17 (docker compose), Foundry/Besu chain (untouched this stage), Flutter app (untouched this stage).

**Spec:** `docs/superpowers/specs/2026-07-21-two-role-rebuild-design.md`

## Global Constraints

- Exactly two human roles. Management = active `ManagementMembership(user, building)`. Resident = active `ResidentOccupancy`. No capability codes anywhere.
- **Spec deviation (approved rationale):** `finance/acceptance.py` + `AcceptanceRecord` survive stage 1 with a swapped gate — `PaymentEvidence.acceptance` is a structural FK and the payment evidence hash chains to the acceptance event. Acceptance dies in stage 3 with the Payment→Settlement reshape.
- `WorkOrder`, work-order flows, payments, fund record/verify, and publication survive stage 1 (they die/reshape in stages 2–3). Emergency fields on WorkOrder are dropped here (they belong to the deleted emergency workflow).
- Keep product-invisible names to minimize churn: file `web/staff.py`, template dir `web/templates/web/staff/`, helper `require_staff_mfa`, URL prefix `/s/`. Only role semantics change.
- No data preservation. If a migration conflicts with the dev DB, drop and recreate it (`docker exec lamto-db-1 psql -U lamto_bootstrap -d postgres -c "DROP DATABASE IF EXISTS lamto;" ...` then `migrate`). Never edit existing migration files; always add new ones via `makemigrations`.
- Test environment (run before ANY pytest command, once per shell):

```bash
docker compose up -d          # db, minio, clamav (besu already runs separately)
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
```

- Module tests: `uv run pytest src/lamto/<app> -q`. Full suite: `uv run pytest src/lamto tests -q`.
- If pytest fails with `database "test_lamto" already exists`: `docker exec lamto-db-1 psql -U lamto_bootstrap -d postgres -c "DROP DATABASE IF EXISTS test_lamto;"`.
- Commit after every task (not every step) — cutover-wave tasks say "module tests green" in the message because the full suite is red until Task 10.

---

### Task 1: ManagementMembership model + require_management gate (expand)

**Files:**
- Modify: `src/lamto/accounts/models.py` (add model after `ResidentOccupancy`, ~line 128)
- Modify: `src/lamto/accounts/services.py` (add function; do NOT remove the capability functions yet)
- Create: `src/lamto/accounts/tests/test_management_access.py`
- Create (generated): `src/lamto/accounts/migrations/00XX_managementmembership.py`

**Interfaces:**
- Consumes: existing `User`, `Building` models.
- Produces: `ManagementMembership(user, building, active)` model with related name defaults; `require_management(user, building_id: int) -> ManagementMembership` raising `PermissionDenied("management")`. Every later task uses exactly these.

- [ ] **Step 1: Write the failing tests**

```python
# src/lamto/accounts/tests/test_management_access.py
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from lamto.accounts.models import Building, ManagementMembership, User
from lamto.accounts.services import require_management


class RequireManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="B1")
        cls.other = Building.objects.create(name="B2")
        cls.manager = User.objects.create_user(email="m@x.vn", password="pw", display_name="M")
        cls.outsider = User.objects.create_user(email="o@x.vn", password="pw", display_name="O")
        cls.membership = ManagementMembership.objects.create(
            user=cls.manager, building=cls.building
        )

    def test_active_member_passes(self):
        got = require_management(self.manager, self.building.pk)
        self.assertEqual(got.pk, self.membership.pk)

    def test_non_member_denied(self):
        with self.assertRaises(PermissionDenied):
            require_management(self.outsider, self.building.pk)

    def test_wrong_building_denied(self):
        with self.assertRaises(PermissionDenied):
            require_management(self.manager, self.other.pk)

    def test_inactive_membership_denied(self):
        ManagementMembership.objects.filter(pk=self.membership.pk).update(active=False)
        with self.assertRaises(PermissionDenied):
            require_management(self.manager, self.building.pk)

    def test_membership_unique_per_user_building(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            ManagementMembership.objects.create(user=self.manager, building=self.building)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest src/lamto/accounts/tests/test_management_access.py -q`
Expected: FAIL — `ImportError: cannot import name 'ManagementMembership'`

- [ ] **Step 3: Add the model**

In `src/lamto/accounts/models.py`, directly after the `ResidentOccupancy` class:

```python
class ManagementMembership(models.Model):
    """The single Management staff role, scoped to a building."""

    user = models.ForeignKey(User, on_delete=models.PROTECT)
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "building"], name="management_membership_once"
            )
        ]
```

- [ ] **Step 4: Add the gate**

In `src/lamto/accounts/services.py`, add at the end (keep existing imports and functions untouched):

```python
def require_management(user, building_id: int) -> "ManagementMembership":
    from .models import ManagementMembership

    membership = ManagementMembership.objects.filter(
        user=user, building_id=building_id, active=True
    ).first()
    if membership is None:
        raise PermissionDenied("management")
    return membership
```

- [ ] **Step 5: Make the migration**

Run: `uv run python manage.py makemigrations accounts`
Expected: one new migration adding `ManagementMembership`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest src/lamto/accounts/tests/test_management_access.py -q`
Expected: 5 passed.

- [ ] **Step 7: Full accounts module still green**

Run: `uv run pytest src/lamto/accounts -q`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/accounts docs/superpowers/plans
git commit -m "feat(accounts): add ManagementMembership and require_management gate"
```

---

### Task 2: Delete the corrections workflow

**Files:**
- Delete: `src/lamto/finance/corrections.py`, `src/lamto/finance/models/corrections.py`, `src/lamto/finance/tests/test_corrections.py`
- Modify: `src/lamto/finance/models/__init__.py` (drop corrections exports), `src/lamto/finance/models/ledger.py` (drop `MaintenanceFundEntry.correction` FK, ~line 82), `src/lamto/web/action_inbox.py` (delete `_correction_review_items`, ~line 532, and its call site in `action_items_for`), plus every other reference found by the grep in Step 1.
- Create (generated): finance migration removing correction models + FK.

**Interfaces:**
- Consumes: nothing new.
- Produces: a codebase with zero `correction` references outside migrations; `MaintenanceFundEntry` without a `correction` field.

- [ ] **Step 1: Enumerate every reference (this is the authoritative to-do list for this task)**

Run: `grep -rn "correction\|Correction" src/lamto tests --include="*.py" -l | grep -v __pycache__ | grep -v migrations`
Expected files include: `finance/corrections.py`, `finance/models/corrections.py`, `finance/models/__init__.py`, `finance/models/ledger.py`, `finance/tests/test_corrections.py`, `web/action_inbox.py`, `accounts/capabilities.py` (leave — deleted whole in Task 13), possibly `finance/selectors.py`, `finance/integrity.py`, `web/views/*`, `testing/factories.py`, `tests/e2e/*`. Fix every file on the list in the steps below; the task is not done while this grep (minus migrations and `capabilities.py`) returns anything.

- [ ] **Step 2: Delete the workflow files**

```bash
git rm src/lamto/finance/corrections.py src/lamto/finance/models/corrections.py src/lamto/finance/tests/test_corrections.py
```

- [ ] **Step 3: Remove structural references**

- `finance/models/__init__.py`: delete the corrections import/re-export lines.
- `finance/models/ledger.py`: delete the `correction = models.ForeignKey(...)` field on `MaintenanceFundEntry` and any correction-related constraint mentioning it.
- `web/action_inbox.py`: delete `_correction_review_items` and remove its call + imports in `action_items_for`.
- Any selector/view/factory/e2e reference from Step 1's list: delete the correction branch or assertion (these are role-workflow features, not shared plumbing). If a web view exposes a correction route, delete the route from `web/urls.py` and the view function.

- [ ] **Step 4: Migration**

Run: `uv run python manage.py makemigrations finance`
Expected: migration deleting the correction models and the `MaintenanceFundEntry.correction` field.

- [ ] **Step 5: Verify green**

Run: `uv run pytest src/lamto tests -q`
Expected: all passed (correction tests are gone; nothing else depended on them).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(finance)!: delete append-only correction workflow"
```

---

### Task 3: Delete the emergency workflow

**Files:**
- Delete: `src/lamto/finance/emergencies.py`, `src/lamto/finance/models/emergencies.py`, `src/lamto/finance/tests/test_emergencies.py`, `src/lamto/finance/management/commands/mark_overdue_ratifications.py`, `src/lamto/web/views/representative.py`
- Modify: `src/lamto/finance/models/__init__.py`, `src/lamto/finance/models/proposals.py` (drop `Proposal.Mode` and the `mode` field), `src/lamto/finance/publication.py` (delete emergency publication paths; normal path only), `src/lamto/maintenance/models.py` (drop `WorkOrder.emergency_requested_by`, `emergency_reason`, `emergency_requested_at`, `emergency`, `drill` fields and the `emergency_label` property, ~lines 196–241), `src/lamto/web/views/board.py` (delete `emergency_authorize`), `src/lamto/web/urls.py` (delete `emergency-authorize`, `emergency-decide` routes and the `representative` import), `src/lamto/web/action_inbox.py` (delete `_emergency_items`, `_emergency_ratification_items` + call sites), `src/lamto/web/forms/staff.py` (delete emergency forms), `src/lamto/accounts/security.py` (remove `"/s/emergency/"` from `BUSINESS_ROUTE_PREFIXES`, `web:emergency-*` from `FINANCE_DOCUMENT_URL_NAMES`)
- Create (generated): finance + maintenance migrations.

**Interfaces:**
- Consumes: nothing new.
- Produces: `Proposal` without `mode` (all proposals are what was previously NORMAL); `WorkOrder` without emergency fields; `publication.py` with a single (normal) publication path.

- [ ] **Step 1: Enumerate every reference**

Run: `grep -rn "emergenc\|Emergenc\|ratif\|Ratif\|\.drill\|drill=" src/lamto tests --include="*.py" -l | grep -v __pycache__ | grep -v migrations`
Fix every listed file; task incomplete while the grep (minus migrations, `capabilities.py`, and this plan) returns code references.

- [ ] **Step 2: Delete the files listed above** (`git rm` each).

- [ ] **Step 3: Remove structural references**

- `finance/models/proposals.py`: delete the `Mode` TextChoices and `mode` field from `Proposal`; delete `mode` from any snapshot/payload construction in `finance/proposals.py`.
- `finance/publication.py`: delete every branch conditioned on `Proposal.Mode.EMERGENCY` / emergency ratification (including `mark_overdue` interplay); keep only the normal path. Where code reads `proposal.mode == Proposal.Mode.NORMAL`, the condition becomes unconditional.
- `maintenance/models.py`: delete the five emergency/drill fields + `emergency_label`; keep `AuthorizationStatus` (approvals task handles it).
- Inbox, urls, forms, security constants: as listed in Files.
- Tests in surviving modules that exercised emergency paths (`test_publication.py`, `test_workorders.py`, e2e drill scenarios): delete those test functions/scenarios only.

- [ ] **Step 4: Migrations**

Run: `uv run python manage.py makemigrations finance maintenance`
Expected: drop of emergency models and fields.

- [ ] **Step 5: Verify green**

Run: `uv run pytest src/lamto tests -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat!: delete emergency spending workflow and proposal modes"
```

---

### Task 4: Delete the approval workflow (Management publishes directly)

**Files:**
- Delete: `src/lamto/finance/approvals.py`, `src/lamto/finance/models/approvals.py`, `src/lamto/finance/tests/test_approvals.py`
- Modify: `src/lamto/finance/models/__init__.py`; `src/lamto/finance/publication.py` (delete `_board_approval`, `_rep_approval` ~lines 155–178 and every consumer; publication payload loses its `"approvals"` key entirely; the gate that raised "Normal publication requires Board and resident-representative approvals." ~line 450 is deleted); `src/lamto/finance/integrity.py` (delete the `version.approval_decisions` walk, ~line 36); `src/lamto/finance/proposals.py` (delete the post-submit notification block ~lines 251–256 that imports `_users_with_capability` — proposal submission no longer notifies approvers); `src/lamto/web/action_inbox.py` (delete `_proposal_approval_items` + call site); `src/lamto/maintenance/models.py` + `src/lamto/maintenance/workorders.py` (WorkOrder `AuthorizationStatus`: with approvals gone, spending work orders are authorized by proposal publication alone — wherever authorization state was derived from `ApprovalDecision`, derive it from "current proposal version is published" instead; if it was stored/written by approvals code, keep the field but set it in the publication path); notification hooks for approval events (`notifications/hooks.py` — delete approval-specific notify functions and their senders); web views/urls exposing approve endpoints (in `web/views/board.py` / `operator.py` — delete the approve view functions + routes).
- Modify: `src/lamto/finance/tests/test_publication.py`, `test_integrity.py`, e2e scenarios — remove approval steps; publication now proceeds directly after submission.
- Create (generated): finance migration dropping approval models.

**Interfaces:**
- Consumes: nothing new.
- Produces: `publish` callable without any approval precondition; publication evidence payload WITHOUT an `"approvals"` key (payload hash changes — republished fixtures in tests must be regenerated, not hand-patched).

- [ ] **Step 1: Enumerate every reference**

Run: `grep -rn "approval\|Approval\|approve\|APPROVE" src/lamto tests --include="*.py" -l | grep -v __pycache__ | grep -v migrations`
Fix every file; task incomplete while the grep (minus migrations/`capabilities.py`) returns code references.

- [ ] **Step 2: Delete the three files** (`git rm`).

- [ ] **Step 3: Reshape publication and integrity** as specified in Files. The publication payload builder (~line 245) currently does:

```python
payload["approvals"] = {}
...
payload["approvals"]["board"] = {...}
payload["approvals"]["resident_rep"] = {...}
```

Delete the `"approvals"` key and both fill-ins. Integrity verification walks only the artifacts that still exist (proposal version, publication snapshot, fund entries).

- [ ] **Step 4: Migration + test reshape**

Run: `uv run python manage.py makemigrations finance`
Update `test_publication.py`/`test_integrity.py`: remove approval setup steps; assert publish succeeds directly after `publish_proposal_version`; regenerate any hard-coded payload-hash expectations by computing them from the new payload builder (never paste stale hashes).

- [ ] **Step 5: Verify green**

Run: `uv run pytest src/lamto tests -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(finance)!: delete approval chains; Management publishes directly"
```

---

### Task 5: Cutover — audit (START OF WAVE: full suite red until Task 10)

**Files:**
- Modify: `src/lamto/audit/models.py` (FK target), `src/lamto/audit/services.py` (validation), `src/lamto/audit/tests/test_immutability.py`
- Create (generated): audit migration.

**Interfaces:**
- Consumes: `ManagementMembership` from Task 1.
- Produces: `record_audit(actor, membership, action, target_type, target_id, result, metadata=None)` where `membership: ManagementMembership | None` — **strict**: passing an `OrganizationMembership` raises `PermissionDenied`. Signature and resident special-cases unchanged. All later tasks call it with `ManagementMembership`.

- [ ] **Step 1: Swap the model FK**

`src/lamto/audit/models.py`:

```python
from django.conf import settings
from django.db import models

from lamto.accounts.models import ManagementMembership


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    membership = models.ForeignKey(
        ManagementMembership, null=True, blank=True, on_delete=models.PROTECT
    )
    # ... rest of the model unchanged (action, target_type, target_id,
    # metadata, result, created_at, append-only save/delete).
```

- [ ] **Step 2: Swap validation in `record_audit`**

`src/lamto/audit/services.py` — replace both `OrganizationMembership` filters:

```python
from lamto.accounts.models import ManagementMembership, ResidentOccupancy
```

In the `membership is None` branch, the fallback check becomes
`ManagementMembership.objects.filter(user_id=getattr(actor, "pk", None), active=True).exists()`.
The `elif` attribution check becomes:

```python
    elif not isinstance(membership, ManagementMembership) or not ManagementMembership.objects.filter(
        pk=membership.pk, user_id=getattr(actor, "pk", None), active=True
    ).exists():
        raise PermissionDenied("Audit membership attribution is invalid.")
```

- [ ] **Step 3: Migration**

Run: `uv run python manage.py makemigrations audit`

- [ ] **Step 4: Update audit tests to build `ManagementMembership` and verify module green**

Run: `uv run pytest src/lamto/audit -q`
Expected: all passed. (Other modules are now red — expected until Task 10.)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(audit)!: attribute events to ManagementMembership (wave 1/6)"
```

---

### Task 6: Cutover — accounts wallet trio + staff signing tests

**Files:**
- Modify: `src/lamto/accounts/models.py` (`SignerWallet.membership`, `WalletRegistrationChallenge.membership`, `SignerAuthorizationRequest.requested_by` → FK `ManagementMembership`, same field names), plus any wallet service code in `accounts/` referencing `OrganizationMembership` for wallets.
- Modify: `src/lamto/accounts/tests/test_models.py` (wallet tests), `src/lamto/web/tests/test_staff_signing.py` (defer full-green to Task 11 if it needs the web shell; update the membership construction now).
- Create (generated): accounts migration.

**Interfaces:**
- Consumes: Task 5's `record_audit`.
- Produces: wallet models keyed by `ManagementMembership`; `make_signer(...)` in factories still broken until Task 10 (known).

- [ ] **Step 1: Swap the three FK targets** (field names unchanged, `on_delete=models.PROTECT` unchanged).
- [ ] **Step 2: Migration:** `uv run python manage.py makemigrations accounts`
- [ ] **Step 3: Update accounts wallet tests** to create `ManagementMembership` instead of org+membership pairs.
- [ ] **Step 4: Module green:** `uv run pytest src/lamto/accounts -q` → all passed.
- [ ] **Step 5: Commit** — `git commit -am "refactor(accounts)!: key signer wallets by ManagementMembership (wave 2/6)"`

---

### Task 7: Cutover — maintenance services

**Files:**
- Modify: `src/lamto/maintenance/triage.py`, `src/lamto/maintenance/workorders.py`, `src/lamto/maintenance/ratings.py` (if it resolves staff), `src/lamto/maintenance/models.py` (any remaining role FK), tests `test_cases.py`, `test_workorders.py`, `test_ratings.py`, `test_reporting.py`.

**Interfaces:**
- Consumes: `require_management(user, building_id)` (Task 1), strict `record_audit` (Task 5).
- Produces: `confirm_triage(operator, ...)`-style entry points keep their signatures but the first argument is now any Management user; internal membership resolution is exactly `require_management(user, building_id)`.

- [ ] **Step 1: Replace membership resolution.** In `triage.py`, delete `_operator_membership` (lines 23–36) and replace every call `_operator_membership(operator, X)` with `require_management(operator, X)` (import from `lamto.accounts.services`). Delete the `REPORT_TRIAGE` / `require_capability` / `OrganizationMembership` imports. In `workorders.py`, likewise delete `_operator_membership` and `_maintenance_membership` (lines 14–43); both call sites use `require_management(user, case.building_id)` — the operator/maintenance distinction no longer exists. `membership.organization.building_id` → `membership.building_id` everywhere.
- [ ] **Step 2: Update maintenance tests**: replace org/role/capability setup with `ManagementMembership.objects.create(user=staff, building=building)`; assertions about "wrong role denied" become "non-management denied".
- [ ] **Step 3: Module green:** `uv run pytest src/lamto/maintenance -q` → all passed.
- [ ] **Step 4: Commit** — `git commit -am "refactor(maintenance)!: management gate for triage and work (wave 3/6)"`

---

### Task 8: Cutover — finance services and models

**Files:**
- Modify models: `src/lamto/finance/models/proposals.py` (`creator_membership` ×2 → `ManagementMembership`), `src/lamto/finance/models/execution.py` (`AcceptanceRecord.membership`, `PaymentEvidence.recorder`, `PaymentVerification.membership`), `src/lamto/finance/models/ledger.py` (`recorder`, `membership`, `publisher`, `actor` FKs).
- Modify services: `src/lamto/finance/proposals.py`, `acceptance.py`, `payments.py`, `fund.py`, `publication.py`, `integrity.py`, `selectors.py` — every `require_capability(...)` becomes `require_management(user, building_id)`; every `Organization.Kind.BOARD`-style kind/role check is deleted (the management gate IS the authorization); `membership.organization.building_id` → `membership.building_id`.
- Modify tests: `test_proposals.py`, `test_acceptance.py`, `test_payments.py`, `test_fund.py`, `test_publication.py`, `test_integrity.py`.
- Create (generated): finance migration.

**Interfaces:**
- Consumes: Tasks 1, 5, 6.
- Produces: unchanged service signatures (`create_proposal(work_order, creator_membership)`, `record_payment(acceptance, membership, ...)` etc.) where every `membership` parameter is now a `ManagementMembership`. Dual-control verify steps (payment verify, fund verify) survive mechanically: any second active Management member may verify; a same-user check (`verifier.pk != recorder.membership_id` style) is KEPT where it exists today.

- [ ] **Step 1: Swap the model FK targets**, `makemigrations finance`.
- [ ] **Step 2: Swap the service gates.** Example — `finance/proposals.py` lines 141–144 become:

```python
    membership = require_management(
        creator_membership.user, locked_work_order.case.building_id
    )
```

(the separate building check disappears — `require_management` scopes by building). Apply the same pattern at every `require_capability` site found by:
`grep -rn "require_capability\|Organization.Kind\|organization.building_id\|organization__building" src/lamto/finance`
The task is incomplete while that grep returns anything.
- [ ] **Step 3: Update finance tests** to two-role setup (one building, 2+ management users for dual-control paths, residents unchanged).
- [ ] **Step 4: Module green:** `uv run pytest src/lamto/finance -q` → all passed.
- [ ] **Step 5: Commit** — `git commit -am "refactor(finance)!: management gate across proposals/payments/fund/publication (wave 4/6)"`

---

### Task 9: Cutover — documents, notifications, evidence

**Files:**
- Modify: `src/lamto/documents/access.py` + `services.py` (role-based access rules → `require_management` or resident-occupancy checks; auditor/board read scopes collapse to management), `src/lamto/notifications/hooks.py` (`_users_with_capability(building_id, code)` → new `_management_users(building_id)` returning `User` queryset via `ManagementMembership`; delete `_users_with_role`), `src/lamto/evidence/services.py` (membership references → `ManagementMembership`).
- Modify tests: `documents/tests/*`, `notifications/tests/test_delivery.py`, `evidence/tests/*`.

**Interfaces:**
- Consumes: Tasks 1, 5.
- Produces: `_management_users(building_id: int)` — every notify hook that targeted a capability now targets all active Management users of the building.

- [ ] **Step 1:** Implement `_management_users`:

```python
def _management_users(building_id: int):
    from lamto.accounts.models import ManagementMembership

    return [
        m.user
        for m in ManagementMembership.objects.select_related("user").filter(
            building_id=building_id, active=True
        )
    ]
```

Replace every `_users_with_capability(building_id, "<code>")` call with `_management_users(building_id)`; delete `_users_with_role` and its callers' role arguments.
- [ ] **Step 2:** Documents access: replace org-kind scoping with: uploader is resident (occupancy checked) or management (`require_management`); download visibility checks likewise. Keep quarantine logic untouched.
- [ ] **Step 3:** Evidence services: mechanical membership-type swap only.
- [ ] **Step 4: Module green:** `uv run pytest src/lamto/documents src/lamto/notifications src/lamto/evidence -q` → all passed.
- [ ] **Step 5: Commit** — `git commit -am "refactor!: management targeting for documents/notifications/evidence (wave 5/6)"`

---

### Task 10: Cutover — factories, e2e seed, wave-end full green

**Files:**
- Modify: `src/lamto/testing/factories.py` (`seed_pilot_world`, `PilotSeed`, `PilotDomainDriver`, `make_signer`), `tests/e2e/*`, `tests/isolation/*`, `tests/fixtures/*` as flagged by grep.

**Interfaces:**
- Consumes: everything above.
- Produces: `PilotSeed` exposing `management_users: list[User]` and `management_memberships: list[ManagementMembership]` instead of per-role members; `make_signer(membership: ManagementMembership, ...)` unchanged otherwise; `PilotDomainDriver` methods drive the same surviving flows (report→triage→case→work→acceptance→payment→publication) with Management actors — approval/emergency/correction driver methods are already gone (Tasks 2–4).

- [ ] **Step 1:** Rewrite the seed: replace the five-organization + six-role construction with one building + N management users (`ManagementMembership` each, wallets via `make_signer`) + residents. Field/attr renames must be chased through every consumer (`grep -rn "seed\.\|PilotSeed" src/lamto tests`).
- [ ] **Step 2:** Update e2e scenarios: drop role-switching steps; Management performs triage, work, acceptance, payment record, second-manager verify, publication.
- [ ] **Step 3: WAVE END — full suite:**

Run: `uv run pytest src/lamto tests -q`
Expected: **all passed** except `src/lamto/web/tests/*` role-workspace/nav/resident tests, which Task 11–12 rewrite. If ONLY web tests fail, proceed; anything else red must be fixed now.
- [ ] **Step 4: Commit** — `git commit -am "refactor(testing)!: two-role pilot world and e2e drivers (wave 6/6)"`

---

### Task 11: Management web shell (staff.py, inbox, security)

**Files:**
- Modify: `src/lamto/web/staff.py` (full rewrite below), `src/lamto/web/views/staff_common.py` (`switch_membership` → building switch; `require_staff_capability` callers), `src/lamto/web/action_inbox.py` (signature `action_items_for(membership: ManagementMembership)`; `_has`/`_building_id` collapse; remaining role conditionals removed — every surviving queue is shown), `src/lamto/web/views/security.py` (delete break-glass views), `src/lamto/web/urls.py` (delete 3 break-glass routes), `src/lamto/accounts/middleware.py` (remove break-glass enforcement if present), templates `web/staff/shell.html` (nav shows all items; switcher lists buildings), `_sign_confirmation.html` untouched.
- Modify tests: `web/tests/test_staff_nav.py` (rewrite: one management user sees all six areas; non-management denied), `web/tests/test_staff_signing.py`, `web/tests/test_exports_and_health.py`, `web/tests/test_list_pattern.py`.

**Interfaces:**
- Consumes: `require_management`, `ManagementMembership`.
- Produces (used by Task 12's views): `resolve_active_management(request, *, building_id=None) -> tuple[ManagementMembership, list[ManagementMembership]]`; `require_management_context(request) -> tuple[ManagementMembership, list[ManagementMembership]]` (MFA + resolution); `staff_context(request, membership, memberships, *, nav_active=None, **extra)` (same name/shape as today minus `capabilities`); session key `SESSION_MANAGEMENT_KEY = "active_management_id"`.

- [ ] **Step 1: Rewrite `src/lamto/web/staff.py`:**

```python
"""Management session helpers: active building membership + workspace nav."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from lamto.accounts.models import ManagementMembership
from lamto.accounts.security import require_staff_mfa

SESSION_MANAGEMENT_KEY = "active_management_id"


def user_memberships(user):
    return (
        ManagementMembership.objects.select_related("building")
        .filter(user=user, active=True)
        .order_by("building__name", "pk")
    )


def resolve_active_management(request, *, building_id=None):
    memberships = list(user_memberships(request.user))
    if not memberships:
        raise PermissionDenied("An active management membership is required.")

    candidate = building_id
    if candidate is None:
        candidate = request.GET.get("building") or request.POST.get("building")
    if candidate is None:
        candidate = request.session.get(SESSION_MANAGEMENT_KEY)

    selected = None
    if candidate is not None:
        try:
            cid = int(candidate)
        except (TypeError, ValueError):
            cid = None
        if cid is not None:
            selected = next((m for m in memberships if m.pk == cid), None)
    if selected is None:
        selected = memberships[0]

    request.session[SESSION_MANAGEMENT_KEY] = selected.pk
    return selected, memberships


def require_management_context(request):
    require_staff_mfa(request)
    return resolve_active_management(request)


def nav_items_for(membership) -> list[dict]:
    return [
        {"label": _("Inbox"), "url_name": "web:action-inbox", "active_key": "inbox"},
        {"label": _("Cases"), "url_name": "web:case-list", "active_key": "cases"},
        {"label": _("Work"), "url_name": "web:work-order-list", "active_key": "work"},
        {"label": _("Finance"), "url_name": "web:proposal-list", "active_key": "finance"},
        {"label": _("Exports"), "url_name": "web:audit-export", "active_key": "exports"},
        {"label": _("Ops"), "url_name": "web:ops-health", "active_key": "ops"},
    ]


def finance_nav_items_for(membership) -> list[dict[str, str]]:
    return [
        {"label": _("Proposals"), "url_name": "web:proposal-list", "active_key": "proposals"},
        {"label": _("Payments"), "url_name": "web:payment-list", "active_key": "payments"},
        {"label": _("Fund"), "url_name": "web:fund-home", "active_key": "fund"},
    ]


def staff_context(request, membership, memberships, *, nav_active=None, **extra):
    from lamto.web.views.staff_common import pop_sign_confirmation

    nav_items = nav_items_for(membership)
    for item in nav_items:
        item["is_active"] = bool(nav_active) and item.get("active_key") == nav_active
    return {
        "membership": membership,
        "memberships": memberships,
        "membership_count": len(memberships) if memberships is not None else 0,
        "nav_items": nav_items,
        "nav_active": nav_active,
        "finance_nav_items": finance_nav_items_for(membership),
        "sign_confirmation": pop_sign_confirmation(request),
        **extra,
    }


def switch_building_redirect(request):
    building = request.POST.get("building") or request.GET.get("building")
    membership, _memberships = resolve_active_management(request, building_id=building)
    request.session[SESSION_MANAGEMENT_KEY] = membership.pk
    return redirect("web:action-inbox")
```

Note: the switcher param is the **membership pk** (candidate matched against membership pks), consistent with today's behavior; templates label it by building name.
- [ ] **Step 2:** `action_inbox.py`: change `action_items_for` to take `ManagementMembership`; delete `_has`, the capability imports, and every role conditional; call all surviving item builders unconditionally (`_manual_triage_items`, `_deadline_risk_items`, `_assigned_work_items` (now `membership.user_id`), `_work_acceptance_items`, `_payment_record_items`, `_payment_verify_items`, `_pending_publication_items`, `_integrity_mismatch_items`, `_failed_outbox_items`, `_quarantined_upload_items`). `_building_id(membership)` returns `membership.building_id`.
- [ ] **Step 3:** `staff_common.py`: `action_inbox` + `staff_home` use `require_management_context`; rename URL handler `switch_membership` → keep route name `switch-membership`? No — replace route: `path("s/building/", staff_common.switch_building, name="switch-building")` and update `shell.html` form. Delete `deny_tech_admin_business_access` / capability imports everywhere in `web/`.
- [ ] **Step 4:** `security.py` views: delete the three break-glass views + template references; keep MFA setup/verify/revoke + reauth + `SecureLoginView`/`secure_logout`.
- [ ] **Step 5:** Update the four web test files listed to the two-role world (management user with TOTP sees nav; resident user gets `PermissionDenied` on `/s/`).
- [ ] **Step 6:** Run: `uv run pytest src/lamto/web -q` — remaining failures must ONLY be in files Task 12 touches (`test_role_workspaces.py`, `test_resident_views.py`, view modules).
- [ ] **Step 7: Commit** — `git commit -am "feat(web)!: management-only shell, building switcher, single inbox"`

---

### Task 12: Topic view modules, URL rewrite, resident PWA deletion

**Files:**
- Create: `src/lamto/web/views/requests.py` (move `case_list`, `case_detail`, `report_detail` from `operator.py`), `src/lamto/web/views/proposals.py` (move `proposal_list`, `proposal_detail`, `proposal_create` from `operator.py`), `src/lamto/web/views/payments.py` (move `payment_list`, `payment_record`, `payment_record_detail`, `payment_verify_detail`, `accept_work` from `board.py`), `src/lamto/web/views/work.py` (move `work_order_list`, `work_order_detail` from `maintenance.py`).
- Delete: `src/lamto/web/views/operator.py`, `board.py`, `maintenance.py`, `auditor.py`, `representative.py` (if not already gone), `resident.py`; `src/lamto/web/forms/resident.py`; `src/lamto/web/tests/test_role_workspaces.py`, `test_resident_views.py`; templates `web/templates/web/resident/` (ALL except `login.html`); the PWA assets (service worker JS + manifest under `web/static/` — locate via `grep -rn "service-worker\|manifest" src/lamto/web/static src/lamto/web/views`); `audit_search` view + template + route.
- Modify: `src/lamto/web/urls.py` (full rewrite below), `src/lamto/config/urls.py` (login template path), move `login.html` → `src/lamto/web/templates/web/login.html`, `src/lamto/web/views/exports.py` (gate: `_require_auditor_export` → `require_management_context`; kind/role checks deleted; `AuditEvent.objects.filter(membership__organization__building_id=…)` → `membership__building_id=…`; `building_id = membership.building_id`), `src/lamto/web/views/health.py` (tech-admin gate → `require_management_context`), `src/lamto/web/views/fund.py` (capability gates → `require_management_context`), `src/lamto/accounts/security.py` (`FINANCE_DOCUMENT_URL_NAMES`: drop deleted url names), templates referencing removed routes.
- Create: rewritten `src/lamto/web/tests/test_management_workspace.py` (covering: management can open every nav area; a resident-only user is denied on all `/s/` routes; case detail renders; payment record requires second-manager verify path reachable).

**Interfaces:**
- Consumes: Task 11's `require_management_context`, `staff_context`.
- Produces: final stage-1 URL map (below). Later stages add `requests`/`settlements` routes to these modules rather than new role files.

- [ ] **Step 1: Move view functions verbatim** (only the gate line changes: `require_staff_capability(request, CODE)` → `require_management_context(request)`), keeping template names and context keys. Views moved, not rewritten.
- [ ] **Step 2: Rewrite `src/lamto/web/urls.py`:**

```python
from django.urls import path
from django.views.generic import RedirectView

from lamto.web.views import exports, fund, health, payments, proposals, requests, security, staff_common, work

app_name = "web"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="web:staff-home", permanent=False), name="root"),
    # Security / MFA
    path("s/security/mfa/setup/", security.mfa_setup, name="mfa-setup"),
    path("s/security/mfa/verify/", security.mfa_verify, name="mfa-verify"),
    path("s/security/mfa/revoke/<int:device_id>/", security.mfa_revoke_device, name="mfa-revoke"),
    path("s/security/reauth/", security.reauth, name="reauth"),
    # Shell
    path("s/", staff_common.staff_home, name="staff-home"),
    path("s/inbox/", staff_common.action_inbox, name="action-inbox"),
    path("s/building/", staff_common.switch_building, name="switch-building"),
    # Requests (cases + reports)
    path("s/cases/", requests.case_list, name="case-list"),
    path("s/reports/<int:pk>/", requests.report_detail, name="staff-report-detail"),
    path("s/cases/<int:pk>/", requests.case_detail, name="case-detail"),
    # Proposals
    path("s/proposals/", proposals.proposal_list, name="proposal-list"),
    path("s/proposals/<int:pk>/", proposals.proposal_detail, name="proposal-detail"),
    path("s/work/<int:pk>/propose/", proposals.proposal_create, name="proposal-create"),
    # Work (dies in stage 2)
    path("s/work/", work.work_order_list, name="work-order-list"),
    path("s/work/<int:pk>/", work.work_order_detail, name="work-order-detail"),
    path("s/work/<int:pk>/accept/", payments.accept_work, name="work-accept"),
    # Payments
    path("s/payments/", payments.payment_list, name="payment-list"),
    path("s/payments/record/", payments.payment_record, name="payment-record"),
    path("s/payments/record/<int:pk>/", payments.payment_record_detail, name="payment-record-detail"),
    path("s/payments/verify/<int:pk>/", payments.payment_verify_detail, name="payment-verify-detail"),
    # Exports
    path("s/audit/export/", exports.audit_export, name="audit-export"),
    # Fund
    path("s/fund/", fund.fund_home, name="fund-home"),
    path("s/fund/record/", fund.fund_record, name="fund-record"),
    path("s/fund/verify/<int:pk>/", fund.fund_verify, name="fund-verify"),
    # Ops
    path("s/ops/health/", health.ops_health, name="ops-health"),
    path("s/ops/metrics/", health.pilot_metrics, name="pilot-metrics"),
]
```

- [ ] **Step 3:** `config/urls.py`: `template_name="web/login.html"`; `git mv src/lamto/web/templates/web/resident/login.html src/lamto/web/templates/web/login.html`; then `git rm -r src/lamto/web/templates/web/resident`.
- [ ] **Step 4:** Fix `exports.py`/`health.py`/`fund.py` gates as listed; update the Exports nav url-name if it differs; `security.py` constants trimmed (`BUSINESS_ROUTE_PREFIXES` drops `/s/audit/`? NO — keep the prefix list only if break-glass code consuming it still exists; if `assert_break_glass_allows_path` was deleted in Task 11, delete both constants and their imports).
- [ ] **Step 5:** Write `test_management_workspace.py` (Django `TestCase` + client, TOTP-verified management user via the same helper the old workspace tests used; assert 200 on each nav URL, 403 for a resident-only user on `/s/`, `/s/cases/`, `/s/payments/`).
- [ ] **Step 6: Web module green:** `uv run pytest src/lamto/web -q` → all passed.
- [ ] **Step 7: Full suite:** `uv run pytest src/lamto tests -q` → all passed.
- [ ] **Step 8: Commit** — `git commit -am "feat(web)!: topic view modules, management-only urls, delete resident PWA"`

---

### Task 13: Contract — delete the role model, capabilities, break-glass; rewrite onboarding

**Files:**
- Modify: `src/lamto/accounts/models.py` (delete `Organization`, `OrganizationMembership`, `CapabilityGrant`, `BreakGlassSession`, `BreakGlassRevocation`; keep `BackupMarker`, `AuthThrottleBucket`), `src/lamto/accounts/services.py` (delete `grant_capability`, `require_capability` and the capabilities import — file now holds only `require_management` and any unrelated helpers), `src/lamto/accounts/security.py` (delete `membership_is_tech_admin`, `deny_tech_admin_business_access`, `active_break_glass_session`, `is_break_glass_active`, `assert_break_glass_allows_path`, `issue_break_glass_consent`, `validate_break_glass_consent`, `start_break_glass`, `revoke_break_glass`, `BUSINESS_ROUTE_PREFIXES`, `FINANCE_DOCUMENT_URL_NAMES`, the `OrganizationMembership` import, and the break-glass constants; `_deny_sensitive` reads `active_management_id` and resolves `ManagementMembership`), `src/lamto/accounts/tenancy.py` (docstring + `from_membership` uses `membership.building_id`), `src/lamto/accounts/middleware.py` (drop any deleted-symbol imports).
- Delete: `src/lamto/accounts/capabilities.py`, `src/lamto/accounts/tests/test_capabilities.py`; break-glass tests inside `test_security.py` (delete those test classes only).
- Rewrite: `src/lamto/accounts/management/commands/onboard_building.py` (below) + `src/lamto/accounts/tests/test_onboard_building.py`.
- Create (generated): accounts migration deleting the five models.

**Interfaces:**
- Consumes: everything.
- Produces: `python manage.py onboard_building --name B --locations ... --units ... [--managers email1,email2]` creating the building, fund, locations, units, and (optionally) management users+memberships.

- [ ] **Step 1: Delete models + services + security symbols** as enumerated. Then:

Run: `grep -rn "OrganizationMembership\|CapabilityGrant\|Organization\b\|break_glass\|BreakGlass\|capabilit" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations`
Expected: **zero** hits. Fix any stragglers before proceeding.
- [ ] **Step 2: Migration:** `uv run python manage.py makemigrations accounts` — deletes the five models. If `makemigrations` complains about dependent migrations state, that's a bug in an earlier task — investigate, don't force.
- [ ] **Step 3: Rewrite the onboarding command:**

```python
"""Onboard a new building tenant: building, fund, locations, units, and
optional Management users. Wallets and the fund opening balance stay in the
runbook — they need real humans and signed evidence.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from lamto.accounts.models import Building, ManagementMembership, Unit, User
from lamto.finance.models import MaintenanceFund
from lamto.maintenance.models import BuildingLocation


def _split(raw):
    return [part.strip() for part in raw.split(",") if part.strip()]


class Command(BaseCommand):
    help = "Create a building tenant with its fund, locations, units, and managers."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Building display name.")
        parser.add_argument("--timezone", default="Asia/Ho_Chi_Minh")
        parser.add_argument("--locations", default="", help="Comma-separated root location names.")
        parser.add_argument("--units", default="", help="Comma-separated unit labels.")
        parser.add_argument(
            "--managers",
            default="",
            help="Comma-separated emails; existing users get a ManagementMembership, "
            "missing users are created inactive-password.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        name = options["name"].strip()
        if not name:
            raise CommandError("--name is required.")
        if Building.objects.filter(name=name).exists():
            raise CommandError(f"Building {name!r} already exists.")
        building = Building.objects.create(name=name, timezone=options["timezone"])
        MaintenanceFund.objects.create(building=building)
        for location_name in _split(options["locations"]):
            BuildingLocation.objects.create(building=building, name=location_name)
        for unit_label in _split(options["units"]):
            Unit.objects.create(building=building, label=unit_label)
        for email in _split(options["managers"]):
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email=email, password=None, display_name=email)
            ManagementMembership.objects.create(user=user, building=building)

        self.stdout.write(self.style.SUCCESS(f"Building onboarded: {name} (id={building.pk})"))
        self.stdout.write(
            "Next steps (runbook): set manager passwords + TOTP, register signer "
            "wallets, add resident occupancies (set phone numbers for phone "
            "login), then record and verify the fund opening balance."
        )
```

- [ ] **Step 4: Update `test_onboard_building.py`:** assert building/fund/locations/units created, `--managers a@x.vn` creates user + membership, duplicate name errors. Delete organization assertions.
- [ ] **Step 5: Full suite:** `uv run pytest src/lamto tests -q` → all passed.
- [ ] **Step 6: Commit** — `git commit -am "feat(accounts)!: delete role/capability/break-glass model; two-role onboarding"`

---

### Task 14: Final verification

**Files:** none (verification only; fix-forward anything found).

- [ ] **Step 1: Role-symbol sweep** (must all return zero code hits outside migrations/locale):

```bash
grep -rn "OPERATOR\|BOARD\|MAINTENANCE\b\|RESIDENT_REP\|AUDITOR\|TECH_ADMIN" src/lamto --include="*.py" | grep -v __pycache__ | grep -v migrations
grep -rn "require_capability\|capabilities_for\|CapabilityGrant" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations
```

- [ ] **Step 2: Fresh-database migration check:**

```bash
docker exec lamto-db-1 psql -U lamto_bootstrap -d postgres -c "DROP DATABASE IF EXISTS lamto;" -c "CREATE DATABASE lamto OWNER lamto_owner;"
uv run python manage.py migrate
```

Expected: clean run, no prompts.
- [ ] **Step 3: Full suite:** `uv run pytest src/lamto tests -q` → all passed.
- [ ] **Step 4: Flutter untouched check:** `cd app && flutter test` → same result as on `master` before stage 1 (the app is untouched this stage; API surface consumed by the app — `/api/v1/*` — was not modified).
- [ ] **Step 5: Commit anything fixed; otherwise tag the stage:**

```bash
git commit -am "chore: stage 1 verification fixes" # only if needed
```

---

## Self-review notes (already applied)

- Acceptance survives stage 1 (structural under payments) — documented deviation, deleted in stage 3.
- `AuthorizationStatus` on WorkOrder: after Task 4, derived from proposal publication; field dies with WorkOrder in stage 2.
- Tasks 5–10 are an explicitly-red wave; every wave task's gate is "own module green", Task 10's gate is full green minus web, Task 12 restores full green.
- The web login page moves out of the resident template dir before that dir is deleted (Task 12 Step 3 ordering).
