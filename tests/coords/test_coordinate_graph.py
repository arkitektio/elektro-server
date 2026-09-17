"""`coordinateGraph` hands back the neighbourhood of one coordinate system; `lineageGraph` its provenance.

Ported from mikro's ``tests/test_coordinate_graph.py``, plus the two ``lineageGraph`` tests of
its ``test_cross_container_derivation.py`` restated over a chain of datasets. Both queries are
vendored resolvers over vendored walks (``graph.traverse``, ``graph.lineage_graph``) that issue
their own queries -- so each carries the organization itself, and each has to prefetch what it
returns or cost a query per edge. Neither property was pinned here.

The list queries answer "which edges exist"; a filter can narrow them by input, output or
kind, but it cannot answer "which edges relate to *this* system", because relatedness is
transitive and a filter is not. Walking it client-side means a round trip per hop. So the
walk happens here, and what comes back is the subgraph -- nodes and directed edges, nothing
composed, in keeping with the rest of the coordinate API.

Reachability is undirected on purpose, and the tests pin that: standing on a clock, the edge
that *points into* it is the sampling law, and a forward-only walk would answer "nothing
relates to this" for exactly the space a user is likeliest to ask about -- one that has no
residents to describe it either.
"""

import pytest

from core import enums, models
from tests import seed
from tests.coords._helpers import counted, create_experiment, derive, derived_dataset

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


GRAPH = """
query Graph($id: ID!, $maxDepth: Int) {
  coordinateGraph(coordinateSystem: $id, maxDepth: $maxDepth) {
    root { id residents { __typename } }
    systems { id name residents { __typename } axes { name type } }
    transformations {
      id kind inputAxes outputAxes
      input { id }
      output { id }
      ... on SequenceTransformation { transformations { id kind } }
    }
  }
}
"""

LINEAGE = """
query Lineage($system: ID!, $maxDepth: Int) {
  lineageGraph(coordinateSystem: $system, maxDepth: $maxDepth) {
    root { id }
    nodes { __typename ... on ArrayDataset { name } }
    edges { id kind input { id } output { id } }
  }
}
"""

_AFFINE_3D = [
    [1.0, 0.0, 0.0, 5.0],
    [0.0, 1.0, 0.0, 5.0],
    [0.0, 0.0, 1.0, 0.0],
]

#: The physical axes of a `seed.SIMPLE_AXES` (c, y, x) dataset.
_PHYSICAL_AXES = [
    seed.physical_axis("c", enums.AxisType.CHANNEL, "a.u."),
    seed.physical_axis("y", enums.AxisType.SPACE, "micrometer"),
    seed.physical_axis("x", enums.AxisType.SPACE, "micrometer"),
]


async def _calibrate(ctx, dataset: models.ArrayDataset) -> models.CoordinateSystem:  # noqa: ANN001
    return await seed.create_physical_space(ctx, dataset, _PHYSICAL_AXES, scale=[1.0, 0.5, 0.5], name="Stage")


async def _register(ctx, dataset: models.ArrayDataset, experiment: models.Experiment) -> models.Transformation:  # noqa: ANN001
    """Authoring the edge into the world IS the placement: there is no experiment membership to join."""
    return await models.Transformation.objects.acreate(
        kind=enums.TransformKindChoices.AFFINE.value,
        input_id=dataset.coordinate_system_id,
        output_id=experiment.world_id,
        params={"affine": _AFFINE_3D},
        organization=ctx.request.organization,
    )


async def _graph(aexecute, system_id, max_depth: int | None = None) -> dict:  # noqa: ANN001
    result = await aexecute(GRAPH, {"id": str(system_id), "maxDepth": max_depth})
    assert not result.errors, result.errors
    return result.data["coordinateGraph"]


def _inhabitants(graph: dict) -> list[list[str]]:
    return sorted(sorted(resident["__typename"] for resident in system["residents"]) for system in graph["systems"])


# --- coordinateGraph ----------------------------------------------------------------------------


async def test_the_walk_reaches_the_whole_neighbourhood_of_a_dataset(aexecute, authenticated_context):
    """From a dataset's sample grid: its lens, its calibration, and the world it sits in."""
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Volume")
    await seed.create_lens(ctx, dataset, slices=[{"axis": "y", "start": 8, "stop": 40}])
    await _calibrate(ctx, dataset)
    experiment = await create_experiment(ctx, "Composition")
    await _register(ctx, dataset, experiment)

    graph = await _graph(aexecute, dataset.coordinate_system_id)

    assert graph["root"]["id"] == str(dataset.coordinate_system_id)

    # Four spaces: the dataset's own grid, the sliced lens' crop, the calibrated space and the
    # experiment's world. The last two hold nothing at all -- a calibrated space and a world
    # are both just reference frames.
    # Level 0 lives in the dataset's own grid -- it IS that grid -- so it is listed beside it.
    assert _inhabitants(graph) == [[], [], ["ArrayDataset", "DataArray"], ["Lens"]]

    # Every edge is inside the component: no endpoint dangles.
    ids = {system["id"] for system in graph["systems"]}
    assert len(graph["transformations"]) == 3, "the lens shift, the calibration and the registration"
    for edge in graph["transformations"]:
        assert edge["input"]["id"] in ids and edge["output"]["id"] in ids

    # And they arrive with their axis order, so the client can compose without a second trip.
    assert all(edge["inputAxes"] for edge in graph["transformations"])


async def test_an_edge_pointing_into_the_root_still_relates_to_it(aexecute, authenticated_context):
    """Reachability is undirected: from a calibrated space, the calibration points *in*.

    A forward-only walk leaves this system with no edges at all -- a calibration maps samples
    *into* physical space, and physical space is a sink. Answering "nothing relates to this"
    for a system whose whole reason to exist is one edge would make the query useless
    exactly where it is most natural to start.
    """
    dataset = await seed.create_array_dataset(authenticated_context, "Volume")
    calibration = await _calibrate(authenticated_context, dataset)

    graph = await _graph(aexecute, calibration.pk)

    assert graph["root"]["residents"] == [], "a calibrated space holds nothing; the edge is what relates it"
    assert graph["transformations"], "the calibration edge points into this system, and it relates to it"
    assert _inhabitants(graph) == [[], ["ArrayDataset", "DataArray"]]

    calibration_edge = next(edge for edge in graph["transformations"] if edge["output"]["id"] == str(calibration.pk))
    # Reached backwards, but reported forwards: the client still knows which way it composes.
    assert calibration_edge["input"]["id"] == str(dataset.coordinate_system_id), "the calibration sets out from the dataset's own space"


async def test_two_datasets_in_one_scene_reach_each_other_through_world(aexecute, authenticated_context):
    """Relatedness is transitive, which is exactly what no filter on `transformations` can express."""
    ctx = authenticated_context
    first = await seed.create_array_dataset(ctx, "First")
    second = await seed.create_array_dataset(ctx, "Second")
    experiment = await create_experiment(ctx, "Composition")
    await _register(ctx, first, experiment)
    await _register(ctx, second, experiment)

    graph = await _graph(aexecute, first.coordinate_system_id)

    assert str(second.coordinate_system_id) in {system["id"] for system in graph["systems"]}, "the second dataset is two hops away, through the world both are registered into"


async def test_max_depth_bounds_the_walk_and_leaves_no_edge_dangling(aexecute, authenticated_context):
    """A depth cutoff must cut whole edges, not leave ones pointing at systems it did not return."""
    ctx = authenticated_context
    first = await seed.create_array_dataset(ctx, "First")
    second = await seed.create_array_dataset(ctx, "Second")
    experiment = await create_experiment(ctx, "Composition")
    await _register(ctx, first, experiment)
    await _register(ctx, second, experiment)

    graph = await _graph(aexecute, first.coordinate_system_id, max_depth=1)

    ids = {system["id"] for system in graph["systems"]}
    assert str(experiment.world_id) in ids, "one hop reaches the world"
    assert str(second.coordinate_system_id) not in ids, "the second dataset is two hops away and the walk was bounded at one"
    for edge in graph["transformations"]:
        assert edge["input"]["id"] in ids and edge["output"]["id"] in ids, "a bounded walk must not return an edge whose endpoint it withheld"


async def test_the_walk_stops_at_the_organization_boundary(aexecute, authenticated_context, other_org_context):
    """A graph walk crosses foreign keys, and every one of them is a chance to cross a tenant.

    The traversal is not a filtered list the scoping layer would narrow on its own: it issues
    its own queries, so it carries the organization itself. Without that, one ID would hand
    back another organization's entire coordinate graph.
    """
    ours = await seed.create_array_dataset(authenticated_context, "Ours")
    theirs = await seed.create_array_dataset(other_org_context, "Theirs")

    # Their system is not ours to read at all.
    denied = await aexecute(GRAPH, {"id": str(theirs.coordinate_system_id), "maxDepth": None})
    assert denied.errors, "a foreign coordinate system must not be a valid root"

    # And nothing of theirs turns up in ours.
    graph = await _graph(aexecute, ours.coordinate_system_id)
    assert str(theirs.coordinate_system_id) not in {system["id"] for system in graph["systems"]}


#: `GRAPH` without the two nested *model* lists (`systems.axes`, a wrapper's `transformations`).
GRAPH_WITHOUT_NESTED_LISTS = """
query Graph($id: ID!, $maxDepth: Int) {
  coordinateGraph(coordinateSystem: $id, maxDepth: $maxDepth) {
    root { id residents { __typename } }
    systems { id name residents { __typename } }
    transformations { id kind inputAxes outputAxes input { id } output { id } }
  }
}
"""


async def _measure_walk(aexecute, ctx, document: str, dataset_count: int) -> tuple[int, int]:  # noqa: ANN001
    """The systems one walk returns, and what it cost, over a fresh world of ``dataset_count`` datasets.

    The lenses are *stepped*, so each one's edge is a SEQUENCE with children: mikro gets its
    wrappers from pyramid levels, and without one the `children` prefetch would go unexercised.
    """
    experiment = await create_experiment(ctx, f"Composition{dataset_count}")
    datasets = [await seed.create_array_dataset(ctx, f"D{dataset_count}-{index}") for index in range(dataset_count)]
    for dataset in datasets:
        await seed.create_lens(ctx, dataset, slices=[{"axis": "y", "start": 8, "stop": 40, "step": 2}])
        await _calibrate(ctx, dataset)
        await _register(ctx, dataset, experiment)

    data, queries = await counted(aexecute, document, {"id": str(datasets[0].coordinate_system_id), "maxDepth": None})
    return len(data["coordinateGraph"]["systems"]), queries


async def test_the_walk_is_flat_in_the_size_of_the_graph(aexecute, authenticated_context):
    """The cost is the depth of the walk, not the width of it.

    A custom resolver returns a plain list, and a plain list is invisible to the optimizer --
    so `axes`, `children` and the endpoints have to be prefetched by the traversal itself or
    every one of them is a query per edge. This pins the property rather than the fix: the
    same count for a world of two datasets and a world of six.
    """
    small_systems, small_queries = await _measure_walk(aexecute, authenticated_context, GRAPH, 2)
    large_systems, large_queries = await _measure_walk(aexecute, authenticated_context, GRAPH, 6)

    assert large_systems > small_systems, "the six-dataset graph must actually be bigger"
    assert large_queries == small_queries, f"the walk's query count grows with the graph: {small_queries} for 2 datasets, {large_queries} for 6"


async def test_the_walk_is_flat_when_no_nested_model_list_is_selected(aexecute, authenticated_context):
    """The control for the test above, and not in mikro: the traversal itself does not grow.

    Same graphs, same walk, minus the two fields strawberry-django resolves through a
    related manager. When the test above fails and this one passes, what grew is the
    resolution of `axes` and `transformations` -- a tenant filter re-applied to a prefetched
    relation throws the prefetch away -- and not `graph.traverse`. That is how the N+1 that
    `OrgScopedOrNested` now prevents was told apart from a fault in the walk.
    """
    small_systems, small_queries = await _measure_walk(aexecute, authenticated_context, GRAPH_WITHOUT_NESTED_LISTS, 2)
    large_systems, large_queries = await _measure_walk(aexecute, authenticated_context, GRAPH_WITHOUT_NESTED_LISTS, 6)

    assert large_systems > small_systems, "the six-dataset graph must actually be bigger"
    assert large_queries == small_queries, f"the walk's query count grows with the graph: {small_queries} for 2 datasets, {large_queries} for 6"


# --- lineageGraph -------------------------------------------------------------------------------


async def _chain(aexecute, zarr_store, ctx) -> tuple[models.ArrayDataset, models.ArrayDataset, models.ArrayDataset]:  # noqa: ANN001
    """raw -> filtered (IDENTITY) -> features (UNMAPPABLE): a lineage that mixes a placing hop and a historical one."""
    raw = await seed.create_dataset(ctx, "Raw", seed.T_AXES, [1000])
    filtered = await derived_dataset(await derive(aexecute, zarr_store, "Filtered", lens=await seed.create_lens(ctx, raw), axes=seed.T_AXES, shape=[1000], value_relation="TRANSFORMED"))
    features = await derived_dataset(
        await derive(aexecute, zarr_store, "Features", axes=[seed.axis("unit", enums.AxisType.INDEX)], shape=[12], entries=[{"kind": "DATASET", "dataset": str(filtered.pk)}]),
    )
    return raw, filtered, features


async def test_the_lineage_graph_steps_through_a_mixed_chain(aexecute, zarr_store, authenticated_context):
    """raw -> filtered -> features, walked from any point in it, in both directions.

    The point of the query: a client standing on the filtered dataset wants the recording above
    it *and* the features below it, and no single-hop field gives that. `coordinateGraph`
    cannot stand in -- it crosses every edge touching a space, so a registration would drag in
    every other dataset on the same clock.

    The chain deliberately mixes kinds. The filtered -> raw edge is a real IDENTITY, and the
    features -> filtered edge is UNMAPPABLE (an entry with no transform), which is exactly the
    hop a spatial walk (`lineage_ancestors`) refuses and a *historical* one must not.
    """
    raw, filtered, _ = await _chain(aexecute, zarr_store, authenticated_context)

    result = await aexecute(LINEAGE, {"system": str(filtered.coordinate_system_id), "maxDepth": None})
    assert not result.errors, result.errors

    graph = result.data["lineageGraph"]
    assert {(node["__typename"], node.get("name")) for node in graph["nodes"]} == {("ArrayDataset", "Raw"), ("ArrayDataset", "Filtered"), ("ArrayDataset", "Features")}, "the whole chain, from the middle of it, in both directions"
    assert sorted(edge["kind"] for edge in graph["edges"]) == ["IDENTITY", "UNMAPPABLE"], "the UNMAPPABLE hop is walked: this is history, not placement"

    # And from the top of the chain the answer is the same component.
    result = await aexecute(LINEAGE, {"system": str(raw.coordinate_system_id), "maxDepth": None})
    assert not result.errors, result.errors
    assert len(result.data["lineageGraph"]["nodes"]) == 3, "a component read from either end is the same component"


async def test_the_lineage_graph_is_bounded_and_excludes_registrations(aexecute, zarr_store, authenticated_context):
    """`maxDepth` bounds the walk, and a clock never enters it.

    A registration is where data was *put*, not where it came from, so it is not a lineage
    edge at all -- which falls out of the shared predicate rather than being filtered for
    here: a clock has no residents, so it is no container.
    """
    ctx = authenticated_context
    raw, _, _ = await _chain(aexecute, zarr_store, ctx)
    clock = await seed.create_physical_space(ctx, raw, seed.CLOCK_AXES, affine=[[0.001, 0.0]], name="clock")

    result = await aexecute(LINEAGE, {"system": str(raw.coordinate_system_id), "maxDepth": 1})
    assert not result.errors, result.errors
    assert {node.get("name") for node in result.data["lineageGraph"]["nodes"]} == {"Raw", "Filtered"}, "one hop reaches the filtered dataset and stops short of its features"

    # The clock the recording is sampled onto is nowhere in the graph, at any depth.
    result = await aexecute(LINEAGE, {"system": str(raw.coordinate_system_id), "maxDepth": None})
    assert not result.errors, result.errors
    assert all(node["__typename"] != "CoordinateSystem" for node in result.data["lineageGraph"]["nodes"])
    outputs = {edge["output"]["id"] for edge in result.data["lineageGraph"]["edges"]}
    assert str(clock.pk) not in outputs, "a registration is not a lineage edge"


async def test_the_lineage_graph_stops_at_the_organization_boundary(aexecute, authenticated_context, other_org_context):
    """Every GraphQL type here is org-scoped, and a lineage root is no exception."""
    theirs = await seed.create_dataset(other_org_context, "Theirs", seed.T_AXES, [1000])
    denied = await aexecute(LINEAGE, {"system": str(theirs.coordinate_system_id), "maxDepth": None})
    assert denied.errors, "a foreign coordinate system must not be a valid lineage root"
