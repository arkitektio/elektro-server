"""Everything fileable can be filed: every container carries a folder.

Ported from mikro's ``tests/test_fileable_folder.py``. mikro files four containers; three of them
exist here (``ArrayDataset``, ``TableDataset`` and ``AnnotationCollection``) beside a
``SparseDataset`` where mikro has a mesh collection -- the four ``FileLink`` calls "a container
holding data" -- so the folder tree is a complete view of a user's data.

The invariant these tests defend is that filing and *placement* stay separate. A folder
says where a user keeps a thing; it never says anything about the space the thing is in.
Nothing here touches a coordinate system, and nothing in the coordinate-graph tests should
ever need to touch a folder.

mikro's helpers patch ``ZarrStore.fill_info``; these go through the ``create_array_dataset``
fixture, over a real ``zarr.json`` in the compose RustFS.
"""

from typing import Any

import pytest

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_ANNOTATION_COLLECTION = """
mutation Create($input: CreateAnnotationCollectionInput!) {
  createAnnotationCollection(input: $input) { id name }
}
"""

CREATE_TABLE = """
mutation Create($input: CreateTableDatasetInput!) {
  createTableDataset(input: $input) { id folder { id name } }
}
"""

_EVENTS = [{"name": "t", "role": "COORDINATE", "axisType": "TIME", "unit": "second"}, {"name": "label", "role": "LABEL", "dtype": "VARCHAR"}]

_T = [{"name": "t", "type": "TIME"}]


async def _create_annotation_collection(aexecute, name: str, derived_from=None) -> dict[str, Any]:  # noqa: ANN001
    """A collection, made the way a client makes one. `createAnnotationCollection` takes no `folder` here (mikro's does)."""
    payload: dict[str, Any] = {"name": name, "axes": _T}
    if derived_from is not None:
        payload["derivedFrom"] = derived_from
    result = await aexecute(CREATE_ANNOTATION_COLLECTION, {"input": payload})
    assert not result.errors, result.errors
    return result.data["createAnnotationCollection"]


async def _create_table(aexecute, ctx, name: str, folder=None) -> dict[str, Any]:  # noqa: ANN001
    """An event table, made the way a client makes one: a finished parquet store, then `createTableDataset`."""
    payload: dict[str, Any] = await seed.table_input(ctx, name, _EVENTS)
    if folder is not None:
        payload["folder"] = str(folder.pk)
    result = await aexecute(CREATE_TABLE, {"input": payload})
    assert not result.errors, result.errors
    return result.data["createTableDataset"]


async def _file_collection(aexecute, collection: dict, folder) -> None:  # noqa: ANN001
    moved = await aexecute("mutation M($input: AssociateInput!) { putAnnotationCollectionsInFolder(input: $input) { id } }", {"input": {"selfs": [collection["id"]], "other": str(folder.pk)}})
    assert not moved.errors, moved.errors


def _derived_from(parent: dict) -> list[dict]:
    return [{"kind": "DATASET", "dataset": parent["id"], "transform": {"kind": "IDENTITY"}}]


async def test_every_container_files_into_a_named_folder(aexecute, create_array_dataset, authenticated_context):
    """Everything that takes a folder on create accepts it and reads it back."""
    ctx = authenticated_context
    folder = await seed.create_folder(ctx, "Experiment A")

    created = [
        await create_array_dataset("Acquired", [1000], folder=folder.pk),
        await _create_table(aexecute, authenticated_context, "Session", folder=folder),
    ]

    for container in created:
        assert container["folder"] is not None, "a container created with a folder must report it"
        assert container["folder"]["name"] == "Experiment A"


async def test_a_container_created_without_a_folder_lands_in_the_default(aexecute, create_array_dataset, authenticated_context):
    """Omitting the folder files it in the user's default, exactly as a file has always been.

    The column is nullable and unfiled rows are legal, but nothing created *through the API*
    is left unfiled.
    """
    dataset = await create_array_dataset("Unfiled", [1000])
    table = await _create_table(aexecute, authenticated_context, "Unfiled session")

    for container in (dataset, table):
        assert container["folder"] is not None, "a container created without a folder still gets the default one"
        assert container["folder"]["name"] == "Default"
    assert dataset["folder"]["id"] == table["folder"]["id"], "one default folder per user, not one per kind"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "core/mutations/annotation_collection.py::create_annotation_collection never files the collection: `AnnotationCollection.objects.create(...)` passes no `folder`, "
        "`CreateAnnotationCollectionInput` has no `folder` field, and `folder_logic.folder_for_new_container` (which createArrayDataset calls) is never consulted. "
        "mikro's createAnnotationCollection takes `folder` and defaults it. So a collection created through the API is unfiled -- invisible in every folder's `children` -- "
        "until someone calls putAnnotationCollectionsInFolder, and the GraphQL type `AnnotationCollection` has no `folder` field to notice it by."
    ),
)
async def test_an_annotation_collection_created_without_a_folder_lands_in_the_default(aexecute):
    """mikro's assertion for the fourth container: nothing created through the API is left unfiled."""
    collection = await _create_annotation_collection(aexecute, "Drawn")

    stored = await models.AnnotationCollection.objects.select_related("folder").aget(pk=collection["id"])
    assert stored.folder is not None, "a container created without a folder still gets the default one"
    assert stored.folder.name == "Default"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Same omission as above, on the derived path: core/mutations/annotation_collection.py::create_annotation_collection does not call "
        "`folder_logic.folder_for_new_container(info, ctx, None, model.derived_from)`, so a collection derived from a filed dataset is created with folder=NULL instead of "
        "inheriting its primary parent's folder. It then cannot be filed by hand either (`putAnnotationCollectionsInFolder` refuses derived data), so it stays unfiled until its parent is moved."
    ),
)
async def test_a_derived_annotation_collection_is_filed_with_its_parent(aexecute, create_array_dataset, authenticated_context):
    """Filing is a historical question, not a spatial one: marks detected on a recording live where the recording lives."""
    home = await seed.create_folder(authenticated_context, "Home")
    parent = await create_array_dataset("Acquired", [1000], folder=home.pk)

    derived = await _create_annotation_collection(aexecute, "Detected", derived_from=_derived_from(parent))

    assert await models.AnnotationCollection.objects.filter(pk=derived["id"], folder=home).aexists(), "a derivation is filed where its parent is"


async def test_a_folder_lists_every_kind_of_container_it_holds(aexecute, create_array_dataset, authenticated_context):
    """The reverse lists on Folder, one per fileable type."""
    ctx = authenticated_context
    folder = await seed.create_folder(ctx, "Everything")

    await create_array_dataset("Acquired", [1000], folder=folder.pk)
    await _file_collection(aexecute, await _create_annotation_collection(aexecute, "Drawn"), folder)
    await _create_table(aexecute, authenticated_context, "Session", folder=folder)
    await seed.create_file(ctx, "cell3.abf", folder)
    await seed.create_folder(ctx, "Sub", parent=folder)

    result = await aexecute(
        """
        query Contents($id: ID!) {
          folder(id: $id) {
            arrayDatasets { name }
            annotationCollections { name }
            tableDatasets { name }
            files { name }
            children { name }
          }
        }
        """,
        {"id": str(folder.pk)},
    )
    assert not result.errors, result.errors

    contents = result.data["folder"]
    assert [d["name"] for d in contents["arrayDatasets"]] == ["Acquired"]
    assert [a["name"] for a in contents["annotationCollections"]] == ["Drawn"]
    assert [b["name"] for b in contents["tableDatasets"]] == ["Session"]
    assert [f["name"] for f in contents["files"]] == ["cell3.abf"]
    assert [f["name"] for f in contents["children"]] == ["Sub"]


async def test_children_returns_the_containers_alongside_files(aexecute, create_array_dataset, authenticated_context):
    """`children` is the folder's contents, so it has to include what folders can now hold.

    It returned only sub-folders and files while the containers were unfileable;
    leaving it that way would have made a folder's contents list quietly incomplete.
    """
    ctx = authenticated_context
    folder = await seed.create_folder(ctx, "Mixed")
    await seed.create_file(ctx, "cell3.abf", folder)
    await create_array_dataset("Acquired", [1000], folder=folder.pk)
    await _file_collection(aexecute, await _create_annotation_collection(aexecute, "Drawn"), folder)
    await _create_table(aexecute, authenticated_context, "Session", folder=folder)

    result = await aexecute("query Children($parent: ID!) { children(parent: $parent) { __typename } }", {"parent": str(folder.pk)})
    assert not result.errors, result.errors

    kinds = {child["__typename"] for child in result.data["children"]}
    assert kinds == {"File", "ArrayDataset", "AnnotationCollection", "TableDataset"}


async def test_children_orders_and_searches_across_every_source(aexecute, create_array_dataset, authenticated_context):
    """The `order` and `search` branches, which fan across all five sources.

    Worth its own test because `children` builds its querysets from a table, and both
    branches ask each source a question it has to be able to answer. Without this test the
    resolver was only ever exercised on the branch where neither runs.
    """
    ctx = authenticated_context
    folder = await seed.create_folder(ctx, "Sortable")
    await create_array_dataset("Beta", [1000], folder=folder.pk)
    await _file_collection(aexecute, await _create_annotation_collection(aexecute, "Gamma"), folder)
    await _create_table(aexecute, authenticated_context, "Alpha", folder=folder)
    await seed.create_file(ctx, "Delta", folder)
    await seed.create_folder(ctx, "Epsilon", parent=folder)

    ORDERED = """
    query Children($parent: ID!, $order: ChildrenOrder) {
      children(parent: $parent, order: $order) {
        __typename
        ... on Folder { name }
        ... on File { name }
        ... on ArrayDataset { name }
        ... on AnnotationCollection { name }
        ... on TableDataset { name }
      }
    }
    """

    ordered = await aexecute(ORDERED, {"parent": str(folder.pk), "order": {"field": "NAME", "direction": "ASC"}})
    assert not ordered.errors, ordered.errors
    assert len(ordered.data["children"]) == 5, "ordering by name must not drop a source"
    by_kind: dict[str, list[str]] = {}
    for child in ordered.data["children"]:
        by_kind.setdefault(child["__typename"], []).append(child["name"])
    assert by_kind == {"Folder": ["Epsilon"], "File": ["Delta"], "ArrayDataset": ["Beta"], "AnnotationCollection": ["Gamma"], "TableDataset": ["Alpha"]}

    by_created = await aexecute(ORDERED, {"parent": str(folder.pk), "order": {"field": "CREATED_AT", "direction": "DESC"}})
    assert not by_created.errors, by_created.errors
    assert len(by_created.data["children"]) == 5

    searched = await aexecute(
        "query Children($parent: ID!, $filters: FolderChildrenFilter) { children(parent: $parent, filters: $filters) { __typename } }",
        {"parent": str(folder.pk), "filters": {"search": "Alpha"}},
    )
    assert not searched.errors, searched.errors
    assert [c["__typename"] for c in searched.data["children"]] == ["TableDataset"], "search must reach the containers, and only match one here"

    unasked = await aexecute(
        "query Children($parent: ID!, $filters: FolderChildrenFilter) { children(parent: $parent, filters: $filters) { __typename } }",
        {"parent": str(folder.pk), "filters": {"search": None, "showChildren": None}},
    )
    assert not unasked.errors, unasked.errors
    assert len(unasked.data["children"]) == 5, "an explicit null is no constraint"


async def test_containers_are_filterable_by_folder(aexecute, create_array_dataset, authenticated_context):
    """`folder` and `folders` on each container filter, and they filter independently."""
    ctx = authenticated_context
    here = await seed.create_folder(ctx, "Here")
    there = await seed.create_folder(ctx, "There")

    await create_array_dataset("Mine", [1000], folder=here.pk)
    await create_array_dataset("Theirs", [1000], folder=there.pk)
    await _create_table(aexecute, authenticated_context, "MyTable", folder=here)
    await _create_table(aexecute, authenticated_context, "TheirTable", folder=there)

    result = await aexecute(
        """
        query ByFolder($here: ID!, $both: [ID!]) {
          here: arrayDatasets(filters: {folder: $here}) { name }
          both: arrayDatasets(filters: {folders: $both}) { name }
          tables: tableDatasets(filters: {folder: $here}) { name }
          unasked: arrayDatasets(filters: {folder: null, folders: null}) { name }
        }
        """,
        {"here": str(here.pk), "both": [str(here.pk), str(there.pk)]},
    )
    assert not result.errors, result.errors

    assert [d["name"] for d in result.data["here"]] == ["Mine"]
    assert {d["name"] for d in result.data["both"]} == {"Mine", "Theirs"}
    assert [b["name"] for b in result.data["tables"]] == ["MyTable"]
    assert {d["name"] for d in result.data["unasked"]} == {"Mine", "Theirs"}, "an explicit null is no constraint"


async def test_deleting_a_folder_unfiles_its_contents_and_destroys_nothing(aexecute, create_array_dataset, authenticated_context):
    """`on_delete=SET_NULL` everywhere: a folder is organisational, so deleting one says
    nothing about whether its contents should exist.

    It was CASCADE, which destroyed data through the database relation and so bypassed the
    per-object delete guards entirely. Deleting the data itself stays where it belongs, on
    the delete mutation for the thing.

    All of them, plus the older holders: the failure this guards against is not "does the
    unfiling happen" but "does a PROTECT FK pointing at a container turn folder deletion
    into a ProtectedError". `AnnotationCollection` is the one to watch, since it holds a
    PROTECT reference to its coordinate system.
    """
    ctx = authenticated_context
    folder = await seed.create_folder(ctx, "Doomed")

    file = await seed.create_file(ctx, "cell3.abf", folder)
    subfolder = await seed.create_folder(ctx, "Sub", parent=folder)
    nested = await seed.create_file(ctx, "nested.abf", subfolder)
    dataset = await create_array_dataset("Survives", [1000], folder=folder.pk)
    collection = await _create_annotation_collection(aexecute, "AndThis")
    await _file_collection(aexecute, collection, folder)
    table = await _create_table(aexecute, authenticated_context, "AlsoSurvives", folder=folder)

    deleted = await aexecute("mutation ($id: ID!) { deleteFolder(input: {id: $id}) }", {"id": str(folder.pk)})
    assert not deleted.errors, deleted.errors

    async def survives_unfiled(model, pk) -> bool:  # noqa: ANN001
        """Still there, and no longer filed. Asked as a query so `<fk>_id` is never read."""
        return await model.objects.filter(pk=pk, folder__isnull=True).aexists()

    assert await survives_unfiled(models.File, file.pk)
    assert await survives_unfiled(models.ArrayDataset, dataset["id"])
    assert await survives_unfiled(models.AnnotationCollection, collection["id"])
    assert await survives_unfiled(models.TableDataset, table["id"])
    # A sub-folder is part of the tree being deleted (`Folder.parent` is CASCADE), and what was
    # in *it* is unfiled the same way: the cascade runs through folders and stops at data.
    assert not await models.Folder.objects.filter(pk=subfolder.pk).aexists()
    assert await survives_unfiled(models.File, nested.pk)


async def test_a_container_can_be_refiled_and_unfiled(aexecute, create_array_dataset, authenticated_context):
    """`put<Things>InFolder` / `release<Things>FromFolder` for every fileable kind.

    Without these a container could be filed once, at creation, and never moved: `folder`
    was on the create inputs and on nothing else. Releasing unfiles and deletes nothing.
    """
    ctx = authenticated_context
    origin = await seed.create_folder(ctx, "Origin")
    destination = await seed.create_folder(ctx, "Destination")

    dataset = await create_array_dataset("Moves", [1000], folder=origin.pk)
    collection = await _create_annotation_collection(aexecute, "AndThis")
    table = await _create_table(aexecute, authenticated_context, "AlsoMoves", folder=origin)
    file = await seed.create_file(ctx, "cell3.abf", origin)

    cases = [
        ("putArrayDatasetsInFolder", "releaseArrayDatasetsFromFolder", models.ArrayDataset, dataset["id"]),
        ("putAnnotationCollectionsInFolder", "releaseAnnotationCollectionsFromFolder", models.AnnotationCollection, collection["id"]),
        ("putTableDatasetsInFolder", "releaseTableDatasetsFromFolder", models.TableDataset, table["id"]),
        ("putFilesInFolder", "releaseFilesFromFolder", models.File, file.pk),
    ]

    for put, release, model, pk in cases:
        moved = await aexecute(f"mutation M($input: AssociateInput!) {{ {put}(input: $input) {{ id name }} }}", {"input": {"selfs": [str(pk)], "other": str(destination.pk)}})
        assert not moved.errors, moved.errors
        assert await model.objects.filter(pk=pk, folder=destination).aexists(), f"{put} must re-file it"

        freed = await aexecute(f"mutation M($input: DesociateInput!) {{ {release}(input: $input) {{ id }} }}", {"input": {"selfs": [str(pk)], "other": str(destination.pk)}})
        assert not freed.errors, freed.errors
        assert await model.objects.filter(pk=pk, folder__isnull=True).aexists(), f"{release} must unfile it"
        assert await model.objects.filter(pk=pk).aexists(), f"{release} must not delete it"


async def test_releasing_a_file_from_a_folder_no_longer_violates_not_null(aexecute, authenticated_context):
    """`File.folder` was NOT NULL while `releaseFilesFromFolder` set it to None.

    Every call was an IntegrityError. Making the column nullable -- which SET_NULL needed
    anyway -- is what that mutation always assumed.
    """
    ctx = authenticated_context
    folder = await seed.create_folder(ctx, "Holding")
    file = await seed.create_file(ctx, "cell3.abf", folder)

    result = await aexecute("mutation M($input: DesociateInput!) { releaseFilesFromFolder(input: $input) { id } }", {"input": {"selfs": [str(file.pk)], "other": str(folder.pk)}})
    assert not result.errors, result.errors

    assert await models.File.objects.filter(pk=file.pk, folder__isnull=True).aexists()


async def test_derived_data_is_filed_with_its_parent_and_cannot_be_filed_alone(aexecute, create_array_dataset, authenticated_context):
    """Only root data is filed explicitly; a derivation inherits and refuses a folder of its own.

    Kind-blind: the dataset below derives UNMAPPABLY from its parent -- per-sweep summary
    numbers that are not anywhere on the parent's grid -- and it is still filed with it.
    Filing is a historical question, not a spatial one.
    """
    ctx = authenticated_context
    home = await seed.create_folder(ctx, "Home")
    elsewhere = await seed.create_folder(ctx, "Elsewhere")

    parent = await create_array_dataset("Acquired", [1000], folder=home.pk)

    unmappably = [{"kind": "DATASET", "dataset": parent["id"]}]
    derived = await create_array_dataset("Measurements", [12], axes=[{"name": "sweep", "type": "INDEX"}], derived_from=unmappably)
    assert derived["folder"]["name"] == "Home", "a derivation is filed where its parent is"

    refused = await create_array_dataset("Rejected", [12], axes=[{"name": "sweep", "type": "INDEX"}], derived_from=unmappably, folder=elsewhere.pk, raw=True)
    assert refused.errors, "naming a folder for derived data must be refused, not silently ignored"
    assert "filed with it" in str(refused.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Rejected").aexists(), "one transaction: the refusal leaves nothing behind"

    moved = await aexecute("mutation M($input: AssociateInput!) { putArrayDatasetsInFolder(input: $input) { id } }", {"input": {"selfs": [derived["id"]], "other": str(elsewhere.pk)}})
    assert moved.errors, "a derived container cannot be re-filed on its own either"
    assert await models.ArrayDataset.objects.filter(pk=derived["id"], folder=home).aexists()


async def test_moving_a_parent_moves_everything_derived_from_it(aexecute, create_array_dataset, authenticated_context):
    """The stored copy stays honest: re-filing a root rewrites its descendants, transitively."""
    ctx = authenticated_context
    home = await seed.create_folder(ctx, "Home")
    destination = await seed.create_folder(ctx, "Destination")

    root = await create_array_dataset("Acquired", [1000], folder=home.pk)
    child = await create_array_dataset("Filtered", [1000], derived_from=_derived_from(root))
    grandchild = await create_array_dataset("Decimated", [1000], derived_from=_derived_from(child))
    marks = await _create_annotation_collection(aexecute, "Detected", derived_from=_derived_from(grandchild))

    assert await models.ArrayDataset.objects.filter(pk=grandchild["id"], folder=home).aexists(), "inheritance is transitive at creation"

    moved = await aexecute("mutation M($input: AssociateInput!) { putArrayDatasetsInFolder(input: $input) { id } }", {"input": {"selfs": [root["id"]], "other": str(destination.pk)}})
    assert not moved.errors, moved.errors

    assert await models.ArrayDataset.objects.filter(pk=root["id"], folder=destination).aexists()
    assert await models.ArrayDataset.objects.filter(pk=child["id"], folder=destination).aexists(), "the child follows"
    assert await models.ArrayDataset.objects.filter(pk=grandchild["id"], folder=destination).aexists(), "and so does the grandchild"
    assert await models.AnnotationCollection.objects.filter(pk=marks["id"], folder=destination).aexists(), "and the marks drawn over it, a container of the other kind"


async def test_a_secondary_parent_does_not_carry_the_filing(aexecute, create_array_dataset, authenticated_context):
    """A fusion sits with its *primary* parent, matching the rule placement already uses."""
    ctx = authenticated_context
    first_home = await seed.create_folder(ctx, "First")
    second_home = await seed.create_folder(ctx, "Second")
    destination = await seed.create_folder(ctx, "Destination")

    primary = await create_array_dataset("Primary", [1000], folder=first_home.pk)
    secondary = await create_array_dataset("Secondary", [1000], folder=second_home.pk)

    fusion = await create_array_dataset("Fused", [1000], derived_from=[*_derived_from(primary), *_derived_from(secondary)])
    assert fusion["folder"]["name"] == "First", "the first declared source is the primary parent"

    moved = await aexecute("mutation M($input: AssociateInput!) { putArrayDatasetsInFolder(input: $input) { id } }", {"input": {"selfs": [secondary["id"]], "other": str(destination.pk)}})
    assert not moved.errors, moved.errors
    assert await models.ArrayDataset.objects.filter(pk=fusion["id"], folder=first_home).aexists(), "moving a secondary parent must not drag the fusion along"


async def test_filing_says_nothing_about_placement(aexecute, create_array_dataset, authenticated_context):
    """Two datasets in one folder share no space, and one dataset's folder is not its system.

    The point of the whole feature: `folder` is organisational and the coordinate graph is
    geometric. If these two ever start informing each other, this test is the one that
    should fail first.
    """
    ctx = authenticated_context
    folder = await seed.create_folder(ctx, "One Folder")

    first = await create_array_dataset("First", [1000], folder=folder.pk)
    second = await create_array_dataset("Second", [1000], folder=folder.pk)

    result = await aexecute(
        """
        query Systems($a: ID!, $b: ID!) {
          a: arrayDataset(id: $a) { folder { id } intrinsicSystem { id } }
          b: arrayDataset(id: $b) { folder { id } intrinsicSystem { id } }
        }
        """,
        {"a": first["id"], "b": second["id"]},
    )
    assert not result.errors, result.errors

    a, b = result.data["a"], result.data["b"]
    assert a["folder"]["id"] == b["folder"]["id"], "same folder"
    assert a["intrinsicSystem"]["id"] != b["intrinsicSystem"]["id"], "sharing a folder must not mean sharing a space"

    systems_before = await models.CoordinateSystem.objects.acount()
    edges_before = await models.Transformation.objects.acount()
    released = await aexecute("mutation M($input: DesociateInput!) { releaseArrayDatasetsFromFolder(input: $input) { id } }", {"input": {"selfs": [first["id"]], "other": str(folder.pk)}})
    assert not released.errors, released.errors
    assert (await models.CoordinateSystem.objects.acount(), await models.Transformation.objects.acount()) == (systems_before, edges_before), "and re-filing writes nothing to the graph"


async def test_another_organization_cannot_file_this_organizations_data(aexecute, create_array_dataset, authenticated_context, other_org_context):
    """Both ends of a filing are organization-scoped lookups: their folder cannot take our data, and ours cannot take theirs."""
    ours = await seed.create_folder(authenticated_context, "Ours")
    theirs = await seed.create_folder(other_org_context, "Theirs")
    dataset = await create_array_dataset("Mine", [1000], folder=ours.pk)

    into_theirs = await aexecute("mutation M($input: AssociateInput!) { putArrayDatasetsInFolder(input: $input) { id } }", {"input": {"selfs": [dataset["id"]], "other": str(theirs.pk)}})
    assert into_theirs.errors
    by_them = await aexecute("mutation M($input: AssociateInput!) { putArrayDatasetsInFolder(input: $input) { id } }", {"input": {"selfs": [dataset["id"]], "other": str(theirs.pk)}}, context=other_org_context)
    assert by_them.errors
    assert await models.ArrayDataset.objects.filter(pk=dataset["id"], folder=ours).aexists()

    listed = await aexecute("query ($parent: ID!) { children(parent: $parent) { __typename } }", {"parent": str(ours.pk)}, context=other_org_context)
    assert listed.errors or listed.data["children"] == [], "and another organization reads nothing of this folder's contents"
