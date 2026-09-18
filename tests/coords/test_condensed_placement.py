"""`asAffine` on an experiment view: a whole placement path condensed into one labelled affine map.

Ported from mikro's ``tests/test_condensed_placement.py``. ``tests/experiment`` pins the one
shape `createExperiment` writes -- a one-axis, total, forward path -- and every hard case of
the vendored composer (``graph.condense_path``) lies outside it: a partial map, a rank change,
a SEQUENCE, an inverted step. The views here go in through the ORM over arbitrary datasets, and
the fixtures keep mikro's spatial axes, because a two-axis map is what makes a transposed or
zero-filled matrix visible.

The graph ships edges rather than answers, deliberately -- the same data under two
registrations has two answers, so no composed matrix is stored anywhere. But a *view*
belongs to exactly one experiment, so its path already has a single right answer, and every
client was reimplementing the composition. They were getting it wrong in the same two
places, and both are pinned below:

**Zero-filling the axes a registration says nothing about.** A (c,y,x) dataset placed on
(y,x) into a (z,y,x) world constrains two axes. Writing a zero row for the third pins the
data at its origin, which is a claim nobody made and which culls it out of every other
slice. There is simply no row.

**Not inverting a step at all.** `pathToWorld` flags a step walked backwards and leaves the
undoing to the reader. `asAffine` does it -- and `SpaceGraph`, which still does not, reports
`ExtentState.INVERTED` rather than guessing.

The third pin is a bug this field surfaced: a SEQUENCE wrapper keeps its map on its
children, so composing it from the wrapper's own (empty) params yields the *identity*,
silently. Every stepped lens is such an edge.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core import enums, models
from core.logic import graph as graph_logic
from tests import seed
from tests.coords._helpers import add_layer, create_experiment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


AS_AFFINE = """
query AsAffine($id: ID!) {
  experiment(id: $id) {
    layers {
      id
      placement
      placementInvariance
      pathToWorld { inverted transformation { id kind } }
      asAffine { matrix inputAxes outputAxes total }
    }
  }
}
"""

STRICT = """
query Strict($id: ID!) {
  experiment(id: $id) {
    layers { id asAffine(strict: true) { matrix outputAxes total } }
  }
}
"""

CREATE_TRANSFORM = """
mutation Create($input: CreateTransformationInput!) {
  createTransformation(input: $input) { id }
}
"""

_OVER_YX = {"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"]}
_MICRON_YX = [seed.physical_axis("y", enums.AxisType.SPACE, "micrometer"), seed.physical_axis("x", enums.AxisType.SPACE, "micrometer")]


async def _view(aexecute, experiment: models.Experiment, query: str = AS_AFFINE) -> dict:  # noqa: ANN001 - the conftest fixture
    result = await aexecute(query, {"id": str(experiment.pk)})
    assert not result.errors, result.errors
    (view,) = result.data["experiment"]["layers"]
    return view


async def _register(aexecute, input_id: int, output_id: int, transform: dict) -> str:  # noqa: ANN001
    result = await aexecute(CREATE_TRANSFORM, {"input": {"input": str(input_id), "output": str(output_id), "transform": transform}})
    assert not result.errors, result.errors
    return str(result.data["createTransformation"]["id"])


def _apply(matrix: list[list[float]], point: list[float]) -> list[float]:
    """Push a point through an M x (N+1) matrix, the way a client would."""
    return [sum(factor * value for factor, value in zip(row[:-1], point)) + row[-1] for row in matrix]


async def test_a_partial_registration_condenses_over_the_axes_it_names(aexecute, authenticated_context):
    """The ordinary case: a BY_DIMENSION on (y,x) into a (z,y,x) world, and no row for z.

    This is the shape `create_identity_registration` writes for every ordinary registration
    and the shape `to_matrix` flatly refuses -- so a fixed-rank composition would fail here,
    which is exactly why the field composes functionals instead.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Tile")  # (c, y, x)
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Composition")  # (z, y, x)

    await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, {**_OVER_YX, "scale": [0.5, 0.5], "translation": [10.0, 20.0]})
    await add_layer(ctx, experiment, lens)

    view = await _view(aexecute, experiment)
    affine = view["asAffine"]

    assert view["placement"] == "PLACED"
    assert affine["inputAxes"] == ["c", "y", "x"], "the columns are the view's own source axis order"
    assert affine["outputAxes"] == ["y", "x"], "the world's z is untouched by this registration, so it has no row"
    assert affine["total"] is False, "a partial registration is not a total map, and says so"

    # y' = 0.5y + 10, x' = 0.5x + 20, and c does not reach the world at all (zero column).
    assert affine["matrix"] == [[0.0, 0.5, 0.0, 10.0], [0.0, 0.0, 0.5, 20.0]]
    assert _apply(affine["matrix"], [1.0, 100.0, 200.0]) == approx([60.0, 120.0])


async def test_strict_refuses_the_partial_map_and_names_the_axes_it_cannot_reach(aexecute, authenticated_context):
    """`strict: true` is for a client that needs a total map and would rather be told than guess.

    The default is the partial answer, because the partial answer is the truth. Strict is the
    opt-in for a renderer that cannot place data along an unconstrained axis and would
    otherwise silently draw it at zero.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Tile")
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Composition")

    await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, _OVER_YX)
    await add_layer(ctx, experiment, lens)

    # Without strict, the same view answers happily.
    assert (await _view(aexecute, experiment))["asAffine"]["total"] is False

    result = await aexecute(STRICT, {"id": str(experiment.pk)})
    assert result.errors, "strict must refuse a map that does not cover every world axis"
    assert "says nothing about ['z']" in str(result.errors[0]), str(result.errors[0])


async def test_a_total_registration_reports_total_and_composes_every_axis(aexecute, authenticated_context):
    """The other side of `total`: a registration naming every world axis has a row for each.

    Without this, a change that made `total` always false would still pass the test above.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Volume", seed.YX_AXES, [64, 64])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Composition")  # (z, y, x)

    # (y, x) -> (z, y, x): three rows, two columns, plus the translation. A tilted section,
    # so z is a real function of y rather than a zero row -- and a 3 x 2 linear part, which
    # is what makes this a *rank-changing* AFFINE with no inverse to ask about.
    await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, {"kind": "AFFINE", "affine": [[0.25, 0.0, 3.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]})
    await add_layer(ctx, experiment, lens)

    affine = (await _view(aexecute, experiment))["asAffine"]
    assert affine["outputAxes"] == ["z", "y", "x"]
    assert affine["total"] is True
    assert _apply(affine["matrix"], [8.0, 5.0]) == approx([5.0, 8.0, 5.0])


async def test_a_stepped_lens_carries_its_crop_and_its_subsample(aexecute, authenticated_context):
    """The SEQUENCE bug, pinned: a wrapper's map lives on its children, not in its params.

    `create_lens_edge` writes a SEQUENCE for a *stepped* lens -- scale on child 0, offset on
    child 1, the wrapper's own `params` empty -- so composing it from those params yields the
    identity and the crop and the subsample vanish without a word. A decimated window of a
    recording is such a lens, so this is not an exotic path.

    The lens takes y from index 8 with a step of 2, so a lens coordinate `k` is dataset
    coordinate `2k + 8`, and the assertions below fail on an identity by exactly that.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Stepped")  # (c, y, x)
    lens = await seed.create_lens(ctx, dataset, slices=[{"axis": "y", "start": 8, "stop": 64, "step": 2}])
    experiment = await create_experiment(ctx, "Composition")  # (z, y, x)
    assert lens.coordinate_system_id != dataset.coordinate_system_id, "a stepped lens owns a space of its own, or there is no SEQUENCE to test"

    await _register(aexecute, dataset.coordinate_system_id, experiment.world_id, _OVER_YX)
    await add_layer(ctx, experiment, lens)

    view = await _view(aexecute, experiment)
    assert any(step["transformation"]["kind"] == "SEQUENCE" for step in view["pathToWorld"]), "the fixture must actually put a SEQUENCE on the path"

    affine = view["asAffine"]
    assert affine["outputAxes"] == ["y", "x"]
    # Lens (c, y, x) = (0, 0, 5) is dataset y = 8, and the registration is an identity on
    # both axes. An identity-composed SEQUENCE would answer y = 0 here.
    assert _apply(affine["matrix"], [0.0, 0.0, 5.0]) == approx([8.0, 5.0])
    assert _apply(affine["matrix"], [0.0, 10.0, 5.0]) == approx([28.0, 5.0]), "the step is a factor of 2, not 1"


async def test_a_path_walked_backwards_is_inverted_rather_than_refused(aexecute, authenticated_context):
    """A step flagged `inverted` is undone, which is the whole thing clients could not do.

    Direction is always forward on the *row*, never on the walk: the registration here was
    authored world -> physical space rather than the other way, which is an ordinary thing
    for a client holding a stage-to-world map to write. The view's data reaches the world
    only by walking that edge backwards, so the composition has to invert it.

    The matrix is checked by pushing a point through it against the composition worked out
    by hand -- a matrix that is right up to a reciprocal passes every structural assertion.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Stage", seed.YX_AXES, [64, 64])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Composition")  # (z, y, x)

    # grid -> physical, stored forward: 0.1 micrometre per sample.
    physical = await seed.create_physical_space(ctx, dataset, axes=_MICRON_YX, scale=[0.1, 0.1])
    # world -> physical, also stored forward: the world's units are half the physical space's.
    await _register(aexecute, experiment.world_id, physical.pk, {**_OVER_YX, "scale": [2.0, 2.0]})
    await add_layer(ctx, experiment, lens)

    view = await _view(aexecute, experiment)
    assert view["pathToWorld"] is not None, "the data reaches the world, backwards down the world's own edge"
    assert any(step["inverted"] for step in view["pathToWorld"]), "the fixture must actually put an inverted step on the path"

    affine = view["asAffine"]
    assert affine["outputAxes"] == ["y", "x"], "the world's z is never mentioned, in either direction"
    # Samples to physical is times 0.1; physical to world is the times-2 edge undone, so halve.
    assert _apply(affine["matrix"], [100.0, 200.0]) == approx([5.0, 10.0])


async def test_a_field_step_errors_and_names_the_edge(aexecute, authenticated_context):
    """A path that exists and does not condense is an error, never a null.

    Null already means two things -- unregistered, or unmappable -- and `placement` is what
    tells them apart. Adding a third meaning ("there is a path but I would not compose it")
    would make the null useless. A FIELD gives its map as the values of an array, so there is
    no closed form at all, and the error says which edge.
    """
    ctx = authenticated_context
    experiment = await create_experiment(ctx, "Composition")

    mask = await seed.create_dataset(ctx, "Mask", seed.YX_AXES, [64, 64])
    objects = await seed.create_dataset(ctx, "Objects", [seed.axis("i", enums.AxisType.INDEX)], [128])
    lens = await seed.create_lens(ctx, mask)

    # The mask's values ARE the map into the object space, and the object space is placed in the world.
    field_id = await _register(
        aexecute,
        mask.coordinate_system_id,
        objects.coordinate_system_id,
        {"kind": "FIELD", "field": str(mask.coordinate_system_id), "inputAxes": ["y", "x"], "outputAxes": ["i"]},
    )
    await _register(aexecute, objects.coordinate_system_id, experiment.world_id, {"kind": "BY_DIMENSION", "inputAxes": ["i"], "outputAxes": ["z"]})
    await add_layer(ctx, experiment, lens)

    result = await aexecute(AS_AFFINE, {"id": str(experiment.pk)})
    assert result.errors, "a FIELD on the path has no closed form, and silence about that would be worse than an error"
    message = str(result.errors[0])
    assert f"transformation {field_id} (FIELD)" in message, message


async def test_an_unregistered_layer_is_null_exactly_as_its_path_is(aexecute, authenticated_context):
    """Null when and only when `pathToWorld` is null, and `placement` still says which gap it is."""
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Unplaced")
    experiment = await create_experiment(ctx, "Composition")
    await add_layer(ctx, experiment, await seed.create_lens(ctx, dataset))

    view = await _view(aexecute, experiment)
    assert view["pathToWorld"] is None
    assert view["asAffine"] is None, "the two nulls agree, because they are the same absence"
    assert view["placement"] == "UNREGISTERED", "and `placement` is still what says which of the two it is"


async def test_an_unmappable_layer_is_null_too_and_placement_tells_it_apart(aexecute, authenticated_context):
    """The second reason for a null, which is a fact to badge rather than a gap to close."""
    ctx = authenticated_context
    source = await seed.create_dataset(ctx, "Source", seed.YX_AXES, [64, 64])
    derived = await seed.create_dataset(ctx, "Measured", seed.YX_AXES, [64, 64])
    experiment = await create_experiment(ctx, "Composition")

    await _register(aexecute, source.coordinate_system_id, experiment.world_id, _OVER_YX)
    await _register(aexecute, derived.coordinate_system_id, source.coordinate_system_id, {"kind": "UNMAPPABLE", "reason": "one row per sorted unit"})
    await add_layer(ctx, experiment, await seed.create_lens(ctx, derived))

    view = await _view(aexecute, experiment)
    assert view["asAffine"] is None
    assert view["placement"] == "UNMAPPABLE", "there is no registration to go and author here"


async def test_as_affine_condenses_the_very_path_that_path_to_world_reports(aexecute, authenticated_context):
    """The two fields must never be able to disagree: same universe, same walk, same tie-break.

    A composed answer that came from a *different* path than the one the client can inspect
    would be worse than no composed answer at all -- it would be unfalsifiable from outside.
    So `condensed_placement` is built on `placement_path`, and this holds it there by
    composing the reported steps by hand and comparing.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Chain", seed.YX_AXES, [64, 64])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Composition")

    physical = await seed.create_physical_space(ctx, dataset, axes=_MICRON_YX, scale=[0.1, 0.1])
    await _register(aexecute, physical.pk, experiment.world_id, {**_OVER_YX, "translation": [5.0, -5.0]})
    await add_layer(ctx, experiment, lens)

    view = await _view(aexecute, experiment)
    assert len(view["pathToWorld"]) == 2, "the fixture must exercise a multi-hop path"

    affine = view["asAffine"]
    # Composed by hand from the reported steps: scale by 0.1 into the physical space, then
    # offset into the world.
    assert _apply(affine["matrix"], [100.0, 200.0]) == approx([15.0, 15.0])

    # And the server's own composition of the same steps, through the logic layer, agrees.
    def composed() -> list[list[float]]:
        condensed = graph_logic.condense_path(
            [(models.Transformation.objects.get(pk=step["transformation"]["id"]), step["inverted"]) for step in view["pathToWorld"]],
            source_axes=[axis.name for axis in dataset.coordinate_system.axes.all()],
            destination_axes=[axis.name for axis in experiment.world.axes.all()],
        )
        return condensed.matrix

    assert await sync_to_async(composed)() == affine["matrix"]
