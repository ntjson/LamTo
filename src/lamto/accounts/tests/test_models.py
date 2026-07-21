from django.test import SimpleTestCase

from lamto.accounts.models import (
    ManagementMembership,
    SignerAuthorizationRequest,
    SignerWallet,
    WalletRegistrationChallenge,
)


class WalletMembershipModelTests(SimpleTestCase):
    def test_wallet_models_use_management_memberships(self):
        self.assertIs(SignerWallet._meta.get_field("membership").related_model, ManagementMembership)
        self.assertIs(
            WalletRegistrationChallenge._meta.get_field("membership").related_model,
            ManagementMembership,
        )
        self.assertIs(
            SignerAuthorizationRequest._meta.get_field("requested_by").related_model,
            ManagementMembership,
        )
