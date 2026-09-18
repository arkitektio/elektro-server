"""Experiments executed against the schema: data laid out on one timeline, as layers.

An experiment is mikro's scene, over time. It holds no time facts of its own: where a
recording sits is one edge from its clock into the experiment's world (``createClockOffset``),
how much of it is shown is a lens, and what is drawn is a layer. These tests state things the
way a client does -- "this recording, 50 ms in, the first 10 ms of it" -- and check what that
was written as, and that the placement read back is the one that was stated.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core.logic import clocks
from core.models import CoordinateSystem, Experiment, ExperimentLayer, Lens, Transformation
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


LAYER_FIELDS = """
    id
    kind
    name
    order
    visible
    placement
    placementValidity
    placementInvariance
    pathToWorld { inverted transformation { kind input { name } output { name } } }
    ... on TraceLayer { duration lens { id shape slices { axis start stop } dataset { id } } }
"""

EXPERIMENT = """
query ($id: ID!) {
  experiment(id: $id) {
    id
    name
    world { id name epoch axes { name type unit } registrations { kind input { name } } }
    layers { %s }
  }
}
""" % LAYER_FIELDS

CREATE_EXPERIMENT = """
mutation ($input: CreateExperimentInput!) {
  createExperiment(input: $input) { id name world { id name epoch axes { name type unit } } }
}
"""

CREATE_CLOCK_OFFSET = "mutation ($input: CreateClockOffsetInput!) { createClockOffset(input: $input) { id kind } }"

CREATE_TRACE_LAYER = """
mutation ($input: CreateTraceLayerInput!) {
  createTraceLayer(input: $input) { %s asAffine { matrix inputAxes outputAxes total } }
}
""" % LAYER_FIELDS

AS_AFFINE = "query ($id: ID!) { experiment(id: $id) { layers { asAffine { matrix } } } }"


async def _experiment(aexecute, name: str, **extra) -> dict:  # noqa: ANN001, ANN003
    created = await aexecute(CREATE_EXPERIMENT, {"input": {"name": name, **extra}})
    assert not created.errors, created.errors
    return created.data["createExperiment"]


async def _place(aexecute, clock, world_id: str, offset: str) -> None:  # noqa: ANN001
    placed = await aexecute(CREATE_CLOCK_OFFSET, {"input": {"clock": str(clock.pk), "onto": world_id, "offset": offset}})
    assert not placed.errors, placed.errors


async def _trace(aexecute, experiment_id: str, dataset, **extra) -> "object":  # noqa: ANN001, ANN003
    return await aexecute(CREATE_TRACE_LAYER, {"input": {"experiment": experiment_id, "dataset": str(dataset.pk), **extra}})


async def test_create_experiment(aexecute, make_simulation_chain):
    """A run recorded at 10 kHz, laid 50 ms into a fresh timeline: t_world = sample * 0.0001 s + 0.05 s."""
    chain = await make_simulation_chain()
    experiment = await _experiment(aexecute, "Exp")
    assert experiment["world"]["name"] == "Exp/world"
    assert experiment["world"]["axes"] == [{"name": "t", "type": "TIME", "unit": "second"}]
    assert experiment["world"]["epoch"] is None, "trial-aligned time has no wall clock"

    await _place(aexecute, chain.clock, experiment["world"]["id"], "50 ms")
    recorded = await _trace(aexecute, experiment["id"], chain.recording, name="Vm")
    assert not recorded.errors, recorded.errors
    injected = await _trace(aexecute, experiment["id"], chain.stimulus)
    assert not injected.errors, injected.errors

    res = await aexecute(EXPERIMENT, {"id": experiment["id"]})
    assert not res.errors, res.errors
    read = res.data["experiment"]
    assert read["world"]["registrations"] == [{"kind": "BY_DIMENSION", "input": {"name": "sim/clock"}}], "two layers of one run, one edge: they cannot be laid out apart"

    recording_layer, stimulus_layer = read["layers"]
    assert (recording_layer["kind"], recording_layer["name"], recording_layer["order"], stimulus_layer["order"]) == ("TRACE", "Vm", 0, 1)
    assert stimulus_layer["name"] == "sim/iclamp", "defaults to the dataset's name"
    assert recording_layer["duration"] == "40 ms", "400 samples at 10 kHz"
    assert recording_layer["lens"]["slices"] == [] and recording_layer["lens"]["shape"] == [400]

    assert (recording_layer["placement"], recording_layer["placementValidity"], recording_layer["placementInvariance"]) == ("PLACED", "INFERRED", "AFFINE")
    hops = [(step["transformation"]["input"]["name"], step["transformation"]["output"]["name"]) for step in recording_layer["pathToWorld"]]
    assert hops == [("sim/soma.v/intrinsic", "sim/clock"), ("sim/clock", "Exp/world")], "sample grid -> simulation clock -> world"
    assert all(step["inverted"] is False for step in recording_layer["pathToWorld"])

    affine = recorded.data["createTraceLayer"]["asAffine"]
    assert (affine["inputAxes"], affine["outputAxes"], affine["total"]) == (["t"], ["t"], True)
    assert affine["matrix"][0] == approx([0.0001, 0.05]), "the sampling law in ms and the offset in s, multiplied out into seconds"

    assert not [field.name for field in ExperimentLayer._meta.get_fields() if field.name in ("offset", "duration", "time_dataset")], "a layer carries no time of its own"


async def test_a_window_is_lowered_to_a_lens_in_sample_indices(aexecute, make_simulation_chain):
    """The 10 ms from 5 ms in, of a run recorded at 10 kHz from t = 0: samples 50 to 150."""
    chain = await make_simulation_chain()
    experiment = await _experiment(aexecute, "Windowed")
    await _place(aexecute, chain.clock, experiment["world"]["id"], "0 s")
    res = await _trace(aexecute, experiment["id"], chain.recording, window={"start": "5 ms", "stop": "15 ms"})
    assert not res.errors, res.errors
    layer = res.data["createTraceLayer"]

    assert layer["lens"]["slices"] == [{"axis": "t", "start": 50, "stop": 150}]
    assert layer["lens"]["shape"] == [100]
    assert layer["duration"] == "10 ms"
    assert [step["transformation"]["kind"] for step in layer["pathToWorld"]] == ["TRANSLATION", "BY_DIMENSION", "BY_DIMENSION"], "lens shift, sampling law, offset"
    assert layer["asAffine"]["matrix"][0] == approx([0.0001, 0.005]), "sample 0 of the window is sample 50 of the run, 5 ms in"


async def test_showing_everything_reuses_the_unsliced_lens(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    for name in ("First", "Second"):
        experiment = await _experiment(aexecute, name)
        await _place(aexecute, chain.clock, experiment["world"]["id"], "0 s")
        res = await _trace(aexecute, experiment["id"], chain.recording)
        assert not res.errors, res.errors
    assert await Lens.objects.filter(dataset=chain.recording).acount() == 1, "an unsliced lens owns no space, so a second would say nothing the first did not"


async def test_refining_the_offset_moves_every_layer_that_looks_through_it(aexecute, make_simulation_chain):
    """Nothing stored a composed path, so there is nothing to go stale."""
    chain = await make_simulation_chain()
    experiment = await _experiment(aexecute, "Movable")
    await _place(aexecute, chain.clock, experiment["world"]["id"], "50 ms")
    assert not (await _trace(aexecute, experiment["id"], chain.recording)).errors
    edge = await sync_to_async(lambda: Transformation.objects.get(input=chain.clock, output_id=experiment["world"]["id"], parent__isnull=True))()

    update = "mutation ($input: UpdateTransformationInput!) { updateTransformation(input: $input) { id } }"
    moved = await aexecute(update, {"input": {"id": str(edge.pk), "affine": [[0.001, 2.0]]}})
    assert not moved.errors, moved.errors

    reread = await aexecute(AS_AFFINE, {"id": experiment["id"]})
    assert reread.data["experiment"]["layers"][0]["asAffine"]["matrix"][0] == approx([0.0001, 2.0])


async def test_an_experiment_can_adopt_a_world_it_does_not_own(aexecute, authenticated_context, make_simulation_chain):
    """Two experiments over one world: the clock is placed on the world once, and both see it there."""
    chain = await make_simulation_chain()
    world = await seed.create_world(authenticated_context, "shared timeline", axes=seed.CLOCK_AXES)
    first = await _experiment(aexecute, "A", coordinateSystem=str(world.pk))
    await _place(aexecute, chain.clock, str(world.pk), "1 s")
    assert not (await _trace(aexecute, first["id"], chain.recording)).errors
    second = await _experiment(aexecute, "B", coordinateSystem=str(world.pk))
    layer = await _trace(aexecute, second["id"], chain.stimulus)
    assert not layer.errors, layer.errors

    assert second["world"]["id"] == str(world.pk)
    assert layer.data["createTraceLayer"]["asAffine"]["matrix"][0][-1] == approx(1.0), "the offset is the world's fact, not either experiment's"
    assert await Transformation.objects.filter(output=world, parent__isnull=True).acount() == 1

    # Deleting an experiment never deletes the space it adopted.
    deleted = await aexecute("mutation ($input: DeleteInput!) { deleteExperiment(input: $input) }", {"input": {"id": first["id"]}})
    assert not deleted.errors, deleted.errors
    assert await CoordinateSystem.objects.filter(pk=world.pk).aexists()


# --- a run timed by a lookup: admitted, and honest about having no matrix ------------------------


async def test_a_layer_over_a_lookup_timed_run_is_placed_without_an_affine_map(aexecute, make_simulation_chain):
    """Deliberately looser than mikro's gate (rfc10), which refuses a layer that does not condense: a timeline can draw samples at looked-up instants."""
    chain = await make_simulation_chain(timing="lookup")
    experiment = await _experiment(aexecute, "CVode")
    await _place(aexecute, chain.clock, experiment["world"]["id"], "0 s")
    res = await _trace(aexecute, experiment["id"], chain.recording)
    assert res.data is not None and res.data["createTraceLayer"]["placement"] == "PLACED"
    layer = res.data["createTraceLayer"]
    assert layer["placementInvariance"] == "DIFFEOMORPHIC", "intervals between samples are not uniform, so nothing metric transfers"
    assert [step["transformation"]["kind"] for step in layer["pathToWorld"]] == ["FIELD", "BY_DIMENSION"]
    assert layer["duration"] is None, "a sample count is not a duration without a sampling law"

    assert res.errors and "asAffine" in str(res.errors[0].path), "the map has no closed form, and says so rather than answering null"


async def test_a_window_over_a_lookup_timed_run_is_refused(aexecute, make_simulation_chain):
    chain = await make_simulation_chain(timing="lookup")
    experiment = await _experiment(aexecute, "NoInverse")
    await _place(aexecute, chain.clock, experiment["world"]["id"], "0 s")
    res = await _trace(aexecute, experiment["id"], chain.recording, window={"start": "5 ms", "stop": "15 ms"})
    assert res.errors and "has no closed-form inverse" in str(res.errors[0])
    assert not await ExperimentLayer.objects.aexists()


# --- CS-first: an experiment over a clock data is already timed on ------------------------------


BOOTSTRAP = """
mutation ($input: CreateExperimentFromCoordinateSystemInput!) {
  createExperimentFromCoordinateSystem(input: $input) {
    id
    name
    world { id }
    layers {
      kind name order placement placementInvariance
      ... on TraceLayer { lens { dataset { name } } }
      ... on SpikesLayer { sparseDataset { name } tickHeight valueMode unitTable { name } }
      ... on EventsLayer { tableDataset { name } timeColumn labelColumn stopColumn }
    }
  }
}
"""


async def test_a_session_clock_is_staged_as_an_experiment(aexecute, authenticated_context):
    """A recording session built CS-first: a clock, a trace, a spike raster and an event table timed on it, one bootstrap.

    The segment's recording sits on its own clock, offset into the session's: the chain of clocks
    is what `frames_into` exists for, so the bootstrap reaches it as `inView` does.
    """
    ctx = authenticated_context
    session = await seed.create_clock(ctx, "session", unit="second")
    segment = await seed.create_clock(ctx, "segment 2", unit="second")
    await seed.offset_onto(ctx, segment, session, "12 s")

    vm = await seed.create_array_dataset(ctx, "Vm", seed.TC_AXES, [[30000, 2]])
    await seed.time_on(ctx, vm.coordinate_system, segment, rate="30 kHz")
    units = await seed.create_table_dataset(ctx, "units", columns=[{"name": "unit_id", "axis_type": seed.enums.AxisType.INDEX}, {"name": "depth", "unit": "micrometer"}])
    raster = await seed.create_sparse_dataset(ctx, "sorted spikes", units=units)
    await seed.time_on(ctx, raster.coordinate_system, session, rate="30 kHz")
    events = await seed.create_table_dataset(ctx, "TTL")
    await seed.offset_onto(ctx, events.coordinate_system, session, "0 s")

    res = await aexecute(BOOTSTRAP, {"input": {"coordinateSystem": str(session.pk)}})
    assert not res.errors, res.errors
    staged = res.data["createExperimentFromCoordinateSystem"]
    assert staged["name"] == "session" and staged["world"]["id"] == str(session.pk), "adopted, and named for the space"

    kinds = [(layer["kind"], layer["name"], layer["order"]) for layer in staged["layers"]]
    assert kinds == [("TRACE", "Vm", 0), ("SPIKES", "sorted spikes", 1), ("EVENTS", "TTL", 2)], "traces, spikes, events -- one per source, one running order"
    trace, spikes, table = staged["layers"]
    assert all(layer["placement"] == "PLACED" for layer in staged["layers"])
    assert trace["placementInvariance"] == "AFFINE", "grid -> segment clock -> session clock, all affine"
    assert (spikes["tickHeight"], spikes["valueMode"], spikes["unitTable"]) == (0.8, "PRESENCE", {"name": "units"})
    assert (table["timeColumn"], table["labelColumn"], table["stopColumn"]) == ("t", "label", None)
    assert not await Transformation.objects.filter(output=session).exclude(input__in=[segment, raster.coordinate_system, events.coordinate_system]).aexists(), "authors no edges"


async def test_the_bootstrap_leaves_out_times_datasets_and_what_is_excluded(aexecute, authenticated_context):
    ctx = authenticated_context
    session = await seed.create_clock(ctx, "session", unit="second")
    signal = await seed.create_dataset(ctx, "Ca", seed.T_AXES, [50])
    times = await seed.create_dataset(ctx, "Ca/times", seed.T_AXES, [50], value_unit="second")
    await sync_to_async(clocks.write_time_lookup)(grid=signal.coordinate_system, clock=session, times=times, input_axis="t", ctx=seed._creation(ctx))
    events = await seed.create_table_dataset(ctx, "TTL")
    await seed.offset_onto(ctx, events.coordinate_system, session, "0 s")

    res = await aexecute(BOOTSTRAP, {"input": {"coordinateSystem": str(session.pk), "name": "only traces", "policy": {"includeEvents": False}}})
    assert not res.errors, res.errors
    staged = res.data["createExperimentFromCoordinateSystem"]
    assert [(layer["kind"], layer["name"]) for layer in staged["layers"]] == [("TRACE", "Ca")], "a times dataset is a lookup's map, not a signal; the events were excluded by policy"
    assert staged["layers"][0]["placementInvariance"] == "DIFFEOMORPHIC"


# --- negatives ---------------------------------------------------------------


async def test_a_clock_has_one_offset_on_another(aexecute, make_simulation_chain):
    """The bug the per-view offset column allowed: stimulus and response silently laid out apart. Now there is one place to say it."""
    chain = await make_simulation_chain()
    experiment = await _experiment(aexecute, "Misaligned")
    await _place(aexecute, chain.clock, experiment["world"]["id"], "50 ms")
    again = await aexecute(CREATE_CLOCK_OFFSET, {"input": {"clock": str(chain.clock.pk), "onto": experiment["world"]["id"], "offset": "60 ms"}})
    assert again.errors and "already sits on" in str(again.errors[0])
    assert await Transformation.objects.filter(input=chain.clock, parent__isnull=True).acount() == 1


async def test_a_layer_with_no_route_into_the_world_is_refused(aexecute, make_simulation_chain):
    """Nothing is placed by default: an assumed offset of zero cannot be told from a measured one."""
    chain = await make_simulation_chain()
    experiment = await _experiment(aexecute, "Floating")
    res = await _trace(aexecute, experiment["id"], chain.recording)
    assert res.errors and "Nothing relates" in str(res.errors[0]) and "createClockOffset" in str(res.errors[0])
    assert not await ExperimentLayer.objects.aexists()


async def test_an_offset_is_between_clocks(aexecute, make_simulation_chain):
    """A sample grid's TIME axis has no unit: placing a grid is a sampling law's job, not an offset's."""
    chain = await make_simulation_chain()
    experiment = await _experiment(aexecute, "Grid")
    res = await aexecute(CREATE_CLOCK_OFFSET, {"input": {"clock": str(chain.grid.pk), "onto": experiment["world"]["id"], "offset": "0 s"}})
    assert res.errors and "is not a clock" in str(res.errors[0])


async def test_create_trace_layer_unknown_dataset(aexecute):
    experiment = await _experiment(aexecute, "ExpBad")
    res = await aexecute(CREATE_TRACE_LAYER, {"input": {"experiment": experiment["id"], "dataset": "999999"}})
    assert res.errors


async def test_create_experiment_missing_name(aexecute):
    res = await aexecute(CREATE_EXPERIMENT, {"input": {}})
    assert res.errors


async def test_a_trace_layer_draws_a_lens_or_a_dataset_but_not_both(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    experiment = await _experiment(aexecute, "Both")
    res = await _trace(aexecute, experiment["id"], chain.recording, lens="1")
    assert res.errors and "exactly one of the two" in str(res.errors[0])


async def test_an_adopted_world_needs_a_time_axis(aexecute, authenticated_context):
    world = await seed.create_world(authenticated_context, "space only", axes=seed.ZYX_WORLD_AXES)
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Flat", "coordinateSystem": str(world.pk)}})
    assert res.errors and "has no TIME axis" in str(res.errors[0])


async def test_another_organization_cannot_draw_this_ones_recordings_or_adopt_its_world(aexecute, authenticated_context, make_simulation_chain, other_org_context):
    chain = await make_simulation_chain()
    world = await seed.create_world(authenticated_context, "mine", axes=seed.CLOCK_AXES)

    theirs = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Theirs"}}, context=other_org_context)
    assert not theirs.errors, theirs.errors
    stolen = await aexecute(CREATE_TRACE_LAYER, {"input": {"experiment": theirs.data["createExperiment"]["id"], "dataset": str(chain.recording.pk)}}, context=other_org_context)
    assert stolen.errors
    adopted = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Squatter", "coordinateSystem": str(world.pk)}}, context=other_org_context)
    assert adopted.errors
    assert not await Experiment.objects.filter(name="Squatter").aexists()
    assert not await ExperimentLayer.objects.aexists()
