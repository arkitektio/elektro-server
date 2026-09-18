"""Folder mutations executed against the schema.

mikro's folder: createFolder / ensureFolder / updateFolder / deleteFolder / pinFolder and the
put/release filing mutations. Filing is organisational only -- it says where a user keeps a
thing, never where the data sits -- and deleting a folder *unfiles* what was in it
(``SET_NULL``), where this service's old ``Dataset`` cascaded and took every file with it.
"""

import pytest
from asgiref.sync import sync_to_async

from core.models import ArrayDataset, File, Folder, SparseDataset, TableDataset
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_FOLDER = "mutation ($input: CreateFolderInput!) { createFolder(input: $input) { id name parent { id } } }"
ENSURE_FOLDER = "mutation ($input: CreateFolderInput!) { ensureFolder(input: $input) { id name } }"
UPDATE_FOLDER = "mutation ($input: ChangeFolderInput!) { updateFolder(input: $input) { id name } }"
DELETE_FOLDER = "mutation ($input: DeleteFolderInput!) { deleteFolder(input: $input) }"
PIN_FOLDER = "mutation ($input: PinFolderInput!) { pinFolder(input: $input) { id pinned } }"
PUT_FOLDERS = "mutation ($input: AssociateInput!) { putFoldersInFolder(input: $input) { id } }"
RELEASE_FOLDERS = "mutation ($input: DesociateInput!) { releaseFoldersFromFolder(input: $input) { id } }"
PUT_FILES = "mutation ($input: AssociateInput!) { putFilesInFolder(input: $input) { id } }"
RELEASE_FILES = "mutation ($input: DesociateInput!) { releaseFilesFromFolder(input: $input) { id } }"
PUT_DATASETS = "mutation ($input: AssociateInput!) { putArrayDatasetsInFolder(input: $input) { id } }"
RELEASE_DATASETS = "mutation ($input: DesociateInput!) { releaseArrayDatasetsFromFolder(input: $input) { id } }"
PUT_TABLES = "mutation ($input: AssociateInput!) { putTableDatasetsInFolder(input: $input) { id } }"
PUT_SPARSE = "mutation ($input: AssociateInput!) { putSparseDatasetsInFolder(input: $input) { id } }"

CHILDREN = """
query ($parent: ID!, $filters: FolderChildrenFilter, $order: ChildrenOrder) {
  children(parent: $parent, filters: $filters, order: $order) {
    __typename
    ... on Folder { name }
    ... on File { name }
    ... on ArrayDataset { name }
    ... on TableDataset { name }
    ... on SparseDataset { name }
    ... on AnnotationCollection { name }
  }
}
"""


async def _make_folder(ctx, name="F", **kwargs) -> Folder:
    return await Folder.objects.acreate(name=name, creator=ctx.request.user, organization=ctx.request.organization, membership=ctx.request.membership, **kwargs)


async def _make_file(ctx, store, folder=None) -> File:
    return await File.objects.acreate(name="f", store=store, folder=folder, creator=ctx.request.user, organization=ctx.request.organization, membership=ctx.request.membership)


# --- happy path --------------------------------------------------------------


async def test_create_folder(aexecute, authenticated_context):
    parent = await _make_folder(authenticated_context, "Parent")
    res = await aexecute(CREATE_FOLDER, {"input": {"name": "My Folder", "parent": str(parent.id)}})
    assert not res.errors, res.errors
    assert res.data["createFolder"] == {"id": res.data["createFolder"]["id"], "name": "My Folder", "parent": {"id": str(parent.id)}}
    assert await Folder.objects.filter(name="My Folder", parent=parent).aexists()


async def test_ensure_folder_is_idempotent(aexecute):
    first = await aexecute(ENSURE_FOLDER, {"input": {"name": "Imports"}})
    second = await aexecute(ENSURE_FOLDER, {"input": {"name": "Imports"}})
    assert not first.errors and not second.errors, (first.errors, second.errors)
    assert first.data["ensureFolder"]["id"] == second.data["ensureFolder"]["id"]
    assert await Folder.objects.filter(name="Imports").acount() == 1


async def test_update_folder(aexecute, authenticated_context):
    folder = await _make_folder(authenticated_context, "Before")
    res = await aexecute(UPDATE_FOLDER, {"input": {"id": str(folder.id), "name": "After"}})
    assert not res.errors, res.errors
    assert res.data["updateFolder"]["name"] == "After"
    await folder.arefresh_from_db()
    assert folder.name == "After"


async def test_pin_folder(aexecute, authenticated_context):
    folder = await _make_folder(authenticated_context, "Pinnable")
    res = await aexecute(PIN_FOLDER, {"input": {"id": str(folder.id), "pin": True}})
    assert not res.errors, res.errors
    assert res.data["pinFolder"]["pinned"] is True
    assert await folder.pinned_by.filter(id=authenticated_context.request.user.id).aexists()

    res = await aexecute(PIN_FOLDER, {"input": {"id": str(folder.id), "pin": False}})
    assert res.data["pinFolder"]["pinned"] is False


async def test_folders_nest(aexecute, authenticated_context):
    parent, child = await _make_folder(authenticated_context, "Parent"), await _make_folder(authenticated_context, "Child")
    res = await aexecute(PUT_FOLDERS, {"input": {"selfs": [str(child.id)], "other": str(parent.id)}})
    assert not res.errors, res.errors
    await child.arefresh_from_db()
    assert child.parent_id == parent.id

    res = await aexecute(RELEASE_FOLDERS, {"input": {"selfs": [str(child.id)], "other": str(parent.id)}})
    assert not res.errors, res.errors
    await child.arefresh_from_db()
    assert child.parent_id is None


async def test_files_are_filed_and_unfiled(aexecute, authenticated_context, bigfile_store):
    folder = await _make_folder(authenticated_context, "Container")
    file = await _make_file(authenticated_context, await bigfile_store())

    res = await aexecute(PUT_FILES, {"input": {"selfs": [str(file.id)], "other": str(folder.id)}})
    assert not res.errors, res.errors
    await file.arefresh_from_db()
    assert file.folder_id == folder.id

    res = await aexecute(RELEASE_FILES, {"input": {"selfs": [str(file.id)], "other": str(folder.id)}})
    assert not res.errors, res.errors
    assert res.data["releaseFilesFromFolder"]["id"] == str(folder.id)
    await file.arefresh_from_db()
    assert file.folder_id is None


async def test_array_datasets_are_filed_and_unfiled(aexecute, authenticated_context, make_dataset):
    folder = await _make_folder(authenticated_context, "Container")
    dataset = await make_dataset()
    res = await aexecute(PUT_DATASETS, {"input": {"selfs": [str(dataset.id)], "other": str(folder.id)}})
    assert not res.errors, res.errors
    assert res.data["putArrayDatasetsInFolder"]["id"] == str(folder.id)
    await dataset.arefresh_from_db()
    assert dataset.folder_id == folder.id

    res = await aexecute(RELEASE_DATASETS, {"input": {"selfs": [str(dataset.id)], "other": str(folder.id)}})
    assert not res.errors, res.errors
    await dataset.arefresh_from_db()
    assert dataset.folder_id is None


async def test_a_derived_dataset_follows_its_parent_and_cannot_be_filed_alone(aexecute, authenticated_context, create_array_dataset):
    """mikro's rule: only root data is filed explicitly, and re-filing a parent moves everything derived from it."""
    archive = await _make_folder(authenticated_context, "Archive")
    raw = await create_array_dataset("raw", [8000])
    derived = await create_array_dataset("filtered", [8000], derived_from=[{"kind": "DATASET", "dataset": raw["id"], "transform": {"kind": "IDENTITY"}}])

    alone = await aexecute(PUT_DATASETS, {"input": {"selfs": [derived["id"]], "other": str(archive.id)}})
    assert alone.errors and "cannot be filed on its own" in str(alone.errors[0])

    moved = await aexecute(PUT_DATASETS, {"input": {"selfs": [raw["id"]], "other": str(archive.id)}})
    assert not moved.errors, moved.errors
    folders = await sync_to_async(lambda: set(ArrayDataset.objects.filter(pk__in=[raw["id"], derived["id"]]).values_list("folder_id", flat=True)))()
    assert folders == {archive.id}, "the derived dataset moved with its parent"

    named = await create_array_dataset("again", [8000], derived_from=[{"kind": "DATASET", "dataset": raw["id"], "transform": {"kind": "IDENTITY"}}], folder=archive.id, raw=True)
    assert named.errors and "cannot be filed on its own" in str(named.errors[0]), "refused rather than silently ignored"


async def test_tables_and_rasters_are_filed_like_datasets(aexecute, authenticated_context):
    """A table (events, units) and a sparse dataset (a spike raster) are filed exactly as an array dataset is."""
    folder = await _make_folder(authenticated_context, "Sorting")
    table = await seed.create_table_dataset(authenticated_context, "units")
    raster = await seed.create_sparse_dataset(authenticated_context, "spikes")

    res = await aexecute(PUT_TABLES, {"input": {"selfs": [str(table.pk)], "other": str(folder.id)}})
    assert not res.errors, res.errors
    res = await aexecute(PUT_SPARSE, {"input": {"selfs": [str(raster.pk)], "other": str(folder.id)}})
    assert not res.errors, res.errors
    assert (await TableDataset.objects.aget(pk=table.pk)).folder_id == folder.id
    assert (await SparseDataset.objects.aget(pk=raster.pk)).folder_id == folder.id


async def test_children_lists_everything_filed_in_a_folder(aexecute, authenticated_context, make_dataset, bigfile_store):
    folder = await _make_folder(authenticated_context, "Everything")
    await _make_folder(authenticated_context, "sub", parent=folder)
    await _make_file(authenticated_context, await bigfile_store(), folder=folder)
    await make_dataset(name="recording", folder=folder)
    await seed.create_table_dataset(authenticated_context, "events", folder=folder)
    await seed.create_sparse_dataset(authenticated_context, "spikes", folder=folder)

    res = await aexecute(CHILDREN, {"parent": str(folder.id)})
    assert not res.errors, res.errors
    assert [(child["__typename"], child["name"]) for child in res.data["children"]] == [
        ("Folder", "sub"),
        ("File", "f"),
        ("ArrayDataset", "recording"),
        ("TableDataset", "events"),
        ("SparseDataset", "spikes"),
    ]

    searched = await aexecute(CHILDREN, {"parent": str(folder.id), "filters": {"search": "recording"}})
    assert [child["name"] for child in searched.data["children"]] == ["recording"]


async def test_deleting_a_folder_unfiles_what_was_in_it(aexecute, authenticated_context, make_dataset, bigfile_store):
    """`SET_NULL`, not `CASCADE`: this service's old `Dataset` took every file and trace in it along."""
    folder = await _make_folder(authenticated_context, "Doomed")
    file = await _make_file(authenticated_context, await bigfile_store(), folder=folder)
    dataset = await make_dataset(folder=folder)

    res = await aexecute(DELETE_FOLDER, {"input": {"id": str(folder.id)}})
    assert not res.errors, res.errors
    assert res.data["deleteFolder"] == str(folder.id)
    assert not await Folder.objects.filter(id=folder.id).aexists()
    await file.arefresh_from_db()
    await dataset.arefresh_from_db()
    assert (file.folder_id, dataset.folder_id) == (None, None)


# --- negatives ---------------------------------------------------------------


async def test_delete_folder_not_found(aexecute):
    res = await aexecute(DELETE_FOLDER, {"input": {"id": "999999"}})
    assert res.errors


async def test_create_folder_missing_required_name(aexecute):
    res = await aexecute(CREATE_FOLDER, {"input": {}})
    assert res.errors


async def test_another_organization_cannot_file_into_or_delete_this_folder(aexecute, authenticated_context, other_org_context, make_dataset):
    folder = await _make_folder(authenticated_context, "Mine")
    theirs = await make_dataset(context=other_org_context, name="theirs")

    filed = await aexecute(PUT_DATASETS, {"input": {"selfs": [str(theirs.id)], "other": str(folder.id)}}, context=other_org_context)
    assert filed.errors
    deleted = await aexecute(DELETE_FOLDER, {"input": {"id": str(folder.id)}}, context=other_org_context)
    assert deleted.errors
    assert await Folder.objects.filter(id=folder.id).aexists()
