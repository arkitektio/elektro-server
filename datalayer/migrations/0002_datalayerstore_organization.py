"""Add the organization FK to datalayer stores.

Added nullable, backfilled with the first organization, then made
non-nullable so the migration also works on databases with existing rows.
Multi-org deployments with pre-existing stores should review the
assignment afterwards.
"""

import django.db.models.deletion
from django.db import migrations, models


def backfill_organizations(apps, schema_editor):
    """Assign an organization to every pre-existing store."""
    Organization = apps.get_model("authentikate", "Organization")
    DatalayerStore = apps.get_model("datalayer", "DatalayerStore")

    if DatalayerStore.objects.filter(organization__isnull=True).exists():
        default_org = Organization.objects.order_by("pk").first()
        if default_org is None:
            raise RuntimeError("Cannot backfill datalayer.DatalayerStore: no organization exists")
        DatalayerStore.objects.filter(organization__isnull=True).update(organization=default_org)


class Migration(migrations.Migration):
    dependencies = [
        ("authentikate", "0005_alter_client_client_id"),
        ("datalayer", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="datalayerstore",
            name="organization",
            field=models.ForeignKey(
                help_text="The organization this store belongs to.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="authentikate.organization",
            ),
        ),
        migrations.RunPython(backfill_organizations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="datalayerstore",
            name="organization",
            field=models.ForeignKey(
                help_text="The organization this store belongs to.",
                on_delete=django.db.models.deletion.CASCADE,
                to="authentikate.organization",
            ),
        ),
    ]
