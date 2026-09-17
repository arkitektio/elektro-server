"""A transformation scoped to one position along one axis: per-channel and per-sweep corrections.

Ported from mikro's ``tests/test_per_index_transforms.py``. The selector is vendored whole --
``createTransformation(selector:)``, ``at:`` on every placement resolver and on ``inView`` --
and its everyday use here is a probe whose channels are sampled with a per-channel skew, or
sweeps that each start at their own instant. Nothing in this service exercised any of it.

``inputAxes`` and ``outputAxes`` select axes *by name*, and nothing on a `Transformation` read
a coordinate **value** to choose parameters. So "for c=2, translate by (0.3, 0.1)" had no
representation. The workaround was one `Lens` per channel, each with its own coordinate
system, its own edge and its own view.

A scoped edge is a *partial* map: it holds where the input coordinate along its axis equals its
index, and says nothing elsewhere. Several of them over one axis are one piecewise map, written as
the several facts they are, so refining one channel's correction moves one channel.

The rule that makes this safe is that a query crosses a scoped edge **only when it fixes that
coordinate**. Without `at` the answer genuinely depends on where you are standing, and inventing
one would be the same class of bug as the pk-ordered tie-break the widest-path search replaced.

The fixture is mikro's: a (c, y, x) dataset in a (z, y, x) world, corrected over (y, x) per
channel. The arithmetic is generic over axis types, and two corrected axes make a transposed
offset visible where one would not.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core import models
from core.logic import graph as graph_logic
from tests import seed
from tests.coords._helpers import add_view, create_experiment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


AT_AFFINE = """
query AtAffine($id: ID!, $at: [CoordinateInput!]) {
  experiment(id: $id) {
    recordingViews {
      id
      asAffine(at: $at) { matrix inputAxes outputAxes total }
      pathToWorld(at: $at) { transformation { id selector { axis index } } }
    }
  }
}
"""

CREATE_TRANSFORM = """
mutation Create($input: CreateTransformationInput!) {
  createTransformation(input: $input) { id selector { axis index } }
}
"""

STATE = """
query State($id: ID!, $at: [CoordinateInput!]) {
  experiment(id: $id) {
    recordingViews { id placement(at: $at) placementValidity(at: $at) placementInvariance(at: $at) }
  }
}
"""

IN_VIEW = """
query InView($id: ID!, $at: [CoordinateInput!]) {
  coordinateSystem(id: $id) {
    inView(region: {min: [-1000, -1000, -1000], max: [1000, 1000, 1000]}, at: $at) {
      extentState
      source { __typename ... on ArrayDataset { id } }
    }
  }
}
"""

#: The per-channel correction every test here authors: over (y, x), leaving c and z alone.
_OVER_YX = {"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"]}


async def _register(aexecute, input_id: int, output_id: int, transform: dict, selector: dict | None = None) -> dict:  # noqa: ANN001 - the conftest fixture
    payload: dict = {"input": str(input_id), "output": str(output_id), "transform": transform}
    if selector is not None:
        payload["selector"] = selector
    result = await aexecute(CREATE_TRANSFORM, {"input": payload})
    assert not result.errors, result.errors
    return result.data["createTransformation"]


async def _errors(aexecute, input_id: int, output_id: int, transform: dict, selector: dict) -> list:  # noqa: ANN001
    result = await aexecute(CREATE_TRANSFORM, {"input": {"input": str(input_id), "output": str(output_id), "transform": transform, "selector": selector}})
    return list(result.errors or [])


async def _view_at(aexecute, experiment: models.Experiment, at: list | None, query: str = AT_AFFINE) -> dict:  # noqa: ANN001
    result = await aexecute(query, {"id": str(experiment.pk), "at": at})
    assert not result.errors, result.errors
    (view,) = result.data["experiment"]["recordingViews"]
    return view


def _translation(matrix: list[list[float]]) -> list[float]:
    """The offset column of an M x (N+1) matrix -- what a per-channel correction moves by."""
    return [row[-1] for row in matrix]


async def _chromatic_experiment(ctx) -> tuple[models.Experiment, models.ArrayDataset]:  # noqa: ANN001
    """A (c,y,x) dataset on one view, with no unscoped route into its experiment's world."""
    experiment = await create_experiment(ctx, "Chromatic")
    dataset = await seed.create_array_dataset(ctx, "Stack", shapes=[[3, 64, 64]])
    await add_view(ctx, experiment, await seed.create_lens(ctx, dataset))
    return experiment, dataset


async def test_one_layer_resolves_differently_per_channel(aexecute, authenticated_context):
    """The whole point: two channels, one view, two placements.

    Each channel's correction is its own edge into the same world -- the shape that used to
    require a lens, a system, an edge and a view per channel.
    """
    experiment, dataset = await _chromatic_experiment(authenticated_context)

    for index, offset in ((0, [0.0, 0.0]), (2, [3.0, 5.0])):
        await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, {**_OVER_YX, "translation": offset}, selector={"axis": "c", "index": index})

    first = await _view_at(aexecute, experiment, [{"name": "c", "value": 0}])
    third = await _view_at(aexecute, experiment, [{"name": "c", "value": 2}])

    assert _translation(first["asAffine"]["matrix"]) == approx([0.0, 0.0])
    assert _translation(third["asAffine"]["matrix"]) == approx([3.0, 5.0]), "the third channel is corrected; the first is not"
    assert first["asAffine"]["outputAxes"] == third["asAffine"]["outputAxes"] == ["y", "x"]

    # And the path reports which scoped edge it actually crossed, rather than leaving the
    # client to infer it from the numbers.
    assert [step["transformation"]["selector"] for step in third["pathToWorld"]] == [{"axis": "c", "index": 2}]


async def test_without_a_fixed_coordinate_a_scoped_edge_is_not_crossed(aexecute, authenticated_context):
    """No `at`, no answer -- rather than an arbitrary one.

    Where the data sits depends on the channel. A query that has not said which channel has no
    single placement to be given, so it gets a null (the same null an unregistered view gets,
    which `placement` distinguishes) instead of whichever edge happened to sort first.
    """
    experiment, dataset = await _chromatic_experiment(authenticated_context)
    await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, {**_OVER_YX, "translation": [3.0, 5.0]}, selector={"axis": "c", "index": 2})

    unfixed = await _view_at(aexecute, experiment, None)
    assert unfixed["asAffine"] is None
    assert unfixed["pathToWorld"] is None

    # Fixing a *different* index on the same axis is equally not a match.
    elsewhere = await _view_at(aexecute, experiment, [{"name": "c", "value": 1}])
    assert elsewhere["asAffine"] is None, "channel 1 has no correction authored, and channel 2's is not it"


async def test_an_unscoped_edge_still_answers_without_at(aexecute, authenticated_context):
    """Every edge written before selectors existed is unscoped, and none of them changed.

    This is the compatibility claim the whole design rests on: `selector_admits` returns True for
    a null selector, so a graph with no per-index edges behaves exactly as it did.
    """
    experiment, dataset = await _chromatic_experiment(authenticated_context)
    await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, {**_OVER_YX, "translation": [1.0, 1.0]})

    unfixed = await _view_at(aexecute, experiment, None)
    assert _translation(unfixed["asAffine"]["matrix"]) == approx([1.0, 1.0])
    assert [step["transformation"]["selector"] for step in unfixed["pathToWorld"]] == [None]

    # And it still answers when a coordinate *is* fixed: `at` narrows what may be crossed, it
    # does not require that everything be scoped.
    fixed = await _view_at(aexecute, experiment, [{"name": "c", "value": 2}])
    assert _translation(fixed["asAffine"]["matrix"]) == approx([1.0, 1.0])


async def test_a_selector_must_name_an_axis_that_can_be_indexed(aexecute, authenticated_context):
    """Three rejections, all at write time where the author is still in the room."""
    experiment, dataset = await _chromatic_experiment(authenticated_context)
    source, world = dataset.coordinate_system_id, experiment.world_id
    transform = {**_OVER_YX, "translation": [1.0, 1.0]}

    absent = await _errors(aexecute, source, world, transform, {"axis": "t", "index": 0})
    assert absent and "does not have" in str(absent[0]), "the dataset is (c,y,x); it has no time axis to be at a position along"

    spatial = await _errors(aexecute, source, world, transform, {"axis": "y", "index": 3})
    assert spatial and "measured rather than indexed" in str(spatial[0]), "a correction varying through space is a FIELD, not a piecewise map"

    negative = await _errors(aexecute, source, world, transform, {"axis": "c", "index": -1})
    assert negative and "non-negative" in str(negative[0])


async def test_refining_one_channel_moves_only_that_channel(aexecute, authenticated_context):
    """Piecewise as several facts, not one row with a list in it.

    Each index is its own edge, so it carries its own `version` and its own provenance, and a
    refinement is the ordinary in-place `updateTransformation` rather than a rewrite of a blob
    that every other channel shares.
    """
    experiment, dataset = await _chromatic_experiment(authenticated_context)

    for index, offset in ((0, [1.0, 1.0]), (1, [2.0, 2.0])):
        await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, {**_OVER_YX, "translation": offset}, selector={"axis": "c", "index": index})

    edge_zero = await models.Transformation.objects.aget(selector={"axis": "c", "index": 0})
    await models.Transformation.objects.filter(pk=edge_zero.pk).aupdate(params={"translation": [9.0, 9.0]})

    assert _translation((await _view_at(aexecute, experiment, [{"name": "c", "value": 0}]))["asAffine"]["matrix"]) == approx([9.0, 9.0])
    assert _translation((await _view_at(aexecute, experiment, [{"name": "c", "value": 1}]))["asAffine"]["matrix"]) == approx([2.0, 2.0]), "channel 1 did not move"


async def test_the_selector_predicate_is_the_only_reader_of_the_convention():
    """A unit-level pin on `selector_admits`, so the three cases stay stated in one place."""
    unscoped = models.Transformation(selector=None)
    scoped = models.Transformation(selector={"axis": "c", "index": 2})

    assert graph_logic.selector_admits(unscoped, None) is True
    assert graph_logic.selector_admits(unscoped, {"c": 7}) is True
    assert graph_logic.selector_admits(scoped, None) is False
    assert graph_logic.selector_admits(scoped, {"t": 2}) is False, "a coordinate on another axis is not a match"
    assert graph_logic.selector_admits(scoped, {"c": 1}) is False
    assert graph_logic.selector_admits(scoped, {"c": 2}) is True


async def test_a_per_index_registration_is_a_registration_everywhere_it_is_asked(aexecute, authenticated_context):
    """The plumbing around the selector, which the walk had and nothing else did.

    `adjacency_of` was the only reader of `selector_admits`, and every other consumer walked
    with no `at` -- so a scoped edge was not merely uncrossable, it was absent. A dataset whose
    only registration was per channel therefore read as *unregistered* to `placement`, to
    `placementValidity`, to `placementInvariance` and to `inView`: registered once per
    channel, and reported as registered nowhere.

    Existence and position are different questions. Whether this data has a place does not
    depend on where the asker is standing; only which place does.
    """
    experiment, dataset = await _chromatic_experiment(authenticated_context)

    for index, offset in ((0, [0.0, 0.0]), (2, [3.0, 5.0])):
        await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, {**_OVER_YX, "translation": offset}, selector={"axis": "c", "index": index})

    # Without a coordinate: a placement, said so, rather than a gap to go and close.
    view = await _view_at(aexecute, experiment, None, STATE)
    assert view["placement"] == "CONDITIONAL", "registered per channel is registered"
    assert view["placementValidity"] != "UNKNOWN", "there is a registration, and how known it is can be read off it"
    assert view["placementInvariance"] != "NONE", "a translation per channel is still a translation"

    # With one: the ordinary answers, about that channel.
    at_two = await _view_at(aexecute, experiment, [{"name": "c", "value": 2}], STATE)
    assert at_two["placement"] == "PLACED"
    assert at_two["placementInvariance"] == "ISOMETRY", "a translation preserves distances"

    # A channel nobody corrected is the one real gap here, and keeps its own answer.
    elsewhere = await _view_at(aexecute, experiment, [{"name": "c", "value": 1}], STATE)
    assert elsewhere["placement"] == "CONDITIONAL", "c=1 has no correction, but the data is still placed per index elsewhere"


async def test_a_layer_can_be_created_over_a_scoped_only_registration(aexecute, authenticated_context):
    """The creation gate refused the view the feature exists to allow.

    Every gate asks `is_placeable_in`, whose walk could not see a scoped edge at all. The shape
    that exposes it is the one the model actually recommends for a per-channel correction: a
    corrected space hanging off the sample grid by a channel-wise edge, and *that* space
    registered into the world. The scoped hop is then in the middle of the chain, where
    nothing rescues it -- with the scoped edge last, a separate branch of `is_placeable_in`
    never consulted the selector and let it through, so the same registration was accepted or
    refused depending only on how many hops it took.

    mikro pins this through `createIntensityLayer`. `createExperiment` lays out recordings by
    their simulation's clock and cannot be handed this dataset, so the gate is asked directly:
    it is the same call (`graph.is_placeable_in`) `createExperiment` makes.
    """
    ctx = authenticated_context
    experiment = await create_experiment(ctx, "Corrected")
    dataset = await seed.create_array_dataset(ctx, "Stack", shapes=[[3, 64, 64]])
    lens = await seed.create_lens(ctx, dataset)
    world = await sync_to_async(lambda: experiment.world)()
    grid = await sync_to_async(lambda: dataset.coordinate_system)()

    # The corrected space. Bare, because a `registrations` entry cannot carry a selector --
    # the per-index edge is authored on its own below. A channel axis, because a selector names
    # an axis of the edge's *input* system and this is where the scoped hop lands. 'a.u.' is
    # how an axis with no measured dimension carries a unit in a unit-carrying space.
    aligned = await aexecute(
        "mutation M($input: CreateCoordinateSystemInput!) { createCoordinateSystem(input: $input) { id } }",
        {"input": {"name": "Aligned", "axes": [{"name": "c", "type": "CHANNEL", "unit": "a.u."}, {"name": "y", "type": "SPACE", "unit": "micrometer"}, {"name": "x", "type": "SPACE", "unit": "micrometer"}]}},
    )
    assert not aligned.errors, aligned.errors
    aligned_id = int(aligned.data["createCoordinateSystem"]["id"])

    # grid -> aligned, per channel. Then aligned -> world, unscoped: nothing unscoped
    # reaches world from the dataset, and the only thing that does is scoped.
    await _register(aexecute, grid.pk, aligned_id, {**_OVER_YX, "translation": [3.0, 5.0]}, selector={"axis": "c", "index": 2})
    await _register(aexecute, aligned_id, world.pk, {**_OVER_YX, "scale": [0.5, 0.5]})

    assert await sync_to_async(graph_logic.is_placeable_in)(world, grid, require_affine=False), "a scoped hop in the middle of the chain is still a route"
    assert await sync_to_async(graph_logic.is_placeable_in)(world, grid, require_affine=True)

    # And it reads as the placement it is, resolving when the channel is fixed.
    await add_view(ctx, experiment, lens)
    assert (await _view_at(aexecute, experiment, None, STATE))["placement"] == "CONDITIONAL"
    assert (await _view_at(aexecute, experiment, [{"name": "c", "value": 2}], STATE))["placement"] == "PLACED"


async def test_a_scoped_source_is_in_view_of_the_space_it_is_registered_into(aexecute, authenticated_context):
    """`inView` never passed `at`, so a per-channel registration was invisible to it.

    The source is in the space -- returning nothing for it was the graph withholding what it
    knew. What it cannot state without a coordinate is the *box*, and CONDITIONAL says exactly
    that rather than leaving an empty extent to be read as "unbounded" or "not here".
    """
    experiment, dataset = await _chromatic_experiment(authenticated_context)
    await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, {**_OVER_YX, "translation": [3.0, 5.0]}, selector={"axis": "c", "index": 2})

    unfixed = await aexecute(IN_VIEW, {"id": str(experiment.world_id), "at": None})
    assert not unfixed.errors, unfixed.errors
    seen = unfixed.data["coordinateSystem"]["inView"]
    assert [hit["source"]["id"] for hit in seen] == [str(dataset.pk)], "in the space, whether or not the question fixed a channel"
    assert seen[0]["extentState"] == "CONDITIONAL"

    fixed = await aexecute(IN_VIEW, {"id": str(experiment.world_id), "at": [{"name": "c", "value": 2}]})
    assert not fixed.errors, fixed.errors
    assert fixed.data["coordinateSystem"]["inView"][0]["extentState"] == "KNOWN", "fixing the channel is what makes a box computable"
