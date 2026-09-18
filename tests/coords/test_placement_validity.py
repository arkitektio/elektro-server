"""Validity is an edge fact, and a view derives it from its path.

Ported from mikro's ``tests/test_placement_validity.py``. ``tests/experiment`` reads
``placementValidity`` once, off the one path `createExperiment` writes; it never checks that
the answer is a *minimum*, nor that validating an edge lifts a view without a write to it.

How-known a placement is lives on the transformation edge, where the writers actually know it
(derived plumbing is VALIDATED, a sampling law read off metadata is INFERRED, an authored
offset is MANUAL, and a client that knows it is guessing says UNKNOWN), and the view's
validity is *derived*: the weakest edge on its path to world. Fixing one edge fixes every
view that looks through it, because there is only one copy of the fact.
"""

import pytest
from asgiref.sync import sync_to_async

from core import enums, models
from tests import seed
from tests.coords._helpers import add_layer, create_experiment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


VIEW_VALIDITY = """
query ViewValidity($id: ID!) {
  experiment(id: $id) {
    layers { id placementValidity pathToWorld { transformation { id validity } } }
  }
}
"""

REGISTER = """
mutation Register($input: CreateTransformationInput!) {
  createTransformation(input: $input) { id validity }
}
"""

REFINE = """
mutation Refine($input: UpdateTransformationInput!) {
  updateTransformation(input: $input) { id validity }
}
"""


async def _view(aexecute, experiment: models.Experiment) -> dict:  # noqa: ANN001 - the conftest fixture
    result = await aexecute(VIEW_VALIDITY, {"id": str(experiment.pk)})
    assert not result.errors, result.errors
    (view,) = result.data["experiment"]["layers"]
    return view


async def test_an_assumed_placement_reads_unknown(aexecute, authenticated_context):
    """An edge a client admits it guessed reads UNKNOWN, and the view surfaces it.

    The server writes UNKNOWN nowhere: it fabricates no placements, so the badge exists for
    a client that has one and knows it is a guess -- an offset eyeballed from a plot, a start
    time read off a filename. It is authored like any other edge; only the validity differs.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Assumed", shapes=[[2, 64, 64]])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Composition")  # (z, y, x)

    registered = await aexecute(
        REGISTER,
        {
            "input": {
                "input": str(dataset.coordinate_system_id),
                "output": str(experiment.world_id),
                "validity": "UNKNOWN",
                "transform": {"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"], "scale": [1.0, 1.0]},
            }
        },
    )
    assert not registered.errors, registered.errors
    assert registered.data["createTransformation"]["validity"] == "UNKNOWN"
    await add_layer(ctx, experiment, lens)

    assert (await _view(aexecute, experiment))["placementValidity"] == "UNKNOWN"


async def test_an_authored_registration_reads_manual_and_validating_it_needs_no_layer_write(aexecute, authenticated_context):
    """MANUAL when someone authors the edge; VALIDATED the moment the edge says so.

    The second half is the point of the move: validating a registration touches the
    *edge*, and the view -- every view over this dataset -- reflects it immediately,
    because its validity is derived, never stored.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Registered")  # (c, y, x)
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Composition")  # (z, y, x)

    registered = await aexecute(
        REGISTER,
        {
            "input": {
                "input": str(dataset.coordinate_system_id),
                "output": str(experiment.world_id),
                "transform": {"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"], "affine": [[1.0, 0.0, 10.0], [0.0, 1.0, 20.0]]},
            }
        },
    )
    assert not registered.errors, registered.errors
    assert registered.data["createTransformation"]["validity"] == "MANUAL", "an edge that arrived through the API was authored by someone"
    edge_id = registered.data["createTransformation"]["id"]
    await add_layer(ctx, experiment, lens)

    assert (await _view(aexecute, experiment))["placementValidity"] == "MANUAL"

    refined = await aexecute(REFINE, {"input": {"id": edge_id, "validity": "VALIDATED"}})
    assert not refined.errors, refined.errors
    assert refined.data["updateTransformation"]["validity"] == "VALIDATED"

    assert (await _view(aexecute, experiment))["placementValidity"] == "VALIDATED"


async def test_the_weakest_edge_on_the_path_wins(aexecute, authenticated_context):
    """Two hops, two validities: the view reads the weaker one, and fixing it lifts the view.

    A **sliced** lens in an experiment over the dataset's physical space walks two edges: the
    crop into the sample grid (VALIDATED -- the server derived it from the slices) and the
    calibration into the physical space (INFERRED -- someone read a step off metadata).
    The view reads INFERRED, because a placement is only as right as its weakest claim.

    The second hop is what makes this a test rather than a tautology: over a one-edge path
    the minimum is the edge itself and nothing is being asserted.

    Validating the calibration -- one edge write, no view write -- lifts the view, because
    its validity is derived.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Calibrated", shapes=[[2, 64, 64]])
    calibration = await seed.create_physical_space(
        ctx,
        dataset,
        axes=[
            seed.physical_axis("c", enums.AxisType.CHANNEL, "a.u."),
            seed.physical_axis("y", enums.AxisType.SPACE, "micrometer"),
            seed.physical_axis("x", enums.AxisType.SPACE, "micrometer"),
        ],
        scale=[1.0, 0.325, 0.325],
    )
    sliced = await seed.create_lens(ctx, dataset, slices=[{"axis": "y", "start": 8, "stop": 40}])
    experiment = await create_experiment(ctx, "Physical", world=calibration)
    await add_layer(ctx, experiment, sliced)

    view = await _view(aexecute, experiment)
    assert [hop["transformation"]["validity"] for hop in view["pathToWorld"]] == ["VALIDATED", "INFERRED"], (
        f"the path must have two hops of differing validity or the minimum below asserts nothing: {view['pathToWorld']}"
    )
    assert view["placementValidity"] == "INFERRED", "the calibration is the weakest claim on the path"

    def validate_calibration() -> None:
        edge = models.Transformation.objects.get(output=calibration)
        edge.validity = "VALIDATED"
        edge.save(update_fields=["validity"])

    await sync_to_async(validate_calibration)()

    assert (await _view(aexecute, experiment))["placementValidity"] == "VALIDATED", "fixing the one edge fixes every view that looks through it"


async def test_the_layer_carries_no_placement_columns():
    """A view's validity is derived: it is no stored column, and the derived field wears its own name."""
    from elektro_server.schema import schema

    for model in (models.ExperimentLayer,):
        columns = {field.name for field in model._meta.get_fields()}
        assert not columns & {"status", "validity", "offset", "duration"}, f"{model.__name__} stores a placement fact: {columns}"

    sdl = str(schema)
    definition = sdl[sdl.find("interface ExperimentLayer ") : sdl.find("\n}", sdl.find("interface ExperimentLayer "))]
    assert "\n  status" not in definition
    assert "placementValidity(" in definition and "): PlacementValidity!" in definition, "the derived aggregate survives, under its own name and taking the coordinate to answer at"
    assert "\n  validity" not in definition, "the bare word belongs to the edge, not the view"

    transformation = sdl[sdl.find("interface Transformation ") : sdl.find("\n}", sdl.find("interface Transformation "))]
    assert "validity: PlacementValidity" in transformation, "the stored fact lives on the edge"
