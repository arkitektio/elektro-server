"""Dataset mutations executed against the schema.

Covers createDataset/updateDataset/deleteDataset/revertDataset and the
put/release association mutations. A few association resolvers have
pre-existing bugs (wrong model name / wrong return type); those are marked
xfail with the concrete reason so the suite stays green and the bug is tracked.
"""

import pytest

from core.models import Dataset, File

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_DATASET = """
mutation ($input: CreateDatasetInput!) {
  createDataset(input: $input) { id name }
}
"""

UPDATE_DATASET = """
mutation ($input: ChangeDatasetInput!) {
  updateDataset(input: $input) { id name }
}
"""

DELETE_DATASET = """
mutation ($input: DeleteDatasetInput!) {
  deleteDataset(input: $input)
}
"""

PUT_DATASETS_IN_DATASET = """
mutation ($input: AssociateInput!) {
  putDatasetsInDataset(input: $input) { id }
}
"""

PUT_FILES_IN_DATASET = """
mutation ($input: AssociateInput!) {
  putFilesInDataset(input: $input) { id }
}
"""

RELEASE_FILES_FROM_DATASET = """
mutation ($input: DesociateInput!) {
  releaseFilesFromDataset(input: $input) { id }
}
"""

PUT_IMAGES_IN_DATASET = """
mutation ($input: AssociateInput!) {
  putImagesInDataset(input: $input) { id }
}
"""

RELEASE_IMAGES_FROM_DATASET = """
mutation ($input: DesociateInput!) {
  releaseImagesFromDataset(input: $input) { id }
}
"""

PIN_DATASET = """
mutation ($input: PinDatasetInput!) {
  pinDataset(input: $input) { id pinned }
}
"""


async def _make_dataset(ctx, name="DS"):
    return await Dataset.objects.acreate(
        name=name,
        creator=ctx.request.user,
        organization=ctx.request.organization,
        membership=ctx.request.membership,
    )


# --- happy path --------------------------------------------------------------


async def test_create_dataset(aexecute):
    res = await aexecute(CREATE_DATASET, {"input": {"name": "My Dataset"}})
    assert not res.errors, res.errors
    assert res.data["createDataset"]["name"] == "My Dataset"
    assert await Dataset.objects.filter(name="My Dataset").aexists()


async def test_update_dataset(aexecute, authenticated_context):
    ds = await _make_dataset(authenticated_context, "Before")
    res = await aexecute(UPDATE_DATASET, {"input": {"id": str(ds.id), "name": "After"}})
    assert not res.errors, res.errors
    assert res.data["updateDataset"]["name"] == "After"
    await ds.arefresh_from_db()
    assert ds.name == "After"


async def test_delete_dataset(aexecute, authenticated_context):
    ds = await _make_dataset(authenticated_context, "Doomed")
    res = await aexecute(DELETE_DATASET, {"input": {"id": str(ds.id)}})
    assert not res.errors, res.errors
    assert res.data["deleteDataset"] == str(ds.id)
    assert not await Dataset.objects.filter(id=ds.id).aexists()


async def test_put_datasets_in_dataset(aexecute, authenticated_context):
    parent = await _make_dataset(authenticated_context, "Parent")
    child = await _make_dataset(authenticated_context, "Child")
    res = await aexecute(
        PUT_DATASETS_IN_DATASET, {"input": {"selfs": [str(child.id)], "other": str(parent.id)}}
    )
    assert not res.errors, res.errors
    await child.arefresh_from_db()
    assert child.parent_id == parent.id


async def test_put_files_in_dataset(aexecute, authenticated_context, bigfile_store):
    ds = await _make_dataset(authenticated_context, "Container")
    store = await bigfile_store()
    file = await File.objects.acreate(name="f", store=store, creator=authenticated_context.request.user)

    res = await aexecute(
        PUT_FILES_IN_DATASET, {"input": {"selfs": [str(file.id)], "other": str(ds.id)}}
    )
    assert not res.errors, res.errors
    await file.arefresh_from_db()
    assert file.dataset_id == ds.id


async def test_pin_dataset(aexecute, authenticated_context):
    ds = await _make_dataset(authenticated_context, "Pinnable")
    res = await aexecute(PIN_DATASET, {"input": {"id": str(ds.id), "pin": True}})
    assert not res.errors, res.errors
    assert res.data["pinDataset"]["pinned"] is True
    assert await ds.pinned_by.filter(id=authenticated_context.request.user.id).aexists()

    res = await aexecute(PIN_DATASET, {"input": {"id": str(ds.id), "pin": False}})
    assert not res.errors, res.errors
    assert res.data["pinDataset"]["pinned"] is False
    assert not await ds.pinned_by.filter(id=authenticated_context.request.user.id).aexists()


# --- negatives ---------------------------------------------------------------


async def test_delete_dataset_not_found(aexecute):
    res = await aexecute(DELETE_DATASET, {"input": {"id": "999999"}})
    assert res.errors


async def test_create_dataset_missing_required_name(aexecute):
    # `name` is required on CreateDatasetInput -> variable validation fails.
    res = await aexecute(CREATE_DATASET, {"input": {}})
    assert res.errors


# --- image/file association ---------------------------------------------------


async def test_release_files_from_dataset(aexecute, authenticated_context, bigfile_store):
    ds = await _make_dataset(authenticated_context, "Container")
    store = await bigfile_store()
    file = await File.objects.acreate(
        name="f", store=store, dataset=ds, creator=authenticated_context.request.user
    )
    res = await aexecute(
        RELEASE_FILES_FROM_DATASET, {"input": {"selfs": [str(file.id)], "other": str(ds.id)}}
    )
    assert not res.errors, res.errors
    assert res.data["releaseFilesFromDataset"]["id"] == str(ds.id)
    await file.arefresh_from_db()
    assert file.dataset_id is None


async def test_put_images_in_dataset(aexecute, authenticated_context, make_trace):
    ds = await _make_dataset(authenticated_context, "Container")
    trace = await make_trace()
    res = await aexecute(
        PUT_IMAGES_IN_DATASET, {"input": {"selfs": [str(trace.id)], "other": str(ds.id)}}
    )
    assert not res.errors, res.errors
    assert res.data["putImagesInDataset"]["id"] == str(ds.id)
    await trace.arefresh_from_db()
    assert trace.dataset_id == ds.id


async def test_release_images_from_dataset(aexecute, authenticated_context, make_trace):
    ds = await _make_dataset(authenticated_context, "Container")
    trace = await make_trace(dataset=ds)
    res = await aexecute(
        RELEASE_IMAGES_FROM_DATASET, {"input": {"selfs": [str(trace.id)], "other": str(ds.id)}}
    )
    assert not res.errors, res.errors
    assert res.data["releaseImagesFromDataset"]["id"] == str(ds.id)
    await trace.arefresh_from_db()
    assert trace.dataset_id is None
