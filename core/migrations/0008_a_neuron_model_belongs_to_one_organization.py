"""A neuron model belongs to exactly one organization.

``NeuronModel`` was the only one of ``ModelCollection`` / ``ModEnvironment`` /
``ModelWorkspace`` / ``Experiment`` without an ``organization`` column: it reached one by
following ``environment``, which ``core.scoping._find_org_path`` is happy to do. Meanwhile
``hash`` was ``unique=True`` **globally** and ``create_neuron_model`` ran an *unscoped*
``update_or_create(hash=...)``. Two organizations uploading the same config therefore shared
one row, and the second silently overwrote the first's ``creator``, ``environment``, ``name``
and ``parent``.

**That damage already happened and is not repairable here.** The overwritten values are gone;
only ``HistoricalNeuronModel`` remembers them. This migration stops it recurring and makes no
attempt to reconstruct anything.

A derived organization could not have fixed it in any case: a unique constraint may only
reference local columns, so "one model per hash per organization" is inexpressible through
``environment__organization``. The new constraint is *strictly weaker* than the global unique
it replaces -- every row satisfying the old one satisfies it -- so there is nothing to
reconcile and no row to split.
"""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def backfill_organization(apps, schema_editor):
    """Every model takes its environment's organization.

    ``environment`` is NOT NULL and ``ModEnvironment.organization`` is NOT NULL, so this leaves
    no row null. Written as a ``Subquery`` because ``UPDATE`` cannot follow a join, so
    ``F("environment__organization_id")`` would not resolve.
    """
    NeuronModel = apps.get_model("core", "NeuronModel")
    ModEnvironment = apps.get_model("core", "ModEnvironment")
    NeuronModel.objects.update(
        organization_id=Subquery(ModEnvironment.objects.filter(pk=OuterRef("environment_id")).values("organization_id")[:1])
    )


class Migration(migrations.Migration):

    dependencies = [
        ("authentikate", "0001_initial"),
        ("core", "0007_coordinate_anchor_sparse"),
    ]

    operations = [
        migrations.AddField(
            model_name="neuronmodel",
            name="organization",
            field=models.ForeignKey(
                help_text="The organization that owns the model",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="neuron_models",
                to="authentikate.organization",
            ),
        ),
        migrations.AddField(
            model_name="historicalneuronmodel",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                help_text="The organization that owns the model",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="authentikate.organization",
            ),
        ),
        migrations.RunPython(backfill_organization, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="neuronmodel",
            name="organization",
            field=models.ForeignKey(
                help_text="The organization that owns the model",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="neuron_models",
                to="authentikate.organization",
            ),
        ),
        migrations.AlterField(
            model_name="neuronmodel",
            name="hash",
            field=models.CharField(db_index=True, help_text="The hash of the model", max_length=1000),
        ),
        migrations.AlterField(
            model_name="historicalneuronmodel",
            name="hash",
            field=models.CharField(db_index=True, help_text="The hash of the model", max_length=1000),
        ),
        migrations.AddConstraint(
            model_name="neuronmodel",
            constraint=models.UniqueConstraint(fields=("organization", "hash"), name="one_model_per_hash_per_organization"),
        ),
    ]
