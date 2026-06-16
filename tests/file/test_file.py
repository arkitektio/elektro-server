"""File mutations executed against the schema: fromFileLike (BigFileStore-backed,
local fill_info) and deleteFile."""

import pytest

from core.models import File

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
