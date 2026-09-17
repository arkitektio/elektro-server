"""createSimulation executed against the schema, over array datasets that already exist.

A run holds no data: its recordings and stimuli *name* datasets made by
``createArrayDataset``, and ``createSimulation`` writes a clock, a site row per dataset, and
one timing edge per dataset -- a sampling law for a fixed recording interval, a time lookup
for a variable time step -- all onto that one clock. Every dataset owns its own sample grid,
as in mikro; that stimulus and response line up is a fact about their edges.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core.models import ArrayDataset, CoordinateSystem, Simulation, Transformation

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_SIMULATION = """
mutation ($input: CreateSimulationInput!) {
  createSimulation(input: $input) {
    id
    name
    description
    duration
    dt
    samplingRate
    clock { id axes { name type unit } epoch }
    timeDataset { id name valueUnit intrinsicSystem { residents { __typename } } }
    recordings { id kind label cell location position samplingRate tStart dataset { id name valueUnit shape intrinsicSystem { id } } }
    stimuli { id kind label samplingRate dataset { id valueUnit intrinsicSystem { id } } }
  }
}
"""

DELETE_SIMULATION = "mutation ($input: DeleteSimulationInput!) { deleteSimulation(input: $input) }"


def _sites(recording: dict, stimulus: dict) -> dict:
    return {
        "recordings": [{"dataset": recording["id"], "kind": "VOLTAGE", "cell": "soma", "location": "0", "position": 0.5}],
        "stimuli": [{"dataset": stimulus["id"], "kind": "CURRENT", "cell": "soma", "location": "0", "position": 0.5, "label": "IClamp"}],
    }


async def _run_datasets(create_array_dataset, samples: int = 1600, stimulus_samples: int | None = None):
    recording = await create_array_dataset("soma.v", [samples], value_unit="mV")
    stimulus = await create_array_dataset("iclamp", [stimulus_samples or samples], value_unit="nA")
    return recording, stimulus


async def test_a_run_recorded_at_a_fixed_interval_has_a_sampling_law_per_dataset(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model()
    rec, stim = await _run_datasets(create_array_dataset)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Sim", "model": str(nm.id), "duration": "40 ms", "dt": "25 us", "sampling": {"rate": "40 kHz"}, **_sites(rec, stim)}})
    assert not res.errors, res.errors
    sim = res.data["createSimulation"]

    assert sim["clock"]["axes"] == [{"name": "t", "type": "TIME", "unit": "millisecond"}], "NEURON counts in milliseconds"
    assert sim["clock"]["epoch"] is None, "simulated time has no wall clock"
    assert (sim["duration"], sim["dt"]) == ("40 ms", "25 µs"), "integrator parameters, kept as stated"
    assert sim["samplingRate"] == "40 kHz" and sim["timeDataset"] is None

    (recording,), (stimulus,) = sim["recordings"], sim["stimuli"]
    assert recording["label"] == "soma: 0(0.5)" and recording["position"] == 0.5
    assert stimulus["label"] == "IClamp"
    assert (recording["dataset"]["id"], stimulus["dataset"]["id"]) == (rec["id"], stim["id"]), "the run named the datasets; it did not copy them"
    assert (recording["dataset"]["valueUnit"], stimulus["dataset"]["valueUnit"]) == ("mV", "nA"), "what was measured is the dataset's to say"
    assert (recording["samplingRate"], recording["tStart"], stimulus["samplingRate"]) == ("40 kHz", "0 s", "40 kHz")

    grids = [recording["dataset"]["intrinsicSystem"]["id"], stimulus["dataset"]["intrinsicSystem"]["id"]]
    assert len(set(grids)) == 2, "every dataset owns its own sample grid, as in mikro"
    edges = await sync_to_async(lambda: list(Transformation.objects.filter(input_id__in=grids, parent__isnull=True).order_by("pk")))()
    assert len(edges) == 2, "one edge per dataset"
    assert {str(edge.output_id) for edge in edges} == {sim["clock"]["id"]}, "all onto the run's one clock, which is what lines stimulus and response up"
    for edge in edges:
        assert edge.params["affine"][0] == approx([0.025, 0.0]), "a period of 1/40 kHz, written in the clock's milliseconds"


async def test_a_run_with_a_variable_time_step_is_timed_by_a_lookup(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model()
    rec, stim = await _run_datasets(create_array_dataset, 731)
    times = await create_array_dataset("CVode/times", [731], value_unit="millisecond")
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "CVode", "model": str(nm.id), "duration": "40 ms", "timeDataset": times["id"], **_sites(rec, stim)}})
    assert not res.errors, res.errors
    sim = res.data["createSimulation"]

    assert sim["samplingRate"] is None and sim["dt"] is None
    assert sim["timeDataset"]["id"] == times["id"], "not a column: read back off a lookup edge"
    assert sim["timeDataset"]["valueUnit"] == "millisecond", "the times are in the clock's unit, which is what lets a number-free lookup be right"
    assert [r["__typename"] for r in sim["timeDataset"]["intrinsicSystem"]["residents"]] == ["ArrayDataset", "DataArray"], "a dataset whose values are a map lives alone"

    grids = [site["dataset"]["intrinsicSystem"]["id"] for site in (*sim["recordings"], *sim["stimuli"])]
    edges = await sync_to_async(lambda: list(Transformation.objects.filter(input_id__in=grids, parent__isnull=True)))()
    assert [edge.kind for edge in edges] == ["FIELD", "FIELD"], "one lookup per dataset, through the one times dataset"
    assert {str(edge.field_id) for edge in edges} == {times["intrinsicSystem"]["id"]}


async def test_delete_simulation_deletes_the_interpretation_and_none_of_the_data(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model()
    rec, stim = await _run_datasets(create_array_dataset, 731)
    times = await create_array_dataset("times", [731], value_unit="millisecond")
    created = await aexecute(CREATE_SIMULATION, {"input": {"name": "Gone", "model": str(nm.id), "duration": "40 ms", "timeDataset": times["id"], **_sites(rec, stim)}})
    assert not created.errors, created.errors

    res = await aexecute(DELETE_SIMULATION, {"input": {"id": created.data["createSimulation"]["id"]}})
    assert not res.errors, res.errors
    assert not await Simulation.objects.filter(name="Gone").aexists()
    assert await ArrayDataset.objects.acount() == 3, "recording, stimulus and times: the run named them, it never owned them"
    assert await CoordinateSystem.objects.acount() == 3, "the clock goes; the three sample grids stay with their data"
    assert await Transformation.objects.acount() == 0, "and the lookups onto that clock go with it"


# --- negatives ---------------------------------------------------------------


async def test_create_simulation_unknown_dataset(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model()
    rec, _ = await _run_datasets(create_array_dataset)
    sites = _sites(rec, {"id": "999999"})
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "SimBad", "model": str(nm.id), "duration": "400 ms", "sampling": {"rate": "1 kHz"}, **sites}})
    assert res.errors
    assert not await Simulation.objects.filter(name="SimBad").aexists(), "resolved before anything is written: no half-made run"
    assert await Transformation.objects.acount() == 0


async def test_create_simulation_unknown_model(aexecute, create_array_dataset):
    rec, stim = await _run_datasets(create_array_dataset)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "SimNoModel", "model": "999999", "duration": "400 ms", "sampling": {"rate": "1 kHz"}, **_sites(rec, stim)}})
    assert res.errors


@pytest.mark.parametrize("timing", [{}, {"sampling": {"rate": "1 kHz"}, "timeDataset": "1"}], ids=["neither", "both"])
async def test_a_run_is_timed_in_exactly_one_way(aexecute, make_neuron_model, create_array_dataset, timing):
    """Both would be two statements of one fact, free to disagree; neither leaves the recordings with no time at all."""
    nm = await make_neuron_model()
    rec, stim = await _run_datasets(create_array_dataset)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Untimed", "model": str(nm.id), "duration": "40 ms", **timing, **_sites(rec, stim)}})
    assert res.errors and "timed in exactly one way" in str(res.errors[0])


async def test_the_datasets_of_one_run_have_one_sample_count(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model()
    rec, stim = await _run_datasets(create_array_dataset, 1600, 1599)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Ragged", "model": str(nm.id), "duration": "40 ms", "sampling": {"rate": "40 kHz"}, **_sites(rec, stim)}})
    assert res.errors and "the same number of samples" in str(res.errors[0])
    assert not await Simulation.objects.filter(name="Ragged").aexists()


async def test_a_site_needs_a_time_axis(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model()
    rec = await create_array_dataset("soma.v", [100])
    stim = await create_array_dataset("not samples", [100], axes=[{"name": "spike", "type": "INDEX"}])
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Untimed", "model": str(nm.id), "duration": "40 ms", "sampling": {"rate": "1 kHz"}, **_sites(rec, stim)}})
    assert res.errors and "has no TIME axis" in str(res.errors[0])


async def test_sample_times_must_be_one_per_sample(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model()
    rec, stim = await _run_datasets(create_array_dataset, 731)
    times = await create_array_dataset("times", [730], value_unit="millisecond")
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Short", "model": str(nm.id), "duration": "40 ms", "timeDataset": times["id"], **_sites(rec, stim)}})
    assert res.errors and "exactly one instant per sample" in str(res.errors[0])


async def test_a_run_with_nothing_recorded_has_nothing_to_time(aexecute, make_neuron_model):
    nm = await make_neuron_model()
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Empty", "model": str(nm.id), "duration": "40 ms", "sampling": {"rate": "1 kHz"}, "recordings": [], "stimuli": []}})
    assert res.errors and "no recordings and no stimuli" in str(res.errors[0])
