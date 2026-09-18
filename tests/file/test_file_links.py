"""File links: the bytes a container was converted from, and the files written out of it.

Ported from mikro's ``tests/test_file_links.py``. Two container kinds exist here --
``DATASET`` and ``ANNOTATION_COLLECTION`` -- so the cases mikro builds on a table dataset are
built on an annotation collection, and the mesh/network/sparse ones have no subject.

The mechanism these tests pin exists because a file is a *store*, not a container. Every
`derivedFrom` entry resolves to a `CoordinateSystem`, because a derivation is an edge of the
coordinate graph and states how one space maps into another -- and a file has no space. So the
lineage between bytes and data is its own relation, and the load-bearing claim, checked by
`test_source_files_leave_the_coordinate_graph_alone`, is that recording it touches the graph
not at all.

Both directions are here, because they are one relation seen from opposite ends: `sourceFiles`
on a container's create mutation, `exportOf` on `fromFileLike`, and `linkFile` for either after
the fact.

mikro patches ``ZarrStore.fill_info``, ``BigFileStore.fill_info`` and
``Datalayer.get_object_size``. Nothing is patched here: the ingest reads a real ``zarr.json`` and
the export reads the size of a real object, both in the compose RustFS.
"""

import pytest

from core import enums, models
from core.inputs.file_link import EXPORT_OF_MEMBERS, file_link_union_types
from core.logic.file_link import _CONTAINER_FIELDS, _CONTAINER_MODELS
from tests.seed import create_dataset, create_file, create_folder

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_WITH_SOURCES = """
mutation D($input: CreateArrayDatasetInput!) {
  createArrayDataset(input: $input) {
    id
    sourceFiles { id seriesIdentifier valueRelation direction file { id name } container { __typename } }
    derivedFrom { id }
  }
}
"""

LINK_FILE = "mutation L($input: LinkFileInput!) { linkFile(input: $input) { id direction container { __typename } file { name } } }"

T = [{"name": "t", "type": "TIME"}]


async def _ingest(aexecute, zarr_store, source_files: list, context=None):  # noqa: ANN001, ANN202
    """Run the real ingest mutation, naming the files the array was converted from. Returns the raw result."""
    store = await zarr_store(context=context, shape=[1000], dimension_names=["t"])
    return await aexecute(CREATE_WITH_SOURCES, {"input": {"name": "Sweep", "data": str(store.id), "scales": [], "axes": T, "sourceFiles": source_files}}, context=context)


async def _create_array_dataset_with_sources(aexecute, zarr_store, source_files: list) -> dict:  # noqa: ANN001
    result = await _ingest(aexecute, zarr_store, source_files)
    assert not result.errors, result.errors
    return result.data["createArrayDataset"]


async def _annotation_collection(aexecute, name: str = "Marks") -> str:  # noqa: ANN001
    """The other container kind, made the way a client makes one. Returns its id."""
    result = await aexecute("mutation ($input: CreateAnnotationCollectionInput!) { createAnnotationCollection(input: $input) { id } }", {"input": {"name": name, "axes": T}})
    assert not result.errors, result.errors
    return result.data["createAnnotationCollection"]["id"]


async def _file_names(aexecute, filters: dict) -> set:  # noqa: ANN001
    """The names the `files` query returns for a filter, as a set."""
    result = await aexecute("query L($filters: FileFilter) { files(filters: $filters) { name } }", {"filters": filters})
    assert not result.errors, result.errors
    return {row["name"] for row in result.data["files"]}


# --------------------------------------------------------------------------------------
# Totality. Three of `DerivedFromInput`'s five parallel lists are guarded by nothing, and a
# missing entry there fails at runtime on the first use with a green suite. This union does
# not repeat that: every kind is checked into every list it has to appear in.
# --------------------------------------------------------------------------------------


async def test_every_container_kind_has_an_input_member() -> None:
    assert set(EXPORT_OF_MEMBERS) == {kind.value for kind in enums.FileLinkContainerKind}, "a FileLinkContainerKind with no member model is advertised in the SDL and unparseable"


async def test_every_container_kind_has_a_published_sdl_member() -> None:
    assert len(file_link_union_types) == len(list(enums.FileLinkContainerKind)), "a member missing from file_link_union_types vanishes from the SDL silently -- nothing references it"


async def test_every_container_kind_resolves_to_a_model_and_a_column() -> None:
    assert set(_CONTAINER_MODELS) == {kind.value for kind in enums.FileLinkContainerKind}, "a kind with no model raises KeyError on the first export link"
    for model in _CONTAINER_MODELS.values():
        assert model in _CONTAINER_FIELDS, f"{model.__name__} resolves from a discriminator but has no FileLink column to be written into"


async def test_every_member_container_field_is_read_by_the_flat_input() -> None:
    """Each member's id field must be one the flat wire type actually forwards."""
    from core.inputs.file_link import _EXPORT_OF_CONTAINER_FIELDS

    for member in EXPORT_OF_MEMBERS.values():
        assert member.CONTAINER_FIELD in _EXPORT_OF_CONTAINER_FIELDS, f"{member.__name__} reads `{member.CONTAINER_FIELD}`, which to_pydantic never forwards -- every use would fail as a missing field"


async def test_the_container_kinds_are_the_four_this_service_has() -> None:
    """mikro's four, less the mesh, plus a sparse dataset (a sorter's output): a kind advertised with no model behind it is the failure the four tests above exist to catch."""
    assert {kind.value for kind in enums.FileLinkContainerKind} == {"DATASET", "TABLE_DATASET", "ANNOTATION_COLLECTION", "SPARSE_DATASET"}
    assert {field.name for field in models.FileLink._meta.get_fields() if field.is_relation and field.related_model in _CONTAINER_FIELDS} == set(_CONTAINER_FIELDS.values())


# --------------------------------------------------------------------------------------
# The ingest direction.
# --------------------------------------------------------------------------------------


async def test_a_dataset_records_the_file_it_was_converted_from(aexecute, zarr_store, authenticated_context):
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "session.abf", folder)

    dataset = await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(file.id), "seriesIdentifier": "sweep-3", "valueRelation": "IDENTICAL"}])

    (link,) = dataset["sourceFiles"]
    assert link["file"]["name"] == "session.abf"
    assert link["seriesIdentifier"] == "sweep-3"
    assert link["valueRelation"] == "IDENTICAL"
    assert link["direction"] == "SOURCE"
    assert link["container"]["__typename"] == "ArrayDataset"


async def test_two_series_of_one_file_are_two_links(aexecute, zarr_store, authenticated_context):
    """A dataset fused from two series names one file twice, and that is not a duplicate.

    This is why the series is part of the link's *identity* rather than a label on it: keyed
    on the file alone, the second entry would be refused as a repeat of the first.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "session.abf", folder)

    dataset = await _create_array_dataset_with_sources(
        aexecute,
        zarr_store,
        [
            {"file": str(file.id), "seriesIdentifier": "sweep-3"},
            {"file": str(file.id), "seriesIdentifier": "sweep-7"},
        ],
    )

    assert [link["seriesIdentifier"] for link in dataset["sourceFiles"]] == ["sweep-3", "sweep-7"]


async def test_naming_one_file_twice_is_refused_with_a_sentence(aexecute, zarr_store, authenticated_context):
    """The writer refuses before the database does, so the client gets prose not an IntegrityError."""
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "session.nwb", folder)

    result = await _ingest(aexecute, zarr_store, [{"file": str(file.id)}, {"file": str(file.id)}])

    assert result.errors
    message = str(result.errors[0].message)
    assert "more than once" in message and "seriesIdentifier" in message, message
    assert "IntegrityError" not in message and "duplicate key" not in message, message

    # One transaction here, which mikro's is not: the links are written after the dataset
    # and its grid, and the refusal takes both back.
    assert not await models.ArrayDataset.objects.filter(name="Sweep").aexists()
    assert await models.CoordinateSystem.objects.acount() == 0
    assert await models.FileLink.objects.acount() == 0


async def test_source_files_leave_the_coordinate_graph_alone(aexecute, zarr_store, authenticated_context):
    """The whole point of the split: recording a file mints no space and writes no edge.

    Had FILE become a `DerivedFromInput` kind, this dataset would carry a coordinate system
    for a file and an UNMAPPABLE edge into it -- a node and an edge in a geometry graph
    holding no geometry.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "session.nwb", folder)

    systems_before = await models.CoordinateSystem.objects.acount()
    edges_before = await models.Transformation.objects.acount()

    dataset = await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(file.id)}])

    assert dataset["derivedFrom"] == [], "a file is not something data is derived *from* -- it has no space to be derived from"
    # One system for the dataset's own sample grid, and nothing else. No file space.
    assert await models.CoordinateSystem.objects.acount() == systems_before + 1
    assert await models.Transformation.objects.acount() == edges_before, "a file link must write no edge: there are no two spaces for one to relate"


# --------------------------------------------------------------------------------------
# The export direction.
# --------------------------------------------------------------------------------------

FROM_FILE_LIKE = """
mutation E($input: FromFileLike!) {
  fromFileLike(input: $input) {
    id
    name
    size
    exportedFrom { direction seriesIdentifier container { __typename ... on ArrayDataset { name } ... on AnnotationCollection { name } } }
    derivedContainers { id }
  }
}
"""


async def test_a_file_records_the_dataset_it_was_written_from(aexecute, bigfile_store, authenticated_context):
    ctx = authenticated_context
    dataset = await create_dataset(ctx, "Sweep")
    store = await bigfile_store(content=b"x" * 42)

    result = await aexecute(FROM_FILE_LIKE, {"input": {"file": str(store.id), "fileName": "sweep.nwb", "exportOf": [{"kind": "DATASET", "dataset": str(dataset.id), "valueRelation": "IDENTICAL"}]}})

    assert not result.errors, result.errors
    file = result.data["fromFileLike"]
    # The supplied name, not the store's key: `fileName` was required and then ignored.
    assert file["name"] == "sweep.nwb"
    assert file["size"] == 42.0, "read off the object in the store, where mikro's test patches `get_object_size`"
    assert file["derivedContainers"] == []
    (link,) = file["exportedFrom"]
    assert link["direction"] == "RENDITION"
    assert link["container"] == {"__typename": "ArrayDataset", "name": "Sweep"}


async def test_a_file_records_the_annotation_collection_it_was_written_from(aexecute, bigfile_store):
    """The second container kind, through the same door: a CSV of event marks."""
    collection = await _annotation_collection(aexecute, "Marks")
    store = await bigfile_store()

    result = await aexecute(FROM_FILE_LIKE, {"input": {"file": str(store.id), "fileName": "marks.csv", "exportOf": [{"kind": "ANNOTATION_COLLECTION", "annotationCollection": collection}]}})

    assert not result.errors, result.errors
    (link,) = result.data["fromFileLike"]["exportedFrom"]
    assert link["container"] == {"__typename": "AnnotationCollection", "name": "Marks"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "core/mutations/file.py::from_file_like is not one transaction: `models.File.objects.create(...)` commits before `file_link_logic.write_export_links` resolves "
        "`exportOf`, so an export naming a dataset that does not exist (or another organization's) returns an error AND leaves the File row behind, filed in the default "
        "folder with no link. `createArrayDataset` was wrapped in `transaction.atomic()` for exactly this exposure; `fromFileLike` has the same shape and was not."
    ),
)
async def test_an_export_of_a_container_that_does_not_exist_leaves_no_file(aexecute, bigfile_store):
    store = await bigfile_store()
    result = await aexecute(FROM_FILE_LIKE, {"input": {"file": str(store.id), "fileName": "ghost.nwb", "exportOf": [{"kind": "DATASET", "dataset": "999999"}]}})
    assert result.errors
    assert not await models.File.objects.filter(name="ghost.nwb").aexists(), "a file whose stated lineage could not be written must not be left behind claiming none"


async def test_link_file_records_an_export_after_the_fact(aexecute, authenticated_context):
    """A dataset exported months later gets the same row the create mutation would have written."""
    ctx = authenticated_context
    dataset = await create_dataset(ctx, "Sweep")
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "sweep.nwb", folder)

    result = await aexecute(LINK_FILE, {"input": {"file": str(file.id), "sourceOf": [{"kind": "DATASET", "dataset": str(dataset.id)}]}})

    assert not result.errors, result.errors
    (link,) = result.data["linkFile"]
    assert link["direction"] == "RENDITION"
    assert link["container"]["__typename"] == "ArrayDataset"
    assert link["file"]["name"] == "sweep.nwb"

    unlinked = await aexecute("mutation U($input: UnlinkFileInput!) { unlinkFile(input: $input) }", {"input": {"id": link["id"]}})
    assert not unlinked.errors, unlinked.errors
    assert await models.FileLink.objects.acount() == 0


async def test_link_file_refuses_an_undecidable_direction(aexecute, authenticated_context):
    """Naming both ends leaves it unsaid which was made from which, and that is the whole column."""
    ctx = authenticated_context
    dataset = await create_dataset(ctx, "Sweep")
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "sweep.abf", folder)

    result = await aexecute(LINK_FILE, {"input": {"file": str(file.id), "dataset": str(dataset.id), "sourceFiles": [{"file": str(file.id)}]}})

    assert result.errors
    assert "not both" in str(result.errors[0].message), result.errors[0].message


async def test_link_file_refuses_two_containers(aexecute, authenticated_context):
    ctx = authenticated_context
    dataset = await create_dataset(ctx, "Sweep")
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "sweep.abf", folder)

    # Two *different kinds* of container, since the input carries one field per kind.
    collection = await _annotation_collection(aexecute)

    result = await aexecute(LINK_FILE, {"input": {"dataset": str(dataset.id), "annotationCollection": collection, "sourceFiles": [{"file": str(file.id)}]}})

    assert result.errors
    assert "Name one container" in str(result.errors[0].message), result.errors[0].message
    assert await models.FileLink.objects.acount() == 0


# --------------------------------------------------------------------------------------
# Strictness and scoping.
# --------------------------------------------------------------------------------------


async def test_an_export_link_rejects_a_field_outside_its_kind() -> None:
    """The union is strict: a contradicting field is an error naming both, never a silent drop."""
    from core.inputs.file_link import ExportOfInput

    flat = ExportOfInput(
        kind=enums.FileLinkContainerKind.DATASET,
        dataset="1",
        annotation_collection="2",
        series_identifier=None,
        value_relation=None,
    )
    with pytest.raises(ValueError) as err:
        flat.to_pydantic()
    assert "does not read `annotationCollection`" in str(err.value)


async def test_a_file_from_another_organization_is_refused(aexecute, zarr_store, authenticated_context, other_org_context):
    """Every id a client sends is org-scoped, and a file link is no exception."""
    foreign_folder = await create_folder(other_org_context, "Theirs")
    foreign_file = await create_file(other_org_context, "theirs.abf", foreign_folder)

    result = await _ingest(aexecute, zarr_store, [{"file": str(foreign_file.id)}])

    assert result.errors, "a file belonging to another organization must not be linkable"
    assert not await models.ArrayDataset.objects.filter(name="Sweep").aexists()
    assert await models.FileLink.objects.acount() == 0


async def test_another_organization_reads_no_link_of_this_one(aexecute, zarr_store, authenticated_context, other_org_context):
    """The read side of the same rule: `fileLinks`, `fileLink(id:)` and `files` are all organization-scoped."""
    ctx = authenticated_context
    file = await create_file(ctx, "session.abf", await create_folder(ctx, "DS"))
    dataset = await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(file.id)}])
    (link,) = dataset["sourceFiles"]

    mine = await aexecute("query { fileLinks { id } files { name } }")
    assert not mine.errors, mine.errors
    assert mine.data == {"fileLinks": [{"id": link["id"]}], "files": [{"name": "session.abf"}]}

    theirs = await aexecute("query { fileLinks { id } files { name } }", context=other_org_context)
    assert not theirs.errors, theirs.errors
    assert theirs.data == {"fileLinks": [], "files": []}

    by_id = await aexecute("query ($id: ID!) { fileLink(id: $id) { id } }", {"id": link["id"]}, context=other_org_context)
    assert by_id.errors or by_id.data["fileLink"] is None


# --------------------------------------------------------------------------------------
# Reading it back by query.
# --------------------------------------------------------------------------------------


async def test_datasets_can_be_filtered_by_the_file_and_series_they_came_from(aexecute, zarr_store, authenticated_context):
    """"Which datasets came from sweep 3 of this file" is a normal query, not a bespoke walk."""
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "session.abf", folder)

    await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(file.id), "seriesIdentifier": "sweep-3"}])
    await create_dataset(ctx, "Unrelated")

    async def names(filters):  # noqa: ANN001, ANN202
        result = await aexecute("query L($filters: ArrayDatasetFilter) { arrayDatasets(filters: $filters) { name } }", {"filters": filters})
        assert not result.errors, result.errors
        return {row["name"] for row in result.data["arrayDatasets"]}

    assert await names({"sourceFile": str(file.id)}) == {"Sweep"}
    assert await names({"sourceSeriesIdentifier": "sweep-3"}) == {"Sweep"}
    assert await names({"sourceSeriesIdentifier": "sweep-9"}) == set()
    assert await names({"sourceFile": None, "sourceSeriesIdentifier": None}) == {"Sweep", "Unrelated"}, "an explicit null is no constraint"


async def test_the_documented_read_fields_all_exist(aexecute, zarr_store, authenticated_context):
    """Every read field the file-link design names must be real.

    A doc that names a field the schema does not have is worse than no doc -- it reads as
    verified.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "session.abf", folder)
    await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(file.id), "seriesIdentifier": "sweep-3"}])

    result = await aexecute(
        """
        query Documented($file: ID!) {
          arrayDatasets {
            sourceFiles { file { name } seriesIdentifier }
            exports { file { name } }
          }
          files {
            derivedContainers { container { __typename } }
            exportedFrom { container { __typename } }
          }
          fromSeries: arrayDatasets(filters: {sourceFile: $file, sourceSeriesIdentifier: "sweep-3"}) { name }
        }
        """,
        {"file": str(file.id)},
    )

    assert not result.errors, result.errors
    assert result.data["fromSeries"] == [{"name": "Sweep"}]


async def test_a_collision_with_a_link_already_on_record_writes_nothing(aexecute, zarr_store, authenticated_context):
    """A second entry colliding with an existing link must not leave the first one written.

    The in-request duplicate is caught by `_refuse_duplicates` before anything is fetched;
    this is the other case -- a link already in the database -- and it is why the existence
    check sits in the resolve phase rather than in the write loop.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    first = await create_file(ctx, "a.abf", folder)
    second = await create_file(ctx, "b.abf", folder)

    dataset = await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(first.id)}])

    # The same file again, behind a fresh one, against the dataset that already links it.
    result = await aexecute(LINK_FILE, {"input": {"dataset": dataset["id"], "sourceFiles": [{"file": str(second.id)}, {"file": str(first.id)}]}})

    assert result.errors
    assert "already records file 'a.abf'" in str(result.errors[0].message), result.errors[0].message
    # The good entry ahead of the collision must not have been written.
    assert await models.FileLink.objects.acount() == 1, "a collision must roll back the entries before it"
    assert not await models.FileLink.objects.filter(file=second).aexists()


async def test_the_three_container_filters_differ_only_by_direction(aexecute, zarr_store, authenticated_context):
    """`sourceOf` and `exportedFrom` are one-way; `linkedTo` is both.

    One dataset with a file on each side of it, so a filter that ignores `direction` returns
    two names where it should return one.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    source = await create_file(ctx, "session.abf", folder)
    export = await create_file(ctx, "sweep.nwb", folder)

    dataset = await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(source.id)}])
    linked = await aexecute(LINK_FILE, {"input": {"file": str(export.id), "sourceOf": [{"kind": "DATASET", "dataset": dataset["id"]}]}})
    assert not linked.errors, linked.errors

    ref = {"kind": "DATASET", "id": dataset["id"]}
    assert await _file_names(aexecute, {"sourceOf": ref}) == {"session.abf"}
    assert await _file_names(aexecute, {"exportedFrom": ref}) == {"sweep.nwb"}
    assert await _file_names(aexecute, {"linkedTo": ref}) == {"session.abf", "sweep.nwb"}


async def test_a_container_ref_reads_the_kind_not_only_the_id(aexecute, authenticated_context):
    """The reason the ref is `{kind, id}` and not a bare ID.

    A dataset and an annotation collection have ids drawn from separate sequences, so an
    unqualified id cannot say which was meant. Rather than forcing a pk collision -- explicit
    `id=` on a BigAutoField leaves the sequence unadvanced and breaks later creates -- this asks
    for the *collection's* pk under `kind: DATASET`. A mapping that ignored `kind` would return
    the collection's file; the right one returns nothing.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    marks_file = await create_file(ctx, "marks.csv", folder)

    collection = await _annotation_collection(aexecute)
    linked = await aexecute(LINK_FILE, {"input": {"annotationCollection": collection, "sourceFiles": [{"file": str(marks_file.id)}]}})
    assert not linked.errors, linked.errors
    assert linked.data["linkFile"][0]["container"]["__typename"] == "AnnotationCollection"

    assert await _file_names(aexecute, {"sourceOf": {"kind": "ANNOTATION_COLLECTION", "id": collection}}) == {"marks.csv"}
    assert await _file_names(aexecute, {"sourceOf": {"kind": "DATASET", "id": collection}}) == set(), "the kind must pick the column, not just the id"


async def test_two_links_to_one_container_return_the_file_once(aexecute, zarr_store, authenticated_context):
    """A to-many hop without `.distinct()` returns the row once per matching link."""
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "session.abf", folder)

    dataset = await _create_array_dataset_with_sources(
        aexecute,
        zarr_store,
        [{"file": str(file.id), "seriesIdentifier": "sweep-3"}, {"file": str(file.id), "seriesIdentifier": "sweep-7"}],
    )

    result = await aexecute("query L($filters: FileFilter) { files(filters: $filters) { name } }", {"filters": {"linkedTo": {"kind": "DATASET", "id": dataset["id"]}}})
    assert not result.errors, result.errors
    assert [row["name"] for row in result.data["files"]] == ["session.abf"], "two links, one file, one row"


async def test_not_derived_survives_a_second_link_join(aexecute, zarr_store, authenticated_context):
    """`notDerived` combined with `sourceOf` -- two `links__` lookups in one query.

    This is why `notDerived` is a `pk__in` subquery rather than `~Q(links__direction=...)`:
    Django builds a second join for the second lookup, and the negated one stops meaning what
    it reads as.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    raw = await create_file(ctx, "session.abf", folder)
    export = await create_file(ctx, "sweep.nwb", folder)

    dataset = await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(raw.id)}])
    linked = await aexecute(LINK_FILE, {"input": {"file": str(export.id), "sourceOf": [{"kind": "DATASET", "dataset": dataset["id"]}]}})
    assert not linked.errors, linked.errors

    ref = {"kind": "DATASET", "id": dataset["id"]}
    # Of the two files touching this dataset, only the raw one was not exported into.
    assert await _file_names(aexecute, {"linkedTo": ref, "notDerived": True}) == {"session.abf"}
    assert await _file_names(aexecute, {"linkedTo": ref, "notDerived": False}) == {"sweep.nwb"}


async def test_unlinked_finds_the_orphan_uploads(aexecute, zarr_store, authenticated_context):
    """`unlinked` is stricter than `notDerived`: no links at all, in either direction."""
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    used = await create_file(ctx, "session.abf", folder)
    await create_file(ctx, "stray.abf", folder)

    await _create_array_dataset_with_sources(aexecute, zarr_store, [{"file": str(used.id)}])

    assert await _file_names(aexecute, {"unlinked": True}) == {"stray.abf"}
    assert await _file_names(aexecute, {"unlinked": False}) == {"session.abf"}
    # Both are notDerived -- nothing was exported into either -- which is the weaker question.
    assert await _file_names(aexecute, {"notDerived": True}) == {"session.abf", "stray.abf"}


async def test_store_filters(aexecute, bigfile_store, authenticated_context):
    """`hasStore` and `populated` are deliberately not complementary.

    mikro's `test_store_and_metadata_filters`, under the name of what it tests: neither service's
    version touches metadata, and this one has no `hasMetadata` filter to touch.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    await create_file(ctx, "complete.abf", folder, store=await bigfile_store(populated=True))
    await create_file(ctx, "storeless.abf", folder)
    await create_file(ctx, "pending.abf", folder, store=await bigfile_store(content=None, populated=False))

    assert await _file_names(aexecute, {"hasStore": True}) == {"complete.abf", "pending.abf"}
    assert await _file_names(aexecute, {"hasStore": False}) == {"storeless.abf"}
    assert await _file_names(aexecute, {"populated": True}) == {"complete.abf"}
    # The storeless file is absent from BOTH populated answers -- the join drops it.
    assert await _file_names(aexecute, {"populated": False}) == {"pending.abf"}
    assert await _file_names(aexecute, {"hasStore": False, "populated": False}) == set()


async def test_extension_normalizes_dot_and_case(aexecute, authenticated_context):
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    await create_file(ctx, "cell3.ABF", folder)
    await create_file(ctx, "export.tar.gz", folder)

    for spelling in ("abf", ".abf", "ABF"):
        assert await _file_names(aexecute, {"extension": spelling}) == {"cell3.ABF"}, spelling
    # A double extension is matched as written.
    assert await _file_names(aexecute, {"extension": "tar.gz"}) == {"export.tar.gz"}


async def test_mime_group_classifies_a_vendor_file_the_content_type_cannot(aexecute, authenticated_context):
    """The case the obvious implementation gets wrong.

    An ABF uploads as `application/octet-stream`, so a contentType-prefix rule would file it
    under OTHER -- exactly the set a client filtering for RECORDING wants to find.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    await create_file(ctx, "cell3.abf", folder, content_type="application/octet-stream")
    await create_file(ctx, "locs.csv", folder, content_type="text/csv")
    await create_file(ctx, "soma.hoc", folder)
    await create_file(ctx, "protocol.pdf", folder)
    await create_file(ctx, "session.zip", folder)
    await create_file(ctx, "notes", folder)

    assert await _file_names(aexecute, {"mimeGroup": "RECORDING"}) == {"cell3.abf"}
    assert await _file_names(aexecute, {"mimeGroup": "TABLE"}) == {"locs.csv"}
    assert await _file_names(aexecute, {"mimeGroup": "MODEL"}) == {"soma.hoc"}
    assert await _file_names(aexecute, {"mimeGroup": "ARCHIVE"}) == {"session.zip"}
    # OTHER is the complement, so an extensionless file lands there and nothing else does.
    assert await _file_names(aexecute, {"mimeGroup": "OTHER"}) == {"notes"}


async def test_mime_group_falls_back_to_the_content_type_of_an_extensionless_file(aexecute, authenticated_context):
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    await create_file(ctx, "readme", folder, content_type="text/plain")
    await create_file(ctx, "notes", folder)

    assert await _file_names(aexecute, {"mimeGroup": "DOCUMENT"}) == {"readme"}, "with no extension to go on, the content type decides"
    assert await _file_names(aexecute, {"mimeGroup": "OTHER"}) == {"notes"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "core/filters.py::_mime_group_q: the groups are not disjoint. `claim()` ORs the `_MIME_GROUP_PREFIXES` content-type prefixes with the extension list instead of "
        "falling back to them 'when the extension says nothing' (the comment above the table), and DOCUMENT's prefix is the bare 'text/', which swallows TABLE's "
        "'text/csv' and 'text/tab-separated-values'. So a `.csv` uploaded as text/csv -- the ordinary case -- is returned by mimeGroup: TABLE *and* by mimeGroup: DOCUMENT. "
        "Identical in mikro/core/filters.py, whose test never queries DOCUMENT."
    ),
)
async def test_a_file_is_in_exactly_one_mime_group(aexecute, authenticated_context):
    """A bucket is a partition: the picker that lists TABLE files and the one that lists DOCUMENT files must not both show the same CSV."""
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    await create_file(ctx, "locs.csv", folder, content_type="text/csv")
    await create_file(ctx, "protocol.pdf", folder, content_type="application/pdf")

    assert await _file_names(aexecute, {"mimeGroup": "TABLE"}) == {"locs.csv"}
    assert await _file_names(aexecute, {"mimeGroup": "DOCUMENT"}) == {"protocol.pdf"}


async def test_link_lists_are_filterable(aexecute, zarr_store, authenticated_context):
    """`FileLinkFilter` reaches the SDL only by being some field's argument.

    Declared on the django_type alone it was absent from the schema entirely, so this pins
    the seam as well as the behaviour.
    """
    ctx = authenticated_context
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "session.abf", folder)
    await _create_array_dataset_with_sources(
        aexecute,
        zarr_store,
        [{"file": str(file.id), "seriesIdentifier": "sweep-3"}, {"file": str(file.id), "seriesIdentifier": "sweep-7"}],
    )

    result = await aexecute(
        """
        query { arrayDatasets {
          all: sourceFiles { seriesIdentifier }
          one: sourceFiles(filters: {seriesIdentifier: {exact: "sweep-3"}}) { seriesIdentifier }
        } }
        """
    )
    assert not result.errors, result.errors
    (dataset,) = result.data["arrayDatasets"]
    assert len(dataset["all"]) == 2
    assert [link["seriesIdentifier"] for link in dataset["one"]] == ["sweep-3"]


async def test_filefilter_publishes_no_surface_filterlookup_already_covers() -> None:
    """`sizes` and `contentTypes` are absent on purpose, not by oversight.

    `IntFilterLookup`/`StrFilterLookup` already carry `inList` and `range`, so
    `size: {range: [a, b]}` and `contentType: {inList: [...]}` answer both. A dedicated field
    would be duplicate SDL surface with a second implementation to keep in step.
    """
    from elektro_server.schema import schema

    sdl = schema.as_str()
    body = sdl[sdl.find("input FileFilter") : sdl.find("\n}", sdl.find("input FileFilter"))]
    assert "sizes:" not in body
    assert "contentTypes:" not in body
    assert "linkedToDataset" not in body, "superseded by linkedTo, which covers both container kinds"
    assert "hasMetadata" not in body, "mikro's filter on a column this service's File does not have"
