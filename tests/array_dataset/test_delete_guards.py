"""Ownership guards on the delete mutations of the data layer: folder, file, dataset, level, lens.

Ported from the data-layer half of mikro's ``tests/test_delete_guards.py`` (its scene and layer
cases have no subject here; ``tests/test_guards.py`` covers the interpretation layer).

mikro guards each delete with an ``owner=`` callable. This service has ONE predicate,
``core.guards.can_delete``, evaluated against the row's governing anchor (a level, a lens and an
anchor defer to their dataset): organization admins may delete anything; the assigner of the task
that created the row may; and its creator may -- unless the caller holds the ``bot`` role, in
which case ownership sits with the task's assigner and not with the bot account.

The default ``authenticated_context`` (static token "test") is an org admin, so the denial path
is exercised through ``bot_context``: a same-org user holding only the ``bot`` role.
``other_org_context`` never reaches the guard at all -- the org-scoped lookup fails first.
"""

import uuid

import pytest
from asgiref.sync import sync_to_async
from koherent.models import Task

from core import models
from datalayer.models import BigFileStore
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


DELETE_FOLDER = "mutation($id: ID!) { deleteFolder(input: {id: $id}) }"
DELETE_FILE = "mutation($id: ID!) { deleteFile(input: {id: $id}) }"
DELETE_ARRAY_DATASET = "mutation($id: ID!) { deleteArrayDataset(input: {id: $id}) }"
DELETE_DATA_ARRAY = "mutation($id: ID!) { deleteDataArray(input: {id: $id}) }"
DELETE_LENS = "mutation($id: ID!) { deleteLens(input: {id: $id}) }"


def _assign_creation_to(instance, assigner, organization) -> None:  # noqa: ANN001 - any provenance-tracked row
    """Say that ``instance`` was created under a task ``assigner`` assigned.

    What a verified provenance token leaves behind: a ``koherent.Task`` row naming the human at
    the root of the causal tree, and the row's creation history entry pointing at it. The guard
    reads exactly that entry (``core.guards._original_task_assigner``).
    """
    token = uuid.uuid4().hex
    task = Task.objects.create(task_id=token, root_task_id=token, assigner=assigner, assigner_sub=assigner.sub, caller_sub=assigner.sub, agent_sub="agent", agent_client_id="agent", issuer="static_issuer", token_id=token, args_hash="", args_hash_algorithm="", organization=organization)
    assert instance.provenance_entries.filter(history_type="+").update(task=task) == 1


# --- creator / assigner / admin guard on a self-anchored model (Folder) -------


async def test_creator_can_delete_own_folder(aexecute, authenticated_context):
    folder = await seed.create_folder(authenticated_context, "Mine")

    result = await aexecute(DELETE_FOLDER, {"id": str(folder.pk)})

    assert not result.errors, result.errors
    assert not await models.Folder.objects.filter(id=folder.pk).aexists()


async def test_non_owner_non_admin_cannot_delete_folder(aexecute, authenticated_context, bot_context):
    # Owned by the admin user (sub 1); the bot user (sub 2, same org) is neither
    # creator nor assigner nor admin.
    folder = await seed.create_folder(authenticated_context, "NotYours")

    denied = await aexecute(DELETE_FOLDER, {"id": str(folder.pk)}, context=bot_context)

    assert denied.errors, "a non-owner non-admin user could delete the folder"
    assert "You are not allowed to delete this Folder." in str(denied.errors[0])
    assert await models.Folder.objects.filter(id=folder.pk).aexists()

    # The creator can still delete it.
    allowed = await aexecute(DELETE_FOLDER, {"id": str(folder.pk)})
    assert not allowed.errors, allowed.errors
    assert not await models.Folder.objects.filter(id=folder.pk).aexists()


async def test_org_admin_can_delete_other_users_folder(aexecute, authenticated_context, bot_context):
    # Created by a second user (sub 2); deleted by the admin user (sub 1).
    folder = await seed.create_folder(bot_context, "BotsFolder")
    assert folder.creator_id != authenticated_context.request.user.id

    result = await aexecute(DELETE_FOLDER, {"id": str(folder.pk)})

    assert not result.errors, result.errors
    assert not await models.Folder.objects.filter(id=folder.pk).aexists()


async def test_a_bot_cannot_delete_even_the_folder_it_created(aexecute, bot_context):
    """Where this guard parts from mikro's: a bot account owns nothing, its task's assigner does."""
    created = await aexecute("mutation { createFolder(input: {name: \"BotMade\"}) { id creator { id } } }", context=bot_context)
    assert not created.errors, created.errors
    assert created.data["createFolder"]["creator"]["id"] == str(bot_context.request.user.pk)

    denied = await aexecute(DELETE_FOLDER, {"id": created.data["createFolder"]["id"]}, context=bot_context)
    assert denied.errors and "You are not allowed to delete this Folder." in str(denied.errors[0])
    assert await models.Folder.objects.filter(name="BotMade").aexists()


async def test_assignee_can_delete_folder(aexecute, authenticated_context, bot_context):
    # Creator is the admin user, but the bot user assigned the task that created it: the
    # assigner path lets the bot delete it.
    folder = await seed.create_folder(authenticated_context, "Assigned")
    await sync_to_async(_assign_creation_to)(folder, bot_context.request.user, bot_context.request.organization)

    result = await aexecute(DELETE_FOLDER, {"id": str(folder.pk)}, context=bot_context)

    assert not result.errors, result.errors
    assert not await models.Folder.objects.filter(id=folder.pk).aexists()


async def test_another_organization_never_reaches_the_guard(aexecute, authenticated_context, other_org_context):
    folder = await seed.create_folder(authenticated_context, "Mine")

    denied = await aexecute(DELETE_FOLDER, {"id": str(folder.pk)}, context=other_org_context)

    assert denied.errors
    assert "not allowed to delete" not in str(denied.errors[0]), "the org-scoped lookup fails first: a foreign row is not found, not forbidden"
    assert await models.Folder.objects.filter(id=folder.pk).aexists()


# --- File ---------------------------------------------------------------------


async def test_delete_file(aexecute, authenticated_context, bigfile_store):
    file = await seed.create_file(authenticated_context, "f.abf", store=await bigfile_store())

    result = await aexecute(DELETE_FILE, {"id": str(file.pk)})

    assert not result.errors, result.errors
    assert not await models.File.objects.filter(id=file.pk).aexists()


async def test_delete_file_denied_for_non_owner(aexecute, authenticated_context, bot_context, bigfile_store):
    store = await bigfile_store()
    file = await seed.create_file(authenticated_context, "f.abf", store=store)

    denied = await aexecute(DELETE_FILE, {"id": str(file.pk)}, context=bot_context)

    assert denied.errors, "a non-owner non-admin user could delete the file"
    assert "You are not allowed to delete this File." in str(denied.errors[0])
    assert await models.File.objects.filter(id=file.pk).aexists()
    assert (await BigFileStore.objects.aget(pk=store.pk)).orphaned_at is None, "a refused delete flags nothing"


# --- ArrayDataset, and the parts that defer to it -------------------------------


async def test_delete_array_dataset(aexecute, authenticated_context):
    array_dataset = await seed.create_array_dataset(authenticated_context, "ADS", shapes=[[1, 32, 32]])

    result = await aexecute(DELETE_ARRAY_DATASET, {"id": str(array_dataset.pk)})

    assert not result.errors, result.errors
    assert not await models.ArrayDataset.objects.filter(id=array_dataset.pk).aexists()
    assert not await models.CoordinateSystem.objects.filter(pk=array_dataset.coordinate_system_id).aexists(), "the grid nothing lives in any more is swept in the same request, which mikro leaves to an orphan sweep"


async def test_delete_array_dataset_denied_for_non_owner(aexecute, authenticated_context, bot_context):
    array_dataset = await seed.create_array_dataset(authenticated_context, "ADS", shapes=[[1, 32, 32]])

    denied = await aexecute(DELETE_ARRAY_DATASET, {"id": str(array_dataset.pk)}, context=bot_context)

    assert denied.errors, "a non-owner non-admin user could delete the array dataset"
    assert "You are not allowed to delete this ArrayDataset." in str(denied.errors[0])
    assert await models.ArrayDataset.objects.filter(id=array_dataset.pk).aexists()
    assert await models.CoordinateSystem.objects.filter(pk=array_dataset.coordinate_system_id).aexists()


async def test_delete_data_array(aexecute, authenticated_context):
    # Level 1, not 0: level 0 *is* the dataset, and `deleteDataArray` refuses it here
    # (`tests/array_dataset/test_array_dataset.py` pins that refusal).
    array_dataset = await seed.create_array_dataset(authenticated_context, "ADS", shapes=[[1, 32, 32], [1, 16, 16]])
    data_array = await models.DataArray.objects.aget(dataset=array_dataset, level=1)

    result = await aexecute(DELETE_DATA_ARRAY, {"id": str(data_array.pk)})

    assert not result.errors, result.errors
    assert not await models.DataArray.objects.filter(id=data_array.pk).aexists()
    assert not await models.CoordinateSystem.objects.filter(pk=data_array.coordinate_system_id).aexists(), "the level's own space goes with it"
    assert await models.CoordinateSystem.objects.filter(pk=array_dataset.coordinate_system_id).aexists(), "the dataset's grid has residents still"


async def test_delete_data_array_defers_to_its_dataset(aexecute, authenticated_context, bot_context):
    """A level carries no creator of its own: `ANCHOR_PATHS` sends the question to the dataset."""
    array_dataset = await seed.create_array_dataset(authenticated_context, "ADS", shapes=[[1, 32, 32], [1, 16, 16]])
    data_array = await models.DataArray.objects.aget(dataset=array_dataset, level=1)

    denied = await aexecute(DELETE_DATA_ARRAY, {"id": str(data_array.pk)}, context=bot_context)
    assert denied.errors and "You are not allowed to delete this DataArray." in str(denied.errors[0])
    assert await models.DataArray.objects.filter(id=data_array.pk).aexists()

    # The dataset's assigner may delete the dataset's level.
    await sync_to_async(_assign_creation_to)(array_dataset, bot_context.request.user, bot_context.request.organization)
    allowed = await aexecute(DELETE_DATA_ARRAY, {"id": str(data_array.pk)}, context=bot_context)
    assert not allowed.errors, allowed.errors
    assert not await models.DataArray.objects.filter(id=data_array.pk).aexists()


async def test_delete_lens(aexecute, authenticated_context):
    array_dataset = await seed.create_array_dataset(authenticated_context, "ADS", shapes=[[1, 32, 32]])
    lens = await seed.create_lens(authenticated_context, array_dataset)

    result = await aexecute(DELETE_LENS, {"id": str(lens.pk)})

    assert not result.errors, result.errors
    assert not await models.Lens.objects.filter(id=lens.pk).aexists()
    assert await models.CoordinateSystem.objects.filter(pk=array_dataset.coordinate_system_id).aexists(), "an unsliced lens shares its dataset's grid, which is the dataset's and stays"


async def test_delete_sliced_lens_takes_the_space_it_owned(aexecute, authenticated_context):
    array_dataset = await seed.create_array_dataset(authenticated_context, "ADS", shapes=[[3, 32, 32]])
    lens = await seed.create_lens(authenticated_context, array_dataset, slices=[{"axis": "c", "start": 1, "stop": 2}])
    assert lens.coordinate_system_id != array_dataset.coordinate_system_id

    result = await aexecute(DELETE_LENS, {"id": str(lens.pk)})

    assert not result.errors, result.errors
    assert not await models.CoordinateSystem.objects.filter(pk=lens.coordinate_system_id).aexists(), "a sliced lens' system is its own -- nothing else can live there -- so it goes with it"
    assert not await models.Transformation.objects.filter(input_id=lens.coordinate_system_id).aexists(), "and the derived edge with the system"
    assert await models.CoordinateSystem.objects.filter(pk=array_dataset.coordinate_system_id).aexists()


async def test_delete_lens_denied_for_non_owner(aexecute, authenticated_context, bot_context):
    array_dataset = await seed.create_array_dataset(authenticated_context, "ADS", shapes=[[1, 32, 32]])
    lens = await seed.create_lens(authenticated_context, array_dataset)

    denied = await aexecute(DELETE_LENS, {"id": str(lens.pk)}, context=bot_context)

    assert denied.errors and "You are not allowed to delete this Lens." in str(denied.errors[0])
    assert await models.Lens.objects.filter(id=lens.pk).aexists()
