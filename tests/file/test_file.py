"""File mutations executed against the schema: fromFileLike, deleteFile, linkFile and unlinkFile.

mikro's file layer. A file is a store, not a container: it has no coordinate system, so a
link between a file and the data it encodes relates *bytes* to data and is deliberately not
a derivation edge. One row says it from either end -- ``sourceFiles`` on
``createArrayDataset`` (an ingest), ``exportOf`` on ``fromFileLike`` (an export), and
``linkFile`` for either after the fact.
"""

import pytest
from asgiref.sync import sync_to_async

from core.models import File, FileLink
from datalayer.models import BigFileStore

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


FROM_FILE_LIKE = """
mutation ($input: FromFileLike!) {
  fromFileLike(input: $input) {
    id
    name
    contentType
    size
    folder { name }
    exportedFrom { direction seriesIdentifier valueRelation container { __typename ... on ArrayDataset { id } } }
    derivedContainers { id }
  }
}
"""

DELETE_FILE = "mutation ($input: DeleteFileInput!) { deleteFile(input: $input) }"

LINK_FILE = """
mutation ($input: LinkFileInput!) {
  linkFile(input: $input) { id direction seriesIdentifier valueRelation file { id } container { __typename ... on ArrayDataset { id } } }
}
"""

UNLINK_FILE = "mutation ($input: UnlinkFileInput!) { unlinkFile(input: $input) }"

SOURCE_FILES = "query ($id: ID!) { arrayDataset(id: $id) { sourceFiles { seriesIdentifier file { name } } exports { file { name } } } }"


async def _make_file(ctx, store, name="f.abf") -> File:
    return await File.objects.acreate(name=name, store=store, creator=ctx.request.user, organization=ctx.request.organization, membership=ctx.request.membership)


async def test_from_file_like_names_sizes_and_files_the_file(aexecute, bigfile_store, authenticated_context):
    store = await bigfile_store(content=b"0123456789", original_file_name="upload.bin", content_type="application/octet-stream")
    res = await aexecute(FROM_FILE_LIKE, {"input": {"fileName": "cell3.abf", "file": str(store.id)}})
    assert not res.errors, res.errors
    data = res.data["fromFileLike"]

    assert data["name"] == "cell3.abf", "the supplied name, not whatever the upload grant recorded"
    assert (data["contentType"], data["size"]) == ("application/octet-stream", 10.0)
    assert data["folder"]["name"] == "Default", "with no folder named, the file is filed in the user's default"
    assert data["exportedFrom"] == [] and data["derivedContainers"] == []

    file = await File.objects.aget(id=data["id"])
    assert file.membership_id == authenticated_context.request.membership.id


async def test_a_file_written_from_a_dataset_says_so(aexecute, bigfile_store, create_array_dataset):
    dataset = await create_array_dataset("recording", [1000])
    store = await bigfile_store()
    export = [{"kind": "DATASET", "dataset": dataset["id"], "valueRelation": "IDENTICAL"}]
    res = await aexecute(FROM_FILE_LIKE, {"input": {"fileName": "recording.nwb", "file": str(store.id), "exportOf": export}})
    assert not res.errors, res.errors
    (link,) = res.data["fromFileLike"]["exportedFrom"]
    assert link == {"direction": "RENDITION", "seriesIdentifier": "", "valueRelation": "IDENTICAL", "container": {"__typename": "ArrayDataset", "id": dataset["id"]}}

    seen = await aexecute(SOURCE_FILES, {"id": dataset["id"]})
    assert seen.data["arrayDataset"] == {"sourceFiles": [], "exports": [{"file": {"name": "recording.nwb"}}]}


async def test_a_dataset_converted_from_a_file_says_so_per_series(aexecute, authenticated_context, bigfile_store, zarr_store):
    file = await _make_file(authenticated_context, await bigfile_store(), "session.nwb")
    store = await zarr_store(shape=[100], dimension_names=["t"])
    payload = {"data": str(store.pk), "scales": [], "name": "sweep 3", "axes": [{"name": "t", "type": "TIME"}], "sourceFiles": [{"file": str(file.id), "seriesIdentifier": "sweep-3"}]}
    created = await aexecute("mutation ($input: CreateArrayDatasetInput!) { createArrayDataset(input: $input) { id sourceFiles { seriesIdentifier direction file { name } } } }", {"input": payload})
    assert not created.errors, created.errors
    assert created.data["createArrayDataset"]["sourceFiles"] == [{"seriesIdentifier": "sweep-3", "direction": "SOURCE", "file": {"name": "session.nwb"}}]

    # Not a derivation: a file has no space, so the graph is untouched.
    lineage = await aexecute("query ($id: ID!) { arrayDataset(id: $id) { derivedFrom { id } } }", {"id": created.data["createArrayDataset"]["id"]})
    assert lineage.data["arrayDataset"]["derivedFrom"] == []


async def test_link_file_records_a_link_after_the_fact_and_refuses_a_duplicate(aexecute, authenticated_context, bigfile_store, make_dataset):
    file = await _make_file(authenticated_context, await bigfile_store())
    dataset = await make_dataset()

    res = await aexecute(LINK_FILE, {"input": {"dataset": str(dataset.id), "sourceFiles": [{"file": str(file.id), "seriesIdentifier": "series-0"}]}})
    assert not res.errors, res.errors
    (link,) = res.data["linkFile"]
    assert (link["seriesIdentifier"], link["direction"]) == ("series-0", "SOURCE")
    assert link["container"] == {"__typename": "ArrayDataset", "id": str(dataset.id)}
    assert link["file"]["id"] == str(file.id)

    again = await aexecute(LINK_FILE, {"input": {"dataset": str(dataset.id), "sourceFiles": [{"file": str(file.id), "seriesIdentifier": "series-0"}]}})
    assert again.errors and "already records file" in str(again.errors[0]), "this service's old nullable series column let the duplicate through"

    other_series = await aexecute(LINK_FILE, {"input": {"dataset": str(dataset.id), "sourceFiles": [{"file": str(file.id), "seriesIdentifier": "series-1"}]}})
    assert not other_series.errors, "two series of one file are two genuinely different sources"

    res = await aexecute(UNLINK_FILE, {"input": {"id": link["id"]}})
    assert not res.errors, res.errors
    assert not await FileLink.objects.filter(id=link["id"]).aexists()
    assert await File.objects.filter(id=file.id).aexists(), "deleting the link touches neither side"


async def test_link_file_names_one_direction(aexecute, authenticated_context, bigfile_store, make_dataset):
    file = await _make_file(authenticated_context, await bigfile_store())
    dataset = await make_dataset()
    both = await aexecute(LINK_FILE, {"input": {"file": str(file.id), "dataset": str(dataset.id), "sourceFiles": [{"file": str(file.id)}]}})
    assert both.errors and "not both" in str(both.errors[0])
    neither = await aexecute(LINK_FILE, {"input": {}})
    assert neither.errors and "A link needs both of its ends" in str(neither.errors[0])


async def test_delete_file_flags_its_store(aexecute, authenticated_context, bigfile_store):
    store = await bigfile_store()
    file = await _make_file(authenticated_context, store, "del.abf")
    res = await aexecute(DELETE_FILE, {"input": {"id": str(file.id)}})
    assert not res.errors, res.errors
    assert res.data["deleteFile"] == str(file.id)
    assert not await File.objects.filter(id=file.id).aexists()
    store = await BigFileStore.objects.aget(pk=store.pk)
    assert store.orphaned_at is not None, "the bytes outlive the request: `purge_orphaned_stores` collects them after a grace period"


async def test_the_file_filters_answer_what_a_picker_asks(aexecute, authenticated_context, bigfile_store, make_dataset):
    recording = await _make_file(authenticated_context, await bigfile_store(), "cell3.ABF")
    await _make_file(authenticated_context, await bigfile_store(), "notes.pdf")
    dataset = await make_dataset()
    await aexecute(LINK_FILE, {"input": {"dataset": str(dataset.id), "sourceFiles": [{"file": str(recording.id)}]}})

    async def names(filters: dict) -> list[str]:
        res = await aexecute("query ($filters: FileFilter) { files(filters: $filters) { name } }", {"filters": filters})
        assert not res.errors, res.errors
        return sorted(file["name"] for file in res.data["files"])

    assert await names({"mimeGroup": "RECORDING"}) == ["cell3.ABF"]
    assert await names({"extension": ".abf"}) == ["cell3.ABF"]
    assert await names({"unlinked": True}) == ["notes.pdf"]
    assert await names({"sourceOf": {"kind": "DATASET", "id": str(dataset.id)}}) == ["cell3.ABF"]
    assert await names({"mimeGroup": None, "unlinked": None}) == ["cell3.ABF", "notes.pdf"], "an explicit null is no constraint"


# --- negatives ---------------------------------------------------------------


async def test_delete_file_not_found(aexecute):
    res = await aexecute(DELETE_FILE, {"input": {"id": "999999"}})
    assert res.errors


async def test_from_file_like_unknown_store(aexecute):
    res = await aexecute(FROM_FILE_LIKE, {"input": {"fileName": "x", "file": "999999"}})
    assert res.errors


async def test_another_organization_cannot_link_to_this_file(aexecute, authenticated_context, other_org_context, bigfile_store, make_dataset):
    file = await _make_file(authenticated_context, await bigfile_store())
    theirs = await make_dataset(context=other_org_context)
    res = await aexecute(LINK_FILE, {"input": {"dataset": str(theirs.id), "sourceFiles": [{"file": str(file.id)}]}}, context=other_org_context)
    assert res.errors
    assert await sync_to_async(FileLink.objects.count)() == 0
