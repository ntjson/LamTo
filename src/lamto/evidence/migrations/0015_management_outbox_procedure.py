from importlib import import_module

from django.db import migrations


_legacy_sql = import_module(
    "lamto.evidence.migrations.0009_outbox_building_backfill_and_guard"
).INSERT_FUNCTION_WITH_BUILDING

MANAGEMENT_OUTBOX_PROCEDURE = (
    "SET ROLE lamto_service;\n"
    + _legacy_sql.replace(
        """    PERFORM 1 FROM public.accounts_organizationmembership
    WHERE id = p_membership_id AND active
      AND role IN ('OPERATOR', 'BOARD', 'RESIDENT_REP') FOR UPDATE;""",
        """    PERFORM 1 FROM public.accounts_managementmembership
    WHERE id = p_membership_id AND active FOR UPDATE;""",
    ).replace(
        """    SELECT o.building_id INTO v_building_id
    FROM public.accounts_organizationmembership m
    JOIN public.accounts_organization o ON o.id = m.organization_id
    WHERE m.id = p_membership_id;""",
        """    SELECT building_id INTO v_building_id
    FROM public.accounts_managementmembership
    WHERE id = p_membership_id;""",
    )
    + "\nRESET ROLE;"
)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_management_wallet_procedures"),
        ("evidence", "0014_alter_blockchainoutboxevent_event_type"),
    ]

    operations = [
        migrations.RunSQL(MANAGEMENT_OUTBOX_PROCEDURE, migrations.RunSQL.noop),
    ]
