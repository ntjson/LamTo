# Staff Workflow Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace error-prone staff evidence identifiers with scoped choices, expose LamTo's accountability chain and signed consequences, improve staff orientation and hierarchy, remove the staff Account tab, and hide resident navigation only on authentication/security pages.

**Architecture:** Keep Django server rendering authoritative. Add small reusable selection and presentation helpers to existing staff modules, render native controls and shared template partials, and use the existing wallet script only to mirror editable form values into review copy. Preserve all domain validation, capabilities, tenancy boundaries, and signature verification.

**Tech Stack:** Python 3.12, Django 5, Django templates, existing vanilla JavaScript and CSS, pytest.

## Global Constraints

- Follow `PRODUCT.md`, `DESIGN.md`, and `docs/superpowers/specs/2026-07-18-staff-workflow-clarity-design.md`.
- WCAG 2.2 AA; visible focus; 44px web targets; color never carries meaning alone.
- No new dependency, API, migration, client-side store, or JavaScript framework.
- Server validation remains authoritative for evidence, tenancy, amounts, capabilities, and signatures.
- Staff Account navigation is removed; the resident account route remains.
- Resident bottom navigation is hidden only on login, MFA setup, and re-authentication pages.
- Write each test first and observe the intended failure before production edits.

---

### Task 1: Scope the Two Navigation Removals

**Files:**
- Modify: `src/lamto/web/tests/test_staff_ui.py`
- Modify: `src/lamto/web/templates/web/base.html`
- Modify: `src/lamto/web/templates/web/resident/login.html`
- Modify: `src/lamto/web/templates/web/security/mfa_setup.html`
- Modify: `src/lamto/web/templates/web/security/reauth.html`
- Modify: `src/lamto/web/templates/web/staff/shell.html`
- Modify: `src/lamto/web/static/web/app.css`

**Interfaces:** `web/base.html` produces `body_class` and `bottom_nav` blocks. Authentication/security templates override both. The resident `web:account` route is unchanged.

- [ ] **Step 1: Add failing contract tests**

Add to `StaffUiContractTests`:

```python
def test_staff_shell_has_no_account_destination(self):
    shell = (STAFF_TEMPLATES / "shell.html").read_text(encoding="utf-8")
    self.assertNotIn("web:account", shell)
    self.assertNotIn(">Account</a>", shell)

def test_authentication_pages_suppress_resident_navigation(self):
    base = (WEB_ROOT / "templates" / "web" / "base.html").read_text(encoding="utf-8")
    self.assertIn("{% block bottom_nav %}", base)
    self.assertIn("{% block body_class %}", base)
    for relative in ("resident/login.html", "security/mfa_setup.html", "security/reauth.html"):
        source = (WEB_ROOT / "templates" / "web" / relative).read_text(encoding="utf-8")
        self.assertIn("{% block bottom_nav %}{% endblock %}", source)
        self.assertIn("{% block body_class %}no-bottom-nav{% endblock %}", source)

def test_authenticated_resident_navigation_remains_in_base(self):
    base = (WEB_ROOT / "templates" / "web" / "base.html").read_text(encoding="utf-8")
    self.assertIn('class="bottom-nav"', base)
    self.assertIn("web:account", base)
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest src/lamto/web/tests/test_staff_ui.py::StaffUiContractTests::test_staff_shell_has_no_account_destination src/lamto/web/tests/test_staff_ui.py::StaffUiContractTests::test_authentication_pages_suppress_resident_navigation src/lamto/web/tests/test_staff_ui.py::StaffUiContractTests::test_authenticated_resident_navigation_remains_in_base -q
```

Expected: two failures because the Account link and unblocked resident navigation still exist.

- [ ] **Step 3: Implement the template seams**

In `web/base.html`, change the body opening and wrap the existing navigation:

```django
<body class="{% block body_class %}{% endblock %}">
{% block bottom_nav %}
<nav class="bottom-nav" role="navigation" aria-label="Resident">
  {# keep all existing resident links unchanged #}
</nav>
{% endblock %}
```

Immediately after `{% extends "web/base.html" %}` in login, MFA setup, and re-authentication templates add:

```django
{% block body_class %}no-bottom-nav{% endblock %}
{% block bottom_nav %}{% endblock %}
```

Delete only the hard-coded Account anchor from `web/staff/shell.html`. Add:

```css
body.no-bottom-nav {
  padding-bottom: 0;
}
```

- [ ] **Step 4: Verify GREEN and commit**

```bash
uv run pytest src/lamto/web/tests/test_staff_ui.py -q
git add src/lamto/web/tests/test_staff_ui.py src/lamto/web/templates/web/base.html src/lamto/web/templates/web/resident/login.html src/lamto/web/templates/web/security/mfa_setup.html src/lamto/web/templates/web/security/reauth.html src/lamto/web/templates/web/staff/shell.html src/lamto/web/static/web/app.css
git commit -m "fix(web): scope account and authentication navigation"
```

Expected: all `test_staff_ui.py` tests pass.

---

### Task 2: Add Finance Subnavigation and Stable Exits

**Files:**
- Modify: `src/lamto/web/tests/test_staff_nav.py`
- Modify: `src/lamto/web/staff.py`
- Modify: `src/lamto/web/templates/web/staff/shell.html`
- Modify: `src/lamto/web/templates/web/staff/work_order_detail.html`
- Modify: `src/lamto/web/templates/web/staff/proposal_detail.html`
- Modify: `src/lamto/web/templates/web/staff/payment_detail.html`
- Modify: `src/lamto/web/templates/web/staff/audit_search.html`
- Modify: `src/lamto/web/static/web/app.css`

**Interfaces:** `finance_nav_items_for(membership) -> list[dict[str, str]]`; every item has `label`, `url_name`, and `active_key`. `staff_context()` exposes `finance_nav_items`.

- [ ] **Step 1: Add failing helper tests**

Extend `NavStructureTests`, reusing `_board()` and `grant_capability()`:

```python
def test_finance_subnavigation_is_capability_filtered(self):
    board = self._board()
    grant_capability(board, PROPOSAL_APPROVE)
    grant_capability(board, PAYMENT_VERIFY)
    self.assertEqual(
        [item["label"] for item in finance_nav_items_for(board)],
        ["Proposals", "Payments"],
    )

def test_fund_only_membership_gets_only_fund_destination(self):
    board = self._board()
    grant_capability(board, FUND_VERIFY)
    self.assertEqual(finance_nav_items_for(board), [{
        "label": "Fund", "url_name": "web:fund-home", "active_key": "fund"
    }])
```

Import `finance_nav_items_for`, the three capability constants, and existing `grant_capability`.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest src/lamto/web/tests/test_staff_nav.py::NavStructureTests::test_finance_subnavigation_is_capability_filtered src/lamto/web/tests/test_staff_nav.py::NavStructureTests::test_fund_only_membership_gets_only_fund_destination -q
```

Expected: import failure because `finance_nav_items_for` does not exist.

- [ ] **Step 3: Implement the helper**

Add to `staff.py`:

```python
def finance_nav_items_for(membership) -> list[dict[str, str]]:
    caps = capabilities_for(membership)
    destinations = (
        ("Proposals", "web:proposal-list", "proposals", {"proposal.create", "proposal.approve", "ledger.publish"}),
        ("Payments", "web:payment-list", "payments", {"payment.record", "payment.verify"}),
        ("Fund", "web:fund-home", "fund", {"fund.record", "fund.verify", "ledger.publish"}),
    )
    return [
        {"label": label, "url_name": url_name, "active_key": active_key}
        for label, url_name, active_key, required in destinations
        if caps & required
    ]
```

Add `finance_nav_items=finance_nav_items_for(membership)` to `staff_context()`. Pass `finance_active="proposals"`, `"payments"`, or `"fund"` from the corresponding views.

- [ ] **Step 4: Render navigation and exits**

Under the primary staff nav:

```django
{% if nav_active == "finance" and finance_nav_items %}
<nav class="finance-nav" aria-label="Finance">
  {% for item in finance_nav_items %}
  <a href="{% url item.url_name %}"{% if finance_active == item.active_key %} class="is-active" aria-current="page"{% endif %}>{{ item.label }}</a>
  {% endfor %}
</nav>
{% endif %}
```

Add a stable `.back-link` before detail headings. Use the owning list route for work, proposals, and payments; use Action Inbox for audit. Add the same destination as a secondary Cancel link beside mutation submit controls. Do not implement undo.

Use existing tokens:

```css
.finance-nav,
.form-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.finance-nav {
  padding: var(--space-2) var(--space-4);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}

.finance-nav a,
.back-link {
  min-height: var(--touch);
  display: inline-flex;
  align-items: center;
  font-weight: 600;
}
```

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest src/lamto/web/tests/test_staff_nav.py src/lamto/web/tests/test_staff_ui.py -q
git add src/lamto/web/tests/test_staff_nav.py src/lamto/web/staff.py src/lamto/web/views src/lamto/web/templates/web/staff src/lamto/web/static/web/app.css
git commit -m "feat(staff): expose finance destinations and stable exits"
```

---

### Task 3: Replace Evidence IDs With Scoped Native Choices

**Files:**
- Modify: `src/lamto/web/tests/test_staff_signing.py`
- Modify: `src/lamto/web/tests/test_role_workspaces.py`
- Modify: `src/lamto/web/staff_signing.py`
- Modify: `src/lamto/web/forms/staff.py`
- Modify: `src/lamto/web/views/maintenance.py`
- Modify: `src/lamto/web/views/board.py`
- Modify: `src/lamto/web/templates/web/staff/work_order_detail.html`

**Interfaces:**
- `document_pair_options(building_id, kind) -> list[tuple[value, label, original, redacted]]`.
- Pair value is `<original_pk>:<redacted_pk>`, validated against freshly rebuilt scoped options on POST.
- `CompleteWorkOrderForm(*, building_id, uploader_id)` owns `before_versions` and `after_versions`.
- `AcceptWorkForm` accepts keyword arguments `invoice_choices` and `acceptance_choices` and owns `invoice_pair` and `acceptance_pair`.
- `RecordPaymentForm` accepts keyword argument `proof_choices` and owns `proof_pair`.

- [ ] **Step 1: Add failing pair-discovery test**

In `UploadDocumentPairTests`, reuse `_pdf()` and `upload_document_pair()`:

```python
def test_document_pair_options_are_scoped_and_human_readable(self):
    original, redacted = upload_document_pair(
        self.building, Document.Kind.INVOICE, self.user,
        _pdf("invoice-original.pdf", b"original"),
        _pdf("invoice-resident.pdf", b"redacted"),
    )
    other = Building.objects.create(name="Other building")
    upload_document_pair(
        other, Document.Kind.INVOICE, self.user,
        _pdf("foreign.pdf", b"foreign original"),
        _pdf("foreign-redacted.pdf", b"foreign redacted"),
    )
    options = document_pair_options(self.building.pk, Document.Kind.INVOICE)
    self.assertEqual([item[0] for item in options], [f"{original.pk}:{redacted.pk}"])
    self.assertIn("invoice-original.pdf", options[0][1])
    self.assertIn("invoice-resident.pdf", options[0][1])
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest src/lamto/web/tests/test_staff_signing.py::UploadDocumentPairTests::test_document_pair_options_are_scoped_and_human_readable -q
```

Expected: import failure for `document_pair_options`.

- [ ] **Step 3: Implement pair discovery in `staff_signing.py`**

```python
def document_pair_options(building_id: int, kind: str):
    versions = (
        DocumentVersion.objects.filter(
            document__building_id=building_id,
            document__kind=kind,
            variant__in=(DocumentVersion.Variant.ORIGINAL, DocumentVersion.Variant.REDACTED),
            scan_status=DocumentVersion.ScanStatus.CLEAN,
        )
        .select_related("document")
        .order_by("document_id", "-version")
    )
    pairs = {}
    for version in versions:
        pairs.setdefault(version.document_id, {}).setdefault(version.variant, version)
    options = []
    for pair in pairs.values():
        original = pair.get(DocumentVersion.Variant.ORIGINAL)
        redacted = pair.get(DocumentVersion.Variant.REDACTED)
        if original and redacted:
            options.append((
                f"{original.pk}:{redacted.pk}",
                f"{original.filename} / {redacted.filename}",
                original,
                redacted,
            ))
    return options

def selected_pair(options, value):
    return next(((original, redacted) for key, _, original, redacted in options if key == value), None)
```

- [ ] **Step 4: Add failing form-scope tests**

Create `StaffEvidenceFormTests(TestCase)` in `test_staff_signing.py`. Build clean before/after documents in the active building and cross-building/wrong-kind documents. Assert:

```python
form = CompleteWorkOrderForm(building_id=self.building.pk, uploader_id=self.user.pk)
self.assertQuerySetEqual(form.fields["before_versions"].queryset, [before])
self.assertQuerySetEqual(form.fields["after_versions"].queryset, [after])

accept = AcceptWorkForm(
    invoice_choices=[(invoice_value, invoice_label)],
    acceptance_choices=[(acceptance_value, acceptance_label)],
)
self.assertEqual(accept.fields["invoice_pair"].choices[1], (invoice_value, invoice_label))
self.assertNotIn("invoice_original_id", accept.fields)
```

Bind a foreign pair value and assert `is_valid()` is false with `Select valid evidence.` on the pair field.

- [ ] **Step 5: Verify RED**

```bash
uv run pytest src/lamto/web/tests/test_staff_signing.py::StaffEvidenceFormTests -q
```

Expected: constructor/field failures.

- [ ] **Step 6: Implement native scoped fields**

Add `before_versions` and `after_versions` as `ModelMultipleChoiceField`s. Their querysets must filter by active building, current uploader, original variant, clean scan status, and `BEFORE_PHOTO`/`AFTER_PHOTO`. Change `CompleteWorkOrderForm.save()` to use its cleaned querysets directly.

Replace acceptance/payment numeric evidence fields with `ChoiceField`s. Their constructors receive choices and prepend `("", "Select evidence…")`. Keep signature, event ID, payment ID, and pinned timestamp fields unchanged.

On each GET and POST, rebuild options before constructing the form:

```python
invoice_options = document_pair_options(building_id, Document.Kind.INVOICE)
form = AcceptWorkForm(
    request.POST or None,
    invoice_choices=[(value, label) for value, label, _, _ in invoice_options],
    acceptance_choices=[(value, label) for value, label, _, _ in acceptance_options],
    initial=initial,
)
```

After `form.is_valid()`, resolve only through `selected_pair()`. If a choice disappeared, attach `Selected evidence is no longer available. Select it again.` and do not sign or save. Delete raw `request.POST.getlist()` evidence handling and manual ID inputs.

- [ ] **Step 7: Verify trust boundaries and commit**

```bash
uv run pytest src/lamto/web/tests/test_staff_signing.py src/lamto/web/tests/test_role_workspaces.py src/lamto/maintenance/tests/test_workorders.py src/lamto/finance/tests/test_acceptance.py src/lamto/finance/tests/test_payments.py -q
git add src/lamto/web/staff_signing.py src/lamto/web/forms/staff.py src/lamto/web/views/maintenance.py src/lamto/web/views/board.py src/lamto/web/templates/web/staff/work_order_detail.html src/lamto/web/tests/test_staff_signing.py src/lamto/web/tests/test_role_workspaces.py
git commit -m "feat(staff): replace evidence ids with scoped choices"
```

Expected: zero failures.

---

### Task 4: Add Accountability Chain and Rigorous Signed Review

**Files:**
- Modify: `src/lamto/web/tests/test_staff_ui.py`
- Modify: `src/lamto/web/views/staff_common.py`
- Modify: `src/lamto/web/views/maintenance.py`
- Modify: `src/lamto/web/views/operator.py`
- Modify: `src/lamto/web/views/board.py`
- Modify: `src/lamto/web/views/auditor.py`
- Create: `src/lamto/web/templates/web/staff/_accountability_chain.html`
- Create: `src/lamto/web/templates/web/staff/_review_summary.html`
- Modify: `src/lamto/web/templates/web/staff/work_order_detail.html`
- Modify: `src/lamto/web/templates/web/staff/proposal_detail.html`
- Modify: `src/lamto/web/templates/web/staff/payment_detail.html`
- Modify: `src/lamto/web/templates/web/staff/audit_search.html`
- Modify: `src/lamto/web/static/web/wallet-signing.js`
- Modify: `src/lamto/web/static/web/app.css`

**Interfaces:**
- `accountability_chain(current, blocked=False) -> list[{key, label, state}]`.
- Stage keys: `report`, `triage`, `work`, `proposal`, `acceptance`, `payment`, `publication`.
- Review bindings: `data-review-form`, `data-review-value`, `data-decision-label`, `data-decision-submit`.

- [ ] **Step 1: Add failing chain/review tests**

```python
class AccountabilityChainTests(SimpleTestCase):
    def test_chain_marks_prior_current_and_upcoming_stages(self):
        chain = staff_common.accountability_chain("payment")
        self.assertEqual(
            [step["state"] for step in chain],
            ["complete", "complete", "complete", "complete", "complete", "current", "upcoming"],
        )

    def test_detail_templates_include_shared_chain(self):
        for name in ("work_order_detail.html", "proposal_detail.html", "payment_detail.html", "audit_search.html"):
            source = (STAFF_TEMPLATES / name).read_text(encoding="utf-8")
            self.assertIn('staff/_accountability_chain.html', source)

def test_signed_actions_have_rigorous_review_summaries(self):
    templates = "\n".join(
        (STAFF_TEMPLATES / name).read_text(encoding="utf-8")
        for name in ("work_order_detail.html", "proposal_detail.html", "payment_detail.html")
    )
    self.assertIn("What you are signing", templates)
    self.assertIn("What happens next", templates)
    self.assertIn("Sign and approve proposal", templates)
    self.assertIn("Sign and accept work", templates)
    self.assertIn("Sign and record payment", templates)
    self.assertIn("bindReviewSummary", WALLET_JS.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest src/lamto/web/tests/test_staff_ui.py::AccountabilityChainTests src/lamto/web/tests/test_staff_ui.py::StaffUiContractTests::test_signed_actions_have_rigorous_review_summaries -q
```

Expected: missing helper, includes, and review binding.

- [ ] **Step 3: Implement the stage builder and partial**

```python
ACCOUNTABILITY_STAGES = (
    ("report", "Report"),
    ("triage", "Triage"),
    ("work", "Work"),
    ("proposal", "Proposal and approval"),
    ("acceptance", "Acceptance"),
    ("payment", "Payment"),
    ("publication", "Publication"),
)

def accountability_chain(current: str, *, blocked: bool = False):
    current_index = [key for key, _ in ACCOUNTABILITY_STAGES].index(current)
    return [{
        "key": key,
        "label": label,
        "state": (
            "blocked" if index == current_index and blocked
            else "current" if index == current_index
            else "complete" if index < current_index
            else "upcoming"
        ),
    } for index, (key, label) in enumerate(ACCOUNTABILITY_STAGES)]
```

Render an ordered list in `_accountability_chain.html`; put `aria-current="step"` on current/blocked stages and print the state text. Pass `work`, `proposal`, `payment`, or `publication` context from existing views and include the partial before technical proof.

- [ ] **Step 4: Implement rigorous review summaries**

`_review_summary.html` must render Action, Acting as, each supplied review item, Consequence, and What happens next in a `<dl>`. Include it immediately before signed submit controls.

Use exact CTA copy:

```text
Sign and approve proposal
Sign and reject for correction
Sign and accept work
Sign and authorize emergency work
Sign and record ratification
Sign and record payment
Sign and verify payment
Sign and publish to resident ledger
```

Add this existing-script helper and call it from the signed-form initializer:

```javascript
function bindReviewSummary(form) {
  if (!form.hasAttribute("data-review-form")) return;
  form.querySelectorAll("[data-review-value]").forEach((target) => {
    const field = form.elements.namedItem(target.dataset.reviewValue);
    if (!field) return;
    const update = () => {
      const option = field.selectedOptions && field.selectedOptions[0];
      target.textContent = option ? option.textContent.trim() : field.value;
    };
    field.addEventListener("input", update);
    field.addEventListener("change", update);
    update();
  });
  const decision = form.elements.namedItem("decision");
  const label = form.querySelector("[data-decision-label]");
  const submit = form.querySelector("[data-decision-submit]");
  if (decision && label && submit) {
    const updateDecision = () => {
      const approving = decision.value === "APPROVE";
      label.textContent = approving ? "Approve proposal" : "Reject for correction";
      submit.textContent = approving ? "Sign and approve proposal" : "Sign and reject for correction";
    };
    decision.addEventListener("change", updateDecision);
    updateDecision();
  }
}
```

Export it through the existing `window.LamToWalletSigning` test seam. Keep typed-data construction unchanged.

- [ ] **Step 5: Add flat CSS and verify**

Use flex-wrapped ordered stages, text labels, existing semantic colors, and border-only review summaries. Do not add cards or shadows.

```bash
uv run pytest src/lamto/web/tests/test_staff_ui.py src/lamto/web/tests/test_staff_signing.py src/lamto/web/tests/test_role_workspaces.py -q
git add src/lamto/web/views src/lamto/web/templates/web/staff src/lamto/web/static/web/wallet-signing.js src/lamto/web/static/web/app.css src/lamto/web/tests/test_staff_ui.py
git commit -m "feat(staff): explain accountability and signed consequences"
```

---

### Task 5: Strengthen Fund/Ops Hierarchy and Verify Everything

**Files:**
- Modify: `src/lamto/web/tests/test_staff_ui.py`
- Modify: `src/lamto/web/templates/web/staff/fund_detail.html`
- Modify: `src/lamto/web/templates/web/staff/ops_health.html`
- Modify: `src/lamto/web/static/web/app.css`

**Interfaces:** Fund uses existing `.balance-value` and `.amount`. Ops groups have IDs `queue-health`, `integrity-health`, `notification-health`, `device-health`, and `anchoring-health`.

- [ ] **Step 1: Add failing hierarchy test**

```python
def test_fund_and_ops_use_product_specific_hierarchy(self):
    fund = (STAFF_TEMPLATES / "fund_detail.html").read_text(encoding="utf-8")
    ops = (STAFF_TEMPLATES / "ops_health.html").read_text(encoding="utf-8")
    self.assertIn('class="balance-value"', fund)
    self.assertIn('class="amount"', fund)
    for section_id in (
        "queue-health", "integrity-health", "notification-health", "device-health", "anchoring-health"
    ):
        self.assertIn(f'id="{section_id}"', ops)
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest src/lamto/web/tests/test_staff_ui.py::StaffUiContractTests::test_fund_and_ops_use_product_specific_hierarchy -q
```

- [ ] **Step 3: Recompose without new cards**

Use the existing prominent amount pattern:

```django
<p class="balance-value">
  <span class="amount">{{ balance_vnd }}</span>
  <span class="currency">VND verified</span>
</p>
```

Put inflow/outflow context in the existing `.stat-grid`. Convert the remaining Fund panels to flat `.workflow-section` regions.

Group Ops metrics into Queue, Evidence integrity, Notifications, Devices, and Anchoring. Put non-zero failures/mismatches before healthy metadata and pair every state color with `Needs attention` or `No current failures` text.

- [ ] **Step 4: Run focused, domain, and full verification**

```bash
uv run pytest src/lamto/web/tests/test_staff_ui.py src/lamto/web/tests/test_staff_nav.py src/lamto/web/tests/test_staff_signing.py src/lamto/web/tests/test_role_workspaces.py src/lamto/web/tests/test_resident_views.py src/lamto/web/tests/test_tenancy_review_minors.py src/lamto/web/tests/test_exports_and_health.py src/lamto/web/tests/test_fund_ops.py -q
uv run pytest src/lamto/maintenance/tests/test_workorders.py src/lamto/finance/tests/test_acceptance.py src/lamto/finance/tests/test_payments.py src/lamto/documents/tests -q
uv run pytest -q
node .agents/skills/impeccable/scripts/detect.mjs --json src/lamto/web/templates/web/staff src/lamto/web/templates/web/resident src/lamto/web/templates/web/security
git diff --check
```

Expected: zero test failures, detector output `[]`, and no whitespace errors.

- [ ] **Step 5: Inspect rendered states**

At 1440×900, 1024×768, and 390×844, capture and read screenshots for:

- login, MFA setup, re-auth: no bottom nav or reserved gap;
- resident home: bottom nav retained;
- staff inbox: Account absent;
- Proposal, Payments, Fund: capability-filtered Finance navigation;
- completion/acceptance/payment: human evidence choices and empty-choice recovery;
- proposal decision: review summary and decision-specific CTA;
- audit: accountability chain;
- fund and Ops: revised hierarchy.

Check keyboard order, 200% zoom, long filenames, wrong-wallet recovery, and reduced motion. If local authentication or environment setup blocks rendering, report the exact blocker and do not claim browser verification.

- [ ] **Step 6: Commit and verify clean state**

```bash
git add src/lamto/web/tests/test_staff_ui.py src/lamto/web/templates/web/staff/fund_detail.html src/lamto/web/templates/web/staff/ops_health.html src/lamto/web/static/web/app.css
git commit -m "feat(staff): prioritize fund and operations status"
git status --short
git log -6 --oneline
```

Expected: clean worktree and five implementation commits after the design/plan commits.
