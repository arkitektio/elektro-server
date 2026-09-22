"""A neuron model owns a space, and its ancestry is an edge rather than a column.

``NeuronModel.parent`` was the last literal parent-column lineage in the schema, and it was
the weaker of the two mechanisms this service carries. It recorded no ``validity`` and no
``value_relation``, it carried no provenance of its own, it was exposed nowhere in GraphQL,
and ``lineageGraph`` could not see it at all -- a model was not a container, so no walk had a
node to stand on. Every other kind of derived thing here says where it came from with a
``Transformation`` edge out of its own coordinate system; a model now says it the same way.

The space a model owns carries a single INDEX axis and nothing placeable, exactly as a table
with no coordinate columns does, so every edge touching it is UNMAPPABLE: the lineage is
recorded and no geometry is claimed, which is the whole truth about a retuned conductance.

**On the design note in ``core/DESIGN.md`` against data migrations** ("a data migration would
have had to re-implement edge derivation against historical models -- a second copy of the
logic this design forbids"): this is not that. An UNMAPPABLE edge has no matrix, no rank and
no axis mapping, and ``assert_edge_rank`` short-circuits on it. Writing one is a plain row
insert, not a second implementation of anything.

**Delete semantics change.** ``parent`` was CASCADE, so deleting a parent deleted its whole
subtree. Now the child's row survives, but ``deleteNeuronModel`` sweeps the space it owns and
that sweep takes every edge touching it -- so deleting a parent leaves its children with an
empty ``derivedFrom``. The recorded parentage goes, not the child. That is what an array
dataset already does when its source is deleted.
"""

import django.db.models.deletion
from django.db import migrations, models


def mint_spaces(apps, schema_editor):
    """Give every existing model a space with one INDEX axis, then convert `parent` into edges.

    Two passes on purpose: every space must exist before any edge can point at one, and a
    parent is just another model whose space may not have been minted yet when its child is
    reached.
    """
    NeuronModel = apps.get_model("core", "NeuronModel")
    CoordinateSystem = apps.get_model("core", "CoordinateSystem")
    Axis = apps.get_model("core", "Axis")
    Transformation = apps.get_model("core", "Transformation")

    for model in NeuronModel.objects.select_related("environment").iterator():
        if model.coordinate_system_id is not None:
            continue
        system = CoordinateSystem.objects.create(
            name=f"{model.name}/model",
            creator_id=model.creator_id,
            organization_id=model.organization_id,
        )
        Axis.objects.create(coordinate_system=system, order=0, name="object", type="INDEX", unit=None)
        model.coordinate_system = system
        model.save(update_fields=["coordinate_system"])

    for model in NeuronModel.objects.filter(parent__isnull=False).select_related("parent").iterator():
        if model.coordinate_system_id is None or model.parent.coordinate_system_id is None:
            continue
        Transformation.objects.create(
            name=f"{model.name} <- {model.parent.name}",
            kind="UNMAPPABLE",
            input_id=model.coordinate_system_id,
            output_id=model.parent.coordinate_system_id,
            params={},
            validity="MANUAL",
            value_relation="TRANSFORMED",
            order=0,
            organization_id=model.organization_id,
            creator_id=model.creator_id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_a_neuron_model_belongs_to_one_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="neuronmodel",
            name="coordinate_system",
            field=models.ForeignKey(
                blank=True,
                help_text="The coordinate system this model owns. Its derivation edges are its lineage",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="neuron_models",
                to="core.coordinatesystem",
            ),
        ),
        migrations.AddField(
            model_name="historicalneuronmodel",
            name="coordinate_system",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                help_text="The coordinate system this model owns. Its derivation edges are its lineage",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="core.coordinatesystem",
            ),
        ),
        migrations.RunPython(mint_spaces, migrations.RunPython.noop),
        migrations.RemoveField(model_name="neuronmodel", name="parent"),
        migrations.RemoveField(model_name="historicalneuronmodel", name="parent"),
    ]
