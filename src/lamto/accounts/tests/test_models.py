from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
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

    def test_all_membership_roles_match_the_fixed_organization_kind_map(self):
        user = get_user_model().objects.create_user(
            email="roles@example.test", password="secret", display_name="All Roles"
        )
        building = Building.objects.create(name="Minh An Residence")
        role_kind_pairs = (
            (OrganizationMembership.Role.OPERATOR, Organization.Kind.OPERATOR),
            (OrganizationMembership.Role.MAINTENANCE, Organization.Kind.OPERATOR),
            (OrganizationMembership.Role.BOARD, Organization.Kind.BOARD),
            (OrganizationMembership.Role.RESIDENT_REP, Organization.Kind.RESIDENT_REP),
            (OrganizationMembership.Role.AUDITOR, Organization.Kind.AUDITOR),
            (OrganizationMembership.Role.TECH_ADMIN, Organization.Kind.PLATFORM),
        )

        for index, (role, kind) in enumerate(role_kind_pairs):
            with self.subTest(role=role):
                organization = Organization.objects.create(
                    building=building, name=f"Organization {index}", kind=kind
                )
                membership = OrganizationMembership(
                    user=user, organization=organization, role=role
                )
                membership.full_clean()
                membership.save()

    def test_model_validation_rejects_kind_change_with_existing_memberships(self):
        user = get_user_model().objects.create_user(
            email="kind-change@example.test", password="secret", display_name="Kind Change"
        )
        building = Building.objects.create(name="Minh An Residence")
        organization = Organization.objects.create(
            building=building, name="Management Board", kind=Organization.Kind.BOARD
        )
        OrganizationMembership.objects.create(
            user=user, organization=organization, role=OrganizationMembership.Role.BOARD
        )

        organization.kind = Organization.Kind.OPERATOR
        with self.assertRaises(ValidationError):
            organization.full_clean()

    def test_direct_kind_update_is_rejected_with_existing_memberships(self):
        user = get_user_model().objects.create_user(
            email="direct-kind-change@example.test", password="secret", display_name="Direct Change"
        )
        building = Building.objects.create(name="Minh An Residence")
        organization = Organization.objects.create(
            building=building, name="Management Board", kind=Organization.Kind.BOARD
        )
        OrganizationMembership.objects.create(
            user=user, organization=organization, role=OrganizationMembership.Role.BOARD
        )

        organization.kind = Organization.Kind.OPERATOR
        with self.assertRaises(IntegrityError), transaction.atomic():
            organization.save(update_fields=["kind"])

    def test_queryset_kind_update_is_rejected_with_existing_memberships(self):
        user = get_user_model().objects.create_user(
            email="queryset-kind-change@example.test", password="secret", display_name="Queryset Change"
        )
        building = Building.objects.create(name="Minh An Residence")
        organization = Organization.objects.create(
            building=building, name="Management Board", kind=Organization.Kind.BOARD
        )
        OrganizationMembership.objects.create(
            user=user, organization=organization, role=OrganizationMembership.Role.BOARD
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Organization.objects.filter(pk=organization.pk).update(kind=Organization.Kind.OPERATOR)

    def test_raw_kind_update_is_rejected_with_existing_memberships(self):
        user = get_user_model().objects.create_user(
            email="raw-kind-change@example.test", password="secret", display_name="Raw Change"
        )
        building = Building.objects.create(name="Minh An Residence")
        organization = Organization.objects.create(
            building=building, name="Management Board", kind=Organization.Kind.BOARD
        )
        OrganizationMembership.objects.create(
            user=user, organization=organization, role=OrganizationMembership.Role.BOARD
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE accounts_organization SET kind = %s WHERE id = %s",
                    [Organization.Kind.OPERATOR, organization.pk],
                )
