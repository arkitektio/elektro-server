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
    clock = clocks.create_clock(name="their clock", ctx=ctx)
    block = models.Block.objects.create(name="their block", organization=organization, creator=user, clock=clock)
    segment = models.BlockSegment.objects.create(block=block, clock=clock)
    signal = models.AnalogSignal.objects.create(segment=segment, dataset=dataset, name="their signal")
    world = clocks.create_clock(name="their world", ctx=ctx)
    experiment = models.Experiment.objects.create(name="their experiment", organization=organization, creator=user, world=world)
    collection = models.AnnotationCollection.objects.create(name="their marks", organization=organization, creator=user, coordinate_system=clocks.create_clock(name="their drawing space", ctx=ctx))
    annotation = models.Annotation.objects.create(collection=collection, name="their event", kind="event", vectors=[[1.0]], creator=user)
    lens = models.Lens.objects.create(dataset=dataset, coordinate_system=dataset.coordinate_system)
    return {
        "deleteFolder": ("DeleteFolderInput", folder),
        "deleteFile": ("DeleteFileInput", file),
        "unlinkFile": ("UnlinkFileInput", link),
        "deleteArrayDataset": ("DeleteArrayDatasetInput", dataset),
        "deleteDataArray": ("DeleteDataArrayInput", level),
        "deleteBlock": ("DeleteBlockInput", block),
        "deleteBlockSegment": ("DeleteInput", segment),
        "deleteAnalogSignal": ("DeleteInput", signal),
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
    for mutation in ("deleteAnnotation", "deleteLens", "deleteAnalogSignal"):
        input_type, row = rows[mutation]
        document = "mutation ($input: %s!) { %s(input: $input) }" % (input_type, mutation)
        res = await aexecute(document, {"input": {"id": str(row.pk)}}, context=other_org_context)
        assert not res.errors, (mutation, res.errors)
        assert not await type(row).objects.filter(pk=row.pk).aexists()
