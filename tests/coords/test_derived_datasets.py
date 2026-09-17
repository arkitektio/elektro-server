"""A derived dataset is placed by where its source is, not by an assumption.

Ported from mikro's ``tests/test_derived_datasets.py`` and ``tests/test_multi_parent_derivation.py``,
through ``createArrayDataset(derivedFrom: [...])``. ``tests/dataset/test_dataset.py`` pins that one
derivation edge is written and read back; it never *places* anything through one, never states
two parents, and never reads the lineage from the source's side.

A filtered signal, a decimation, a channel mean, a spike sorting: none of them is a fresh
acquisition, and none of them sits anywhere on its own account. Its samples stand in a
definite relation to the lens they were computed from, and that relation is a fact about two
grids -- so it is an edge, like the lens crop and the sampling law, and not a label describing
one. Recorded that way, the derived dataset inherits its source's placement: refine the source's
registration and the derived data moves with it, because there is only one copy of the fact.

A fusion has several parents, and the creator's declared order says which one places it: the
first `derivedFrom` entry is the primary parent, and it drives the lineage root and the order
`derivedFrom` reports.

Unlike mikro's helper, nothing here patches ``ZarrStore.fill_info``: ``zarr_store(shape=...)``
writes a real ``zarr.json`` to the compose RustFS and the mutation reads it back. The views go
in through the ORM (``_helpers.add_view``); `createExperiment` lays out simulations by their
clock, and these datasets are placed by a registration of their source instead.
"""

import pytest
from asgiref.sync import sync_to_async

from core import enums, models
from core.logic import graph as graph_logic
from tests import seed
from tests.coords._helpers import add_view, create_experiment, derive, derived_dataset

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


REGISTER = """
mutation Register($input: CreateTransformationInput!) {
  createTransformation(input: $input) { id kind }
}
"""

PLACEMENT = """
query Placement($id: ID!) {
  experiment(id: $id) {
    recordingViews {
      id
      placement
      pathToWorld {
        inverted
        transformation {
          id kind inputAxes outputAxes
          input { id }
          output { id residents { __typename } }
        }
      }
    }
  }
}
"""

DERIVED = """
query Derived($id: ID!) {
  arrayDataset(id: $id) {
    id
    derivedFrom { id kind inputAxes outputAxes output { id } }
  }
}
"""

DERIVED_DATASETS = """
query Children($id: ID!) {
  arrayDataset(id: $id) {
    id
    derivedDatasets { id name }
  }
}
"""

DATASETS = """
query List($filters: ArrayDatasetFilter) {
  arrayDatasets(filters: $filters) { name }
}
"""

_AFFINE_3D = [
    [1.0, 0.0, 0.0, 5.0],
    [0.0, 1.0, 0.0, 5.0],
    [0.0, 0.0, 1.0, 0.0],
]

#: A multichannel recording and what a channel mean of it looks like: the rank change every
#: projection test below is about.
_TC_SHAPE = [1000, 4]


async def _register(aexecute, dataset: models.ArrayDataset, world_id) -> None:  # noqa: ANN001
    """Register a (c, y, x) dataset into a (z, y, x) world, by an affine someone measured."""
    registered = await aexecute(REGISTER, {"input": {"input": str(dataset.coordinate_system_id), "output": str(world_id), "transform": {"kind": "AFFINE", "affine": _AFFINE_3D}}})
    assert not registered.errors, registered.errors


async def _view(aexecute, experiment: models.Experiment) -> dict:  # noqa: ANN001
    result = await aexecute(PLACEMENT, {"id": str(experiment.pk)})
    assert not result.errors, result.errors
    (view,) = result.data["experiment"]["recordingViews"]
    return view


async def _children(aexecute, dataset: models.ArrayDataset) -> list[dict]:  # noqa: ANN001
    result = await aexecute(DERIVED_DATASETS, {"id": str(dataset.pk)})
    assert not result.errors, result.errors
    return result.data["arrayDataset"]["derivedDatasets"]


async def _names(aexecute, filters: dict) -> set[str]:  # noqa: ANN001
    result = await aexecute(DATASETS, {"filters": filters})
    assert not result.errors, result.errors
    return {dataset["name"] for dataset in result.data["arrayDatasets"]}


def _identity(lens: models.Lens) -> dict:
    return {"kind": "LENS", "lens": str(lens.pk), "transform": {"kind": "IDENTITY"}}


async def _two_sources(ctx):  # noqa: ANN001, ANN202
    """Two acquired datasets with a full lens each -- the parents of every fusion below."""
    left = await seed.create_array_dataset(ctx, "Left")
    left_lens = await seed.create_lens(ctx, left)
    right = await seed.create_array_dataset(ctx, "Right")
    right_lens = await seed.create_lens(ctx, right)
    return left, left_lens, right, right_lens


async def _fuse(aexecute, zarr_store, name: str, entries: list[dict]):  # noqa: ANN001, ANN202
    return await derive(aexecute, zarr_store, name, axes=seed.SIMPLE_AXES, shape=[3, 64, 64], entries=entries)


# --- placement through the source ---------------------------------------------------------------


async def test_a_derived_dataset_walks_to_world_through_its_source(aexecute, zarr_store, authenticated_context):
    """The path runs through the source's systems, not around them.

    The placement search partitions its edge universe per dataset, so before the lineage
    closure the walk crossed the derivation edge into the source's system and then
    **dead-ended** -- the source's own edges live in the source's bucket, which was never
    merged. `pathToWorld` came back null for data that is perfectly well placed.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Source")  # (c, y, x)
    source_lens = await seed.create_lens(ctx, source)
    experiment = await create_experiment(ctx, "Exp")

    # The SOURCE is registered into the world. The derived dataset never is.
    await _register(aexecute, source, experiment.world_id)

    # A zero-phase filter: same grid, so the derivation is an identity.
    derived = await derived_dataset(await derive(aexecute, zarr_store, "Filtered", lens=source_lens, axes=seed.SIMPLE_AXES, shape=[3, 64, 64]))
    await add_view(ctx, experiment, await seed.create_lens(ctx, derived))

    path = (await _view(aexecute, experiment))["pathToWorld"]
    assert path is not None, "a derived dataset is placed by its source; the walk must cross the derivation edge"

    # It ends in the source's registration -- the derived data inherits it.
    assert path[-1]["transformation"]["output"]["residents"] == [], "the walk ends in a space nothing lives in: a world"
    assert str(source.coordinate_system_id) in [step["transformation"]["input"]["id"] for step in path], "the walk passes through the source dataset's own space"

    # And no registration was fabricated for the derived dataset.
    inputs = [edge.input_id async for edge in models.Transformation.objects.filter(parent__isnull=True, output_id=experiment.world_id)]
    assert inputs == [source.coordinate_system_id], f"the derived dataset must inherit, not be pinned: {inputs}"


async def test_an_unregistered_derived_dataset_is_placed_through_its_source(aexecute, zarr_store, authenticated_context):
    """When nothing is registered yet the view is UNREGISTERED -- and registering the SOURCE fixes it.

    Nothing fabricates a placement. The honest fix is the one a client authors about the data
    the samples came from: register the source, and the derived view reaches world through its
    derivation edge. Registering the derived dataset directly would also produce a path, but it
    would be a second, shorter claim beside the lineage -- which is exactly why the server
    never writes one on its own.

    (mikro's version also pins that `createIntensityLayer` refuses the unregistered layer. The
    creating mutation here is this service's own and is pinned in ``tests/experiment``.)
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Source")
    derived = await derived_dataset(await derive(aexecute, zarr_store, "Filtered", lens=await seed.create_lens(ctx, source), axes=seed.SIMPLE_AXES, shape=[3, 64, 64]))
    experiment = await create_experiment(ctx, "Exp")
    await add_view(ctx, experiment, await seed.create_lens(ctx, derived))

    unplaced = await _view(aexecute, experiment)
    assert (unplaced["placement"], unplaced["pathToWorld"]) == ("UNREGISTERED", None), "nothing places the derived dataset yet"

    # Register the SOURCE -- the claim that is actually true.
    world = await sync_to_async(lambda: experiment.world)()
    await seed.register_into_world(ctx, world, source)

    placed = await _view(aexecute, experiment)
    assert placed["placement"] == "PLACED"
    path = placed["pathToWorld"]
    assert path[-1]["transformation"]["output"]["residents"] == [], "the walk ends in a space nothing lives in: a world"
    assert str(source.coordinate_system_id) in [step["transformation"]["input"]["id"] for step in path], "the walk goes through the source dataset's own space"


# --- reading the lineage, from both ends --------------------------------------------------------


async def test_the_derivation_edge_is_readable_on_the_dataset(aexecute, zarr_store, authenticated_context):
    """`derivedFrom` is the edge itself, so a client can compose it -- not a label about it."""
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Source")
    derived = await derive(aexecute, zarr_store, "Sorted", lens=await seed.create_lens(ctx, source), axes=seed.SIMPLE_AXES, shape=[3, 64, 64])
    assert not derived.errors, derived.errors

    result = await aexecute(DERIVED, {"id": derived.data["createArrayDataset"]["id"]})
    assert not result.errors, result.errors

    (edge,) = result.data["arrayDataset"]["derivedFrom"]
    assert edge["kind"] == "IDENTITY"
    assert edge["inputAxes"] == ["c", "y", "x"]
    assert edge["outputAxes"] == ["c", "y", "x"]
    assert edge["output"]["id"] == str(source.coordinate_system_id), "an unsliced lens owns no space, so the edge lands in the source's own grid"

    # An acquired dataset was derived from nothing, and says so.
    plain = await aexecute(DERIVED, {"id": str(source.pk)})
    assert not plain.errors, plain.errors
    assert plain.data["arrayDataset"]["derivedFrom"] == []


async def test_the_derivation_is_readable_from_the_source_as_well(aexecute, zarr_store, authenticated_context):
    """`derivedDatasets` answers "what came out of this" -- the same edges, read backwards.

    A source cannot otherwise be asked what was made from it: `derivedFrom` only points
    upwards, so finding a dataset's descendants meant fetching every dataset and reading
    each one's parents. The inverse is a query over the same edges, so the two can never
    disagree; there is no back-reference column to fall out of step.

    On the lens as well as the dataset, because a derivation names a *lens*: which selection a
    sorting was computed from is the finer question, and the dataset-level field aggregates it
    over every lens. The lens here is sliced, so the two questions are asked of two spaces.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Source")
    lens = await seed.create_lens(ctx, source, slices=[{"axis": "y", "start": 8, "stop": 40}])

    derived = await derive(aexecute, zarr_store, "Sorted", lens=lens, axes=seed.SIMPLE_AXES, shape=[3, 32, 64])
    assert not derived.errors, derived.errors
    child_id = derived.data["createArrayDataset"]["id"]

    assert [child["id"] for child in await _children(aexecute, source)] == [child_id]

    # The same fact through the lens the derivation actually named.
    from_lens = await aexecute("query L($id: ID!) { lens(id: $id) { id derivedDatasets { id name } } }", {"id": str(lens.pk)})
    assert not from_lens.errors, from_lens.errors
    assert [child["name"] for child in from_lens.data["lens"]["derivedDatasets"]] == ["Sorted"]

    # A leaf produced nothing, and says so rather than echoing its own parent back.
    leaf = await aexecute(DERIVED_DATASETS, {"id": child_id})
    assert not leaf.errors, leaf.errors
    assert leaf.data["arrayDataset"]["derivedDatasets"] == []


async def test_a_fusion_is_a_child_of_every_source_it_named_exactly_once(aexecute, zarr_store, authenticated_context):
    """Report every child, not just the ones this source places -- and each child once.

    Two traps the naive query falls into. A fusion has several parents but only the first
    *places* it, so a walk that follows placement would hide the fusion from its second
    source -- yet it is just as much derived from it, and `derivedFrom` says so from the
    other side. And a fusion of two lenses of ONE source has two edges landing in that
    source: one relation, two facts, and the child must still be listed once.
    """
    ctx = authenticated_context
    primary, primary_lens, secondary, secondary_lens = await _two_sources(ctx)

    fusion = await _fuse(aexecute, zarr_store, "Fused", [_identity(primary_lens), _identity(secondary_lens)])
    assert not fusion.errors, fusion.errors
    fused_id = fusion.data["createArrayDataset"]["id"]

    for source in (primary, secondary):
        assert [child["id"] for child in await _children(aexecute, source)] == [fused_id], f"{source.name} is a real parent of the fusion, primary or not"

    # Two lenses of ONE source: two edges into it, still one child.
    other_lens = await seed.create_lens(ctx, primary, slices=[{"axis": "y", "start": 8, "stop": 40}])
    two_lens_fusion = await _fuse(aexecute, zarr_store, "SelfFused", [_identity(primary_lens), _identity(other_lens)])
    assert not two_lens_fusion.errors, two_lens_fusion.errors
    assert len(two_lens_fusion.data["createArrayDataset"]["derivedFrom"]) == 2, "the dedup below is only a test if two edges really land in one source"

    names = [child["name"] for child in await _children(aexecute, primary)]
    assert names.count("SelfFused") == 1, f"one child, however many of its edges land here: {names}"


async def test_an_unmappable_child_is_still_a_child(aexecute, zarr_store, authenticated_context):
    """The inverse is kind-blind, exactly as `derivedFrom` is.

    "This came from that, and the geometry did not survive" is a derivation -- the one the
    UNMAPPABLE kind exists to record. The placement walks refuse that edge; a lineage
    report must not, or the source silently disowns the very data whose provenance is
    hardest to reconstruct by other means.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Raw")
    measured = await derive(aexecute, zarr_store, "Measurements", lens=await seed.create_lens(ctx, source), axes=seed.SIMPLE_AXES, shape=[3, 64, 64], transform={"kind": "UNMAPPABLE"})
    assert not measured.errors, measured.errors

    assert [child["name"] for child in await _children(aexecute, source)] == ["Measurements"]


async def test_a_calibrated_dataset_is_not_its_own_child(aexecute, authenticated_context):
    """A sampling law runs sample grid -> clock, and looks exactly like a derivation leaving this dataset's space.

    It is nothing of the sort: a dataset is not computed from itself, and a clock is nobody's
    data. Only the guard that skips the dataset asking (and the rule that a space nothing lives
    in is no container) keeps it out, so this is the test that says the guard is load-bearing.
    """
    dataset = await seed.create_dataset(authenticated_context, "Sampled", seed.T_AXES, [1000])
    await seed.create_physical_space(authenticated_context, dataset, seed.CLOCK_AXES, affine=[[0.001, 0.0]], name="clock")

    assert await _children(aexecute, dataset) == [], "a clock is a space to be sampled onto, not a descendant"
    assert await _names(aexecute, {"notDerived": True}) == {"Sampled"}, "and the sampling law does not make the dataset a derived one either"


# --- what a derivation may state ----------------------------------------------------------------


async def test_a_projection_drops_an_axis_as_by_dimension(aexecute, zarr_store, authenticated_context):
    """A mean over channels is a rank change, and BY_DIMENSION is how a rank change is stated."""
    ctx = authenticated_context
    source = await seed.create_dataset(ctx, "Probe", seed.TC_AXES, _TC_SHAPE)

    derived = await derive(aexecute, zarr_store, "ChannelMean", lens=await seed.create_lens(ctx, source), axes=seed.T_AXES, shape=[1000], transform={"kind": "BY_DIMENSION", "inputAxes": ["t"], "outputAxes": ["t"]})
    assert not derived.errors, derived.errors

    (edge,) = derived.data["createArrayDataset"]["derivedFrom"]
    assert edge["kind"] == "BY_DIMENSION"
    # The projection says nothing about c -- which is exactly the truth, and exactly what a
    # square edge could not have said.
    assert edge["inputAxes"] == ["t"]
    assert edge["outputAxes"] == ["t"]


async def test_identity_is_not_a_rank_claim_in_disguise(aexecute, zarr_store, authenticated_context):
    """IDENTITY says the two grids ARE the same. Between different axes that is a lie.

    IDENTITY carries no parameters, so no rank check would otherwise look at it. A projection
    stated as an identity would say that a (t, c) recording and its (t) channel mean are the
    same space, and nothing downstream could tell that apart from a genuine in-place operation.
    """
    ctx = authenticated_context
    source = await seed.create_dataset(ctx, "Probe", seed.TC_AXES, _TC_SHAPE)

    derived = await derive(aexecute, zarr_store, "ChannelMean", lens=await seed.create_lens(ctx, source), axes=seed.T_AXES, shape=[1000], transform={"kind": "IDENTITY"})

    assert derived.errors, "an identity between (t,c) and (t) is a rank change wearing an identity's clothes"
    assert "IDENTITY" in str(derived.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="ChannelMean").aexists(), "and the refusal takes the dataset with it: the dataset, its grid and its edges are one transaction"
    assert not await models.CoordinateSystem.objects.filter(name="ChannelMean/intrinsic").aexists()


async def test_a_categorized_derivation_states_it_on_the_edge(aexecute, zarr_store, authenticated_context):
    """`valueRelation` is the other axis of a derivation edge: what happened to the *numbers*.

    The spatial kind says where a spike sorting's samples sit (IDENTITY); CATEGORIZED says what
    happened to the values -- they became unit ids. The portable half of mikro's
    `test_a_categorized_derivation_bootstraps_a_label_layer`; the label layer it bootstraps
    there has no counterpart here.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Raw")
    lens = await seed.create_lens(ctx, source)

    sorted_ = await derive(aexecute, zarr_store, "Sorted", lens=lens, axes=seed.SIMPLE_AXES, shape=[3, 64, 64], value_relation="CATEGORIZED")
    assert not sorted_.errors, sorted_.errors
    assert sorted_.data["createArrayDataset"]["derivedFrom"][0]["valueRelation"] == "CATEGORIZED", "the statement rides the derivation edge itself"

    filtered = await derive(aexecute, zarr_store, "Filtered", lens=lens, axes=seed.SIMPLE_AXES, shape=[3, 64, 64], value_relation="TRANSFORMED")
    assert not filtered.errors, filtered.errors
    assert filtered.data["createArrayDataset"]["derivedFrom"][0]["valueRelation"] == "TRANSFORMED"

    def categorized() -> set[int]:
        return graph_logic.categorized_dataset_ids({int(sorted_.data["createArrayDataset"]["id"]), int(filtered.data["createArrayDataset"]["id"]), source.pk})

    assert await sync_to_async(categorized)() == {int(sorted_.data["createArrayDataset"]["id"])}, "and the one reader of it tells the two apart"


async def test_a_derivation_may_be_a_map_axis(aexecute, zarr_store, authenticated_context):
    """A transposed dataset states its derivation as the pure permutation it is.

    `derivedFrom` carries the same union every authored edge does, so a MAP_AXIS is stated
    directly instead of dressed up as a BY_DIMENSION.
    """
    ctx = authenticated_context
    source = await seed.create_dataset(ctx, "Probe", seed.TC_AXES, _TC_SHAPE)

    result = await derive(
        aexecute,
        zarr_store,
        "Transposed",
        axes=[seed.axis("c", enums.AxisType.CHANNEL), seed.axis("t", enums.AxisType.TIME)],
        shape=[4, 1000],
        lens=await seed.create_lens(ctx, source),
        # Pairs are positional, `inputAxes[i] -> outputAxes[i]`, and an axis maps onto the axis it
        # *is*: the child's `c` is the source's `c`. What is permuted is the storage order, which
        # the edge reads off the two systems. Pairing `c -> t` instead would relate a channel
        # index to an instant, and the graph refuses that (see the test below).
        transform={"kind": "MAP_AXIS", "inputAxes": ["c", "t"], "outputAxes": ["c", "t"]},
    )
    assert not result.errors, result.errors

    (reported,) = result.data["createArrayDataset"]["derivedFrom"]
    assert reported["kind"] == "MAP_AXIS"
    assert reported["inputAxes"] == ["c", "t"] and reported["outputAxes"] == ["c", "t"]

    edge = await models.Transformation.objects.aget(pk=reported["id"])
    assert edge.validity == enums.PlacementValidityChoices.MANUAL.value, "a derivation is an authored claim"
    assert edge.params == {}, "a MAP_AXIS's map is its axis lists; it carries no parameters"


async def test_a_map_axis_cannot_put_a_channel_in_correspondence_with_time(aexecute, zarr_store, authenticated_context):
    """A channel index is not an instant. mikro's version of the test above pairs `x -> y`, two SPACE axes; the
    electrophysiology analogue of "transposed" tempts one to write `c -> t`, which is a different and meaningless claim."""
    ctx = authenticated_context
    source = await seed.create_dataset(ctx, "Probe", seed.TC_AXES, _TC_SHAPE)

    result = await derive(
        aexecute,
        zarr_store,
        "Crossed",
        axes=[seed.axis("c", enums.AxisType.CHANNEL), seed.axis("t", enums.AxisType.TIME)],
        shape=[4, 1000],
        lens=await seed.create_lens(ctx, source),
        transform={"kind": "MAP_AXIS", "inputAxes": ["c", "t"], "outputAxes": ["t", "c"]},
    )
    assert result.errors and "relates two different kinds of axis" in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Crossed").aexists(), "refused before the dataset was written"


async def test_a_derivation_may_be_a_field(authenticated_context):
    """A FIELD derivation writes through the same guards a registration FIELD does.

    Written through the writer directly: at ingest a self-field is unrepresentable (the
    derived system is created in the same mutation), so the API-facing case is a
    pre-existing dataset's system -- and the self-field PROTECT normalization must still
    hold when a direct caller states one, which is what the `field is None` pin proves.

    The field space carries a dataset because a FIELD's map is *the values of an array*:
    `assert_field_is_dereferenceable` refuses a bare space.
    """
    ctx = seed._creation(authenticated_context)
    spikes = await seed.create_dataset(authenticated_context, "unit 3", seed.SPIKE_AXES, [412], value_unit="second")

    def build() -> models.Transformation:
        events = models.CoordinateSystem.objects.create(name="events", creator=ctx.user, organization=ctx.organization)
        models.Axis.objects.create(coordinate_system=events, order=0, name="i", type=enums.AxisTypeChoices.INDEX.value)
        edge = graph_logic.write_relation_edge(
            name="unit 3 <- events",
            input_system=spikes.coordinate_system,
            output_system=events,
            kind="FIELD",
            field=spikes.coordinate_system,
            input_axes=["spike"],
            output_axes=["i"],
            ctx=ctx,
        )
        assert graph_logic.is_traversable(edge) and not graph_logic.is_reverse_traversable(edge), "a FIELD derivation places one way, forwards"
        return edge

    edge = await sync_to_async(build)()
    assert edge.kind == enums.TransformKindChoices.FIELD.value
    assert edge.input_axes == ["spike"] and edge.output_axes == ["i"]
    assert edge.field_id is None, "a self-field is stored as null, or PROTECT would make the dataset's space undeletable"
    assert edge.validity == enums.PlacementValidityChoices.MANUAL.value


# --- the `notDerived` filter ----------------------------------------------------------------------


async def test_derived_from_and_not_derived_filters(aexecute, zarr_store, authenticated_context):
    """`notDerived` lists the roots -- `graph_logic.derivation_edges` as a query.

    So it inherits that function's rule: an edge landing in a space nothing lives in is not a
    derivation (a sampling law runs sample grid -> clock, and would otherwise make every
    sampled dataset a derived one). mikro's version also pins a `derivedFrom: ID` filter and
    its composition with `spec`/`hasPhysicalSpace`; none of the three exists on `ArrayDatasetFilter`.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Acquired")
    child = await derive(aexecute, zarr_store, "Filtered", lens=await seed.create_lens(ctx, source), axes=seed.SIMPLE_AXES, shape=[3, 64, 64])
    assert not child.errors, child.errors

    # The calibration edge is the trap: it leaves the source's own system just as a
    # derivation does.
    await seed.create_physical_space(
        ctx,
        source,
        axes=[seed.physical_axis("c", enums.AxisType.CHANNEL, "a.u."), seed.physical_axis("y", enums.AxisType.SPACE, "micrometer"), seed.physical_axis("x", enums.AxisType.SPACE, "micrometer")],
        scale=[1.0, 0.5, 0.5],
    )

    # The source is not its own child, however many edges leave its system.
    assert await _names(aexecute, {"notDerived": True}) == {"Acquired"}
    assert await _names(aexecute, {"notDerived": False}) == {"Filtered"}
    assert await _names(aexecute, {"notDerived": None}) == {"Acquired", "Filtered"}, "an explicit null is no constraint, not `false`"

    # And it composes with the other lookups rather than replacing them.
    assert await _names(aexecute, {"notDerived": True, "name": {"iContains": "filt"}}) == set()
    assert await _names(aexecute, {"notDerived": False, "name": {"iContains": "filt"}}) == {"Filtered"}


async def test_derivation_filters_are_kind_blind(aexecute, zarr_store, authenticated_context):
    """An UNMAPPABLE child still came from here: reporting it is the whole point of the kind."""
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Acquired")
    unmappable = await derive(aexecute, zarr_store, "Sorted", lens=await seed.create_lens(ctx, source), axes=seed.SIMPLE_AXES, shape=[3, 64, 64], transform={"kind": "UNMAPPABLE"}, value_relation="CATEGORIZED")
    assert not unmappable.errors, unmappable.errors

    assert await _names(aexecute, {"notDerived": True}) == {"Acquired"}
    assert await _names(aexecute, {"notDerived": False}) == {"Sorted"}


async def test_derived_from_reports_every_parent_of_a_fusion(aexecute, zarr_store, authenticated_context):
    """A fusion has two real parents, and both are roots -- not only the one that places it."""
    ctx = authenticated_context
    _, lens_a, _, lens_b = await _two_sources(ctx)

    fused = await _fuse(aexecute, zarr_store, "Fused", [_identity(lens_a), _identity(lens_b)])
    assert not fused.errors, fused.errors

    assert await _names(aexecute, {"notDerived": True}) == {"Left", "Right"}
    assert await _names(aexecute, {"notDerived": False}) == {"Fused"}


# --- several parents ------------------------------------------------------------------------------


async def test_a_fusion_records_every_parent_in_declared_order(aexecute, zarr_store, authenticated_context):
    """`derivedFrom` is the declared list, not a pk lottery: swap the input and the order swaps."""
    left, left_lens, right, right_lens = await _two_sources(authenticated_context)

    async def fuse(name: str, first: models.Lens, second: models.Lens) -> str:
        result = await _fuse(aexecute, zarr_store, name, [_identity(first), _identity(second)])
        assert not result.errors, result.errors
        return result.data["createArrayDataset"]["id"]

    fused_id = await fuse("Fused", left_lens, right_lens)
    swapped_id = await fuse("Swapped", right_lens, left_lens)

    left_space, right_space = str(left.coordinate_system_id), str(right.coordinate_system_id)
    for dataset_id, expected in ((fused_id, [left_space, right_space]), (swapped_id, [right_space, left_space])):
        result = await aexecute(DERIVED, {"id": dataset_id})
        assert not result.errors, result.errors
        assert [edge["output"]["id"] for edge in result.data["arrayDataset"]["derivedFrom"]] == expected, "the first entry is the primary parent, and only the creator says which that is"


async def test_a_duplicate_source_is_refused(aexecute, zarr_store, authenticated_context):
    """One entry per source: a second entry for the same lens is two claims about one relation."""
    _, left_lens, _, _ = await _two_sources(authenticated_context)

    result = await _fuse(aexecute, zarr_store, "DoubleCounted", [_identity(left_lens), _identity(left_lens)])
    assert result.errors, "the same lens twice is not a fusion, it is a contradiction waiting to be written"
    # "source", not "lens": the duplicate check keys on (kind, id), so it catches two entries
    # naming the same dataset as readily as two naming the same lens -- and does not collide
    # two different kinds of source that happen to share a numeric id.
    assert "distinct source" in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="DoubleCounted").aexists()


async def test_an_unmappable_entry_may_not_hide_a_mappable_parent(aexecute, zarr_store, authenticated_context):
    """The primary is the placing parent, so an UNMAPPABLE first entry ahead of a mappable one is refused.

    The walks refuse an UNMAPPABLE primary -- that is its contract -- so a mappable parent
    behind it would be recorded and never placed by. Reversed, the same pair is fine: the
    mappable parent places, the UNMAPPABLE one records the history that did not survive.
    """
    _, left_lens, _, right_lens = await _two_sources(authenticated_context)
    lost = {"kind": "UNMAPPABLE", "reason": "geometry lost"}

    refused = await _fuse(aexecute, zarr_store, "HiddenParent", [{"kind": "LENS", "lens": str(left_lens.pk), "transform": lost}, _identity(right_lens)])
    assert refused.errors, "a mappable parent must not hide behind an UNMAPPABLE primary"
    assert "primary" in str(refused.errors[0])

    # An entry with no transform at all IS unmappable, so it hides a parent just the same.
    silent = await _fuse(aexecute, zarr_store, "SilentParent", [{"kind": "LENS", "lens": str(left_lens.pk)}, _identity(right_lens)])
    assert silent.errors and "primary" in str(silent.errors[0])

    accepted = await _fuse(aexecute, zarr_store, "DeclaredParent", [_identity(right_lens), {"kind": "LENS", "lens": str(left_lens.pk), "transform": lost}])
    assert not accepted.errors, accepted.errors


async def test_an_all_unmappable_fusion_is_a_root_and_its_layer_is_refused_as_unmappable(aexecute, zarr_store, authenticated_context):
    """History from several sources, geometry from none: the data is its own root, and its view reads UNMAPPABLE.

    Not UNREGISTERED: there is no missing registration to author, and the badge must not send
    anyone looking for one. (mikro pins the same verdict on its layer mutation's refusal; the
    query-time state reads the same predicate, and is what this service exposes.)
    """
    ctx = authenticated_context
    _, left_lens, _, right_lens = await _two_sources(ctx)
    reduced = {"kind": "UNMAPPABLE", "reason": "reduced away"}

    derived = await _fuse(aexecute, zarr_store, "Measurements", [{"kind": "LENS", "lens": str(left_lens.pk), "transform": reduced}, {"kind": "LENS", "lens": str(right_lens.pk), "transform": reduced}])
    dataset = await derived_dataset(derived)

    ancestors = await sync_to_async(graph_logic.lineage_ancestors)(dataset)
    root = await sync_to_async(graph_logic.primary_lineage_root)(dataset)
    assert ancestors == [], "no parent maps, so none places -- the spatial lineage is empty"
    assert root.pk == dataset.pk

    experiment = await create_experiment(ctx, "Exp")
    await add_view(ctx, experiment, await seed.create_lens(ctx, dataset))

    view = await _view(aexecute, experiment)
    assert view["pathToWorld"] is None
    assert view["placement"] == "UNMAPPABLE", "nothing can place this, which is not the same as nothing having placed it yet"


async def test_the_lineage_is_the_primary_chain_and_history_keeps_every_parent(aexecute, zarr_store, authenticated_context):
    """`lineage_ancestors` is the fact tree's chain; `derivation_edges` is the full history.

    A fusion owes both parents historically, but it *sits* where its primary sits: the
    spatial lineage walks the first-declared edge only, and the second parent is a
    recorded fact that never places.
    """
    left, left_lens, _, right_lens = await _two_sources(authenticated_context)
    dataset = await derived_dataset(await _fuse(aexecute, zarr_store, "Fused", [_identity(left_lens), _identity(right_lens)]))

    ancestors = await sync_to_async(graph_logic.lineage_ancestors)(dataset)
    assert [ancestor.pk for ancestor in ancestors] == [left.pk], "the spatial lineage is the primary chain: the fusion sits where its first-declared parent sits"

    edges = await sync_to_async(graph_logic.derivation_edges)(dataset)
    assert len(edges) == 2, "history is not placement: derivedFrom still reports every parent"

    root = await sync_to_async(graph_logic.primary_lineage_root)(dataset)
    assert root.pk == left.pk, "the root is reached by taking the FIRST edge at every hop, not any edge"


async def test_a_fusion_places_through_either_parent(aexecute, zarr_store, authenticated_context):
    """A fusion reaches the world through *whichever* parent is registered.

    Every derivation edge is walkable, rivals and all, so a fusion sits wherever a parent of
    it sits and the choice between two routes is the tie-break's, not the data's. It is the
    same decision that lets a space hold rival claims.
    """
    ctx = authenticated_context
    left, left_lens, right, right_lens = await _two_sources(ctx)
    dataset = await derived_dataset(await _fuse(aexecute, zarr_store, "Fused", [_identity(left_lens), _identity(right_lens)]))

    experiment = await create_experiment(ctx, "Exp")
    await add_view(ctx, experiment, await seed.create_lens(ctx, dataset))

    await _register(aexecute, right, experiment.world_id)
    assert (await _view(aexecute, experiment))["placement"] == "PLACED", "the secondary parent's registration places the fusion too"

    # And registering the primary as well leaves the fusion placed -- two routes now, which
    # is exactly the rival case the tie-break exists to settle.
    await _register(aexecute, left, experiment.world_id)

    path = (await _view(aexecute, experiment))["pathToWorld"]
    assert path is not None
    assert path[-1]["transformation"]["output"]["residents"] == [], "the path ends in a space nothing lives in: a world"
    hops = [step["transformation"]["input"]["id"] for step in path]
    assert str(left.coordinate_system_id) in hops, "the walk goes through the primary parent's own system"
    assert str(right.coordinate_system_id) not in hops, "and never through the secondary's"


# --- which of two routes --------------------------------------------------------------------------


def _best_path(source_pk: int, target_pk: int):  # noqa: ANN202
    """Every top-level edge, fetched the way the real universe fetches them, then searched.

    `adjacency_of` reads both endpoints and their axes (through `is_reverse_traversable` ->
    `edge_axis_names`), so the same `select_related`/`prefetch_related` the production fetchers
    use is not an optimisation here -- without it the reads happen lazily, one per edge.
    """
    edges = list(models.Transformation.objects.filter(parent__isnull=True).select_related("input", "output").prefetch_related("children", "input__axes", "output__axes"))
    return graph_logic._bfs_path(graph_logic.adjacency_of(edges), source_pk, target_pk)


def _yx_space(ctx, name: str) -> models.CoordinateSystem:  # noqa: ANN001
    made = models.CoordinateSystem.objects.create(name=name, creator=ctx.user, organization=ctx.organization)
    graph_logic.create_pixel_axes(made, seed.YX_AXES)
    return made


async def test_a_validated_route_beats_a_shorter_unknown_one(authenticated_context):
    """The rival case the tie-break exists to settle, now actually settled.

    The walk used to be an unweighted BFS: fewest hops, ties by edge pk, and `validity` never
    read during the search. So the *first-authored* one-hop UNKNOWN registration won over a
    two-hop chain of VALIDATED ones -- and `placementValidity` then dutifully reported UNKNOWN.
    The system chose the worse answer and said so.

    The rival is authored **first**, so it also holds the lower pk: under the old rule it won on
    both counts. It must now lose on the one that matters.
    """
    ctx = seed._creation(authenticated_context)
    source, midpoint, world = [await sync_to_async(_yx_space)(ctx, name) for name in ("Source", "Midpoint", "World")]
    build = sync_to_async(graph_logic.build_registration_edge)

    # Authored first, so it is both the shortest route and the lowest pk.
    guess = await build(input_system=source, output_system=world, kind="TRANSLATION", translation=[9.0, 9.0], validity=enums.PlacementValidity.UNKNOWN.value, ctx=ctx)
    # The longer, better-known route.
    await build(input_system=source, output_system=midpoint, kind="TRANSLATION", translation=[1.0, 1.0], validity=enums.PlacementValidity.VALIDATED.value, ctx=ctx)
    await build(input_system=midpoint, output_system=world, kind="TRANSLATION", translation=[2.0, 2.0], validity=enums.PlacementValidity.VALIDATED.value, ctx=ctx)

    path = await sync_to_async(_best_path)(source.pk, world.pk)

    assert path is not None
    assert len(path) == 2, "the two-hop VALIDATED chain wins, though it is longer and later"
    assert guess.pk not in {edge.pk for edge, _ in path}, "the shorter UNKNOWN guess is not the route"
    assert graph_logic.weakest_validity([edge.validity for edge, _ in path]) == enums.PlacementValidityChoices.VALIDATED.value


async def test_among_equally_known_routes_the_shortest_still_wins(authenticated_context):
    """Validity is the first key, not the only one: hops still break its ties."""
    ctx = seed._creation(authenticated_context)
    source, midpoint, world = [await sync_to_async(_yx_space)(ctx, name) for name in ("Source", "Midpoint", "World")]

    for a, b in ((source, midpoint), (midpoint, world), (source, world)):
        await sync_to_async(graph_logic.build_registration_edge)(input_system=a, output_system=b, kind="TRANSLATION", translation=[1.0, 1.0], validity=enums.PlacementValidity.VALIDATED.value, ctx=ctx)

    path = await sync_to_async(_best_path)(source.pk, world.pk)
    assert path is not None and len(path) == 1, "all three edges are equally known, so the direct one wins on hops"
