"""A simulated run, CS-first: a run is its clock, and what was run is a spoke on each output.

There is no run row. A clock is a node with an identity of its own, minted once per run, so it
already *is* the run: which traces make up one run is the graph -- the datasets timed onto one
clock -- and what was run (the model, NEURON's ``dt`` and ``tstop``) is a ``SimulationState``
spoke on each output's own anchor, beside the ``RecordingSite`` or ``StimulusSite`` that says
where on the model, all said at ``createArrayDataset``. The outputs of one clock must agree on
what was run; an *input* -- a stimulus waveform -- carries no spoke, and one waveform may drive
many runs. ``createSession`` mints a clock (or takes one) and times datasets onto it, exactly as
for a wet recording session, and a session's traces are read back as what is *placed* onto its
clock (``placeableIn``) -- not as its residents, since a trace lives in its own sample grid.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core.models import ArrayDataset, CoordinateSystem, RecordingSite, SimulationState, StimulusSite, Transformation
from tests.seed import SOMA_MODEL

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


_ANCHORS = "anchors { coordinates recordingSite { kind label cell location position model { id } } stimulusSite { kind label } simulation { model { id } duration dt } }"

CREATE_SESSION = "mutation ($input: CreateSessionInput!) { createSession(input: $input) { id name epoch axes { name type unit } } }"
CREATE_SAMPLING_LAW = "mutation ($input: CreateSamplingLawInput!) { createSamplingLaw(input: $input) { id } }"
DATASET = "query ($id: ID!) { arrayDataset(id: $id) { id valueUnit simulation { model { id name } duration dt } %s } }" % _ANCHORS
IN_SESSION = "query ($space: ID!, $affine: Boolean) { arrayDatasets(filters: {placeableIn: {space: $space, requireAffine: $affine}}) { id } }"
PLACED = "query ($id: ID!, $affine: Boolean!) { coordinateSystem(id: $id) { placedSystems(requireAffine: $affine) { residents { __typename ... on ArrayDataset { id } } } } }"


def _run(model, *, duration: str = "40 ms", dt: str | None = "25 us") -> dict:
    return {"model": str(model.id), "duration": duration, **({"dt": dt} if dt else {})}


async def _run_datasets(create_array_dataset, model, samples: int = 1600, stimulus_samples: int | None = None, **run):
    """A recorded and an injected output of one run of ``model``, each carrying the run and its site on its whole-dataset anchor."""
    recording = await create_array_dataset(
        "soma.v",
        [samples],
        anchors=[{"axisAnchors": [], "valueUnit": {"unit": "mV"}, "simulation": _run(model, **run), "recordingSite": {"model": str(model.id), "kind": "VOLTAGE", "cell": "soma", "location": "0", "position": 0.5}}],
    )
    stimulus = await create_array_dataset(
        "iclamp",
        [stimulus_samples or samples],
        anchors=[{"axisAnchors": [], "valueUnit": {"unit": "nA"}, "simulation": _run(model, **run), "stimulusSite": {"model": str(model.id), "kind": "CURRENT", "cell": "soma", "location": "0", "position": 0.5, "label": "IClamp"}}],
    )
    return recording, stimulus


def _session(name: str, *datasets: dict, **timing) -> dict:
    return {"input": {"name": name, "timeUnit": "millisecond", "datasets": [dataset["id"] for dataset in datasets], **timing}}


def _onto(clock: dict, *datasets: dict, **timing) -> dict:
    return {"input": {"clock": clock["id"], "datasets": [dataset["id"] for dataset in datasets], **timing}}


async def _in_session(aexecute, clock: dict, affine: bool | None = None) -> list[str]:
    res = await aexecute(IN_SESSION, {"space": clock["id"], "affine": affine})
    assert not res.errors, res.errors
    return sorted(dataset["id"] for dataset in res.data["arrayDatasets"])


async def test_what_was_run_is_a_spoke_on_the_output(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, _ = await _run_datasets(create_array_dataset, nm)

    res = await aexecute(DATASET, {"id": rec["id"]})
    assert not res.errors, res.errors
    recording = res.data["arrayDataset"]
    assert recording["simulation"] == {"model": {"id": str(nm.id), "name": nm.name}, "duration": "40 ms", "dt": "25 µs"}, "the integrator's parameters, kept as stated"
    (anchor,) = recording["anchors"]
    assert anchor["recordingSite"] == {"kind": "VOLTAGE", "label": "soma: 0(0.5)", "cell": "soma", "location": "0", "position": 0.5, "model": {"id": str(nm.id)}}, "where it was recorded: a place on the model"
    assert recording["valueUnit"] == "mV", "what was measured is the dataset's to say"

    wet = await create_array_dataset("patch", [100])
    assert (await aexecute(DATASET, {"id": wet["id"]})).data["arrayDataset"]["simulation"] is None, "a recording was not computed"


async def test_a_run_is_its_clock(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm)
    res = await aexecute(CREATE_SESSION, _session("Sim", rec, stim, sampling={"rate": "40 kHz"}))
    assert not res.errors, res.errors
    clock = res.data["createSession"]
    assert (clock["name"], clock["epoch"], clock["axes"]) == ("Sim/clock", None, [{"name": "t", "type": "TIME", "unit": "millisecond"}]), "NEURON counts in milliseconds; simulated time has no wall clock"

    grids = [rec["intrinsicSystem"]["id"], stim["intrinsicSystem"]["id"]]
    assert len(set(grids)) == 2, "every dataset owns its own sample grid, as in mikro"
    edges = await sync_to_async(lambda: list(Transformation.objects.filter(input_id__in=grids, parent__isnull=True).order_by("pk")))()
    assert len(edges) == 2, "one edge per dataset"
    assert {str(edge.output_id) for edge in edges} == {clock["id"]}, "all onto the one clock, which is what lines stimulus and response up"
    for edge in edges:
        assert edge.params["affine"][0] == approx([0.025, 0.0]), "a period of 1/40 kHz, written in the clock's milliseconds"

    assert await _in_session(aexecute, clock) == sorted([rec["id"], stim["id"]]), "the run's outputs are what is placed onto its clock"
    placed = await aexecute(PLACED, {"id": clock["id"], "affine": True})
    residents = {resident["id"] for system in placed.data["coordinateSystem"]["placedSystems"] for resident in system["residents"] if resident["__typename"] == "ArrayDataset"}
    assert residents == {rec["id"], stim["id"]}, "the same answer, space by space: each output lives in its own grid, placed onto the clock"


async def test_a_variable_step_run_is_in_its_session_but_not_offered_to_a_picker(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm, 731, dt=None)
    times = await create_array_dataset("CVode/times", [731], value_unit="millisecond")
    res = await aexecute(CREATE_SESSION, _session("CVode", rec, stim, timeDataset=times["id"]))
    assert not res.errors, res.errors
    clock = res.data["createSession"]

    edges = await sync_to_async(lambda: list(Transformation.objects.filter(input_id__in=[rec["intrinsicSystem"]["id"], stim["intrinsicSystem"]["id"]], parent__isnull=True)))()
    assert [edge.kind for edge in edges] == ["FIELD", "FIELD"], "one lookup per dataset, through the one times dataset"
    assert await SimulationState.objects.filter(dt__isnull=True).acount() == 2, "an adaptive integrator states no dt, and none is invented"

    assert rec["id"] not in await _in_session(aexecute, clock), "a picker offers what one affine map can draw, and a lookup is not one"
    assert set(await _in_session(aexecute, clock, affine=False)) >= {rec["id"], stim["id"]}, "but they are in the session: placed onto its clock, across a FIELD"
    placed = await aexecute(PLACED, {"id": clock["id"], "affine": False})
    residents = {resident["id"] for system in placed.data["coordinateSystem"]["placedSystems"] for resident in system["residents"] if resident["__typename"] == "ArrayDataset"}
    assert {rec["id"], stim["id"]} <= residents


# --- what is one run -------------------------------------------------------------------------------


async def test_one_stimulus_drives_many_runs(aexecute, make_neuron_model, create_array_dataset):
    """An input carries no spoke: one waveform is timed onto each run's clock, and is in each session."""
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    waveform = await create_array_dataset("step 100 pA", [1600], value_unit="nA")
    clocks = []
    for name in ("seed 1", "seed 2"):
        output = await create_array_dataset(f"{name}/soma.v", [1600], anchors=[{"axisAnchors": [], "simulation": _run(nm), "recordingSite": {"model": str(nm.id), "cell": "soma"}}])
        res = await aexecute(CREATE_SESSION, _session(name, output, waveform, sampling={"rate": "40 kHz"}))
        assert not res.errors, res.errors
        clocks.append((res.data["createSession"], output))

    for clock, output in clocks:
        assert await _in_session(aexecute, clock) == sorted([output["id"], waveform["id"]]), "two runs with the same facts are two clocks"


async def test_the_outputs_of_one_clock_agree_on_what_was_run(aexecute, make_neuron_model, create_array_dataset):
    ran = await make_neuron_model(name="ran", json_model=SOMA_MODEL)
    other = await make_neuron_model(name="other", json_model=SOMA_MODEL)
    rec, _ = await _run_datasets(create_array_dataset, ran)
    _, stim = await _run_datasets(create_array_dataset, other)
    res = await aexecute(CREATE_SESSION, _session("Mixed", rec, stim, sampling={"rate": "40 kHz"}))
    assert res.errors and "would disagree about what was run" in str(res.errors[0]), res.errors
    assert not await CoordinateSystem.objects.filter(name="Mixed/clock").aexists(), "one transaction: no clock is left behind"


@pytest.mark.parametrize("run", [{"dt": "50 us"}, {"duration": "80 ms"}], ids=["dt", "duration"])
async def test_an_output_of_another_run_cannot_join_a_clock_later(aexecute, make_neuron_model, create_array_dataset, run):
    """Checked where the disagreement would arise: when an output is timed onto a clock, whichever mutation does it."""
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm)
    session = await aexecute(CREATE_SESSION, _session("Run", rec, stim, sampling={"rate": "40 kHz"}))
    assert not session.errors, session.errors
    clock = session.data["createSession"]
    straggler, _ = await _run_datasets(create_array_dataset, nm, **run)
    res = await aexecute(CREATE_SAMPLING_LAW, {"input": {"source": straggler["intrinsicSystem"]["id"], "clock": clock["id"], "samplingRate": "40 kHz"}})
    assert res.errors and "would disagree about what was run" in str(res.errors[0]), res.errors

    same, same_stim = await _run_datasets(create_array_dataset, nm)
    joined = await aexecute(CREATE_SESSION, _onto(clock, same, same_stim, sampling={"rate": "40 kHz"}))
    assert not joined.errors, "a second batch of the same run joins its clock"
    assert joined.data["createSession"]["id"] == clock["id"]
    assert len(await _in_session(aexecute, clock)) == 4


async def test_a_dataset_is_computed_by_one_model(make_neuron_model, create_array_dataset):
    ran = await make_neuron_model(name="ran", json_model=SOMA_MODEL)
    other = await make_neuron_model(name="other", json_model=SOMA_MODEL)
    res = await create_array_dataset("soma.v", [100], anchors=[{"axisAnchors": [], "simulation": _run(ran), "recordingSite": {"model": str(other.id), "cell": "soma"}}], raw=True)
    assert res.errors and "name different neuron models" in str(res.errors[0]), res.errors
    assert not await ArrayDataset.objects.aexists()


async def test_a_session_names_its_clock_one_way(aexecute, create_array_dataset):
    rec = await create_array_dataset("Vm", [1600])
    minted = await aexecute(CREATE_SESSION, _session("Patch", rec, sampling={"rate": "40 kHz"}))
    assert not minted.errors, minted.errors
    both = await aexecute(CREATE_SESSION, {"input": {"name": "x", "clock": minted.data["createSession"]["id"], "datasets": [rec["id"]], "sampling": {"rate": "1 kHz"}}})
    assert both.errors and "Exactly one of the two" in str(both.errors[0])


# --- negatives ---------------------------------------------------------------


async def test_a_session_names_existing_datasets(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, _ = await _run_datasets(create_array_dataset, nm)
    res = await aexecute(CREATE_SESSION, _session("Bad", rec, {"id": "999999"}, sampling={"rate": "1 kHz"}))
    assert res.errors
    assert not await CoordinateSystem.objects.filter(name="Bad/clock").aexists(), "resolved before anything is written"
    assert await Transformation.objects.acount() == 0


@pytest.mark.parametrize("timing", [{}, {"sampling": {"rate": "1 kHz"}, "timeDataset": "1"}], ids=["neither", "both"])
async def test_a_session_is_timed_in_exactly_one_way(aexecute, create_array_dataset, timing):
    rec = await create_array_dataset("soma.v", [100])
    res = await aexecute(CREATE_SESSION, _session("Untimed", rec, **timing))
    assert res.errors and "timed in exactly one way" in str(res.errors[0])


async def test_a_session_has_datasets(aexecute):
    res = await aexecute(CREATE_SESSION, {"input": {"name": "Empty", "datasets": [], "sampling": {"rate": "1 kHz"}}})
    assert res.errors, "a clock alone is `createCoordinateSystem`"


async def test_the_datasets_of_one_session_have_one_sample_count(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm, 1600, 1599)
    res = await aexecute(CREATE_SESSION, _session("Ragged", rec, stim, sampling={"rate": "40 kHz"}))
    assert res.errors and "the same number of samples" in str(res.errors[0])
    assert not await CoordinateSystem.objects.filter(name="Ragged/clock").aexists()


async def test_a_session_needs_a_time_axis(aexecute, create_array_dataset):
    rec = await create_array_dataset("soma.v", [100])
    units = await create_array_dataset("not samples", [100], axes=[{"name": "unit", "type": "INDEX"}])
    res = await aexecute(CREATE_SESSION, _session("Untimed", rec, units, sampling={"rate": "1 kHz"}))
    assert res.errors and "has no TIME axis" in str(res.errors[0])


async def test_sample_times_must_be_one_per_sample(aexecute, create_array_dataset):
    rec = await create_array_dataset("soma.v", [731])
    times = await create_array_dataset("times", [730], value_unit="millisecond")
    res = await aexecute(CREATE_SESSION, _session("Short", rec, timeDataset=times["id"]))
    assert res.errors and "exactly one instant per sample" in str(res.errors[0])


async def test_a_dataset_carries_one_site_per_anchor(make_neuron_model, create_array_dataset):
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


@pytest.mark.parametrize("spoke", ["recordingSite", "simulation"])
async def test_a_trace_is_of_a_model_of_the_callers_organization(make_neuron_model, create_array_dataset, other_org_context, spoke):
    theirs = await make_neuron_model(context=other_org_context, json_model=SOMA_MODEL)
    value = {"model": str(theirs.id), "cell": "soma"} if spoke == "recordingSite" else _run(theirs)
    res = await create_array_dataset("soma.v", [100], anchors=[{"axisAnchors": [], spoke: value}], raw=True)
    assert res.errors and not await ArrayDataset.objects.aexists()


async def test_a_model_lists_what_was_computed_from_it(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    rec, stim = await _run_datasets(create_array_dataset, nm)
    res = await aexecute(
        "query ($id: ID!) { neuronModel(id: $id) { simulatedDatasets { id } recordingSites { kind cell } stimulusSites { label } } }",
        {"id": str(nm.id)},
    )
    assert not res.errors, res.errors
    assert res.data["neuronModel"] == {
        "simulatedDatasets": [{"id": rec["id"]}, {"id": stim["id"]}],
        "recordingSites": [{"kind": "VOLTAGE", "cell": "soma"}],
        "stimulusSites": [{"label": "IClamp"}],
    }


async def test_a_models_sessions_group_its_outputs_by_clock(aexecute, make_neuron_model, create_array_dataset):
    """One session per run -- per clock its outputs are timed onto -- and what is not timed yet under a null clock."""
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    other = await make_neuron_model(name="other", json_model=SOMA_MODEL)
    waveform = await create_array_dataset("step 100 pA", [1600], value_unit="nA")
    first = await _run_datasets(create_array_dataset, nm)
    second = await _run_datasets(create_array_dataset, nm)
    theirs, _ = await _run_datasets(create_array_dataset, other)
    untimed = await _run_datasets(create_array_dataset, nm)
    clocks = []
    for name, outputs in (("run 1", first), ("run 2", second)):
        res = await aexecute(CREATE_SESSION, _session(name, *outputs, waveform, sampling={"rate": "40 kHz"}))
        assert not res.errors, res.errors
        clocks.append(res.data["createSession"]["id"])
    assert not (await aexecute(CREATE_SESSION, _session("theirs", theirs, sampling={"rate": "40 kHz"}))).errors

    res = await aexecute("query ($id: ID!) { neuronModel(id: $id) { sessions { clock { id name } datasets { id } } } }", {"id": str(nm.id)})
    assert not res.errors, res.errors
    sessions = res.data["neuronModel"]["sessions"]
    assert [(s["clock"] and s["clock"]["name"]) for s in sessions] == ["run 1/clock", "run 2/clock", None]
    assert [s["clock"]["id"] for s in sessions[:2]] == clocks
    assert [[d["id"] for d in s["datasets"]] for s in sessions] == [
        [first[0]["id"], first[1]["id"]],
        [second[0]["id"], second[1]["id"]],
        [untimed[0]["id"], untimed[1]["id"]],
    ], "the model's outputs only: the shared waveform is an input, and the other model's output is not this model's"


CONFIG_SESSIONS = """
query ($id: ID!) {
  neuronModel(id: $id) {
    config {
      cells {
        id
        sessions { clock { name } datasets { id } }
        topology { sections { id sessions { clock { name } datasets { id } } } }
      }
    }
  }
}
"""


def _by_clock(sessions: list[dict]) -> dict:
    return {(s["clock"] or {}).get("name"): [d["id"] for d in s["datasets"]] for s in sessions}


async def test_a_cell_and_a_section_show_the_sessions_they_were_recorded_in(aexecute, make_neuron_model, create_array_dataset):
    """Recording sites on a cell or a section, grouped by run. Two cells each with a `soma` section keep theirs apart; an injected stimulus is not a recording."""
    nm = await make_neuron_model(name="two cells", json_model=TWO_CELLS)

    async def output(name: str, cell: str, location: str, spoke: str = "recordingSite") -> dict:
        return await create_array_dataset(name, [1600], anchors=[{"axisAnchors": [], "simulation": _run(nm), spoke: {"model": str(nm.id), "cell": cell, "location": location}}])

    pyr_soma = await output("pyr soma", "pyr", "soma")
    pyr_apical = await output("pyr apical", "pyr", "apical")
    injected = await output("pyr soma iclamp", "pyr", "soma", spoke="stimulusSite")
    int_soma = await output("int soma", "int", "soma")
    untimed = await output("pyr soma, not timed", "pyr", "soma")
    assert not (await aexecute(CREATE_SESSION, _session("run 1", pyr_soma, pyr_apical, injected, sampling={"rate": "40 kHz"}))).errors
    assert not (await aexecute(CREATE_SESSION, _session("run 2", int_soma, sampling={"rate": "40 kHz"}))).errors

    res = await aexecute(CONFIG_SESSIONS, {"id": str(nm.id)})
    assert not res.errors, res.errors
    cells = {cell["id"]: cell for cell in res.data["neuronModel"]["config"]["cells"]}
    sections = {(cell_id, section["id"]): _by_clock(section["sessions"]) for cell_id, cell in cells.items() for section in cell["topology"]["sections"]}

    assert _by_clock(cells["pyr"]["sessions"]) == {"run 1/clock": [pyr_soma["id"], pyr_apical["id"]], None: [untimed["id"]]}, "the stimulus was injected, not recorded"
    assert _by_clock(cells["int"]["sessions"]) == {"run 2/clock": [int_soma["id"]]}
    assert sections == {
        ("pyr", "soma"): {"run 1/clock": [pyr_soma["id"]], None: [untimed["id"]]},
        ("pyr", "apical"): {"run 1/clock": [pyr_apical["id"]]},
        ("int", "soma"): {"run 2/clock": [int_soma["id"]]},
    }, "a section id is the cell's: `soma` of `int` is not `soma` of `pyr`"

    listed = await aexecute(
        "query ($m: ID!, $c: ID!) { sections(modelId: $m, cellId: $c) { id sessions { clock { name } datasets { id } } } }",
        {"m": str(nm.id), "c": "int"},
    )
    assert not listed.errors, listed.errors
    assert [(s["id"], _by_clock(s["sessions"])) for s in listed.data["sections"]] == [("soma", {"run 2/clock": [int_soma["id"]]})], "the same answer through `sections`"


async def test_a_site_naming_no_cell_is_on_the_sole_cell(aexecute, make_neuron_model, create_array_dataset):
    nm = await make_neuron_model(json_model=SOMA_MODEL)
    recorded = await create_array_dataset("Vm", [1600], anchors=[{"axisAnchors": [], "recordingSite": {"model": str(nm.id), "location": "0"}}])
    assert not (await aexecute(CREATE_SESSION, _session("run", recorded, sampling={"rate": "40 kHz"}))).errors
    res = await aexecute(CONFIG_SESSIONS, {"id": str(nm.id)})
    assert not res.errors, res.errors
    (cell,) = res.data["neuronModel"]["config"]["cells"]
    (section,) = cell["topology"]["sections"]
    assert _by_clock(cell["sessions"]) == _by_clock(section["sessions"]) == {"run/clock": [recorded["id"]]}
