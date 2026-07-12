from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.audit.models import AuditEvent
from lamto.audit.services import record_audit


class AuditImmutabilityTests(TestCase):
    def make_board_membership(self):
        user = get_user_model().objects.create_user(
            email="board@example.test", password="secret", display_name="Board Member"
        )
        building = Building.objects.create(name="Minh An Residence")
        organization = Organization.objects.create(
            building=building, name="Management Board", kind=Organization.Kind.BOARD
        )
        return OrganizationMembership.objects.create(
            user=user, organization=organization, role=OrganizationMembership.Role.BOARD
        )

    def test_audit_is_append_only(self):
        membership = self.make_board_membership()
        event = record_audit(
            actor=membership.user,
            membership=membership,
            action="proposal.approve",
            target_type="ProposalVersion",
            target_id="42",
            result="allowed",
        )

        event.result = "changed"
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()

    def test_database_trigger_rejects_bulk_and_raw_mutation(self):
        membership = self.make_board_membership()
        event = record_audit(
            actor=membership.user,
            membership=membership,
            action="proposal.approve",
            target_type="ProposalVersion",
            target_id="42",
            result="allowed",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            AuditEvent.objects.filter(pk=event.pk).update(result="changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM audit_auditevent WHERE id = %s", [event.pk])
