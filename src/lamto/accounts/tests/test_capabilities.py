from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from lamto.accounts.capabilities import (
    ALLOWED_ORGANIZATION_KINDS,
    AUDIT_EXPORT,
    CORRECTION_APPROVE,
    CORRECTION_CREATE,
    FUND_RECORD,
    FUND_VERIFY,
    LEDGER_PUBLISH,
    PAYMENT_RECORD,
    PAYMENT_VERIFY,
    PROPOSAL_APPROVE,
    PROPOSAL_CREATE,
    REPORT_TRIAGE,
    TECH_ADMIN,
    WORK_ACCEPT,
    WORK_ASSIGN,
)
from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.accounts.services import grant_capability, require_capability


class CapabilityTests(TestCase):
    def make_membership(self, kind, role):
        user = get_user_model().objects.create_user(
            email=f"{role.lower()}-{kind.lower()}@example.test",
            password="secret",
            display_name=role,
        )
        building = Building.objects.create(name="Minh An Residence")
        organization = Organization.objects.create(building=building, name=kind, kind=kind)
        return OrganizationMembership.objects.create(user=user, organization=organization, role=role)

    def make_board_membership(self):
        return self.make_membership(Organization.Kind.BOARD, OrganizationMembership.Role.BOARD)

    def test_capability_must_be_explicit(self):
        membership = self.make_board_membership()

        with self.assertRaises(PermissionDenied):
            require_capability(membership.user, membership.id, PROPOSAL_APPROVE)

        grant_capability(membership, PROPOSAL_APPROVE)

        self.assertEqual(
            require_capability(membership.user, membership.id, PROPOSAL_APPROVE), membership
        )

    def test_capability_kind_allowlist_is_fixed(self):
        expected = {
            REPORT_TRIAGE: {Organization.Kind.OPERATOR},
            WORK_ASSIGN: {Organization.Kind.OPERATOR},
            PROPOSAL_CREATE: {Organization.Kind.OPERATOR},
            PROPOSAL_APPROVE: {Organization.Kind.BOARD, Organization.Kind.RESIDENT_REP},
            WORK_ACCEPT: {Organization.Kind.BOARD},
            PAYMENT_RECORD: {Organization.Kind.BOARD},
            PAYMENT_VERIFY: {Organization.Kind.BOARD},
            FUND_RECORD: {Organization.Kind.BOARD},
            FUND_VERIFY: {Organization.Kind.BOARD},
            LEDGER_PUBLISH: {Organization.Kind.BOARD},
            CORRECTION_CREATE: {Organization.Kind.OPERATOR},
            CORRECTION_APPROVE: {Organization.Kind.BOARD, Organization.Kind.RESIDENT_REP},
            AUDIT_EXPORT: {Organization.Kind.AUDITOR},
            TECH_ADMIN: {Organization.Kind.PLATFORM},
        }
        self.assertLessEqual(expected.items(), ALLOWED_ORGANIZATION_KINDS.items())
        self.assertEqual(len(ALLOWED_ORGANIZATION_KINDS), len(expected) + 1)

    def test_grant_rejects_unknown_or_wrong_organization_kind(self):
        membership = self.make_membership(
            Organization.Kind.OPERATOR, OrganizationMembership.Role.OPERATOR
        )

        with self.assertRaises(PermissionDenied):
            grant_capability(membership, PROPOSAL_APPROVE)
        with self.assertRaises(PermissionDenied):
            grant_capability(membership, "unknown")
