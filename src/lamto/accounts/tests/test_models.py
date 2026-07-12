from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from lamto.accounts.models import Building, Organization, OrganizationMembership


class AccountModelTests(TestCase):
    def test_email_user_can_join_one_building_organization(self):
        user = get_user_model().objects.create_user(
            email="board@example.test", password="secret", display_name="Board One"
        )
        building = Building.objects.create(name="Minh An Residence", timezone="Asia/Ho_Chi_Minh")
        organization = Organization.objects.create(
            building=building, name="Management Board", kind=Organization.Kind.BOARD
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=organization, role=OrganizationMembership.Role.BOARD
        )

        self.assertEqual(user.username, None)
        self.assertEqual(membership.organization.building, building)

    def test_membership_role_must_match_organization_kind(self):
        user = get_user_model().objects.create_user(
            email="operator@example.test", password="secret", display_name="Operator One"
        )
        building = Building.objects.create(name="Minh An Residence")
        board = Organization.objects.create(
            building=building, name="Management Board", kind=Organization.Kind.BOARD
        )
        membership = OrganizationMembership(
            user=user, organization=board, role=OrganizationMembership.Role.OPERATOR
        )

        with self.assertRaises(ValidationError):
            membership.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            membership.save()
