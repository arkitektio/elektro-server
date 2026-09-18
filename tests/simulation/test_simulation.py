"""createSimulation executed against the schema, over array datasets that already exist.

A run holds no data and no row per dataset. What was recorded where is a ``RecordingSite`` (or
``StimulusSite``) spoke on each dataset's own anchor, said at ``createArrayDataset``; what
``createSimulation`` writes is a clock and one timing edge per dataset it is handed -- a
sampling law for a fixed recording interval, a time lookup for a variable time step -- all onto
that one clock. Which datasets belong to the run is read back off those edges.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core.models import ArrayDataset, CoordinateSystem, RecordingSite, Simulation, StimulusSite, Transformation

from tests.seed import SOMA_MODEL

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


_DATASET = "id name valueUnit intrinsicSystem { id residents { __typename } } anchors { coordinates recordingSite { kind label cell location position model { id } } stimulusSite { kind label } }"

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
    datasets { %s }
    recordings { %s }
    stimuli { %s }
  }
}
""" % (_DATASET, _DATASET, _DATASET)

DELETE_SIMULATION = "mutation ($input: DeleteSimulationInput!) { deleteSimulation(input: $input) }"


def _datasets(recording: dict, stimulus: dict) -> dict:
    return {"datasets": [recording["id"], stimulus["id"]]}


async def _run_datasets(create_array_dataset, model, samples: int = 1600, stimulus_samples: int | None = None):
    """A recorded and an injected dataset, each carrying its site -- a place on ``model`` -- on its whole-dataset anchor."""
    recording = await create_array_dataset(
        "soma.v", [samples], anchors=[{"axisAnchors": [], "valueUnit": {"unit": "mV"}, "recordingSite": {"model": str(model.id), "kind": "VOLTAGE", "cell": "soma", "location": "0", "position": 0.5}}]
    )
    stimulus = await create_array_dataset(
        "iclamp", [stimulus_samples or samples], anchors=[{"axisAnchors": [], "valueUnit": {"unit": "nA"}, "stimulusSite": {"model": str(model.id), "kind": "CURRENT", "cell": "soma", "location": "0", "position": 0.5, "label": "IClamp"}}]
    )
    return recording, stimulus


async def test_a_run_recorded_at_a_fixed_interval_has_a_sampling_law_per_dataset(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Sim", "model": str(nm.id), "duration": "40 ms", "dt": "25 us", "sampling": {"rate": "40 kHz"}, **_datasets(rec, stim)}})
    assert not res.errors, res.errors
    sim = res.data["createSimulation"]

    assert sim["clock"]["axes"] == [{"name": "t", "type": "TIME", "unit": "millisecond"}], "NEURON counts in milliseconds"
    assert sim["clock"]["epoch"] is None, "simulated time has no wall clock"
    assert (sim["duration"], sim["dt"]) == ("40 ms", "25 µs"), "integrator parameters, kept as stated"
    assert sim["samplingRate"] == "40 kHz" and sim["timeDataset"] is None

    (recording,), (stimulus,) = sim["recordings"], sim["stimuli"]
    assert [d["id"] for d in sim["datasets"]] == [rec["id"], stim["id"]], "the run's datasets are read off its timing edges, in the order they were written"
    assert (recording["id"], stimulus["id"]) == (rec["id"], stim["id"]), "the run named the datasets; it did not copy them"
    (site,) = [anchor["recordingSite"] for anchor in recording["anchors"] if anchor["recordingSite"]]
    assert site == {"kind": "VOLTAGE", "label": "soma: 0(0.5)", "cell": "soma", "location": "0", "position": 0.5, "model": {"id": str(nm.id)}}, "where it was recorded is the dataset's own spoke, a place on the model"
    (injected,) = [anchor["stimulusSite"] for anchor in stimulus["anchors"] if anchor["stimulusSite"]]
    assert injected == {"kind": "CURRENT", "label": "IClamp"}
    assert (recording["valueUnit"], stimulus["valueUnit"]) == ("mV", "nA"), "what was measured is the dataset's to say"

    grids = [recording["intrinsicSystem"]["id"], stimulus["intrinsicSystem"]["id"]]
    assert len(set(grids)) == 2, "every dataset owns its own sample grid, as in mikro"
    edges = await sync_to_async(lambda: list(Transformation.objects.filter(input_id__in=grids, parent__isnull=True).order_by("pk")))()
    assert len(edges) == 2, "one edge per dataset"
    assert {str(edge.output_id) for edge in edges} == {sim["clock"]["id"]}, "all onto the run's one clock, which is what lines stimulus and response up"
    for edge in edges:
        assert edge.params["affine"][0] == approx([0.025, 0.0]), "a period of 1/40 kHz, written in the clock's milliseconds"


async def test_a_run_with_a_variable_time_step_is_timed_by_a_lookup(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm, 731)
    times = await create_array_dataset("CVode/times", [731], value_unit="millisecond")
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "CVode", "model": str(nm.id), "duration": "40 ms", "timeDataset": times["id"], **_datasets(rec, stim)}})
    assert not res.errors, res.errors
    sim = res.data["createSimulation"]

    assert sim["samplingRate"] is None and sim["dt"] is None
    assert sim["timeDataset"]["id"] == times["id"], "not a column: read back off a lookup edge"
    assert sim["timeDataset"]["valueUnit"] == "millisecond", "the times are in the clock's unit, which is what lets a number-free lookup be right"
    assert [r["__typename"] for r in sim["timeDataset"]["intrinsicSystem"]["residents"]] == ["ArrayDataset", "DataArray"], "a dataset whose values are a map lives alone"

    grids = [dataset["intrinsicSystem"]["id"] for dataset in sim["datasets"]]
    edges = await sync_to_async(lambda: list(Transformation.objects.filter(input_id__in=grids, parent__isnull=True)))()
    assert [edge.kind for edge in edges] == ["FIELD", "FIELD"], "one lookup per dataset, through the one times dataset"
    assert {str(edge.field_id) for edge in edges} == {times["intrinsicSystem"]["id"]}


async def test_delete_simulation_deletes_the_interpretation_and_none_of_the_data(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm, 731)
    times = await create_array_dataset("times", [731], value_unit="millisecond")
    created = await aexecute(CREATE_SIMULATION, {"input": {"name": "Gone", "model": str(nm.id), "duration": "40 ms", "timeDataset": times["id"], **_datasets(rec, stim)}})
    assert not created.errors, created.errors

    res = await aexecute(DELETE_SIMULATION, {"input": {"id": created.data["createSimulation"]["id"]}})
    assert not res.errors, res.errors
    assert not await Simulation.objects.filter(name="Gone").aexists()
    assert await ArrayDataset.objects.acount() == 3, "recording, stimulus and times: the run named them, it never owned them"
    assert await CoordinateSystem.objects.acount() == 3, "the clock goes; the three sample grids stay with their data"
    assert await Transformation.objects.acount() == 0, "and the lookups onto that clock go with it"


# --- negatives ---------------------------------------------------------------


async def test_create_simulation_unknown_dataset(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, _ = await _run_datasets(create_array_dataset, nm)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "SimBad", "model": str(nm.id), "duration": "400 ms", "sampling": {"rate": "1 kHz"}, **_datasets(rec, {"id": "999999"})}})
    assert res.errors
    assert not await Simulation.objects.filter(name="SimBad").aexists(), "resolved before anything is written: no half-made run"
    assert await Transformation.objects.acount() == 0


async def test_create_simulation_unknown_model(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "SimNoModel", "model": "999999", "duration": "400 ms", "sampling": {"rate": "1 kHz"}, **_datasets(rec, stim)}})
    assert res.errors


@pytest.mark.parametrize("timing", [{}, {"sampling": {"rate": "1 kHz"}, "timeDataset": "1"}], ids=["neither", "both"])
async def test_a_run_is_timed_in_exactly_one_way(aexecute, make_neuron_model, create_array_dataset, timing):
    """Both would be two statements of one fact, free to disagree; neither leaves the datasets with no time at all."""
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Untimed", "model": str(nm.id), "duration": "40 ms", **timing, **_datasets(rec, stim)}})
    assert res.errors and "timed in exactly one way" in str(res.errors[0])


async def test_the_datasets_of_one_run_have_one_sample_count(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm, 1600, 1599)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Ragged", "model": str(nm.id), "duration": "40 ms", "sampling": {"rate": "40 kHz"}, **_datasets(rec, stim)}})
    assert res.errors and "the same number of samples" in str(res.errors[0])
    assert not await Simulation.objects.filter(name="Ragged").aexists()


async def test_a_site_needs_a_time_axis(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec = await create_array_dataset("soma.v", [100])
    stim = await create_array_dataset("not samples", [100], axes=[{"name": "unit", "type": "INDEX"}])
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Untimed", "model": str(nm.id), "duration": "40 ms", "sampling": {"rate": "1 kHz"}, **_datasets(rec, stim)}})
    assert res.errors and "has no TIME axis" in str(res.errors[0])


async def test_sample_times_must_be_one_per_sample(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm, 731)
    times = await create_array_dataset("times", [730], value_unit="millisecond")
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Short", "model": str(nm.id), "duration": "40 ms", "timeDataset": times["id"], **_datasets(rec, stim)}})
    assert res.errors and "exactly one instant per sample" in str(res.errors[0])


async def test_a_run_named_with_no_datasets_is_only_its_clock(aexecute, make_neuron_model, create_array_dataset):
    """CS-first: mint the run's clock, then time datasets on it one sampling law at a time -- the same as a recording session."""
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Later", "model": str(nm.id), "duration": "40 ms"}})
    assert not res.errors, res.errors
    sim = res.data["createSimulation"]
    assert sim["datasets"] == [] and sim["samplingRate"] is None
    assert sim["clock"]["axes"] == [{"name": "t", "type": "TIME", "unit": "millisecond"}]

    rec, _ = await _run_datasets(create_array_dataset, nm, 400)
    timed = await aexecute(
        "mutation ($input: CreateSamplingLawInput!) { createSamplingLaw(input: $input) { id kind } }",
        {"input": {"source": rec["intrinsicSystem"]["id"], "clock": sim["clock"]["id"], "samplingRate": "10 kHz"}},
    )
    assert not timed.errors, timed.errors
    asked = await aexecute("query ($id: ID!) { simulation(id: $id) { samplingRate datasets { id } recordings { id } stimuli { id } } }", {"id": sim["id"]})
    assert not asked.errors, asked.errors
    assert asked.data["simulation"] == {"samplingRate": "10 kHz", "datasets": [{"id": rec["id"]}], "recordings": [{"id": rec["id"]}], "stimuli": []}, "timing a dataset on the clock is what makes it the run's"

    again = await aexecute(
        "mutation ($input: CreateSamplingLawInput!) { createSamplingLaw(input: $input) { id } }",
        {"input": {"source": rec["intrinsicSystem"]["id"], "clock": sim["clock"]["id"], "samplingRate": "20 kHz"}},
    )
    assert again.errors and "already timed" in str(again.errors[0]), "a second law onto the same clock would be a rival, not a correction"


async def test_timing_is_refused_without_datasets_to_time(aexecute, make_neuron_model):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Empty", "model": str(nm.id), "duration": "40 ms", "sampling": {"rate": "1 kHz"}}})
    assert res.errors and "no datasets were named" in str(res.errors[0])


async def test_a_dataset_carries_one_site_per_anchor(aexecute, make_neuron_model, create_array_dataset):
    """A value was recorded or injected: a clamp's command and its response are two channels, each with a site."""
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    res = await create_array_dataset(
        "both",
        [100],
        anchors=[{"axisAnchors": [], "recordingSite": {"model": str(nm.id), "kind": "VOLTAGE"}, "stimulusSite": {"model": str(nm.id), "kind": "CURRENT"}}],
        raw=True,
    )
    assert res.errors and "both a recording site and a stimulus site" in str(res.errors[0])
    assert not await RecordingSite.objects.aexists() and not await StimulusSite.objects.aexists()


# --- a site is part of a neuron model ------------------------------------------------------------

TWO_CELLS = {
    "cells": [
        {"id": "pyr", "biophysics": {"compartments": []}, "topology": {"sections": [{"id": "soma", "length": "20 um"}, {"id": "apical", "length": "200 um"}]}},
        {"id": "int", "biophysics": {"compartments": []}, "topology": {"sections": [{"id": "soma", "length": "10 um"}]}},
    ]
}


@pytest.mark.parametrize(
    ("site", "refusal"),
    [
        ({"cell": "basket"}, "has no cell 'basket'. Its cells are ['int', 'pyr']"),
        ({"cell": "int", "location": "apical"}, "cell 'int' of model 'two cells' has no section 'apical'. Its sections are ['soma']"),
        ({"location": "soma"}, "Name the `cell` the section belongs to"),
    ],
    ids=["unknown-cell", "section-of-another-cell", "section-without-cell"],
)
async def test_a_site_names_a_place_its_model_declares(make_neuron_model, create_array_dataset, site, refusal):
    nm = await make_neuron_model(name="two cells", json_model=TWO_CELLS)
    res = await create_array_dataset("soma.v", [100], anchors=[{"axisAnchors": [], "recordingSite": {"model": str(nm.id), **site}}], raw=True)
    assert res.errors and refusal in str(res.errors[0]), res.errors
    assert not await ArrayDataset.objects.aexists(), "refused with its dataset: one transaction"


async def test_a_section_alone_is_read_on_the_models_only_cell(make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    dataset = await create_array_dataset("soma.v", [100], anchors=[{"axisAnchors": [], "stimulusSite": {"model": str(nm.id), "location": "0", "position": 0.5}}])
    site = await StimulusSite.objects.select_related("model").aget(anchor__dataset_id=dataset["id"])
    assert (site.model_id, site.cell, site.location) == (nm.id, None, "0"), "the cell is not written in for the caller; the model has one"


async def test_a_site_is_on_a_model_of_the_callers_organization(make_neuron_model, create_array_dataset, other_org_context):
    theirs = await make_neuron_model(context=other_org_context, json_model=SOMA_MODEL)
    res = await create_array_dataset("soma.v", [100], anchors=[{"axisAnchors": [], "recordingSite": {"model": str(theirs.id), "cell": "soma"}}], raw=True)
    assert res.errors and not await RecordingSite.objects.aexists()


async def test_a_run_times_only_datasets_sited_on_its_model(aexecute, make_neuron_model, create_array_dataset):
    ran = await make_neuron_model(name="ran", json_model=SOMA_MODEL)
    other = await make_neuron_model(name="other", json_model=SOMA_MODEL)
    rec, _ = await _run_datasets(create_array_dataset, ran)
    _, stim = await _run_datasets(create_array_dataset, other)
    res = await aexecute(CREATE_SIMULATION, {"input": {"name": "Mixed", "model": str(ran.id), "duration": "40 ms", "sampling": {"rate": "40 kHz"}, **_datasets(rec, stim)}})
    assert res.errors and "carries sites on model ['other'], but this is a run of model 'ran'" in str(res.errors[0]), res.errors
    assert not await Simulation.objects.filter(name="Mixed").aexists()


async def test_a_model_lists_the_sites_that_are_part_of_it(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    await _run_datasets(create_array_dataset, nm)
    res = await aexecute("query ($id: ID!) { neuronModel(id: $id) { recordingSites { kind cell } stimulusSites { label } } }", {"id": str(nm.id)})
    assert not res.errors, res.errors
    assert res.data["neuronModel"] == {"recordingSites": [{"kind": "VOLTAGE", "cell": "soma"}], "stimulusSites": [{"label": "IClamp"}]}
