import tempfile
import time
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.documents.models import DocumentVersion
from lamto.finance.models import MaintenanceFundEntry
from lamto.finance.selectors import pending_reconciliation_proposals
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-fundops-")


def _pdf(name, body):
    return SimpleUploadedFile(name, b"%PDF-1.4\n" + body, content_type="application/pdf")


def _full_publish(seed):
    """Run the pilot expenditure through verified payment (not yet published)."""
    d = PilotDomainDriver(seed)
    d.login(None, "resident").submit_report("Lift noise", "Lift 2")
    d.login(None, "operator").confirm_triage_and_create_paid_work_order()
    d.login(None, "operator").submit_signed_proposal()
    d.login(None, "board_approver").approve_proposal()
    d.login(None, "resident_representative").coapprove_proposal()
    d.login(None, "maintenance").complete_assigned_work()
    d.login(None, "board_payment_recorder").accept_and_record_payment()
    d.login(None, "board_payment_verifier").verify_payment()
    d.confirm_all_chain_events()
    return d


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class FundSelectorTests(TestCase):
    def test_pending_reconciliation_lists_paid_but_unpublished(self):
        seed = seed_pilot_world(building_name="Fund Sel B", email_prefix="fs")
        _full_publish(seed)  # verified payment, settled chain, no publication yet
        pending = list(pending_reconciliation_proposals(seed.building.pk))
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0], seed.proposal)

    def test_pending_reconciliation_excludes_unsettled_verification(self):
        """Eligibility matches domain gates: settled prerequisites required, not only VERIFIED."""
        from lamto.evidence.models import BlockchainOutboxEvent

        seed = seed_pilot_world(building_name="Fund Sel Unsettled", email_prefix="fsu")
        _full_publish(seed)
        v_event = seed.proposal.work_order.acceptance.payment.verification.outbox_event
        # QUEUED is not a status in this codebase; PENDING is non-settled.
        BlockchainOutboxEvent.objects.filter(pk=v_event.pk).update(
            status=BlockchainOutboxEvent.Status.PENDING
        )
        pending = list(pending_reconciliation_proposals(seed.building.pk))
        self.assertEqual(pending, [])

    def test_pending_fund_verification_is_not_verified_fund_entries(self):
        from lamto.finance.selectors import (
            pending_fund_verification_entries,
            verified_fund_entries,
        )
        seed = seed_pilot_world(building_name="Fund Sel Pend", email_prefix="fsp")
        verified_ids = {e.pk for e in verified_fund_entries(seed.building.pk)}
        pending_ids = {e.pk for e in pending_fund_verification_entries(seed.building.pk)}
        self.assertTrue(verified_ids.isdisjoint(pending_ids))

    def _emergency_paid_but_unpublished(self, seed, *, ratify=True):
        """Authorize (optional ratify) an emergency spend through verified payment."""
        from datetime import timedelta

        from lamto.finance.emergencies import (
            authorize_emergency,
            build_emergency_authorization_evidence_typed_data,
            build_emergency_ratification_evidence_typed_data,
            decide_emergency,
            request_emergency,
        )
        from lamto.testing.factories import new_event_id

        d = PilotDomainDriver(seed)
        d.login(None, "resident").submit_report("Pipe burst", "Basement")
        d.login(None, "operator").confirm_triage_and_create_paid_work_order()
        work = seed.work_order
        operator = seed.roles["operator"]
        board = seed.roles["board_emergency_approver"]
        rep = seed.roles["resident_representative"]

        requested = request_emergency(work, operator, "Flood risk", drill=False)
        authorized_at = requested.emergency_requested_at
        event_id = new_event_id()
        typed = build_emergency_authorization_evidence_typed_data(
            requested, board, 5_000_000, event_id, timestamp=authorized_at
        )
        signature = seed.sign_typed(board, typed)
        authorization = authorize_emergency(
            requested, board, 5_000_000, signature, event_id, now=authorized_at
        )
        if ratify:
            decided_at = authorized_at + timedelta(hours=1)
            rat_event_id = new_event_id()
            rat_typed = build_emergency_ratification_evidence_typed_data(
                authorization,
                rep,
                "RATIFY",
                "Safety ok",
                rat_event_id,
                timestamp=decided_at,
            )
            rat_sig = seed.sign_typed(rep, rat_typed)
            decide_emergency(
                authorization,
                rep,
                "RATIFY",
                "Safety ok",
                rat_sig,
                rat_event_id,
                now=decided_at,
            )
        d.confirm_all_chain_events()
        d.login(None, "operator").submit_signed_proposal()
        d.login(None, "maintenance").complete_assigned_work()
        d.login(None, "board_payment_recorder").accept_and_record_payment()
        d.login(None, "board_payment_verifier").verify_payment()
        d.confirm_all_chain_events()
        seed.proposal.refresh_from_db()
        authorization.refresh_from_db()
        return authorization

    def test_pending_reconciliation_excludes_emergency_without_terminal_outcome(self):
        """EMERGENCY needs terminal ratification — not silent skip of mode gates."""
        from lamto.finance.models import Proposal

        seed = seed_pilot_world(building_name="Fund Sel Emer", email_prefix="fse")
        self._emergency_paid_but_unpublished(seed, ratify=False)
        self.assertEqual(seed.proposal.mode, Proposal.Mode.EMERGENCY)
        # Auth exists but no terminal outcome → prepare_publication rejects.
        pending = list(pending_reconciliation_proposals(seed.building.pk))
        self.assertEqual(pending, [])

    def test_pending_reconciliation_excludes_emergency_before_24h_window(self):
        """24h ratification window must pass before emergency is publication-eligible."""
        from datetime import timedelta
        from unittest.mock import patch

        from django.utils import timezone

        from lamto.finance.models import Proposal

        seed = seed_pilot_world(building_name="Fund Sel EmerWin", email_prefix="fsew")
        authorization = self._emergency_paid_but_unpublished(seed, ratify=True)
        self.assertEqual(seed.proposal.mode, Proposal.Mode.EMERGENCY)
        self.assertGreater(authorization.ratification_deadline, timezone.now())

        # Before the 24h window: not publication-eligible.
        pending = list(pending_reconciliation_proposals(seed.building.pk))
        self.assertEqual(pending, [])

        # After the window: same settled emergency chain becomes eligible.
        after_deadline = authorization.ratification_deadline + timedelta(minutes=1)
        with patch("django.utils.timezone.now", return_value=after_deadline):
            pending_after = list(pending_reconciliation_proposals(seed.building.pk))
        self.assertEqual(pending_after, [seed.proposal])


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class FundHomeTests(TestCase):
    def _login(self, seed, role_key):
        membership = seed.roles[role_key]
        self.client.force_login(membership.user)
        device = TOTPDevice.objects.create(
            user=membership.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = membership.pk
        session.save()
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        return membership

    def test_fund_home_shows_balance_entries_and_pending(self):
        seed = seed_pilot_world(building_name="Fund Home B", email_prefix="fh")
        _full_publish(seed)
        self._login(seed, "fund_recorder")
        resp = self.client.get(reverse("web:fund-home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Maintenance fund")
        self.assertContains(resp, "Verified entries")
        self.assertContains(resp, "Pending fund verification")
        self.assertContains(resp, "Pending reconciliation")
        # The seeded opening balance is a verified entry.
        self.assertContains(resp, "Opening balance")

    def test_fund_home_renders_chart_and_window_stats(self):
        seed = seed_pilot_world(building_name="Fund Chart B", email_prefix="fch")
        self._login(seed, "fund_recorder")
        resp = self.client.get(reverse("web:fund-home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="fund-chart-data"')
        self.assertContains(resp, "Opening balance")
        self.assertContains(resp, "Closing balance")
        self.assertContains(resp, "Total inflows")
        self.assertContains(resp, "Total outflows")
        self.assertEqual(resp.context["chart_range"], "6m")
        self.assertEqual(len(resp.context["chart_points"]), 6)
        first = resp.context["chart_points"][0]
        self.assertIsInstance(first["period_start"], str)

    def test_fund_home_range_toggle_and_fallback(self):
        seed = seed_pilot_world(building_name="Fund Chart R", email_prefix="fcr")
        self._login(seed, "fund_recorder")
        resp = self.client.get(reverse("web:fund-home"), {"range": "30d"})
        self.assertEqual(len(resp.context["chart_points"]), 30)
        resp = self.client.get(reverse("web:fund-home"), {"range": "bogus"})
        self.assertEqual(resp.context["chart_range"], "6m")

    def test_fund_home_window_stats_reconcile(self):
        seed = seed_pilot_world(building_name="Fund Chart S", email_prefix="fcs")
        self._login(seed, "fund_recorder")
        ctx = self.client.get(reverse("web:fund-home")).context
        self.assertEqual(
            ctx["window_opening_vnd"]
            + ctx["window_inflows_vnd"]
            + ctx["window_outflows_vnd"],
            ctx["window_closing_vnd"],
        )

    def test_without_fund_capability_is_forbidden(self):
        seed = seed_pilot_world(building_name="Fund Home Deny", email_prefix="fhd")
        self._login(seed, "maintenance")
        self.assertEqual(self.client.get(reverse("web:fund-home")).status_code, 403)


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class FundRecordTests(TestCase):
    def _login(self, seed, role_key):
        membership = seed.roles[role_key]
        self.client.force_login(membership.user)
        device = TOTPDevice.objects.create(
            user=membership.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = membership.pk
        session.save()
        return membership

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_prepare_then_sign_records_inflow(self):
        from datetime import datetime

        from lamto.finance.fund import build_fund_source_evidence_typed_data, get_or_create_fund

        seed = seed_pilot_world(building_name="Fund Rec B", email_prefix="fr")
        recorder = self._login(seed, "fund_recorder")
        account = seed.accounts[recorder.pk]
        url = reverse("web:fund-record")

        prepare = self.client.post(
            url,
            {
                "action": "prepare",
                "entry_type": MaintenanceFundEntry.EntryType.INFLOW,
                "amount_vnd": 2_000_000,
                "evidence_original": _pdf("e.pdf", b"orig"),
                "evidence_redacted": _pdf("er.pdf", b"redacted differs"),
            },
        )
        self.assertEqual(prepare.status_code, 200)
        self.assertContains(prepare, "data-signed-form")
        sign = prepare.context["sign_form"].initial

        fund = get_or_create_fund(seed.building)
        original = DocumentVersion.objects.get(pk=sign["evidence_original_id"])
        redacted = DocumentVersion.objects.get(pk=sign["evidence_redacted_id"])
        ts = datetime.fromisoformat(sign["entry_timestamp"])
        typed = build_fund_source_evidence_typed_data(
            fund,
            recorder,
            sign["fund_entry_id"],
            MaintenanceFundEntry.EntryType.INFLOW,
            2_000_000,
            original,
            redacted,
            sign["event_id"],
            timestamp=ts,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()

        submit = self.client.post(
            url,
            {
                "action": "submit",
                "entry_type": MaintenanceFundEntry.EntryType.INFLOW,
                "amount_vnd": 2_000_000,
                "evidence_original_id": original.pk,
                "evidence_redacted_id": redacted.pk,
                "fund_entry_id": sign["fund_entry_id"],
                "entry_timestamp": sign["entry_timestamp"],
                "event_id": sign["event_id"],
                "signature": signature,
            },
        )
        self.assertRedirects(submit, reverse("web:fund-home"))
        entry = MaintenanceFundEntry.objects.get(pk=sign["fund_entry_id"])
        self.assertEqual(entry.entry_type, MaintenanceFundEntry.EntryType.INFLOW)
        self.assertEqual(entry.amount_vnd, 2_000_000)
        self.assertFalse(hasattr(entry, "verification"))

    def test_non_recorder_forbidden(self):
        seed = seed_pilot_world(building_name="Fund Rec Deny", email_prefix="frd")
        self._login(seed, "fund_verifier")  # verify-only cannot record
        self.assertEqual(self.client.get(reverse("web:fund-record")).status_code, 403)


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class FundVerifyTests(TestCase):
    def _login(self, seed, role_key):
        membership = seed.roles[role_key]
        self.client.force_login(membership.user)
        device = TOTPDevice.objects.create(
            user=membership.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = membership.pk
        session.save()
        return membership

    def _unverified_entry(self, seed):
        """Record an inflow via the recorder domain path (unverified)."""
        from datetime import datetime
        from lamto.finance.fund import (
            allocate_fund_entry_id,
            build_fund_source_evidence_typed_data,
            get_or_create_fund,
            record_fund_source,
        )
        from lamto.documents.models import Document

        fund = get_or_create_fund(seed.building)
        recorder = seed.roles["fund_recorder"]
        original, redacted = seed.document_pair(Document.Kind.CONTRACT, recorder.user, "inflow")
        entry_id = allocate_fund_entry_id()
        ts = timezone.now()
        event_id = "0x" + "22" * 32
        typed = build_fund_source_evidence_typed_data(
            fund, recorder, entry_id, MaintenanceFundEntry.EntryType.INFLOW,
            1_000_000, original, redacted, event_id, timestamp=ts,
        )
        sig = seed.sign_typed(recorder, typed)
        return record_fund_source(
            fund, MaintenanceFundEntry.EntryType.INFLOW, 1_000_000, original, redacted,
            recorder, sig, event_id, fund_entry_id=entry_id, timestamp=ts,
        )

    def test_verifier_signs_and_verifies(self):
        from lamto.finance.fund import build_fund_verification_evidence_typed_data

        seed = seed_pilot_world(building_name="Fund Ver B", email_prefix="fv")
        entry = self._unverified_entry(seed)
        verifier = self._login(seed, "fund_verifier")
        account = seed.accounts[verifier.pk]
        url = reverse("web:fund-verify", kwargs={"pk": entry.pk})

        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        event_id = page.context["verify_form"].initial["event_id"]
        typed = build_fund_verification_evidence_typed_data(
            entry, verifier, event_id, timestamp=entry.recorded_at
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()
        resp = self.client.post(url, {"event_id": event_id, "signature": signature})
        self.assertRedirects(resp, reverse("web:fund-home"))
        entry.refresh_from_db()
        self.assertTrue(hasattr(entry, "verification"))

    def test_recorder_cannot_verify_own_source(self):
        from lamto.finance.fund import build_fund_verification_evidence_typed_data

        seed = seed_pilot_world(building_name="Fund Ver Deny", email_prefix="fvd")
        entry = self._unverified_entry(seed)
        # Recorder also holds verify capability for this test.
        from lamto.accounts.services import grant_capability
        from lamto.accounts.capabilities import FUND_VERIFY

        recorder = seed.roles["fund_recorder"]
        grant_capability(recorder, FUND_VERIFY)
        self._login(seed, "fund_recorder")
        account = seed.accounts[recorder.pk]
        url = reverse("web:fund-verify", kwargs={"pk": entry.pk})
        page = self.client.get(url)
        event_id = page.context["verify_form"].initial["event_id"]
        typed = build_fund_verification_evidence_typed_data(
            entry, recorder, event_id, timestamp=entry.recorded_at
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()
        resp = self.client.post(url, {"event_id": event_id, "signature": signature})
        self.assertEqual(resp.status_code, 403)
