import json
import inspect
import re
import subprocess
from pathlib import Path

from django.test import SimpleTestCase
from django.utils import timezone

from lamto.web.action_inbox import ActionItem
from lamto.web.views import staff_common


WEB_ROOT = Path(__file__).resolve().parents[1]
STAFF_TEMPLATES = WEB_ROOT / "templates" / "web" / "staff"
APP_CSS = WEB_ROOT / "static" / "web" / "app.css"
WALLET_JS = WEB_ROOT / "static" / "web" / "wallet-signing.js"
PROPOSAL_VIEW = WEB_ROOT / "views" / "proposals.py"
STAFF_FORMS = WEB_ROOT / "forms" / "staff.py"


class StaffUiContractTests(SimpleTestCase):
    def test_staff_layout_is_wide_flat_and_uses_unboxed_workflows(self):
        css = APP_CSS.read_text(encoding="utf-8")
        templates = "\n".join(
            path.read_text(encoding="utf-8") for path in STAFF_TEMPLATES.glob("*.html")
        )

        self.assertIn("width: min(72rem, 100%);", css)
        self.assertIn("box-shadow: none;", css)
        self.assertIn(".record-layout", css)
        self.assertIn(".workflow-section", css)
        self.assertNotIn("signed-box", templates)

    def test_technical_proof_is_disclosed_progressively_with_auditor_override(self):
        proposal = (STAFF_TEMPLATES / "proposal_detail.html").read_text(encoding="utf-8")
        self.assertIn("Technical proof", proposal)

    def test_primary_and_current_states_are_exposed_consistently(self):
        shell = (STAFF_TEMPLATES / "shell.html").read_text(encoding="utf-8")
        templates = "\n".join(
            path.read_text(encoding="utf-8") for path in STAFF_TEMPLATES.glob("*.html")
        )

        self.assertIn('aria-current="page"', shell)
        self.assertIn("button button-primary", templates)
        self.assertIn('role="status" aria-live="polite"', templates)
        self.assertIn("data-signing-error", templates)

    def test_proposal_publication_does_not_reload_during_signing(self):
        proposal = (STAFF_TEMPLATES / "proposal_detail.html").read_text(encoding="utf-8")

        self.assertNotIn("window.location.href", proposal)
        self.assertIn("publish_typed_data", proposal)

    def test_hidden_signature_error_offers_only_visible_recovery_steps(self):
        forms = STAFF_FORMS.read_text(encoding="utf-8")

        self.assertNotIn("paste a valid hex signature", forms)
        self.assertIn("Keep your entries", forms)

    def test_signing_failure_is_inline_and_restores_the_submit_control(self):
        path_json = json.dumps(str(WALLET_JS))
        node_script = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({path_json}, 'utf8');
const status = {{ textContent: '' }};
const error = {{ textContent: '', hidden: true }};
const button = {{ disabled: false }};
const fields = {{
  signature: {{ value: '' }},
  event_id: {{ value: '0x' + '1'.repeat(64) }},
}};
const typed = {{ textContent: JSON.stringify({{
  types: {{}}, primaryType: 'Evidence', domain: {{}},
  message: {{ eventId: fields.event_id.value }}
}}) }};
class HTMLFormElement {{
  constructor() {{ this.dataset = {{}}; this.attributes = {{}}; }}
  hasAttribute(name) {{ return name === 'data-signed-form'; }}
  getAttribute() {{ return ''; }}
  setAttribute(name, value) {{ this.attributes[name] = value; }}
  removeAttribute(name) {{ delete this.attributes[name]; }}
  querySelector(selector) {{
    if (selector === '[name="signature"]') return fields.signature;
    if (selector === '[name="event_id"]') return fields.event_id;
    if (selector === '[data-signing-status]') return status;
    if (selector === '[data-signing-error]') return error;
    if (selector.includes("script[type='application/json']")) return typed;
    return null;
  }}
  querySelectorAll() {{ return [button]; }}
  appendChild() {{}}
  removeEventListener() {{}}
}}
const document = {{
  readyState: 'complete',
  querySelectorAll: () => [],
  addEventListener: () => {{}},
  createElement: () => ({{}}),
}};
const window = {{
  document,
  ethereum: {{ request: async () => {{ throw new Error('wallet unavailable'); }} }},
}};
const sandbox = {{ window, document, HTMLFormElement, globalThis: {{}} }};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const form = new HTMLFormElement();
const event = {{ target: form, preventDefault() {{}}, stopPropagation() {{}} }};
sandbox.window.LamToWalletSigning.handleSignedSubmit(event).then(() => {{
  if (form.attributes['aria-busy']) process.exit(2);
  if (button.disabled) process.exit(3);
  if (error.hidden || !error.textContent.includes('wallet unavailable')) process.exit(4);
  process.exit(0);
}}).catch((err) => {{ console.error(err); process.exit(5); }});
"""
        result = subprocess.run(
            ["node", "-e", node_script], capture_output=True, text=True, check=False
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_staff_shell_has_no_account_destination(self):
        shell = (STAFF_TEMPLATES / "shell.html").read_text(encoding="utf-8")
        self.assertNotIn("web:account", shell)
        self.assertNotIn(">Account</a>", shell)

    def test_authentication_pages_suppress_resident_navigation(self):
        base = (WEB_ROOT / "templates" / "web" / "base.html").read_text(encoding="utf-8")
        self.assertIn("{% block bottom_nav %}", base)
        self.assertIn("{% block body_class %}", base)
        for relative in ("login.html", "security/mfa_setup.html", "security/reauth.html"):
            source = (WEB_ROOT / "templates" / "web" / relative).read_text(encoding="utf-8")
            self.assertIn("{% block bottom_nav %}{% endblock %}", source)
            self.assertIn("{% block body_class %}no-bottom-nav{% endblock %}", source)

    def test_resident_navigation_is_removed_from_base(self):
        base = (WEB_ROOT / "templates" / "web" / "base.html").read_text(encoding="utf-8")
        self.assertNotIn('class="bottom-nav"', base)
        self.assertNotIn("web:account", base)

    def test_signed_actions_have_rigorous_review_summaries(self):
        templates = "\n".join(
            (STAFF_TEMPLATES / name).read_text(encoding="utf-8")
            for name in (
                "work_order_detail.html",
                "proposal_detail.html",
                "payment_detail.html",
                "_review_summary.html",
            )
        )
        self.assertIn("What you are signing", templates)
        self.assertIn("What happens next", templates)
        self.assertIn("Sign and publish to resident ledger", templates)
        self.assertIn("Sign and accept work", templates)
        self.assertIn("Sign and record payment", templates)
        self.assertIn("bindReviewSummary", WALLET_JS.read_text(encoding="utf-8"))

    def test_signing_forms_share_an_accessible_review_summary(self):
        partial_name = 'staff/_review_summary.html'
        for name in (
            "_fund_forms.html",
            "proposal_create.html",
            "work_order_detail.html",
            "proposal_detail.html",
            "payment_detail.html",
        ):
            source = (STAFF_TEMPLATES / name).read_text(encoding="utf-8")
            self.assertIn(partial_name, source)

        partial = (STAFF_TEMPLATES / "_review_summary.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('class="review-summary"', partial)
        self.assertIn('aria-live="polite"', partial)
        self.assertIn("What happens next", partial)

        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in STAFF_TEMPLATES.glob("*.html")
            if path.name != "_review_summary.html"
        )
        self.assertNotIn('<section class="review-summary"', templates)

    def test_staff_vnd_values_are_humanized_in_templates_and_review_js(self):
        for path in STAFF_TEMPLATES.glob("*.html"):
            source = path.read_text(encoding="utf-8")
            rendered_vnd = re.findall(r"{{[^}]*_vnd[^}]*}}", source)
            for expression in rendered_vnd:
                self.assertIn(
                    "|intcomma",
                    expression,
                    f"{path.name} leaves a VND amount unformatted: {expression}",
                )

        wallet = WALLET_JS.read_text(encoding="utf-8")
        self.assertIn("formatVnd", wallet)
        self.assertIn('endsWith("_vnd")', wallet)

        script = f"""
const fs = require('fs');
const vm = require('vm');
const document = {{ readyState: 'complete', querySelectorAll: () => [] }};
const window = {{ document }};
vm.runInNewContext(fs.readFileSync({json.dumps(str(WALLET_JS))}, 'utf8'), {{
  window, document, globalThis: {{}}
}});
if (window.LamToWalletSigning.formatVnd('2500000000') !== '2,500,000,000') {{
  process.exit(1);
}}
"""
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_not_ready_signing_controls_remain_focusable(self):
        templates = "\n".join(
            path.read_text(encoding="utf-8") for path in STAFF_TEMPLATES.glob("*.html")
        )
        self.assertNotRegex(templates, r"\{% if not [^%]+ %\}disabled\{% endif %\}")
        self.assertIn('aria-disabled="true"', templates)

        wallet = WALLET_JS.read_text(encoding="utf-8")
        self.assertIn('getAttribute("aria-disabled") === "true"', wallet)

    def test_lists_use_task_rows_and_cases_reuse_the_shared_list(self):
        shared_list = (STAFF_TEMPLATES / "_list.html").read_text(encoding="utf-8")
        cases = (STAFF_TEMPLATES / "case_detail.html").read_text(encoding="utf-8")
        shell = (STAFF_TEMPLATES / "shell.html").read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")
        inbox = (STAFF_TEMPLATES / "action_inbox.html").read_text(encoding="utf-8")
        toolbar = (STAFF_TEMPLATES / "_list_toolbar.html").read_text(encoding="utf-8")

        self.assertIn('class="task-list"', shared_list)
        self.assertIn('class="task-row"', shared_list)
        self.assertIn("task-action", shared_list)
        self.assertIn("No next action", shared_list)
        self.assertNotIn("card-link", shared_list)
        self.assertIn("staff/_list.html", cases)
        self.assertNotIn("filter-bar", cases)
        self.assertNotIn("filter-bar", inbox)
        self.assertIn("staff/_list_toolbar.html", inbox)
        self.assertIn("staff/_pagination.html", inbox)
        self.assertIn("Apply filters", toolbar)
        self.assertIn("secondary_filters", toolbar)
        self.assertIn('item.is_active', shell)
        self.assertIn('role="{% if \'error\' in message.tags %}alert{% else %}status{% endif %}"', shell)
        self.assertIn("get_current_language", shell)
        self.assertIn("lamtoI18n", shell)
        self.assertIn("No amount recorded", shared_list)
        self.assertIn("deadline-soon", css)
        self.assertIn("deadline-overdue", css)
        self.assertIn("--color-surface-muted", css)
        self.assertIn("--color-focus-on-dark", css)
        self.assertIn(".staff-nav a:focus-visible", css)
        self.assertIn("min-height: var(--touch)", css)
        self.assertIn("accountability-stage-pending", css)
        self.assertIn("#8a5c00", css)
        self.assertIn("system-ui, -apple-system", css)
        self.assertNotIn(".record-row", css)

    def test_payment_detail_links_ledger_evidence(self):
        payment = (STAFF_TEMPLATES / "payment_detail.html").read_text(encoding="utf-8")
        self.assertIn("web:audit-export", payment)
        self.assertIn("ledger_entry", payment)
        self.assertIn("payment_doc_hashes", payment)
        self.assertIn("staff/_hash_value.html", payment)
        self.assertIn("data-copy", (STAFF_TEMPLATES / "_hash_value.html").read_text(encoding="utf-8"))

    def test_ops_attention_states_link_to_the_exception_queue_without_dead_branches(self):
        ops = (STAFF_TEMPLATES / "ops_health.html").read_text(encoding="utf-8")
        self.assertIn("queue_needs_attention", ops)
        self.assertIn("status=exceptions", ops)
        self.assertIn("Review", ops)
        self.assertNotIn("Needs attention</a>", ops)
        self.assertNotRegex(ops, r"\{% if health\.[^%]+ %\}\s*<div><dt>")

    def test_fund_and_ops_use_product_specific_hierarchy(self):
        fund = (STAFF_TEMPLATES / "fund_detail.html").read_text(encoding="utf-8")
        ops = (STAFF_TEMPLATES / "ops_health.html").read_text(encoding="utf-8")
        self.assertIn('class="balance-value"', fund)
        self.assertIn('class="amount"', fund)
        for section_id in (
            "queue-health", "integrity-health", "notification-health", "device-health", "anchoring-health"
        ):
            self.assertIn(f'id="{section_id}"', ops)


class AccountabilityChainTests(SimpleTestCase):
    def test_chain_marks_prior_current_and_upcoming_stages(self):
        chain = staff_common.accountability_chain("payment")
        self.assertEqual(
            [step["state"] for step in chain],
            [
                "complete",
                "complete",
                "complete",
                "complete",
                "complete",
                "current",
                "upcoming",
            ],
        )

    def test_published_marks_every_stage_complete(self):
        chain = staff_common.accountability_chain(None)
        self.assertEqual({step["state"] for step in chain}, {"complete"})

    def _states(self, **kwargs):
        return [
            step["state"]
            for step in staff_common.accountability_chain_for(published=False, **kwargs)
        ]

    def test_stage_work_in_progress_spending(self):
        from types import SimpleNamespace

        wo = SimpleNamespace(
            pk=1, status="IN_PROGRESS", requires_spending=True, proposal=None, acceptance=None
        )
        self.assertEqual(
            self._states(work_order=wo),
            ["complete", "complete", "current", "upcoming", "upcoming", "upcoming", "upcoming"],
        )

    def test_stage_proposal_after_work_done_without_publication(self):
        from types import SimpleNamespace

        wo = SimpleNamespace(
            pk=1,
            status="AWAITING_ACCEPTANCE",
            requires_spending=True,
            proposal=None,
            acceptance=None,
        )
        self.assertEqual(
            self._states(work_order=wo),
            ["complete", "complete", "complete", "current", "upcoming", "upcoming", "upcoming"],
        )

    def test_stage_acceptance_after_proposal_authorized(self):
        from types import SimpleNamespace

        proposal = SimpleNamespace(pk=2, status="NORMAL_AUTHORIZED")
        wo = SimpleNamespace(
            pk=1,
            status="AWAITING_ACCEPTANCE",
            requires_spending=True,
            proposal=proposal,
            acceptance=None,
        )
        self.assertEqual(
            self._states(work_order=wo, proposal=proposal),
            ["complete", "complete", "complete", "complete", "current", "upcoming", "upcoming"],
        )

    def test_stage_payment_after_acceptance(self):
        from types import SimpleNamespace

        acceptance = SimpleNamespace(pk=3, payment=None)
        wo = SimpleNamespace(
            pk=1,
            status="ACCEPTED",
            requires_spending=True,
            proposal=SimpleNamespace(pk=2, status="NORMAL_AUTHORIZED"),
            acceptance=acceptance,
        )
        self.assertEqual(
            self._states(work_order=wo, acceptance=acceptance),
            ["complete", "complete", "complete", "complete", "complete", "current", "upcoming"],
        )

    def test_stage_publication_after_payment_recorded(self):
        from types import SimpleNamespace

        payment = SimpleNamespace(pk=4)
        acceptance = SimpleNamespace(pk=3, payment=payment)
        wo = SimpleNamespace(
            pk=1,
            status="ACCEPTED",
            requires_spending=True,
            proposal=SimpleNamespace(pk=2, status="NORMAL_AUTHORIZED"),
            acceptance=acceptance,
        )
        payment.acceptance = acceptance
        acceptance.work_order = wo
        self.assertEqual(
            self._states(payment=payment, publication_pending=False),
            ["complete", "complete", "complete", "complete", "complete", "complete", "current"],
        )

    def test_stage_publication_awaiting_confirmation_is_pending_not_complete(self):
        from types import SimpleNamespace

        payment = SimpleNamespace(pk=4)
        acceptance = SimpleNamespace(pk=3, payment=payment)
        proposal = SimpleNamespace(pk=2, status="NORMAL_AUTHORIZED")
        wo = SimpleNamespace(
            pk=1,
            status="ACCEPTED",
            requires_spending=True,
            proposal=proposal,
            acceptance=acceptance,
        )
        payment.acceptance = acceptance
        acceptance.work_order = wo
        chain = staff_common.accountability_chain_for(
            payment=payment,
            proposal=proposal,
            published=False,
            publication_pending=True,
        )
        self.assertEqual(
            [step["state"] for step in chain],
            ["complete", "complete", "complete", "complete", "complete", "complete", "pending"],
        )
        self.assertEqual(
            str(chain[-1]["state_label"]),
            str(staff_common.STAGE_STATE_LABELS["pending"]),
        )
        self.assertNotEqual(chain[-1]["state"], "complete")

    def test_stage_all_complete_when_published(self):
        from types import SimpleNamespace

        wo = SimpleNamespace(
            pk=1, status="CLOSED", requires_spending=True, proposal=None, acceptance=None
        )
        chain = staff_common.accountability_chain_for(work_order=wo, published=True)
        self.assertEqual({step["state"] for step in chain}, {"complete"})

    def test_stage_rejected_proposal_is_blocked(self):
        from types import SimpleNamespace

        proposal = SimpleNamespace(pk=2, status="REJECTED")
        wo = SimpleNamespace(
            pk=1,
            status="IN_PROGRESS",
            requires_spending=True,
            proposal=proposal,
            acceptance=None,
        )
        chain = staff_common.accountability_chain_for(
            work_order=wo, proposal=proposal, published=False
        )
        self.assertEqual(
            [step["state"] for step in chain],
            ["complete", "complete", "complete", "blocked", "upcoming", "upcoming", "upcoming"],
        )

    def test_deadline_tone_is_proportional(self):
        from datetime import timedelta

        now = timezone.now()
        self.assertEqual(staff_common.deadline_tone(now + timedelta(days=7), now=now), "neutral")
        self.assertEqual(staff_common.deadline_tone(now + timedelta(hours=12), now=now), "soon")
        self.assertEqual(staff_common.deadline_tone(now - timedelta(hours=1), now=now), "overdue")

    def test_detail_templates_include_shared_chain(self):
        for name in (
            "work_order_detail.html",
            "proposal_detail.html",
            "payment_detail.html",
        ):
            source = (STAFF_TEMPLATES / name).read_text(encoding="utf-8")
            self.assertIn("staff/_accountability_chain.html", source)

    def test_views_derive_chain_from_records(self):
        for path in (
            WEB_ROOT / "views" / "requests.py",
            WEB_ROOT / "views" / "proposals.py",
            WEB_ROOT / "views" / "payments.py",
            WEB_ROOT / "views" / "work.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn("accountability_chain_for", source)
            self.assertNotRegex(source, r'accountability_chain\("')


class ActionInboxUiTests(SimpleTestCase):
    def _item(self, number, *, kind="payment_verification", priority=20, deadline=None):
        return ActionItem(
            kind=kind,
            title=f"Review payment {number}",
            summary=f"Lift repair payment {number}",
            target_type="PaymentEvidence",
            target_id=number,
            url=f"/payments/{number}/",
            priority=priority,
            deadline_at=deadline,
        )

    def test_inbox_groups_and_filters_tasks(self):
        prepare = getattr(staff_common, "prepare_action_inbox", None)
        self.assertIsNotNone(prepare)
        self.assertIn("status", inspect.signature(prepare).parameters)
        items = [
            self._item(1, kind="payment_verification", priority=5),
            self._item(2, kind="deadline_risk", deadline=timezone.now()),
            self._item(3, kind="failed_outbox", priority=9),
        ]

        result = prepare(
            items, query="payment 2", kind="", status="due_soon", page_number=1
        )
        visible = [item for group in result["groups"] for item in group["items"]]

        self.assertEqual(
            [str(group["label"]) for group in result["groups"]],
            [str(dict(staff_common.ACTION_GROUPS)["due_soon"])],
        )
        self.assertEqual([item.target_id for item in visible], [2])

    def test_inbox_paginates_and_exposes_filter_state(self):
        prepare = getattr(staff_common, "prepare_action_inbox", None)
        self.assertIsNotNone(prepare)
        items = [self._item(number) for number in range(1, 23)]

        result = prepare(
            items,
            query="",
            kind="payment_verification",
            page_number=2,
        )

        visible = [item for group in result["groups"] for item in group["items"]]
        self.assertEqual([item.target_id for item in visible], [21, 22])
        self.assertEqual(result["active_kind"], "payment_verification")
        self.assertEqual(result["page"].number, 2)
