"""`createSparseDataset`: two identified axes, and one or both stored layouts.

A sparse dataset is the shape a colouring needs when a feature stops being a *schema* fact and
becomes a *data* one. Everything asserted here is a refusal that would otherwise be silent:

* a store whose shape contradicts the declared axes places every lookup one position out and
  raises nothing;
* two stores indexing the same axis are one capability twice, with nothing to say which a
  reader should use;
* an axis identified by nothing is not a lax dataset -- it is one no source can ever key,
  because `assert_edge_rank` can only account for an axis the edge supplies or the target
  identifies.

The load-bearing test is :func:`test_the_keyed_axis_is_produced_and_the_referenced_one_is_not`:
a mask supplies one id, and the other axis is accounted for without it.
"""

import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import enums, models
from elektro_server.schema import schema
from tests import seed

CREATE = """
mutation Create($input: CreateSparseDatasetInput!) {
  createSparseDataset(input: $input) {
    id
    name
    axisNames
    shape
    indexableAxes
    arrays { indexedAxis indexedAxisName path store { id spec shape layouts { path encoding indexedAxis indexOrder rangeReadable } } }
    axisReferences { axis references { id name } }
    coordinateSystem { id axes { name type } }
  }
}
"""


#: A mask whose pixels are object ids. `(y, x)` in, one id out.
YX_AXES = [seed.axis("y", enums.AxisType.SPACE), seed.axis("x", enums.AxisType.SPACE)]

#: The declared axes of the matrix, in the order its stores' `shape` is written.
def _axes(mask=None, features=None, *, keyed: str = "object", table_axis: str = "feature") -> list[dict]:
    """The two axes, each carrying what identifies it.

    A builder rather than a constant now: identification lives on the axis, so the axes cannot be
    written without the things that identify them -- which is the point of the shape.
    """
    identifications = {
        keyed: {"kind": "DATASET", "dataset": str(mask.pk)} if mask is not None else None,
        table_axis: {"kind": "TABLE", "table": features} if features is not None else None,
    }
    return [{"name": name, "identifiedBy": [identifications[name]] if identifications[name] else []} for name in ("feature", "object")]

#: 40 features x 12 objects. Small, and the two extents differ so a transposed shape is caught.
SHAPE = [40, 12]


async def _mask(ctx: HttpContext, name: str = "cell labels"):
    """A label mask whose level-0 array has a zarr store, so a plan has something to name.

    `resolve_field_store` refuses a storeless array outright -- a plan is instructions for a
    worker, and one that cannot say where to sample is not instructions.
    """
    dataset = await seed.create_array_dataset(ctx, name, axes=YX_AXES, shapes=[[64, 64]])

    def attach() -> None:
        store = models.ZarrStore.objects.create(path=f"s3://zarr/{name}", bucket="zarr", key=name.replace(" ", "-"), organization=ctx.request.organization)
        array = dataset.data_arrays.get(level=0)
        array.store = store
        array.save()

    await sync_to_async(attach)()
    return dataset


def _layout(axis: int, rank: int = 2, nnz: int = 96) -> dict:
    """One entry of a store's `layouts`, as `finishSparseUpload` would have recorded it."""
    return seed.sparse_layout(axis, rank=rank, nnz=nnz)


async def _store(ctx: HttpContext, key: str, axes: tuple[int, ...] = (0,), shape: list[int] | None = None) -> models.SparseStore:
    """A finished sparse store holding a layout per axis in ``axes``. See `seed.create_sparse_store`."""
    return await seed.create_sparse_store(ctx, key, axes=axes, shape=list(shape if shape is not None else SHAPE))


async def _features_table(ctx: HttpContext, name: str = "features") -> str:
    """A table one feature position identifies a row of: keyed by a single INDEX column."""
    parquet = await sync_to_async(models.ParquetStore.objects.create)(path=f"s3://parquet/{name}", bucket="parquet", key=name, organization=ctx.request.organization, populated=True, columns=[{"name": "feature_id", "type": "BIGINT", "nullable": True}, {"name": "symbol", "type": "VARCHAR", "nullable": True}])
    result = await schema.execute(
        "mutation Create($input: CreateTableDatasetInput!) { createTableDataset(input: $input) { id } }",
        context_value=ctx,
        variable_values={
            "input": {
                "name": name,
                "data": str(parquet.pk),
                "columns": [
                    {"name": "feature_id", "dtype": "BIGINT", "axisType": "INDEX"},
                    {"name": "symbol", "dtype": "VARCHAR", "role": "LABEL"},
                ],
            }
        },
    )
    assert not result.errors, result.errors
    return result.data["createTableDataset"]["id"]


async def _create(ctx: HttpContext, name: str, **extra: object) -> object:
    return await schema.execute(CREATE, context_value=ctx, variable_values={"input": {"name": name, **extra}})


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_layouts_land_as_two_arrays_of_one_dataset(authenticated_context: HttpContext):
    """One matrix, two stores, and the axis each indexes derived from its own encoding."""
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    store = await _store(authenticated_context, "matrix", axes=(0, 1))

    result = await _create(
        authenticated_context,
        "expression",
        store=str(store.pk),
        axes=_axes(mask, features),
    )
    assert not result.errors, result.errors
    dataset = result.data["createSparseDataset"]

    assert dataset["axisNames"] == ["feature", "object"]
    assert dataset["shape"] == SHAPE, "read off the stores, never declared"
    assert [axis["type"] for axis in dataset["coordinateSystem"]["axes"]] == ["INDEX", "INDEX"]

    arrays = {array["indexedAxisName"]: array["path"] for array in dataset["arrays"]}
    assert arrays == {"feature": "layouts/axis0", "object": "layouts/axis1"}, "each layout is a child of the one store"
    assert len({array["store"]["id"] for array in dataset["arrays"]}) == 1, "one matrix is one upload"
    assert sorted(dataset["indexableAxes"]) == ["feature", "object"], "both questions answerable in one read"

    assert [(entry["axis"], entry["references"]["name"]) for entry in dataset["axisReferences"]] == [("feature", "features")]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_one_layout_is_legal_and_offers_one_capability(authenticated_context: HttpContext):
    """A dataset with a single store is not half-built: it answers one question, and says so."""
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    by_feature = await _store(authenticated_context, "by-feature", axes=(0,))

    result = await _create(
        authenticated_context,
        "expression",
        store=str(by_feature.pk),
        axes=_axes(mask, features),
    )
    assert not result.errors, result.errors
    assert result.data["createSparseDataset"]["indexableAxes"] == ["feature"], "one store, one capability"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_keyed_axis_is_produced_and_the_referenced_one_is_not(authenticated_context: HttpContext):
    """The rule this whole shape rests on: a mask supplies one id, and that is enough.

    `assert_edge_rank` accounts for every axis of a FIELD's target -- by the edge, or by the
    target's own identification. `feature` is identified by `references`, so the edge produces
    only `object`, and the edge is written rather than refused.
    """
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    store = await _store(authenticated_context, "by-feature", axes=(0,))

    result = await _create(
        authenticated_context,
        "expression",
        store=str(store.pk),
        axes=_axes(mask, features),
    )
    assert not result.errors, result.errors

    def edges() -> list[models.Transformation]:
        system = models.CoordinateSystem.objects.get(pk=result.data["createSparseDataset"]["coordinateSystem"]["id"])
        return list(models.Transformation.objects.filter(output=system, kind=enums.TransformKind.FIELD.value))

    field_edges = await sync_to_async(edges)()
    assert len(field_edges) == 1, "one source, one FIELD edge"
    assert field_edges[0].output_axes == ["object"], "the mask supplies the object id and nothing about a feature"
    assert sorted(field_edges[0].input_axes) == ["x", "y"], "and it consumes the pixel grid to do it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_axis_identified_by_nothing_is_refused(authenticated_context: HttpContext):
    """`identifiedBy` is a list now, so the empty case is expressible and comes back as prose.

    It was a singular required field, and "identified by nothing" was a document GraphQL would
    not accept -- a stronger guarantee, and the one thing the list form gives up. It is worth it:
    a singular field cannot say "keyed by a nucleus mask *and* a cell mask", which
    `write_key_edges` has always supported and which is an ordinary case. One line buys it back.
    """
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    store = await _store(authenticated_context, "by-feature", axes=(0,))

    axes = _axes(mask, features)
    axes[0]["identifiedBy"] = []
    result = await _create(authenticated_context, "expression", store=str(store.pk), axes=axes)

    assert result.errors
    message = str(result.errors[0])
    assert "empty `identifiedBy`" in message
    assert "no source could ever key" in message
    assert not await sync_to_async(models.SparseDataset.objects.filter(name="expression").exists)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_axis_identified_two_ways_at_once_is_refused(authenticated_context: HttpContext):
    """The union reads one id field, chosen by `kind`, and rejects any other."""
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    store = await _store(authenticated_context, "by-feature", axes=(0,))

    axes = _axes(mask, features)
    axes[0]["identifiedBy"] = [{"kind": "TABLE", "table": features, "dataset": str(mask.pk)}]
    result = await _create(authenticated_context, "expression", store=str(store.pk), axes=axes)

    assert result.errors
    assert "dataset" in str(result.errors[0]), "name the field that does not belong to this kind"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_keyed_axis_the_source_cannot_supply_is_refused(authenticated_context: HttpContext):
    """The check the caller's statement buys: the derivation now has something to disagree with.

    Naming the axis is not naming the split -- `consumed` and the passthrough are still derived --
    but it lets the refusal say which axis the caller meant, instead of counting ids.
    """
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    store = await _store(authenticated_context, "by-feature", axes=(0,))

    # The mask spans (y, x), so an axis called `y` is one it *shares* with the matrix -- it passes
    # through by name rather than being supplied, and no source ever produces it. Naming an axis
    # the mask does not share would be fine whichever way round it is, which is worth knowing:
    # `feature` keyed by the mask and `object` by a table is not an error, only unusual.
    result = await _create(
        authenticated_context,
        "expression",
        store=str(store.pk),
        axes=[
            {"name": "y", "identifiedBy": [{"kind": "DATASET", "dataset": str(mask.pk)}]},
            {"name": "object", "identifiedBy": [{"kind": "TABLE", "table": features}]},
        ],
    )
    assert result.errors
    message = str(result.errors[0])
    assert "was declared to key 'y'" in message, "name the axis the caller meant"
    assert "passes through rather than being supplied" in message, "say why, not just that it is wrong"
    assert not await sync_to_async(models.SparseDataset.objects.filter(name="expression").exists)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_stores_indexing_one_axis_are_refused(authenticated_context: HttpContext):
    """One capability twice, and nothing to say which a reader should use."""
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    store = await _store(authenticated_context, "one", axes=(0,))
    await sync_to_async(models.SparseStore.objects.filter(pk=store.pk).update)(layouts=[_layout(0), _layout(0)])

    result = await _create(
        authenticated_context,
        "expression",
        store=str(store.pk),
        axes=_axes(mask, features),
    )
    assert result.errors
    assert "one capability twice" in str(result.errors[0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_store_whose_shape_contradicts_the_axes_is_refused(authenticated_context: HttpContext):
    """The check only possible because the store read its own shape rather than being told it.

    Two *stores* disagreeing about the shape is no longer representable -- one matrix is one
    upload, so there is one declaration -- which is a simplification rather than a hole. What is
    still checkable, and still silent if missed, is a declaration whose rank does not match the
    bytes: every lookup would land one axis out.
    """
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    store = await _store(authenticated_context, "one", axes=(0,), shape=[*SHAPE, 2])

    result = await _create(
        authenticated_context,
        "expression",
        store=str(store.pk),
        axes=_axes(mask, features),
    )
    assert result.errors
    assert "the same number of them" in str(result.errors[0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unfinished_store_is_refused(authenticated_context: HttpContext):
    """An unfinished store knows nothing about itself, so a dataset over it would know nothing."""
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context)
    store = await _store(authenticated_context, "unfinished", axes=(0,))
    await sync_to_async(models.SparseStore.objects.filter(pk=store.pk).update)(populated=False, layouts=None, shape=None)

    result = await _create(
        authenticated_context,
        "expression",
        store=str(store.pk),
        axes=_axes(mask, features),
    )
    assert result.errors
    assert "finishSparseUpload" in str(result.errors[0]), "name the step that would have read it"


# `test_a_non_index_axis_is_refused` lived here. `SparseAxisInput` has no `type` field, so a
# CHANNEL axis is no longer something a caller can write and the refusal has nothing to catch --
# the check and the field that made it necessary were removed together.


# --------------------------------------------------------------------------- #
# Rank three -- two axes is one case, not the definition
# --------------------------------------------------------------------------- #
#: 40 features x 12 objects x 3 timepoints. Three different extents, so an axis mix-up cannot
#: survive a shape check by coincidence.
CUBE_SHAPE = [40, 12, 3]
def _cube_axes(mask, features, timepoints) -> list[dict]:
    """Three axes, one keyed and two referenced. The rule does not change with rank."""
    return [
        {"name": "feature", "identifiedBy": [{"kind": "TABLE", "table": features}]},
        {"name": "object", "identifiedBy": [{"kind": "DATASET", "dataset": str(mask.pk)}]},
        {"name": "timepoint", "identifiedBy": [{"kind": "TABLE", "table": timepoints}]},
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_rank_three_matrix_is_a_sparse_dataset(authenticated_context: HttpContext):
    """A layout is one axis made contiguous, so an array of rank n has up to n of them.

    The store, the datalayer reader and this mutation are all written that way. A
    (feature, object, timepoint) matrix answers "this feature", "this object" and "this
    timepoint" in one contiguous read each, and costs one stored layout per question.

    The identification rule does not change and is what makes the shape hold together: the mask
    supplies the object id, and the other two axes are identified by the tables whose rows their
    positions are. Every axis accounted for exactly once, at any rank.
    """
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context, "features")
    timepoints = await _features_table(authenticated_context, "timepoints")
    store = await _store(authenticated_context, "cube", axes=(0, 1, 2), shape=CUBE_SHAPE)

    result = await schema.execute(
        CREATE,
        context_value=authenticated_context,
        variable_values={
            "input": {
                "name": "expression over time",
                "axes": _cube_axes(mask, features, timepoints),
                "store": str(store.pk),
            }
        },
    )
    assert not result.errors, result.errors
    dataset = result.data["createSparseDataset"]

    assert dataset["axisNames"] == ["feature", "object", "timepoint"]
    assert dataset["shape"] == CUBE_SHAPE, "read off the store, never declared"
    assert sorted(dataset["indexableAxes"]) == ["feature", "object", "timepoint"], "all three questions answerable"
    assert {array["path"] for array in dataset["arrays"]} == {"layouts/axis0", "layouts/axis1", "layouts/axis2"}
    assert len({array["store"]["id"] for array in dataset["arrays"]}) == 1, "one matrix is one upload, at any rank"

    # Above rank two every layout is a csr_matrix over the raveled view, and `indexOrder` is what
    # makes a returned position meaningful -- it is not derivable from the bytes.
    layouts = {entry["indexedAxis"]: entry for entry in dataset["arrays"][0]["store"]["layouts"]}
    assert {entry["encoding"] for entry in layouts.values()} == {"csr_matrix"}
    assert layouts[1]["indexOrder"] == [0, 2]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_rank_three_edge_still_produces_exactly_one_id(authenticated_context: HttpContext):
    """The FIELD rule is unchanged by rank: a mask supplies one id, and the rest identify themselves."""
    mask = await _mask(authenticated_context)
    features = await _features_table(authenticated_context, "features")
    timepoints = await _features_table(authenticated_context, "timepoints")
    store = await _store(authenticated_context, "cube", axes=(1,), shape=CUBE_SHAPE)

    result = await schema.execute(
        CREATE,
        context_value=authenticated_context,
        variable_values={
            "input": {
                "name": "expression over time",
                "axes": _cube_axes(mask, features, timepoints),
                "store": str(store.pk),
            }
        },
    )
    assert not result.errors, result.errors

    def edges() -> list[models.Transformation]:
        system = models.CoordinateSystem.objects.get(pk=result.data["createSparseDataset"]["coordinateSystem"]["id"])
        return list(models.Transformation.objects.filter(output=system, kind=enums.TransformKind.FIELD.value))

    field_edges = await sync_to_async(edges)()
    assert len(field_edges) == 1
    assert field_edges[0].output_axes == ["object"], "one place holds one id, whatever the rank of what it keys"


