"""Trace (a.k.a. Image) mutations executed against the schema:
updateImage, deleteImage, and fromTraceLike (store-backed via MinIO)."""

import pytest

from core.models import Trace

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


UPDATE_IMAGE = """
mutation ($input: UpdateTraceInput!) {
  updateImage(input: $input) { id name }
}
"""

DELETE_IMAGE = """
mutation ($input: DeleteTraceInput!) {
  deleteImage(input: $input)
}
"""

FROM_TRACE_LIKE = """
mutation ($input: FromTraceLikeInput!) {
  fromTraceLike(input: $input) { id name }
}
"""


async def test_update_image(aexecute, make_trace):
    trace = await make_trace(name="old")
    res = await aexecute(
        UPDATE_IMAGE, {"input": {"id": str(trace.id), "name": "new", "tags": ["a", "b"]}}
    )
    assert not res.errors, res.errors
    assert res.data["updateImage"]["name"] == "new"
    await trace.arefresh_from_db()
    assert trace.name == "new"


async def test_delete_image(aexecute, make_trace):
    trace = await make_trace()
    res = await aexecute(DELETE_IMAGE, {"input": {"id": str(trace.id)}})
    assert not res.errors, res.errors
    assert res.data["deleteImage"] == str(trace.id)
    assert not await Trace.objects.filter(id=trace.id).aexists()


async def test_from_trace_like(aexecute, authenticated_context, zarr_store):
    from core.models import Dataset

    # Pass an explicit dataset: the default-dataset fallback (get_trace_dataset)
    # omits membership and trips a NOT NULL constraint (separate resolver bug).
    ds = await Dataset.objects.acreate(
        name="ds",
        creator=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
        membership=authenticated_context.request.membership,
    )
    store = await zarr_store()  # row + seeded zarr.json in MinIO
    res = await aexecute(
        FROM_TRACE_LIKE,
        {"input": {"array": str(store.id), "name": "from-array", "dataset": str(ds.id)}},
    )
    assert not res.errors, res.errors
    assert res.data["fromTraceLike"]["name"] == "from-array"
    assert await Trace.objects.filter(name="from-array").aexists()


# --- negatives ---------------------------------------------------------------


async def test_delete_image_not_found(aexecute):
    res = await aexecute(DELETE_IMAGE, {"input": {"id": "999999"}})
    assert res.errors


async def test_from_trace_like_missing_zarr_metadata(aexecute, zarr_store):
    store = await zarr_store(seed=False)  # no zarr.json -> fill_info raises FileNotFoundError
    res = await aexecute(FROM_TRACE_LIKE, {"input": {"array": str(store.id), "name": "broken"}})
    assert res.errors
