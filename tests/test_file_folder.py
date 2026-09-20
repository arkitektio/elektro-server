"""``File.folder``: where a file is filed, null once its folder is gone."""

import pytest
from kante.context import HttpContext

from core.models import Folder
from tests.seed import create_file, create_folder

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

QUERY = """
    query ($filters: FileFilter) {
        files(filters: $filters) { name folder { id name } }
    }
"""


async def test_file_exposes_its_folder(aexecute, authenticated_context: HttpContext) -> None:
    folder = await create_folder(authenticated_context, "Recordings")
    await create_file(authenticated_context, "cell01.abf", folder)

    result = await aexecute(QUERY, {"filters": {}})
    assert not result.errors, result.errors
    assert result.data["files"] == [{"name": "cell01.abf", "folder": {"id": str(folder.pk), "name": "Recordings"}}]


async def test_deleting_the_folder_unfiles_the_file(aexecute, authenticated_context: HttpContext) -> None:
    folder = await create_folder(authenticated_context, "Recordings")
    await create_file(authenticated_context, "cell01.abf", folder)
    await Folder.objects.filter(pk=folder.pk).adelete()

    result = await aexecute(QUERY, {"filters": {}})
    assert not result.errors, result.errors
    assert result.data["files"] == [{"name": "cell01.abf", "folder": None}]
