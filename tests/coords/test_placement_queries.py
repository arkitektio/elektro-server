"""The experiment and placement API must not scale its query count with its view count.

Ported from mikro's ``tests/test_placement_queries.py``. The per-request memos these pin
(``scene_graph.for_request``, the shared root-edge fetch, ``_placeable_ids``) are vendored,
and nothing here counted a query: an experiment of forty recordings is the ordinary case,
and an N+1 in a placement resolver is invisible to every test that builds one view.

Every placement field (`pathToWorld`, `asAffine`, and the space's `placedSystems`) is a custom
resolver over the coordinate graph, so the optimizer cannot see what it touches: it walks
`view.lens.coordinate_system` for a client that selected nothing but `pathToWorld`. Left
alone, each view rebuilt the experiment's adjacency from scratch and the reachability closure
ran once per field.

These tests pin the property that fixes rather than the fix: **the same query count for an
experiment of three views and one of seven**. A count that grows with the views is the N+1
coming back, whatever shape it returns in.
"""

import pytest
from asgiref.sync import sync_to_async

from core import enums, models
from core.logic import graph as graph_logic
from core.logic import scene_graph, space_graph
from tests import seed
from tests.coords._helpers import QueryCounter, add_layer, counted, create_experiment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


_VIEW_PLACEMENT = """
      id
      pathToWorld { inverted transformation { id kind inputAxes outputAxes ... on SequenceTransformation { transformations { id kind inputAxes outputAxes } } } }
      asAffine { matrix inputAxes outputAxes total }
      placement
      placementValidity
      placementInvariance
"""

EXPERIMENT_PLACEMENTS = """
query ExperimentPlacements {
  experiments {
    id
    layers { %s }
    world { placedSystems { id residents { __typename } } }
  }
}
""" % _VIEW_PLACEMENT

SPACE_PLACED = """
query SpacePlaced { coordinateSystems { id placedSystems { id } } }
"""

SPACE_PLACED_TWICE = """
query SpaceBoth { coordinateSystems { id placedSystems { id } again: placedSystems { id } } }
"""

_AFFINE = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
]


async def _seed_experiment(ctx, *, view_count: int) -> models.Experiment:  # noqa: ANN001
    """An experiment of `view_count` views spread over two registered datasets.

    Two datasets, not one: a single-dataset experiment would not catch an adjacency that is
    rebuilt per dataset, and both datasets' edges have to stay in their own adjacency for
    the BFS to keep returning the path it returns today.
    """
    datasets = [await seed.create_array_dataset(ctx, f"Placed{index}") for index in range(2)]
    lenses = [await seed.create_lens(ctx, dataset, slices=[{"axis": "y", "start": 8, "stop": 40}]) for dataset in datasets]
    experiment = await create_experiment(ctx, "Composition")

    for index in range(view_count):
        await add_layer(ctx, experiment, lenses[index % len(lenses)])

    # Authoring the edge into the world is the placement (one truth per space):
    # nothing to add to any experiment.
    for dataset in datasets:
        await models.Transformation.objects.acreate(
            kind=enums.TransformKindChoices.AFFINE.value,
            input_id=dataset.coordinate_system_id,
            output_id=experiment.world_id,
            params={"affine": _AFFINE},
            organization=ctx.request.organization,
        )
    return experiment


def _view_count(data: dict) -> int:
    (experiment,) = data["experiments"]
    return len(experiment["layers"])


async def test_scene_placements_are_flat_in_layer_count(aexecute, authenticated_context):
    """Asking an experiment for its views' placements costs the same at 7 views as at 3."""
    await _seed_experiment(authenticated_context, view_count=3)
    small_data, small_queries = await counted(aexecute, EXPERIMENT_PLACEMENTS)

    await models.Experiment.objects.all().adelete()
    await _seed_experiment(authenticated_context, view_count=7)
    large_data, large_queries = await counted(aexecute, EXPERIMENT_PLACEMENTS)

    assert _view_count(small_data) == 3
    assert _view_count(large_data) == 7
    every_view = large_data["experiments"][0]["layers"]
    assert all(view["placement"] == "PLACED" and view["asAffine"] for view in every_view), "every placement field is actually exercised"
    assert large_queries == small_queries, f"the placement query count grows with the views: {small_queries} for 3 views, {large_queries} for 7"


async def test_a_spaces_placeable_set_is_walked_once_per_request(aexecute, authenticated_context):
    """`placedSystems` answers from one walk of the space per request, however often it is asked.

    It derives from `placeable_system_ids_in`, which is a registrations fetch, a residence
    map, a descendant closure, a lineage-closed edge fetch and a reverse BFS. Asking a *list*
    of systems for it twice is 2N of those without a memo.

    mikro asks `placedSystems` and `annotations`, the two fields that share the memo there.
    Only the first exists here, so it is asked twice under an alias -- the memo is keyed by
    space, not by field, so it is the same property. Asserted as "twice costs the same as
    once, plus the second read": the read is the placed systems and a prefetch per resident
    relation, which is a bound well under what one more walk per space would cost.
    """
    for index in range(3):
        dataset = await seed.create_array_dataset(authenticated_context, f"Placed{index}")
        world = await seed.create_world(authenticated_context, f"World{index}", seed.ZYX_WORLD_AXES)
        await seed.register_into_world(authenticated_context, world, dataset)

    _one_data, one_queries = await counted(aexecute, SPACE_PLACED)
    both_data, both_queries = await counted(aexecute, SPACE_PLACED_TWICE)

    assert len(both_data["coordinateSystems"]) >= 6, "the fixture must cover several spaces, or N walks and one look alike"
    extra = both_queries - one_queries
    read = 1 + len(graph_logic.RESIDENT_RELATIONS)
    assert extra <= read * len(both_data["coordinateSystems"]), (
        f"asking `placedSystems` a second time cost {extra} queries over {len(both_data['coordinateSystems'])} spaces: "
        "the placeable set is being walked a second time per space instead of read from the request memo"
    )


async def test_two_scenes_over_one_world_share_the_root_edge_fetch(authenticated_context):
    """The world's edges are fetched once per request, not once per experiment composing over it.

    An experiment's searchable universe is its world's edges plus its views' datasets' facts, and
    the first half is the *world's* -- identical for every experiment over it. Listing
    experiments would otherwise refetch it per experiment, which is the same N+1 as the
    per-view one, one level up.

    The `SpaceGraph` assertion is the other half of the rule, and it is not a limitation: that
    graph hands back whole containers, so it scopes its edges to the organization, and
    organization-scoped rows are simply not the same rows. The key carries the scoping so the
    two cannot silently share.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Shared")
    experiment_a = await create_experiment(ctx, "A")
    world = await sync_to_async(lambda: experiment_a.world)()
    await seed.register_into_world(ctx, world, dataset)
    experiment_b = await create_experiment(ctx, "B", world=world)

    def check() -> None:
        loaders: dict = {}

        a = scene_graph.SceneGraph(experiment_a, loaders=loaders)
        b = scene_graph.SceneGraph(experiment_b, loaders=loaders)
        assert a.universe.root_edges is b.universe.root_edges, "two experiments over one world must share the world's edge fetch"
        assert len(loaders["space_root_edges"]) == 1

        scoped = space_graph.SpaceGraph(world, organization=ctx.request.organization, loaders=loaders)
        assert scoped.universe.root_edges is not a.universe.root_edges, "an organization-scoped fetch is a different set of rows"
        assert len(loaders["space_root_edges"]) == 2, "so it gets its own key rather than reusing the unscoped one"

    await sync_to_async(check)()


CREATE_EXPERIMENT = """
mutation ($input: CreateExperimentInput!) { createExperiment(input: $input) { id } }
"""

CREATE_CLOCK_OFFSET = """
mutation ($input: CreateClockOffsetInput!) { createClockOffset(input: $input) { id } }
"""

CREATE_TRACE_LAYER = """
mutation ($input: CreateTraceLayerInput!) { createTraceLayer(input: $input) { id } }
"""


async def test_creating_a_layer_is_flat_in_scene_size(aexecute, authenticated_context, make_simulation_chain):
    """Laying out one more recording costs the same over a world of 7 runs as over a world of 3.

    The placement check a creating mutation runs (is this source placeable in this world?)
    must fetch a universe whose size depends on the dataset and the world, not on how much is
    already laid out there -- or assembling a timeline gets slower with every run already on it.

    mikro measures `createIntensityLayer` against the layers already in a scene; so does this,
    with `already` other runs, each with its clock laid into the shared timeline and a trace
    layer of it in the experiment.
    """

    async def measure(already: int) -> int:
        world = await seed.create_world(authenticated_context, f"Timeline{already}")
        created = await aexecute(CREATE_EXPERIMENT, {"input": {"name": f"Timeline{already}", "coordinateSystem": str(world.pk)}})
        assert not created.errors, created.errors
        experiment = created.data["createExperiment"]["id"]
        for index in range(already):
            earlier = await make_simulation_chain(name=f"earlier{already}-{index}")
            placed = await aexecute(CREATE_CLOCK_OFFSET, {"input": {"clock": str(earlier.clock.pk), "onto": str(world.pk), "offset": f"{index} s"}})
            assert not placed.errors, placed.errors
            laid = await aexecute(CREATE_TRACE_LAYER, {"input": {"experiment": experiment, "dataset": str(earlier.recording.pk)}})
            assert not laid.errors, laid.errors

        incoming = await make_simulation_chain(name=f"incoming{already}")
        placed = await aexecute(CREATE_CLOCK_OFFSET, {"input": {"clock": str(incoming.clock.pk), "onto": str(world.pk), "offset": "100 s"}})
        assert not placed.errors, placed.errors
        variables = {"input": {"experiment": experiment, "dataset": str(incoming.recording.pk)}}
        with QueryCounter() as counter:
            result = await aexecute(CREATE_TRACE_LAYER, variables)
        assert not result.errors, result.errors
        return len(counter)

    # Warm the process-lifetime caches (content types, auth) on a throwaway world first.
    await measure(1)

    small_queries = await measure(3)
    large_queries = await measure(7)
    assert large_queries == small_queries, f"creating a layer costs more over a fuller world: {small_queries} queries at 3 runs, {large_queries} at 7"
