"""What is in view of a region asked in a coordinate system, and which anchors go with it.

Ported from mikro's ``tests/test_in_view.py``, without its mesh case (no mesh collection
exists here). ``test_coordinate_api.py`` and ``test_clocks.py`` pin the everyday answer -- a
recording on its clock -- and that answer is a single, total, forward, one-axis map. This file
pins everything that case cannot reach: a registration that changes rank, one that points the
wrong way, one that denies a correspondence, and what a region shorter or longer than the
space means.

**An extent is partial.** Composing at one fixed rank is right inside a dataset -- a lens and a
sampling law keep its axes -- and wrong across a registration. A (c,y,x) dataset registered
onto the (y,x) of a (z,y,x) world is a *slab*, extended along z, and a number written for z
would cull it out of every view it is really in. So the extent names the axes it constrains
and stays silent about the rest, and the overlap test is a conjunction over the axes both
sides name. The same holds for a (t, c) recording on a clock: nothing is claimed about c.

**A source is never culled for being unbounded.** A path that can only be walked backwards
comes back with a state saying so and a full path, because refusing to bound something is not
the same as knowing it is out of view -- the same distinction `placement` draws beside a null
`pathToWorld`.

Nothing here is stored. Refining a registration moves every extent that looks through it,
which is the property `test_refining_a_registration_moves_the_extent` exists to hold.
"""

import pytest
from asgiref.sync import sync_to_async

from core import enums, models
from core.logic import coords as coords_logic
from tests import seed
from tests.coords._helpers import QueryCounter

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


SPATIAL_AXES = seed.ZYX_AXES

IN_VIEW = """
query InView($id: ID!, $region: BoundingBoxInput!) {
  coordinateSystem(id: $id) {
    inView(region: $region) {
      extentState
      invariance
      validity
      extent { axis min max }
      system { id }
      path { inverted transformation { id kind } }
      source {
        __typename
        ... on ArrayDataset { id name }
        ... on Lens { id }
      }
    }
  }
}
"""


async def _in_view(aexecute, system_id, mins: list[float], maxs: list[float]) -> list[dict]:  # noqa: ANN001
    result = await aexecute(IN_VIEW, {"id": str(system_id), "region": {"min": mins, "max": maxs}})
    assert not result.errors, result.errors
    return result.data["coordinateSystem"]["inView"]


def _extent(hit: dict) -> dict[str, list[float]]:
    return {entry["axis"]: [entry["min"], entry["max"]] for entry in hit["extent"]}


async def _registered(ctx, name: str, axes: list | None = None, shape: list[int] | None = None):  # noqa: ANN001, ANN202
    """A dataset registered by identity into a fresh (z, y, x) world: ``(dataset, world, edge)``."""
    dataset = await seed.create_dataset(ctx, name, axes or SPATIAL_AXES, shape or [8, 64, 64])
    world = await seed.create_world(ctx, name, seed.ZYX_WORLD_AXES)
    edge = await seed.register_into_world(ctx, world, dataset)
    return dataset, world, edge


# --- the extent -------------------------------------------------------------------


async def test_a_rank_changing_registration_constrains_only_the_axes_it_names(aexecute, authenticated_context):
    """A (c,y,x) dataset in a (z,y,x) world is a slab: bounded in y and x, free in z.

    The headline, and the case that fails without axis-aware composition -- `to_matrix` has
    no BY_DIMENSION branch, which is the kind every ordinary registration is written as.

    ABLATION: write a 0 for the unconstrained z and a region anywhere else in z culls this
    dataset away, silently, while looking exactly like a correct answer.
    """
    _, world, _ = await _registered(authenticated_context, "Slab", seed.SIMPLE_AXES, [3, 64, 64])

    (hit,) = await _in_view(aexecute, world.pk, [0.0, 0.0, 0.0], [10.0, 10.0, 10.0])

    assert hit["extentState"] == "KNOWN"
    assert _extent(hit) == {"y": [-0.5, 63.5], "x": [-0.5, 63.5]}, "z is not constrained by a registration that never mentions it"
    assert hit["source"]["name"] == "Slab"

    far = await _in_view(aexecute, world.pk, [900.0, 0.0, 0.0], [910.0, 10.0, 10.0])
    assert len(far) == 1, "a region far away in the one axis the registration says nothing about must not cull the source"


async def test_the_extent_is_the_half_voxel_box_of_the_level_zero_array(aexecute, authenticated_context):
    """Sample n covers [n-0.5, n+0.5), so a shape of S spans [-0.5, S-0.5] -- not [0, S]."""
    _, world, _ = await _registered(authenticated_context, "Boxed")

    (hit,) = await _in_view(aexecute, world.pk, [-100.0, -100.0, -100.0], [100.0, 100.0, 100.0])
    assert _extent(hit) == {"z": [-0.5, 7.5], "y": [-0.5, 63.5], "x": [-0.5, 63.5]}


async def test_refining_a_registration_moves_the_extent(aexecute, authenticated_context):
    """The extent is derived, so one edge write moves it -- with no write to any source.

    The twin of `test_placement_validity`'s "fixing one edge fixes every layer". A stored
    per-source box would need a fan-out here, and the fan-out is what goes missing.
    """
    _, world, edge = await _registered(authenticated_context, "Refined")

    before = await _in_view(aexecute, world.pk, [-100.0] * 3, [100.0] * 3)
    assert _extent(before[0])["x"] == [-0.5, 63.5]

    def refine() -> None:
        child = edge.children.first()
        child.kind = enums.TransformKindChoices.SCALE.value
        child.params = {"scale": [2.0, 2.0, 2.0]}
        child.save(update_fields=["kind", "params"])

    await sync_to_async(refine)()

    after = await _in_view(aexecute, world.pk, [-200.0] * 3, [200.0] * 3)
    assert _extent(after[0])["x"] == [-1.0, 127.0], "refining the edge moved every extent that looks through it"


async def test_the_queried_system_is_in_view_of_itself(aexecute, authenticated_context):
    """A source whose own system IS the queried one: empty path, exact by construction."""
    dataset = await seed.create_dataset(authenticated_context, "Rooted", SPATIAL_AXES, [8, 64, 64])

    (hit,) = await _in_view(aexecute, dataset.coordinate_system_id, [0.0, 0.0, 0.0], [10.0, 10.0, 10.0])
    assert hit["path"] == []
    assert hit["validity"] == "VALIDATED"
    assert hit["invariance"] == "ISOMETRY"
    assert _extent(hit) == {"z": [-0.5, 7.5], "y": [-0.5, 63.5], "x": [-0.5, 63.5]}


# --- the states -------------------------------------------------------------------


async def test_an_unmappable_registration_is_not_in_view(aexecute, authenticated_context):
    """The one genuine exclusion: a declared non-correspondence is not a placement at all."""
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Unmapped", SPATIAL_AXES, [8, 64, 64])
    world = await seed.create_world(ctx, "Unmapped", seed.ZYX_WORLD_AXES)
    await models.Transformation.objects.acreate(
        kind=enums.TransformKindChoices.UNMAPPABLE.value,
        input_id=dataset.coordinate_system_id,
        output=world,
        params={},
        creator=ctx.request.user,
        organization=ctx.request.organization,
    )

    assert await _in_view(aexecute, world.pk, [-100.0] * 3, [100.0] * 3) == []


async def test_a_backwards_registration_keeps_its_path_and_states_why_it_has_no_extent(aexecute, authenticated_context):
    """Composed forward only -- so an inverted step is reported, not silently culled.

    The step IS invertible (the search offers a backwards step only when it is), so the
    client inverts the flagged edge itself. The server declining to do arithmetic is not the
    same as the map having no inverse.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Backwards", SPATIAL_AXES, [8, 64, 64])
    world = await seed.create_world(ctx, "Backwards", seed.ZYX_WORLD_AXES)
    await models.Transformation.objects.acreate(
        kind=enums.TransformKindChoices.ROTATION.value,
        input=world,
        output_id=dataset.coordinate_system_id,
        params={"affine": [[0.0, -1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]},
        creator=ctx.request.user,
        organization=ctx.request.organization,
    )

    (hit,) = await _in_view(aexecute, world.pk, [-100.0] * 3, [100.0] * 3)
    assert hit["extentState"] == "INVERTED"
    assert hit["extent"] == []
    assert any(step["inverted"] for step in hit["path"]), "the path is still returned, flagged, for the client to invert"


# --- the region -------------------------------------------------------------------


async def test_a_region_that_misses_the_source_returns_nothing(aexecute, authenticated_context):
    """The cull actually culls, on an axis the registration does constrain."""
    _, world, _ = await _registered(authenticated_context, "Elsewhere")
    assert await _in_view(aexecute, world.pk, [500.0, 500.0, 500.0], [600.0, 600.0, 600.0]) == []


async def test_a_degenerate_region_probes_a_plane(aexecute, authenticated_context):
    """min == max is the probe a client sends to ask what is under this slice; bounds are closed."""
    _, world, _ = await _registered(authenticated_context, "Sliced")
    assert len(await _in_view(aexecute, world.pk, [4.0, 4.0, 4.0], [4.0, 4.0, 4.0])) == 1


async def test_a_shorter_region_constrains_only_its_leading_axes(aexecute, authenticated_context):
    """A 2D box asked of a 3D space says nothing about the third axis, rather than pinning it to zero."""
    _, world, _ = await _registered(authenticated_context, "Prefix")
    assert len(await _in_view(aexecute, world.pk, [0.0, 0.0], [4.0, 4.0])) == 1


async def test_a_region_longer_than_the_system_is_refused(aexecute, authenticated_context):
    """Naming more axes than the system has is a client error, not an empty result."""
    world = await seed.create_world(authenticated_context, "Narrow", seed.ZYX_WORLD_AXES)

    result = await aexecute(IN_VIEW, {"id": str(world.pk), "region": {"min": [0.0] * 5, "max": [1.0] * 5}})
    assert result.errors, "a region of five axes over a three-axis system must not silently succeed"
    assert "it cannot name more than it has" in str(result.errors[0])


# --- anchors ----------------------------------------------------------------------

IN_VIEW_ANCHORS = """
query InView($id: ID!, $region: BoundingBoxInput!) {
  coordinateSystem(id: $id) {
    inView(region: $region) {
      source { __typename ... on ArrayDataset { id name } }
      anchors { id coordinates channelLabel { label } }
    }
  }
}
"""


async def _anchors_in_view(aexecute, system_id, mins: list[float], maxs: list[float]) -> list[dict]:  # noqa: ANN001
    result = await aexecute(IN_VIEW_ANCHORS, {"id": str(system_id), "region": {"min": mins, "max": maxs}})
    assert not result.errors, result.errors
    return result.data["coordinateSystem"]["inView"]


async def _pin(dataset, *coordinates: dict) -> None:  # noqa: ANN001
    """Anchors on ``dataset``, one per coordinate dict, written off the event loop."""
    for entry in coordinates:
        await models.CoordinateAnchor.objects.acreate(dataset=dataset, coordinates=entry)


async def test_an_anchor_pinned_outside_the_region_is_culled(aexecute, authenticated_context):
    """The one that exercises the cull: a pinned axis the region *does* constrain.

    The dataset's z is registered onto the world's z, so each anchor's slab is one sample wide
    there and a region covering only the first plane must reject the anchor at z=7. This is
    the test that puts the second walk, the composed forms and the half-sample slab under load
    -- an anchor pinned on an axis the world does not have (below) can never fail any of them.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Stacked", SPATIAL_AXES, [8, 64, 64])
    world = await seed.create_world(ctx, "Stacked", seed.ZYX_WORLD_AXES)
    await _pin(dataset, {"z": 0}, {"z": 7})
    await seed.register_into_world(ctx, world, dataset)

    (hit,) = await _anchors_in_view(aexecute, world.pk, [-1.0, -100.0, -100.0], [1.0, 100.0, 100.0])
    assert [anchor["coordinates"] for anchor in hit["anchors"]] == [{"z": 0}], "the anchor seven planes away is not in a region one plane deep"

    (whole,) = await _anchors_in_view(aexecute, world.pk, [-100.0] * 3, [100.0] * 3)
    assert len(whole["anchors"]) == 2, "and both are in view of a region covering the stack"


async def test_an_anchor_on_an_axis_the_space_does_not_have_is_never_culled(aexecute, authenticated_context):
    """A (t,y,x) dataset in a (z,y,x) world: nothing constrains t, so no region can reject its anchors."""
    ctx = authenticated_context
    axes = [seed.axis("t", enums.AxisType.TIME), seed.axis("y", enums.AxisType.SPACE), seed.axis("x", enums.AxisType.SPACE)]
    dataset = await seed.create_dataset(ctx, "Timed", axes, [10, 64, 64])
    world = await seed.create_world(ctx, "Timed", seed.ZYX_WORLD_AXES)
    await _pin(dataset, {"t": 0}, {"t": 9})
    await seed.register_into_world(ctx, world, dataset)

    (hit,) = await _anchors_in_view(aexecute, world.pk, [0.0, 0.0, 0.0], [10.0, 10.0, 10.0])
    assert len(hit["anchors"]) == 2, "an axis the space does not have cannot cull an anchor"


async def test_an_anchor_that_pins_no_registered_axis_is_in_view_whenever_its_container_is(aexecute, authenticated_context):
    """A channel label is everywhere: it pins c, and the region says nothing about c."""
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Channelled", seed.SIMPLE_AXES, [3, 64, 64])  # (c, y, x)
    world = await seed.create_world(ctx, "Channelled", seed.ZYX_WORLD_AXES)
    await _pin(dataset, {"c": 0})
    await seed.register_into_world(ctx, world, dataset)

    (hit,) = await _anchors_in_view(aexecute, world.pk, [0.0, 0.0, 0.0], [10.0, 10.0, 10.0])
    assert [anchor["coordinates"] for anchor in hit["anchors"]] == [{"c": 0}]


async def test_the_anchors_of_a_recording_in_view_of_a_window_of_its_clock(aexecute, authenticated_context):
    """The three cases above on the shape this service actually sees: a (t, c) recording on a clock.

    A sweep marker pins t and is culled by a window that ends before it; a channel label pins c,
    which the clock does not have, and the dataset-wide anchor pins nothing at all -- so both
    are in view of every window the recording itself is in.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Recording", seed.TC_AXES, [1000, 4])
    clock = await seed.create_world(ctx, "Session")  # (t), in seconds; registered by identity, so one sample is one second
    await _pin(dataset, {}, {"c": 2}, {"t": 900}, {"t": 5, "c": 0})
    await seed.register_into_world(ctx, clock, dataset)

    (early,) = await _anchors_in_view(aexecute, clock.pk, [0.0], [10.0])
    assert sorted(str(anchor["coordinates"]) for anchor in early["anchors"]) == ["{'c': 2}", "{'t': 5, 'c': 0}", "{}"], "the marker at t=900 is outside the first ten seconds"

    (late,) = await _anchors_in_view(aexecute, clock.pk, [899.5], [900.5])
    assert sorted(str(anchor["coordinates"]) for anchor in late["anchors"]) == ["{'c': 2}", "{'t': 900}", "{}"]

    assert await _anchors_in_view(aexecute, clock.pk, [5000.0], [6000.0]) == [], "and when the recording is out of view there is no source to hang an anchor on"


async def test_only_this_organizations_sources_and_anchors_are_in_view(aexecute, authenticated_context, other_org_context):
    """Every read is organization-scoped here: a world answers with nothing to a caller it does not belong to."""
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Mine", SPATIAL_AXES, [8, 64, 64])
    world = await seed.create_world(ctx, "Mine", seed.ZYX_WORLD_AXES)
    await _pin(dataset, {"z": 0})
    await seed.register_into_world(ctx, world, dataset)

    theirs = await aexecute(IN_VIEW_ANCHORS, {"id": str(world.pk), "region": {"min": [-100.0] * 3, "max": [100.0] * 3}}, context=other_org_context)
    assert theirs.errors or not (theirs.data["coordinateSystem"] or {}).get("inView"), "another organization's caller sees neither the source nor its anchors"


# --- cost -------------------------------------------------------------------------


async def test_the_query_count_does_not_grow_with_the_sources(aexecute, authenticated_context):
    """A flat cost in the number of registered sources -- the property the whole module exists for.

    Flat in the source *count*, on flat lineages: the derivation and lineage closures cost one
    query per generation, which is bounded by the shape of the data rather than by how much of
    it there is.
    """
    ctx = authenticated_context

    async def build(name: str, count: int) -> str:
        world = await seed.create_world(ctx, name, seed.ZYX_WORLD_AXES)
        for index in range(count):
            dataset = await seed.create_dataset(ctx, f"{name}-{index}", SPATIAL_AXES, [8, 64, 64])
            await seed.register_into_world(ctx, world, dataset)
        return str(world.pk)

    small = await build("Small", 2)
    large = await build("Large", 6)

    # Warmed first, and measured on separate requests after: the first execution in a process
    # pays one-off costs (content types, permissions) that no steady-state client pays, and
    # counting them would bury the thing under test.
    await _in_view(aexecute, small, [-100.0] * 3, [100.0] * 3)

    counts = []
    for world_id in (small, large):
        with QueryCounter() as counter:
            hits = await _in_view(aexecute, world_id, [-100.0] * 3, [100.0] * 3)
        counts.append(len(counter.queries))

    assert len(hits) == 6, "the larger space really did have more sources in view"
    assert counts[0] == counts[1], f"the cost grew with the sources: {counts[0]} then {counts[1]}"


async def test_the_query_count_does_not_grow_with_the_anchored_sources(aexecute, authenticated_context):
    """mikro's version of the test above: every source carries anchors.

    The anchor resolution returns early when a dataset has none, so the test above measures it
    bailing. Here it is measured doing its actual work.
    """
    ctx = authenticated_context

    async def build(name: str, count: int) -> str:
        world = await seed.create_world(ctx, name, seed.ZYX_WORLD_AXES)
        for index in range(count):
            dataset = await seed.create_dataset(ctx, f"{name}-{index}", SPATIAL_AXES, [8, 64, 64])
            await _pin(dataset, {"z": 0})
            await seed.register_into_world(ctx, world, dataset)
        return str(world.pk)

    small = await build("Small", 2)
    large = await build("Large", 6)

    await _anchors_in_view(aexecute, small, [-100.0] * 3, [100.0] * 3)

    counts = []
    for world_id in (small, large):
        with QueryCounter() as counter:
            hits = await _anchors_in_view(aexecute, world_id, [-100.0] * 3, [100.0] * 3)
        counts.append(len(counter.queries))

    assert len(hits) == 6, "the larger space really did have more sources in view"
    assert all(len(hit["anchors"]) == 1 for hit in hits), "and every one of them resolved its anchor"
    assert counts[0] == counts[1], f"the cost grew with the sources: {counts[0]} then {counts[1]}"


# --- the closed form --------------------------------------------------------------


async def test_the_closed_form_interval_agrees_with_the_corner_enumeration():
    """`form_interval` is the O(n) shortcut for what `transformed_bbox` does with 2**n corners.

    Pinned rather than argued: "obviously equivalent" is how a sign error survives. A shear
    and a negative scale are included because those are where taking min/max of the two
    extreme corners alone would go wrong.
    """
    mins, maxs = [-1.0, 2.0, 0.0], [3.0, 5.0, 4.0]
    matrix = [
        [1.0, 0.5, 0.0, 7.0],
        [0.0, -2.0, 0.0, -1.0],
        [0.3, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    reference = coords_logic.transformed_bbox(mins, maxs, [(enums.TransformKindChoices.AFFINE.value, {"affine": matrix})])

    forms = {name: coords_logic.AxedForm(coefficients=tuple(matrix[index][:3]), constant=matrix[index][3]) for index, name in enumerate(["a", "b", "c"])}
    closed = coords_logic.axed_bbox(mins, maxs, forms)

    for index, name in enumerate(["a", "b", "c"]):
        assert closed[name][0] == pytest.approx(reference["min"][index])
        assert closed[name][1] == pytest.approx(reference["max"][index])


async def test_boxes_overlap_ignores_the_axes_only_one_side_names():
    """Silence is not a zero: an axis one side does not constrain cannot exclude anything."""
    slab = {"y": [0.0, 10.0], "x": [0.0, 10.0]}
    assert coords_logic.boxes_overlap(slab, {"z": [900.0, 910.0], "y": [1.0, 2.0], "x": [1.0, 2.0]})
    assert not coords_logic.boxes_overlap(slab, {"y": [90.0, 95.0], "x": [1.0, 2.0]})
    assert coords_logic.boxes_overlap(slab, {"y": [10.0, 10.0], "x": [0.0, 0.0]}), "closed bounds, so a plane probe on the edge still meets it"
