"""UNMAPPABLE: the one edge that says nothing corresponds, and is believed.

Ported from mikro's ``tests/test_unmappable_transforms.py``. Here the everyday UNMAPPABLE is
a spike sorting or a feature extraction: datasets computed from a recording whose sample index
did not survive the computation. ``createArrayDataset`` writes that edge whenever a ``derivedFrom``
entry states no transform, so the gates below are live code in this service and were untested.

Every other transform kind asserts that a point maps. There was no way to assert that none
does -- so data whose geometry a task destroyed could only be recorded by lying with an
IDENTITY, or not recorded at all, which loses the lineage along with the geometry.

The kind is easy. What earns it is that the graph *acts* on it: the placement search
refuses the edge in both directions, and the lineage stops there -- while discovery still
returns it and `derivedFrom` still reports it, because "why can this not be placed" is a
question the client is entitled to an answer to.

Every test below that pins a gate is written so that removing the gate makes it fail. The
views go in through the ORM (``_helpers.add_layer``), as they do in mikro: the query-time
behaviour of an unplaced view is what is pinned, and no creating mutation would admit one.
"""

import pytest
from asgiref.sync import sync_to_async

from core import enums, models
from core.logic import graph as graph_logic
from tests import seed
from tests.coords._helpers import add_layer, create_experiment, derive, derived_dataset

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


REGISTER = """
mutation Register($input: CreateTransformationInput!) {
  createTransformation(input: $input) { id kind }
}
"""

PLACEMENT = """
query Placement($id: ID!) {
  experiment(id: $id) {
    layers { id placement pathToWorld { transformation { id kind } } }
    world { registrations { id kind name } }
  }
}
"""

DERIVED = """
query Derived($id: ID!) {
  arrayDataset(id: $id) {
    id
    derivedFrom { id kind ... on UnmappableTransformation { reason } output { id } }
  }
}
"""

GRAPH = """
query Graph($id: ID!) {
  coordinateGraph(coordinateSystem: $id) {
    systems { id residents { __typename } }
    transformations { id kind }
  }
}
"""

_AFFINE_3D = [
    [1.0, 0.0, 0.0, 5.0],
    [0.0, 1.0, 0.0, 5.0],
    [0.0, 0.0, 1.0, 0.0],
]


async def _experiment_with_registered_source(aexecute, ctx, source: models.ArrayDataset) -> models.Experiment:  # noqa: ANN001
    """An experiment whose (z, y, x) world the (c, y, x) source is registered into, by an affine someone measured."""
    experiment = await create_experiment(ctx, "Exp")
    registered = await aexecute(REGISTER, {"input": {"input": str(source.coordinate_system_id), "output": str(experiment.world_id), "transform": {"kind": "AFFINE", "affine": _AFFINE_3D}}})
    assert not registered.errors, registered.errors
    return experiment


async def _views(aexecute, experiment: models.Experiment) -> list[dict]:  # noqa: ANN001
    result = await aexecute(PLACEMENT, {"id": str(experiment.pk)})
    assert not result.errors, result.errors
    return result.data["experiment"]["layers"]


async def test_an_unmappable_edge_is_not_a_way_to_world(aexecute, zarr_store, authenticated_context):
    """The search will not cross it, so the data it relates has no path -- which is the truth.

    ABLATION: un-gate the forward step in `graph.adjacency_of` and the BFS walks straight
    through the derivation into the source's systems and out to world, handing the client a
    composable path across a stated non-correspondence. It would look exactly like every
    other path.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Raw")
    source_lens = await seed.create_lens(ctx, source)
    experiment = await _experiment_with_registered_source(aexecute, ctx, source)

    derived = await derive(aexecute, zarr_store, "Features", lens=source_lens, axes=seed.SIMPLE_AXES, shape=[3, 64, 64], transform={"kind": "UNMAPPABLE", "reason": "feature extraction over the sample axis"})
    dataset = await derived_dataset(derived)
    await add_layer(ctx, experiment, await seed.create_lens(ctx, dataset))

    (view,) = await _views(aexecute, experiment)
    assert view["pathToWorld"] is None, "the source is placed, but nothing relates this data to the source -- so it is not placed"
    # And the client is told *which* kind of null this is.
    assert view["placement"] == "UNMAPPABLE"


async def test_an_unmappable_edge_in_a_scene_is_still_not_a_way_to_world(aexecute, authenticated_context):
    """Even registered into the experiment's world, the search will not walk it.

    This is the case that pins the FORWARD gate specifically. The world's own edges are
    in every view's adjacency, so an UNMAPPABLE edge authored straight into the world -- by
    a client that thought registering it was how you place the data -- sits one hop from
    world in the search's own edge set. Nothing but the gate stops the BFS taking it and
    reporting a placement.

    ABLATION: un-gate the forward step in `graph.adjacency_of` and `pathToWorld` resolves.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Features")
    lens = await seed.create_lens(ctx, dataset)

    # A world sharing no axis NAME with the dataset, so the unmappable edge is the only
    # candidate route to world.
    experiment = await create_experiment(ctx, "Exp", axes=[seed.physical_axis("u", enums.AxisType.SPACE, "micrometer"), seed.physical_axis("v", enums.AxisType.SPACE, "micrometer")])
    registered = await aexecute(
        REGISTER,
        {"input": {"input": str(dataset.coordinate_system_id), "output": str(experiment.world_id), "transform": {"kind": "UNMAPPABLE", "reason": "nothing about this data is anywhere"}}},
    )
    assert not registered.errors, registered.errors
    await add_layer(ctx, experiment, lens)

    (view,) = await _views(aexecute, experiment)
    assert view["pathToWorld"] is None, "an edge that maps nothing is not a route, wherever it is filed"
    assert view["placement"] == "UNMAPPABLE"


async def test_the_lineage_stops_but_the_provenance_does_not(aexecute, zarr_store, authenticated_context):
    """Two halves that must not be confused: placement ends here, history does not.

    `lineage_ancestors` answers "who places this", and nothing places data across an
    UNMAPPABLE edge -- so this dataset is its own root. `derivedFrom` answers "where did
    this come from", and the answer is the edge itself. Gate the wrong one of the two and
    `derivedFrom` goes null, which is precisely the silence UNMAPPABLE exists to break.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Raw")
    source_lens = await seed.create_lens(ctx, source)

    derived = await derive(aexecute, zarr_store, "Features", lens=source_lens, axes=seed.SIMPLE_AXES, shape=[3, 64, 64], transform={"kind": "UNMAPPABLE", "reason": "feature extraction"})
    dataset = await derived_dataset(derived)

    ancestors = await sync_to_async(graph_logic.lineage_ancestors)(dataset)
    root = await sync_to_async(graph_logic.primary_lineage_root)(dataset)
    assert ancestors == [], "nothing places this data, so it inherits no placement -- it is a root"
    assert root.pk == dataset.pk

    result = await aexecute(DERIVED, {"id": str(dataset.pk)})
    assert not result.errors, result.errors

    edges = result.data["arrayDataset"]["derivedFrom"]
    assert len(edges) == 1, "the lineage is the whole reason to record an unmappable relation"
    assert edges[0]["kind"] == "UNMAPPABLE"
    assert edges[0]["reason"] == "feature extraction"


async def test_an_unmappable_edge_is_still_discoverable(aexecute, zarr_store, authenticated_context):
    """Discovery is kind-blind; placement is not. That asymmetry is the design.

    A client that gets `pathToWorld: null` needs to find out *why*, and the edge is the
    answer. Filtering it out of `coordinateGraph` -- which someone will eventually be
    tempted to do, on the grounds that it "goes nowhere" -- would leave the client with a
    null and no way to interpret it.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Raw")
    source_lens = await seed.create_lens(ctx, source)

    derived = await derive(aexecute, zarr_store, "Features", lens=source_lens, axes=seed.SIMPLE_AXES, shape=[3, 64, 64], transform={"kind": "UNMAPPABLE"})
    dataset = await derived_dataset(derived)

    result = await aexecute(GRAPH, {"id": str(dataset.coordinate_system_id)})
    assert not result.errors, result.errors

    graph = result.data["coordinateGraph"]
    assert "UNMAPPABLE" in [edge["kind"] for edge in graph["transformations"]]
    # And the source's systems are reachable *as nodes* -- relatedness is real, it is only
    # the coordinates that do not travel.
    assert str(source.coordinate_system_id) in [system["id"] for system in graph["systems"]]


def _atlas(ctx, name: str = "Atlas") -> models.CoordinateSystem:  # noqa: ANN001
    """A unit-less (c, y, x) space, written as rows."""
    atlas = models.CoordinateSystem.objects.create(name=name, organization=ctx.request.organization)
    for index, axis in enumerate(["c", "y", "x"]):
        models.Axis.objects.create(coordinate_system=atlas, order=index, name=axis, type=enums.AxisTypeChoices.SPACE.value if axis != "c" else enums.AxisTypeChoices.CHANNEL.value)
    return atlas


async def test_a_displacement_field_is_not_walked_backwards(authenticated_context):
    """Rank was never the whole rule; it only looked like it was.

    Every kind that was creatable happened to be invertible, so "same number of axes on
    both sides" was a sufficient test -- and stopped being one the moment a FIELD became
    writable. A warp field maps N axes to N axes and has no closed-form inverse at all, so
    a rank-only gate hands the client an `inverted: true` step it cannot honour.

    ABLATION: revert `is_reverse_traversable` to the rank comparison and this passes a path
    back, inverting a displacement field.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Warped")

    def build() -> tuple[models.Transformation, models.Transformation]:
        grid = dataset.coordinate_system
        world = _atlas(ctx)

        # The warp field is a node, not a store on the edge: its own space, carrying the
        # DISPLACEMENT value axis that says its numbers are offsets rather than positions.
        field = models.CoordinateSystem.objects.create(name="Warp field", organization=ctx.request.organization)
        for index, (axis, kind) in enumerate((("y", enums.AxisTypeChoices.SPACE), ("x", enums.AxisTypeChoices.SPACE), ("d", enums.AxisTypeChoices.DISPLACEMENT))):
            models.Axis.objects.create(coordinate_system=field, order=index, name=axis, type=kind.value)

        # Authored world -> grid, so reaching world from the data REQUIRES inverting it.
        warp = models.Transformation.objects.create(kind=enums.TransformKindChoices.FIELD.value, input=world, output=grid, field=field, organization=ctx.request.organization)
        scale = models.Transformation.objects.create(kind=enums.TransformKindChoices.SCALE.value, input=grid, output=world, params={"scale": [1.0, 2.0, 2.0]}, organization=ctx.request.organization)
        return warp, scale

    warp, scale = await sync_to_async(build)()

    assert await sync_to_async(graph_logic.is_reverse_traversable)(warp) is False, "a displacement field has no closed-form inverse, whatever its rank"
    assert await sync_to_async(graph_logic.is_traversable)(warp) is True, "forwards it is a perfectly good map"

    # The fence: an equal-rank SCALE still inverts, so the gate has not simply been welded shut.
    assert await sync_to_async(graph_logic.is_reverse_traversable)(scale) is True


async def test_a_sequence_is_invertible_only_if_its_children_are(authenticated_context):
    """A wrapper's kind says nothing about whether it can be undone. Its children do.

    A set-membership test on the wrapper's own kind -- the obvious implementation -- would
    wave this through: SEQUENCE is a perfectly invertible kind, right up until one of its
    steps is a warp field.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Warped")
    organization = ctx.request.organization

    def build() -> tuple[models.Transformation, models.Transformation]:
        grid = dataset.coordinate_system
        target = _atlas(ctx)

        field = models.CoordinateSystem.objects.create(name="Warp field", organization=organization)
        models.Axis.objects.create(coordinate_system=field, order=0, name="d", type=enums.AxisTypeChoices.DISPLACEMENT.value)

        honest = models.Transformation.objects.create(kind=enums.TransformKindChoices.SEQUENCE.value, input=grid, output=target, organization=organization)
        models.Transformation.objects.create(kind=enums.TransformKindChoices.SCALE.value, parent=honest, order=0, params={"scale": [1.0, 2.0, 2.0]}, organization=organization)
        models.Transformation.objects.create(kind=enums.TransformKindChoices.TRANSLATION.value, parent=honest, order=1, params={"translation": [0.0, 1.0, 1.0]}, organization=organization)

        warped = models.Transformation.objects.create(kind=enums.TransformKindChoices.SEQUENCE.value, input=grid, output=target, organization=organization)
        models.Transformation.objects.create(kind=enums.TransformKindChoices.SCALE.value, parent=warped, order=0, params={"scale": [1.0, 2.0, 2.0]}, organization=organization)
        models.Transformation.objects.create(kind=enums.TransformKindChoices.FIELD.value, parent=warped, order=1, field=field, organization=organization)

        return honest, warped

    honest, warped = await sync_to_async(build)()

    assert await sync_to_async(graph_logic.is_reverse_traversable)(honest) is True
    assert await sync_to_async(graph_logic.is_reverse_traversable)(warped) is False, "a sequence is only as invertible as its least invertible step"


async def test_an_unmappable_edge_does_not_poison_an_roi_box(aexecute, zarr_store, authenticated_context):
    """An ROI's box is composed along the walk to intrinsic, and that walk must not take it.

    `_edge_towards_intrinsic` picks the first edge out of a system that stays inside the
    dataset. An UNMAPPABLE derivation is such an edge, and taking it would push the box
    through a map that does not exist -- or, since it has no matrix, raise, be swallowed by
    `compute_intrinsic_bbox`, and hand back a box in the wrong frame with an intrinsic
    label on it. Silently.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Raw")
    source_lens = await seed.create_lens(ctx, source)

    derived = await derive(aexecute, zarr_store, "Features", lens=source_lens, axes=seed.SIMPLE_AXES, shape=[3, 64, 64], transform={"kind": "UNMAPPABLE"})
    dataset = await derived_dataset(derived)

    vectors = [[0.0, 0.0, 0.0], [2.0, 8.0, 8.0]]

    def boxes() -> tuple[dict, dict]:
        derived_box = graph_logic.compute_intrinsic_bbox(dataset.coordinate_system, vectors)
        # The same ROI on a dataset with no derivation at all: whatever the box convention
        # is, the unmappable edge must not have changed it.
        plain_box = graph_logic.compute_intrinsic_bbox(source.coordinate_system, vectors)
        return derived_box, plain_box

    derived_box, plain_box = await sync_to_async(boxes)()
    assert derived_box == plain_box, "the walk to intrinsic must not step across an unmappable edge: the box would come back in another dataset's frame, labelled as this one's"


async def test_placement_distinguishes_a_gap_from_an_impossibility(aexecute, zarr_store, authenticated_context):
    """PLACED, UNREGISTERED, UNMAPPABLE -- because a null `pathToWorld` meant two things.

    One of them is a gap in the data: nobody has registered this yet, and authoring the edge
    closes it. The other is a fact about the data: it can never be placed. A client that
    cannot tell them apart either badges real gaps as impossible or sends people looking for
    a registration that cannot exist.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Raw")
    source_lens = await seed.create_lens(ctx, source)
    experiment = await _experiment_with_registered_source(aexecute, ctx, source)

    # PLACED: registered, and the walk finds it.
    await add_layer(ctx, experiment, source_lens)

    # UNMAPPABLE: related to the placed data, and by an edge that maps nothing.
    derived = await derive(aexecute, zarr_store, "Features", lens=source_lens, axes=seed.SIMPLE_AXES, shape=[3, 64, 64], transform={"kind": "UNMAPPABLE"})
    dataset = await derived_dataset(derived)
    await add_layer(ctx, experiment, await seed.create_lens(ctx, dataset))

    # UNREGISTERED: a perfectly placeable dataset that nobody has placed. It shares no axis
    # name with the world, so no registration exists and none can be assumed.
    stranger = await seed.create_dataset(ctx, "Stranger", [seed.axis("object", enums.AxisType.INDEX)], [12])
    await add_layer(ctx, experiment, await seed.create_lens(ctx, stranger))

    states = [view["placement"] for view in await _views(aexecute, experiment)]
    assert states == ["PLACED", "UNMAPPABLE", "UNREGISTERED"], states


async def test_a_fusion_with_one_unmappable_parent_is_a_gap_not_an_impossibility(aexecute, zarr_store, authenticated_context):
    """UNMAPPABLE is claimed only when the data reaches nowhere at all.

    A fusion whose two parents are related to it differently -- one across an edge that maps
    nothing, one across an ordinary identity -- can be placed: register the parent it does
    relate to, or the fusion itself, and the walk finds it. Reading the verdict off "any
    lineage edge is UNMAPPABLE" badged that as impossible and sent whoever read the badge away
    from a gap they could have closed in one mutation.

    The intact parent is deliberately *not* registered into the world here, so the fusion is
    genuinely unplaced. What is being pinned is which of the two reasons it is given.
    """
    ctx = authenticated_context
    destroyed = await seed.create_array_dataset(ctx, "Destroyed source")
    destroyed_lens = await seed.create_lens(ctx, destroyed)
    intact = await seed.create_array_dataset(ctx, "Intact source")
    intact_lens = await seed.create_lens(ctx, intact)

    fused = await derive(
        aexecute,
        zarr_store,
        "Fusion",
        axes=seed.SIMPLE_AXES,
        shape=[3, 64, 64],
        entries=[
            # The primary parent must be one that places the data; the write path refuses an
            # UNMAPPABLE first entry, which is the same rule from the other side.
            {"kind": "LENS", "lens": str(intact_lens.pk), "transform": {"kind": "IDENTITY"}},
            {"kind": "LENS", "lens": str(destroyed_lens.pk), "transform": {"kind": "UNMAPPABLE"}},
        ],
    )
    dataset = await derived_dataset(fused)

    # An experiment over a world nothing in this lineage is registered into.
    experiment = await create_experiment(ctx, "Empty world")
    await add_layer(ctx, experiment, await seed.create_lens(ctx, dataset))

    assert [view["placement"] for view in await _views(aexecute, experiment)] == ["UNREGISTERED"], "the intact parent is a route, so the registration is merely missing"


async def test_the_write_path_refuses_a_map_on_an_unmappable_edge(aexecute, authenticated_context):
    """It carries no parameters, and no rank constrains it. Both halves matter."""
    ctx = authenticated_context
    first = await seed.create_array_dataset(ctx, "Recording")
    second = await seed.create_dataset(ctx, "Units", [seed.axis("object", enums.AxisType.INDEX)], [12])
    grid, units = str(first.coordinate_system_id), str(second.coordinate_system_id)

    # Rank-free: a (c,y,x) grid and a one-axis enumeration of objects, related, with no map.
    # Every other kind would have been rejected here, and rightly.
    made = await aexecute(REGISTER, {"input": {"input": units, "output": grid, "transform": {"kind": "UNMAPPABLE", "reason": "one row per sorted unit"}}})
    assert not made.errors, made.errors
    assert made.data["createTransformation"]["kind"] == "UNMAPPABLE"

    # But it may not carry a map, in the same breath as denying there is one. The parse
    # layer's strict members are the gate that fires through the API: UNMAPPABLE reads
    # `reason` and nothing else.
    lying = await aexecute(REGISTER, {"input": {"input": units, "output": grid, "transform": {"kind": "UNMAPPABLE", "scale": [1.0]}}})
    assert lying.errors, "an UNMAPPABLE edge with a scale asserts a correspondence and denies one at once"
    assert "does not read `scale`" in str(lying.errors[0])

    # And it cannot be refined into one later, through the back door.
    refined = await aexecute(
        "mutation Refine($input: UpdateTransformationInput!) { updateTransformation(input: $input) { id } }",
        {"input": {"id": made.data["createTransformation"]["id"], "affine": [[1.0, 0.0], [0.0, 1.0]]}},
    )
    assert refined.errors, "refining an unmappable edge would write parameters that nothing will ever read"
