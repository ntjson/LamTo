from django.test import SimpleTestCase

from lamto.accounts.models import ManagementMembership
from lamto.finance.models import (
    AcceptanceRecord,
    MaintenanceFundEntry,
    FundEntryVerification,
    PaymentEvidence,
    PaymentVerification,
    PublicationGateFailure,
    PublicationSnapshot,
    Proposal,
    ProposalVersion,
)


class FinanceMembershipModelTests(SimpleTestCase):
    def test_finance_attribution_uses_management_memberships(self):
        for model, field in (
            (Proposal, "creator_membership"),
            (ProposalVersion, "creator_membership"),
            (AcceptanceRecord, "membership"),
            (PaymentEvidence, "recorder"),
            (PaymentVerification, "membership"),
            (MaintenanceFundEntry, "recorder"),
            (FundEntryVerification, "membership"),
            (PublicationSnapshot, "publisher"),
            (PublicationGateFailure, "actor"),
        ):
            self.assertIs(
                model._meta.get_field(field).related_model,
                ManagementMembership,
            )
