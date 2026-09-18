"""Filter tests for the files query (FileFilter).

Ported from the file half of mikro's ``tests/test_filters_file_table.py`` (there is no table
dataset here). The link, store, extension and mime-group filters are in ``test_file_links.py``.
"""

import pytest

from core.enums import FileLinkDirectionChoices
from core.models import ArrayDataset, FileLink
from tests.seed import create_file, create_folder

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

FILE_QUERY = """
    query List($filters: FileFilter) {
        files(filters: $filters) { id name }
    }
"""


async def file_names(aexecute, filters, context=None):  # noqa: ANN001, ANN201
    result = await aexecute(FILE_QUERY, {"filters": filters}, context=context)
    assert not result.errors, result.errors
    return {f["name"] for f in result.data["files"]}


async def test_file_filter_by_folder(aexecute, authenticated_context):
    ds_a = await create_folder(authenticated_context, "A")
    ds_b = await create_folder(authenticated_context, "B")
    await create_file(authenticated_context, "InA", ds_a)
    await create_file(authenticated_context, "InB", ds_b)
    await create_file(authenticated_context, "Unfiled")

    assert await file_names(aexecute, {"folder": str(ds_a.id)}) == {"InA"}
    assert await file_names(aexecute, {"folders": [str(ds_a.id), str(ds_b.id)]}) == {"InA", "InB"}


async def test_file_filter_by_size_and_content_type(aexecute, authenticated_context):
    ds = await create_folder(authenticated_context, "DS")
    await create_file(authenticated_context, "Small", ds, size=100, content_type="text/csv")
    await create_file(authenticated_context, "Big", ds, size=10_000, content_type="application/x-hdf5")

    assert await file_names(aexecute, {"size": {"gte": 1000}}) == {"Big"}
    assert await file_names(aexecute, {"contentType": {"exact": "text/csv"}}) == {"Small"}


async def test_file_filter_by_not_derived(aexecute, authenticated_context):
    """`notDerived` separates the files a converter read from the files written out of data here.

    In mikro it used to read the `File.origins` M2M, which no resolver ever wrote -- so it
    answered `true` for every file and `false` for none. It reads the file's links, which the
    mutations actually write.
    """
    ctx = authenticated_context
    ds = await create_folder(ctx, "DS")
    await create_file(ctx, "Original", ds)
    exported = await create_file(ctx, "Derived", ds)

    dataset = await ArrayDataset.objects.acreate(name="Source data", creator=ctx.request.user, organization=ctx.request.organization)
    await FileLink.objects.acreate(
        file=exported,
        dataset=dataset,
        direction=FileLinkDirectionChoices.RENDITION.value,
        creator=ctx.request.user,
        organization=ctx.request.organization,
    )

    assert await file_names(aexecute, {"notDerived": True}) == {"Original"}
    assert await file_names(aexecute, {"notDerived": False}) == {"Derived"}


async def test_file_filter_by_search(aexecute, authenticated_context):
    ds = await create_folder(authenticated_context, "DS")
    await create_file(authenticated_context, "measurements.csv", ds)
    await create_file(authenticated_context, "raw.abf", ds)

    assert await file_names(aexecute, {"search": "MEASURE"}) == {"measurements.csv"}


async def test_an_explicit_null_is_no_constraint(aexecute, authenticated_context):
    """`USE_DEPRECATED_FILTERS`: strawberry-django hands a resolver the explicit `null` a client sent, and every one of these must read it as "not asked"."""
    ctx = authenticated_context
    ds = await create_folder(ctx, "DS")
    await create_file(ctx, "a.abf", ds, size=1)
    await create_file(ctx, "b.csv")

    nothing_asked = {
        "folder": None,
        "folders": None,
        "search": None,
        "notDerived": None,
        "unlinked": None,
        "sourceOf": None,
        "exportedFrom": None,
        "linkedTo": None,
        "seriesIdentifier": None,
        "hasStore": None,
        "populated": None,
        "extension": None,
        "mimeGroup": None,
    }
    assert await file_names(aexecute, nothing_asked) == {"a.abf", "b.csv"}
    for field in nothing_asked:
        assert await file_names(aexecute, {field: None}) == {"a.abf", "b.csv"}, field
    assert await file_names(aexecute, {"extension": "  "}) == {"a.abf", "b.csv"}, "a blank extension asks for nothing either"


async def test_files_are_listed_per_organization(aexecute, authenticated_context, other_org_context):
    """Every list here is organization-scoped, whatever the filter says."""
    mine = await create_folder(authenticated_context, "Mine")
    await create_file(authenticated_context, "mine.abf", mine)
    await create_file(other_org_context, "theirs.abf", await create_folder(other_org_context, "Theirs"))

    assert await file_names(aexecute, {}) == {"mine.abf"}
    assert await file_names(aexecute, {"search": "abf"}, context=other_org_context) == {"theirs.abf"}
    assert await file_names(aexecute, {"folder": str(mine.id)}, context=other_org_context) == set(), "naming another organization's folder finds nothing in it"
