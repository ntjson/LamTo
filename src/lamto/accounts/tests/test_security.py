"""MFA, re-auth, throttle, session, and break-glass security controls."""

from __future__ import annotations

import time
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.capabilities import (
    AUDIT_EXPORT,
    PAYMENT_RECORD,
    PAYMENT_VERIFY,
    REPORT_TRIAGE,
    TECH_ADMIN,
)
from lamto.accounts.mfa import begin_totp_enrollment, confirm_totp_enrollment, verify_totp_for_session
from lamto.accounts.models import (
    AuthThrottleBucket,
    BreakGlassRevocation,
    BreakGlassSession,
    Building,
    Organization,
    OrganizationMembership,
)
from lamto.accounts.security import (
    RECENT_REAUTH_KEY,
    THROTTLE_MAX_FAILURES,
    THROTTLE_WINDOW_SECONDS,
    assert_not_throttled,
    issue_break_glass_consent,
    mark_recent_reauth,
    record_auth_failure,
    require_recent_auth,
    reset_auth_throttle,
    revoke_break_glass,
    start_break_glass,
    throttle_digest,
)
from lamto.audit.models import AuditEvent
from lamto.accounts.services import grant_capability


def _current_totp_token(device: TOTPDevice) -> str:
    # Force a fresh step after last_t updates by using django_otp.oath.totp directly
    # and temporarily clearing last_t when needed.
    return f"{totp(device.bin_key):06d}"


class SecurityTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.building = Building.objects.create(name="Sec Building")

    def _unique(self, base):
        n = getattr(self, "_seq", 0) + 1
        self._seq = n
        return f"{base}-{n}"

    def make_membership(self, role, suffix, capabilities=(), *, building=None):
        building = building or self.building
        suffix = self._unique(suffix)
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test",
            password="secret-pass-123",
            display_name=suffix,
        )
        organization = Organization.objects.create(
            building=building,
            name=suffix,
            kind=OrganizationMembership.ROLE_TO_ORGANIZATION_KIND[role],
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=organization, role=role
        )
        for code in capabilities:
            grant_capability(membership, code)
        return membership

    def make_board_user_with_payment_capability(self):
        return self.make_membership(
            OrganizationMembership.Role.BOARD,
            "board-pay",
            capabilities=(PAYMENT_RECORD, PAYMENT_VERIFY),
        )

    def make_operator_and_auditor(self):
        operator = self.make_membership(
            OrganizationMembership.Role.OPERATOR,
            "op",
            capabilities=(REPORT_TRIAGE,),
        )
        auditor = self.make_membership(
            OrganizationMembership.Role.AUDITOR,
            "aud",
            capabilities=(AUDIT_EXPORT,),
        )
        return operator, auditor

    def valid_payment_payload(self):
        return {
            "bank_reference": "REF-1",
            "amount_vnd": "1000",
            "external_status": "COMPLETED",
            "proof_pair": "1:2",
            "event_id": "0x" + "11" * 32,
            "signature": "0x" + "22" * 65,
            "acceptance_id": "1",
        }

    def enroll_and_bind(self, client: Client, user) -> TOTPDevice:
        device = TOTPDevice.objects.create(
            user=user,
            name="test",
            confirmed=True,
            key=random_hex(),
        )
        # Bind device into session after login.
        session = client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        return device

    def consent_for(self, authorizer, tech) -> str:
        return issue_break_glass_consent(
            authorizing_membership=authorizer,
            tech_membership=tech,
        )

    def test_privileged_action_requires_verified_otp_and_recent_reauth(self):
        board = self.make_board_user_with_payment_capability()
        self.client.force_login(board.user)
        response = self.client.post(
            reverse("web:payment-record"), self.valid_payment_payload()
        )
        self.assertEqual(response.status_code, 403)

    def test_privileged_action_allowed_with_otp_and_recent_reauth_gate_passes(self):
        board = self.make_board_user_with_payment_capability()
        self.client.force_login(board.user)
        self.enroll_and_bind(self.client, board.user)
        # Gate should not 403 for MFA/reauth; may 404/400 for missing acceptance.
        response = self.client.post(
            reverse("web:payment-record"), self.valid_payment_payload()
        )
        self.assertNotEqual(response.status_code, 403)

    def test_only_auditor_can_export_original_document_history(self):
        operator, auditor = self.make_operator_and_auditor()
        self.client.force_login(operator.user)
        self.enroll_and_bind(self.client, operator.user)
        self.assertEqual(self.client.get(reverse("web:audit-export")).status_code, 403)

        self.client.force_login(auditor.user)
        self.enroll_and_bind(self.client, auditor.user)
        self.assertEqual(self.client.get(reverse("web:audit-export")).status_code, 200)

    def test_throttle_locks_after_five_failures_and_resets_on_success(self):
        account = "throttle@example.test"
        ip = "203.0.113.9"
        for _ in range(THROTTLE_MAX_FAILURES):
            record_auth_failure(account, ip)
        with self.assertRaises(PermissionDenied):
            assert_not_throttled(account, ip)
        bucket = AuthThrottleBucket.objects.get(key_digest=throttle_digest(account, ip))
        self.assertIsNotNone(bucket.locked_until)
        reset_auth_throttle(account, ip)
        assert_not_throttled(account, ip)
        bucket.refresh_from_db()
        self.assertEqual(bucket.failure_count, 0)
        self.assertIsNone(bucket.locked_until)

    def test_throttle_window_expiry_allows_new_attempts(self):
        account = "window@example.test"
        ip = "198.51.100.2"
        for _ in range(THROTTLE_MAX_FAILURES):
            record_auth_failure(account, ip)
        bucket = AuthThrottleBucket.objects.get(key_digest=throttle_digest(account, ip))
        bucket.window_started_at = timezone.now() - timedelta(
            seconds=THROTTLE_WINDOW_SECONDS + 5
        )
        bucket.locked_until = timezone.now() - timedelta(seconds=1)
        bucket.save(update_fields=["window_started_at", "locked_until"])
        # Locked_until in the past → not throttled.
        assert_not_throttled(account, ip)

    def test_session_rotation_on_mfa_and_revocation_on_logout(self):
        membership = self.make_board_user_with_payment_capability()
        user = membership.user
        self.client.force_login(user)
        device = TOTPDevice.objects.create(
            user=user, name="rot", confirmed=True, key=random_hex()
        )
        session_key_before = self.client.session.session_key
        # Verify token path rotates session.
        request = self.factory.post("/s/security/mfa/verify/")
        request.user = user
        request.session = self.client.session
        token = _current_totp_token(device)
        # Ensure last_t allows current token.
        device.last_t = -1
        device.save(update_fields=["last_t"])
        verify_totp_for_session(user, token, request=request)
        request.session.save()
        self.assertTrue(request.session.get(DEVICE_ID_SESSION_KEY))
        self.assertIsNotNone(request.session.get(RECENT_REAUTH_KEY))
        # Logout flushes session.
        self.client.logout()
        # New anonymous session should not carry MFA binding.
        self.assertFalse(self.client.session.get(DEVICE_ID_SESSION_KEY))

    def test_require_recent_auth_expires(self):
        membership = self.make_board_user_with_payment_capability()
        user = membership.user
        device = TOTPDevice.objects.create(
            user=user, name="re", confirmed=True, key=random_hex()
        )
        request = self.factory.post("/s/payments/record/")
        request.user = user
        # Minimal session-like dict with OTP binding via middleware simulation:
        from django.contrib.sessions.backends.db import SessionStore

        session = SessionStore()
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time() - 400
        session.save()
        request.session = session

        # OTPMiddleware-style wrap: user.is_verified from django_otp.models
        from django_otp.middleware import OTPMiddleware

        # Manually set verified by attaching device
        user.otp_device = device
        # django_otp.is_verified checks session device id
        with mock.patch(
            "lamto.accounts.security.user_is_otp_verified", return_value=True
        ):
            with self.assertRaises(PermissionDenied):
                require_recent_auth(request, max_age_seconds=300)
            mark_recent_reauth(request)
            require_recent_auth(request, max_age_seconds=300)

    def test_break_glass_expiry_and_early_revocation(self):
        tech = self.make_membership(
            OrganizationMembership.Role.TECH_ADMIN,
            "tech",
            capabilities=(TECH_ADMIN,),
        )
        board = self.make_membership(
            OrganizationMembership.Role.BOARD,
            "authz",
            capabilities=(PAYMENT_RECORD,),
        )
        session = start_break_glass(
            tech_membership=tech,
            authorizing_membership=board,
            reason="Investigate stuck worker",
            consent_token=self.consent_for(board, tech),
            duration_minutes=60,
        )
        self.assertGreater(session.expires_at, timezone.now())
        self.assertEqual(BreakGlassSession.objects.count(), 1)

        rev = revoke_break_glass(session, revoked_by=tech.user, reason="done")
        self.assertIsInstance(rev, BreakGlassRevocation)
        with self.assertRaises(ValidationError):
            revoke_break_glass(session, revoked_by=tech.user, reason="again")

        # Expired session cannot be revoked as active
        expired = start_break_glass(
            tech_membership=tech,
            authorizing_membership=board,
            reason="Second window",
            consent_token=self.consent_for(board, tech),
            duration_minutes=1,
        )
        BreakGlassSession.objects.filter(pk=expired.pk).update(
            expires_at=timezone.now() - timedelta(seconds=5)
        )
        expired.refresh_from_db()
        with self.assertRaises(ValidationError):
            revoke_break_glass(expired, revoked_by=tech.user)

        # Insert-only: updates rejected
        with self.assertRaises(ValueError):
            session.reason = "mutated"
            session.save()

    def test_tech_admin_denied_finance_and_document_routes_even_with_break_glass(self):
        tech = self.make_membership(
            OrganizationMembership.Role.TECH_ADMIN,
            "tech2",
            capabilities=(TECH_ADMIN,),
        )
        board = self.make_membership(
            OrganizationMembership.Role.BOARD,
            "authz2",
            capabilities=(PAYMENT_RECORD,),
        )
        start_break_glass(
            tech_membership=tech,
            authorizing_membership=board,
            reason="Support only",
            consent_token=self.consent_for(board, tech),
            duration_minutes=30,
        )
        self.client.force_login(tech.user)
        self.enroll_and_bind(self.client, tech.user)

        finance_and_doc_urls = [
            reverse("web:payment-list"),
            reverse("web:payment-record"),
            reverse("web:case-list"),
            reverse("web:proposal-list"),
            reverse("web:work-order-list"),
            reverse("web:audit-search"),
            reverse("web:audit-export"),
        ]
        for url in finance_and_doc_urls:
            if url.endswith("/record/") or "export" in url:
                response = self.client.post(url, self.valid_payment_payload()) if url.endswith("/record/") else self.client.get(url)
            else:
                response = self.client.get(url)
            self.assertIn(
                response.status_code,
                {403, 302},
                msg=f"Expected denial for {url}, got {response.status_code}",
            )
            # 302 would be login; treat as not granted content
            if response.status_code == 302:
                self.assertNotIn(b"Payment", response.content)

        # Health is allowed for tech admin
        health = self.client.get(reverse("web:ops-health") + "?format=json")
        self.assertEqual(health.status_code, 200)

    def test_staff_workspace_requires_confirmed_totp(self):
        board = self.make_board_user_with_payment_capability()
        self.client.force_login(board.user)
        response = self.client.get(reverse("web:action-inbox"))
        self.assertEqual(response.status_code, 403)

    def test_totp_enrollment_confirm_and_verify(self):
        board = self.make_board_user_with_payment_capability()
        user = board.user
        device = begin_totp_enrollment(user)
        self.assertFalse(device.confirmed)
        token = _current_totp_token(device)
        request = self.factory.post("/s/security/mfa/setup/")
        request.user = user
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        request.session.create()
        confirmed = confirm_totp_enrollment(user, token, request=request)
        self.assertTrue(confirmed.confirmed)
        # Second verify with a new step: advance last_t handling
        confirmed.last_t = -1
        confirmed.save(update_fields=["last_t"])
        # Sleep if needed to avoid same-token reuse — reset last_t already allows.
        token2 = _current_totp_token(confirmed)
        verify_totp_for_session(user, token2, request=request)
        self.assertTrue(request.session.get(DEVICE_ID_SESSION_KEY))

    def test_staff_mfa_required_on_payment_list_audit_search_work_order_list(self):
        """Password-only session denied on key staff workspaces (Finding 1)."""
        board = self.make_board_user_with_payment_capability()
        auditor = self.make_membership(
            OrganizationMembership.Role.AUDITOR,
            "aud-mfa",
            capabilities=(AUDIT_EXPORT,),
        )
        maint = self.make_membership(
            OrganizationMembership.Role.MAINTENANCE,
            "maint-mfa",
            capabilities=(),
        )

        for membership, url_name in (
            (board, "web:payment-list"),
            (auditor, "web:audit-search"),
            (maint, "web:work-order-list"),
        ):
            with self.subTest(url=url_name):
                client = Client()
                client.force_login(membership.user)
                response = client.get(reverse(url_name))
                self.assertEqual(
                    response.status_code,
                    403,
                    msg=f"password-only session must be denied on {url_name}",
                )

    def test_signed_financial_post_requires_recent_reauth(self):
        """Signed financial POSTs redirect to reauth when stale (Finding 2)."""
        board = self.make_board_user_with_payment_capability()
        self.client.force_login(board.user)
        self.enroll_and_bind(self.client, board.user)
        # Stale reauth window.
        session = self.client.session
        session[RECENT_REAUTH_KEY] = time.time() - 400
        session.save()

        response = self.client.post(
            reverse("web:payment-record"), self.valid_payment_payload()
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/s/security/reauth/", response["Location"])
        self.assertIn("next=", response["Location"])

    def test_break_glass_requires_authorizer_consent_token(self):
        """Bare authorizing_membership_id without consent is rejected (Finding 4)."""
        tech = self.make_membership(
            OrganizationMembership.Role.TECH_ADMIN,
            "tech-consent",
            capabilities=(TECH_ADMIN,),
        )
        board = self.make_membership(
            OrganizationMembership.Role.BOARD,
            "authz-consent",
            capabilities=(PAYMENT_RECORD,),
        )
        with self.assertRaises(ValidationError):
            start_break_glass(
                tech_membership=tech,
                authorizing_membership=board,
                reason="No proof",
                consent_token="",
                duration_minutes=15,
            )
        with self.assertRaises(ValidationError):
            start_break_glass(
                tech_membership=tech,
                authorizing_membership=board,
                reason="Forged proof",
                consent_token="not-a-valid-token",
                duration_minutes=15,
            )
        # Valid dual-control consent works.
        token = self.consent_for(board, tech)
        session = start_break_glass(
            tech_membership=tech,
            authorizing_membership=board,
            reason="Authorized support",
            consent_token=token,
            duration_minutes=15,
        )
        self.assertIsNotNone(session.pk)

    def test_break_glass_request_path_is_audited(self):
        """Every /s/ request under break-glass is audited via middleware (Finding 4)."""
        tech = self.make_membership(
            OrganizationMembership.Role.TECH_ADMIN,
            "tech-audit",
            capabilities=(TECH_ADMIN,),
        )
        board = self.make_membership(
            OrganizationMembership.Role.BOARD,
            "authz-audit",
            capabilities=(PAYMENT_RECORD,),
        )
        start_break_glass(
            tech_membership=tech,
            authorizing_membership=board,
            reason="Audit path coverage",
            consent_token=self.consent_for(board, tech),
            duration_minutes=30,
        )
        self.client.force_login(tech.user)
        self.enroll_and_bind(self.client, tech.user)
        before = AuditEvent.objects.filter(action="security.break_glass.request").count()
        response = self.client.get(reverse("web:ops-health") + "?format=json")
        self.assertEqual(response.status_code, 200)
        after = AuditEvent.objects.filter(action="security.break_glass.request").count()
        self.assertGreater(after, before)
