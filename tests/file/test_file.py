"""File mutations executed against the schema: fromFileLike (BigFileStore-backed,
local fill_info) and deleteFile."""

import uuid

import pytest
from asgiref.sync import sync_to_async

from core.models import File, FileView

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


FROM_FILE_LIKE = """
mutation ($input: FromFileLike!) {
  fromFileLike(input: $input) { id name }
}
"""

DELETE_FILE = """
mutation ($input: DeleteFileInput!) {
  deleteFile(input: $input)
}
"""


async def test_from_file_like(aexecute, bigfile_store):
    store = await bigfile_store()
    res = await aexecute(FROM_FILE_LIKE, {"input": {"name": "f.dat", "file": str(store.id)}})
    assert not res.errors, res.errors
    assert res.data["fromFileLike"]["name"] == "f.dat"
    assert await File.objects.filter(name="f.dat").aexists()


async def test_delete_file(aexecute, authenticated_context, bigfile_store):
    store = await bigfile_store()
    file = await File.objects.acreate(name="del", store=store, creator=authenticated_context.request.user)
    res = await aexecute(DELETE_FILE, {"input": {"id": str(file.id)}})
    assert not res.errors, res.errors
    assert res.data["deleteFile"] == str(file.id)
    assert not await File.objects.filter(id=file.id).aexists()


# --- negatives ---------------------------------------------------------------


async def test_delete_file_not_found(aexecute):
    res = await aexecute(DELETE_FILE, {"input": {"id": "999999"}})
    assert res.errors


async def test_from_file_like_unknown_store(aexecute):
    res = await aexecute(FROM_FILE_LIKE, {"input": {"name": "x", "file": "999999"}})
    assert res.errors


# --- parity: enriched fields + default-dataset fallback ----------------------

FROM_FILE_LIKE_RICH = """
mutation ($input: FromFileLike!) {
  fromFileLike(input: $input) { id name contentType size views { id } }
}
"""


async def test_from_file_like_populates_metadata_and_default_dataset(aexecute, authenticated_context):
    """fromFileLike derives the name/content_type from the store and, when no
    dataset is given, drops the file into the user's default dataset."""
    from datalayer.models import BigFileStore

    @sync_to_async
    def _store():
        return BigFileStore.objects.create(
            organization=authenticated_context.request.organization,
            key=uuid.uuid4().hex,
            bucket="media",
            original_file_name="vendor.czi",
            content_type="application/octet-stream",
        )

    store = await _store()
    res = await aexecute(FROM_FILE_LIKE_RICH, {"input": {"name": "ignored", "file": str(store.id)}})
    assert not res.errors, res.errors
    data = res.data["fromFileLike"]
    # name comes from the store's original_file_name, not the input
    assert data["name"] == "vendor.czi"
    assert data["contentType"] == "application/octet-stream"

    file = await File.objects.aget(id=data["id"])
    # fell back to a (default) dataset instead of leaving it dangling
    assert file.dataset_id is not None
    assert file.membership_id == authenticated_context.request.membership.id


# --- FileView ----------------------------------------------------------------

CREATE_FILE_VIEW = """
mutation ($input: CreateFileViewInput!) {
  createFileView(input: $input) {
    id seriesIdentifier trace { id } file { id }
  }
}
"""

DELETE_FILE_VIEW = """
mutation ($input: DeleteInput!) {
  deleteFileView(input: $input)
}
"""


async def test_create_and_delete_file_view(aexecute, authenticated_context, bigfile_store, make_trace):
    store = await bigfile_store()
    file = await File.objects.acreate(name="f", store=store, creator=authenticated_context.request.user)
    trace = await make_trace()

    res = await aexecute(
        CREATE_FILE_VIEW,
        {"input": {"file": str(file.id), "trace": str(trace.id), "seriesIdentifier": "series-0"}},
    )
    assert not res.errors, res.errors
    view = res.data["createFileView"]
    assert view["seriesIdentifier"] == "series-0"
    assert view["trace"]["id"] == str(trace.id)
    assert view["file"]["id"] == str(file.id)
    # reachable as a view on the file
    assert await FileView.objects.filter(file=file, trace=trace).aexists()

    res = await aexecute(DELETE_FILE_VIEW, {"input": {"id": view["id"]}})
    assert not res.errors, res.errors
    assert not await FileView.objects.filter(id=view["id"]).aexists()
