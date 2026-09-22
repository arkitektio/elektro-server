"""Tenant isolation of the delete mutations, end to end.

The bug this pins: a delete looked its row up with a bare ``objects.get(id=...)`` and then
asked :func:`core.guards.can_delete`, whose first rule lets an organization admin delete
anything -- without asking *which* organization's admin. So an admin of one organization
could delete another organization's rows by id.

The static ``test`` token is an admin of ``static_org``; the rows below belong to
``other_org``. Every delete must fail as "not found", and every row must survive.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@sync_to_async
def _theirs(other):
    """One row of several kinds, all in the other organization."""
    from core.logic import clocks

    organization, user = other.request.organization, other.request.user
    ctx = seed._creation(other)
    folder = models.Folder.objects.create(name="theirs", creator=user, organization=organization, membership=other.request.membership)
    dataset = seed._seed_array_dataset_sync(other, "their dataset", seed.T_AXES, [[100], [10]], None, "mV", folder)
    level = dataset.data_arrays.get(level=1)
    file = models.File.objects.create(name="their file", folder=folder, creator=user, organization=organization, membership=other.request.membership)
    link = models.FileLink.objects.create(file=file, dataset=dataset, direction="SOURCE", creator=user, organization=organization)
    world = clocks.create_clock(name="their world", ctx=ctx)
    experiment = models.Experiment.objects.create(name="their experiment", organization=organization, creator=user, world=world)
    lens_for_layer = models.Lens.objects.create(dataset=dataset, coordinate_system=dataset.coordinate_system)
    layer = models.ExperimentLayer.objects.create(experiment=experiment, kind="trace", lens=lens_for_layer)
    table = seed._seed_table_dataset_sync(other, "their events", [{"name": "t", "axis_type": seed.enums.AxisType.TIME, "unit": "second"}], folder)
    raster = seed._seed_sparse_dataset_sync(other, "their spikes", seed.RASTER_AXES, [4, 100], None, folder)
    collection = models.AnnotationCollection.objects.create(name="their marks", organization=organization, creator=user, coordinate_system=clocks.create_clock(name="their drawing space", ctx=ctx))
    annotation = models.Annotation.objects.create(collection=collection, name="their event", kind="event", vectors=[[1.0]], creator=user)
    lens = models.Lens.objects.create(dataset=dataset, coordinate_system=dataset.coordinate_system)
    return {
        "deleteFolder": ("DeleteFolderInput", folder),
        "deleteFile": ("DeleteFileInput", file),
        "unlinkFile": ("UnlinkFileInput", link),
        "deleteArrayDataset": ("DeleteArrayDatasetInput", dataset),
        "deleteDataArray": ("DeleteDataArrayInput", level),
        "deleteLayer": ("DeleteInput", layer),
        "deleteTableDataset": ("DeleteTableDatasetInput", table),
        "deleteSparseDataset": ("DeleteSparseDatasetInput", raster),
        "deleteExperiment": ("DeleteInput", experiment),
        "deleteAnnotation": ("DeleteAnnotationInput", annotation),
        "deleteAnnotationCollection": ("DeleteAnnotationCollectionInput", collection),
        "deleteLens": ("DeleteLensInput", lens),
        "deleteCoordinateSystem": ("DeleteCoordinateSystemInput", world),
    }


async def test_an_admin_of_one_organization_cannot_delete_another_organizations_rows(aexecute, other_org_context):
    rows = await _theirs(other_org_context)

    for mutation, (input_type, row) in rows.items():
        document = "mutation ($input: %s!) { %s(input: $input) }" % (input_type, mutation)
        res = await aexecute(document, {"input": {"id": str(row.pk)}})  # as the admin of static_org
        assert res.errors, f"{mutation} deleted a row of another organization"
        assert "not allowed" not in str(res.errors[0]), f"{mutation} found the row and only then refused: the lookup itself must not cross organizations"
        assert await type(row).objects.filter(pk=row.pk).aexists(), f"{mutation} removed {type(row).__name__} {row.pk}"


async def test_the_owning_organization_can_still_delete_them(aexecute, other_org_context):
    """The scoping must not have made deletes impossible: the creator deletes their own rows."""
    rows = await _theirs(other_org_context)
    for mutation in ("deleteAnnotation", "deleteLayer", "deleteLens", "deleteTableDataset", "deleteSparseDataset"):
        input_type, row = rows[mutation]
        document = "mutation ($input: %s!) { %s(input: $input) }" % (input_type, mutation)
        res = await aexecute(document, {"input": {"id": str(row.pk)}}, context=other_org_context)
        assert not res.errors, (mutation, res.errors)
        assert not await type(row).objects.filter(pk=row.pk).aexists()


CREATE_NEURON_MODEL = """
mutation ($input: CreateNeuronModelInput!) {
  createNeuronModel(input: $input) { id name coordinateSystem { id } }
}
"""


async def test_two_organizations_can_hold_the_same_model_config(aexecute, authenticated_context, other_org_context):
    """One org's create must not match -- and overwrite -- another's row.

    `NeuronModel.hash` was `unique=True` *globally* while `create_neuron_model` ran an unscoped
    `update_or_create(hash=...)`, so the same config uploaded by two organizations produced one
    shared row whose `creator`, `environment` and `name` belonged to whoever wrote last. It also
    made the model unable to own a space once it became a lineage container: a coordinate
    system's organization is required and single-valued, so a shared row had no single answer.

    The constraint is `(organization, hash)` now, and the lookup matches it.
    """
    config = {"cells": [], "vInit": "-67 mV", "temperature": "36 degC"}

    mine_env = await models.ModEnvironment.objects.acreate(name="mine-env", organization=authenticated_context.request.organization)
    theirs_env = await models.ModEnvironment.objects.acreate(name="theirs-env", organization=other_org_context.request.organization)

    mine = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "Mine", "environment": str(mine_env.id), "config": config}},
        context=authenticated_context,
    )
    theirs = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "Theirs", "environment": str(theirs_env.id), "config": config}},
        context=other_org_context,
    )
    assert not mine.errors, mine.errors
    assert not theirs.errors, theirs.errors

    # Two rows, not one -- and neither name was overwritten by the other's write.
    assert mine.data["createNeuronModel"]["id"] != theirs.data["createNeuronModel"]["id"]
    assert await models.NeuronModel.objects.filter(name="Mine").acount() == 1
    assert await models.NeuronModel.objects.filter(name="Theirs").acount() == 1

    # Each owns its own space, scoped to its own organization.
    assert mine.data["createNeuronModel"]["coordinateSystem"]["id"] != theirs.data["createNeuronModel"]["coordinateSystem"]["id"]
    mine_row = await models.NeuronModel.objects.aget(name="Mine")
    theirs_row = await models.NeuronModel.objects.aget(name="Theirs")
    assert mine_row.organization_id == authenticated_context.request.organization.id
    assert theirs_row.organization_id == other_org_context.request.organization.id
