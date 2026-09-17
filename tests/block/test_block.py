"""Block mutations executed against the schema: createBlock over existing array datasets, and deleteBlock.

``createBlock`` is the interpretation layer. Data enters through ``createArrayDataset`` (a
real ``zarr.json`` in RustFS, see the ``create_array_dataset`` fixture); a block then *names*
those datasets and says what Neo says about them -- a sampling rate and a start time, a
vector of sample times, spike times and the window they were observed over -- and the
server writes a clock and one edge per signal. Nothing about time is a column afterwards,
so these tests read every fact back the way a client would, and check that it is *one* edge
that says it. And because a block made no data, deleting one deletes none.
"""

import datetime

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core.models import AnalogSignal, ArrayDataset, Block, CoordinateSystem, Transformation

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_BLOCK = """
mutation ($input: CreateBlockInput!) {
  createBlock(input: $input) {
    id
    name
    description
    recordingTime
    pinned
    folder { name }
    clock { id epoch axes { name type unit } residents { __typename } }
    groups { id }
    segments {
      id
      index
      name
      description
      startTime
      clock { id }
      block { id }
      analogSignals {
        id
        name
        description
        color
        samplingRate
        tStart
        segment { id }
        samplingLaw { kind validity invariance inputAxes outputAxes ... on ByDimensionTransformation { id } }
        dataset { id shape axisNames valueUnit intrinsicSystem { id axes { name type unit } } }
      }
      irregularlySampledSignals {
        id
        name
        description
        segment { id }
        dataset { id shape valueUnit }
        timeDataset { id name shape valueUnit intrinsicSystem { residents { __typename } } }
      }
      spikeTrains {
        id
        name
        description
        tStart
        tStop
        segment { id }
        dataset { id shape axisNames valueUnit intrinsicSystem { axes { name type } } }
        waveforms { id shape axisNames valueUnit }
      }
    }
  }
}
"""

DELETE_BLOCK = """
mutation ($input: DeleteBlockInput!) {
  deleteBlock(input: $input)
}
"""

SPIKES = [{"name": "spike", "type": "INDEX"}]
WAVEFORMS = [{"name": "spike", "type": "INDEX"}, {"name": "c", "type": "CHANNEL"}, {"name": "t", "type": "TIME"}]


async def test_create_block_empty(aexecute):
    # No segments -> pure-DB happy path (no object store needed).
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Block", "segments": []}})
    assert not res.errors, res.errors
    block = res.data["createBlock"]
    assert block["name"] == "Block"
    assert block["folder"]["name"] == "Default", "filed in the user's default folder, like everything else"
    assert block["clock"]["axes"] == [{"name": "t", "type": "TIME", "unit": "second"}], "every block has a session clock, in seconds by default"
    assert block["clock"]["residents"] == [], "a clock is a frame: nothing lives in it"
    assert block["recordingTime"] is None, "no recording time given, so the clock is unanchored rather than stamped with 'now'"
    assert await Block.objects.filter(name="Block").aexists()


async def test_the_recording_time_is_the_session_clocks_epoch(aexecute):
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Anchored", "recordingTime": "2026-09-17T09:00:00+00:00"}})
    assert not res.errors, res.errors
    block = res.data["createBlock"]
    assert block["recordingTime"] == block["clock"]["epoch"] == "2026-09-17T09:00:00+00:00"

    clock = await CoordinateSystem.objects.aget(pk=block["clock"]["id"])
    assert clock.epoch == datetime.datetime(2026, 9, 17, 9, 0, tzinfo=datetime.timezone.utc)


async def test_an_analog_signal_is_one_dataset_and_one_sampling_law(aexecute, create_array_dataset):
    """A 4-channel signal at 30 kHz starting 2 s in: one (t, c) dataset, one edge, and the rate read back off it."""
    probe = await create_array_dataset("probe", [30000, 4], value_unit="uV")
    signal_input = {"dataset": probe["id"], "samplingRate": "30 kHz", "tStart": "2 s", "color": "#ff0000"}
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Session", "segments": [{"name": "trial 1", "analogSignals": [signal_input]}]}})
    assert not res.errors, res.errors
    (segment,) = res.data["createBlock"]["segments"]
    (signal,) = segment["analogSignals"]

    assert signal["name"] == "probe", "a signal is named after its dataset unless it says otherwise"
    assert signal["dataset"]["id"] == probe["id"], "the block named the dataset; it did not copy it"
    assert signal["dataset"]["shape"] == [30000, 4]
    assert signal["dataset"]["axisNames"] == ["t", "c"]
    assert signal["dataset"]["valueUnit"] == "uV", "the signal's unit is its dataset's value unit, not a column of its own"
    assert [(a["name"], a["type"], a["unit"]) for a in signal["dataset"]["intrinsicSystem"]["axes"]] == [("t", "TIME", None), ("c", "CHANNEL", None)]

    # Derived, not stored: there is no sampling_rate column to read.
    assert signal["samplingRate"] == "30 kHz"
    assert signal["tStart"] == "2 s"
    assert signal["samplingLaw"]["kind"] == "BY_DIMENSION"
    assert (signal["samplingLaw"]["inputAxes"], signal["samplingLaw"]["outputAxes"]) == (["t"], ["t"]), "the law names the time axis and says nothing about channels"
    assert (signal["samplingLaw"]["validity"], signal["samplingLaw"]["invariance"]) == ("INFERRED", "AFFINE")

    grid_id, clock_id = signal["dataset"]["intrinsicSystem"]["id"], segment["clock"]["id"]
    edges = await sync_to_async(lambda: list(Transformation.objects.filter(input_id=grid_id, output_id=clock_id, parent__isnull=True)))()
    assert len(edges) == 1, "a scale edge beside a translation edge would be two rival maps, not a composition"
    assert edges[0].params["affine"][0] == approx([1 / 30000, 2.0])
    assert not [field.name for field in AnalogSignal._meta.get_fields() if field.name in ("sampling_rate", "t_start", "time_trace", "unit")]


async def test_a_signal_says_nothing_about_what_its_dataset_is(aexecute, create_array_dataset):
    """The data layer's facts are not restated by the interpretation: there is nowhere to restate them."""
    dataset = await create_array_dataset("v", [100])
    for stale in ({"axes": [{"name": "t", "type": "TIME"}]}, {"unit": "mV"}, {"channels": [{"index": 0, "name": "ch0"}]}, {"trace": dataset["id"]}):
        res = await aexecute(CREATE_BLOCK, {"input": {"name": "B", "segments": [{"analogSignals": [{"dataset": dataset["id"], "samplingRate": "1 kHz", **stale}]}]}})
        assert res.errors and "is not defined by type 'AnalogSignalInput'" in str(res.errors[0]), stale


async def test_correcting_the_sampling_law_corrects_the_sampling_rate(aexecute, create_array_dataset):
    """The edge is the fact: refine it and everything read through it moves, because nothing stored a copy."""
    dataset = await create_array_dataset("v", [1000])
    created = await aexecute(CREATE_BLOCK, {"input": {"name": "S", "segments": [{"analogSignals": [{"dataset": dataset["id"], "samplingRate": "1 kHz"}]}]}})
    assert not created.errors, created.errors
    signal = created.data["createBlock"]["segments"][0]["analogSignals"][0]
    assert (signal["samplingRate"], signal["tStart"]) == ("1 kHz", "0 s")

    update = "mutation ($input: UpdateTransformationInput!) { updateTransformation(input: $input) { id validity } }"
    fixed = await aexecute(update, {"input": {"id": signal["samplingLaw"]["id"], "affine": [[0.0005, 0.25]], "validity": "VALIDATED"}})
    assert not fixed.errors, fixed.errors

    reread = await aexecute("query ($id: ID!) { analogSignal(id: $id) { samplingRate tStart samplingLaw { validity } } }", {"id": signal["id"]})
    assert not reread.errors, reread.errors
    assert reread.data["analogSignal"] == {"samplingRate": "2 kHz", "tStart": "250 ms", "samplingLaw": {"validity": "VALIDATED"}}


async def test_segments_have_their_own_clocks_related_to_the_sessions_by_an_offset(aexecute):
    segments = [{"name": "baseline", "startTime": "0 s"}, {"name": "drug", "startTime": "90 s"}, {"name": "unsynced"}, {"name": "absolute", "timebase": "SESSION"}]
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Session", "segments": segments}})
    assert not res.errors, res.errors
    block = res.data["createBlock"]
    baseline, drug, unsynced, absolute = block["segments"]

    assert [s["index"] for s in block["segments"]] == [0, 1, 2, 3]
    assert (baseline["startTime"], drug["startTime"]) == ("0 s", "90 s")
    assert unsynced["startTime"] is None, "a segment whose start is unknown is honestly unrelated to the session, not placed at zero"
    assert absolute["clock"]["id"] == block["clock"]["id"], "session-relative signals need no second clock"
    assert absolute["startTime"] == "0 s"
    assert len({baseline["clock"]["id"], drug["clock"]["id"], unsynced["clock"]["id"], block["clock"]["id"]}) == 4


async def test_an_irregular_signal_is_timed_by_a_lookup_through_its_times(aexecute, create_array_dataset):
    samples = await create_array_dataset("Ca", [500], value_unit="a.u.")
    times = await create_array_dataset("Ca/times", [500], value_unit="second")
    signal_input = {"dataset": samples["id"], "timesDataset": times["id"]}
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Imaging", "segments": [{"irregularlySampledSignals": [signal_input]}]}})
    assert not res.errors, res.errors
    (signal,) = res.data["createBlock"]["segments"][0]["irregularlySampledSignals"]

    assert signal["dataset"]["valueUnit"] == "a.u."
    assert signal["timeDataset"]["id"] == times["id"], "not a column: read back off the lookup edge"
    assert signal["timeDataset"]["valueUnit"] == "second", "the times are in the block's time unit, which is what lets a number-free lookup be right"
    assert [r["__typename"] for r in signal["timeDataset"]["intrinsicSystem"]["residents"]] == ["ArrayDataset", "DataArray"], "a dataset whose values are a map lives alone in its system"

    edge = await sync_to_async(lambda: Transformation.objects.get(input__datasets__id=signal["dataset"]["id"], parent__isnull=True))()
    assert edge.kind == "FIELD"


async def test_a_spike_train_keeps_its_observation_window_and_is_its_own_lookup(aexecute, create_array_dataset):
    spikes = await create_array_dataset("unit 3", [412], axes=SPIKES, value_unit="second")
    waveforms = await create_array_dataset("unit 3/waveforms", [412, 4, 60], axes=WAVEFORMS, value_unit="uV")
    train = {"dataset": spikes["id"], "waveformsDataset": waveforms["id"], "tStart": "0 s", "tStop": "10 min"}
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Sorted", "segments": [{"spikeTrains": [train]}]}})
    assert not res.errors, res.errors
    (spike_train,) = res.data["createBlock"]["segments"][0]["spikeTrains"]

    assert spike_train["dataset"]["intrinsicSystem"]["axes"] == [{"name": "spike", "type": "INDEX"}], "spike number has no metric"
    assert spike_train["dataset"]["valueUnit"] == "second"
    assert (spike_train["tStart"], spike_train["tStop"]) == ("0 s", "600 s"), "the window is stated, not derived: spike times cannot say how long nothing happened"
    assert spike_train["waveforms"]["shape"] == [412, 4, 60]
    assert spike_train["waveforms"]["valueUnit"] == "uV"

    edge = await sync_to_async(lambda: Transformation.objects.get(input__datasets__id=spike_train["dataset"]["id"], parent__isnull=True))()
    assert (edge.kind, edge.field_id) == ("FIELD", None), "its values are its times, so the field is the input itself"


async def test_the_spike_axis_is_read_not_assumed(aexecute, create_array_dataset):
    """Whatever the INDEX axis is called is what the lookup consumes; a TIME axis is not spike numbers at all."""
    events = await create_array_dataset("unit 7", [20], axes=[{"name": "event", "type": "INDEX"}], value_unit="second")
    ok = await aexecute(CREATE_BLOCK, {"input": {"name": "Named", "segments": [{"spikeTrains": [{"dataset": events["id"], "tStart": "0 s", "tStop": "1 s"}]}]}})
    assert not ok.errors, ok.errors
    edge = await sync_to_async(lambda: Transformation.objects.get(input__datasets__id=events["id"], parent__isnull=True))()
    assert edge.input_axes == ["event"]

    sampled = await create_array_dataset("not spikes", [20], value_unit="second")
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Wrong", "segments": [{"spikeTrains": [{"dataset": sampled["id"], "tStart": "0 s", "tStop": "1 s"}]}]}})
    assert res.errors and "exactly one axis, typed INDEX" in str(res.errors[0])
    assert not await Block.objects.filter(name="Wrong").aexists()


async def test_delete_block_deletes_the_interpretation_and_none_of_the_data(aexecute, create_array_dataset):
    """A block made no data, so it deletes none: the datasets stay, and only what existed because of the block goes."""
    v = await create_array_dataset("v", [1000])
    samples = await create_array_dataset("Ca", [50])
    times = await create_array_dataset("Ca/times", [50], value_unit="second")
    segment = {"analogSignals": [{"dataset": v["id"], "samplingRate": "1 kHz"}], "irregularlySampledSignals": [{"dataset": samples["id"], "timesDataset": times["id"]}]}
    created = await aexecute(CREATE_BLOCK, {"input": {"name": "Temporary", "segments": [segment]}})
    assert not created.errors, created.errors
    block_id = created.data["createBlock"]["id"]
    assert await CoordinateSystem.objects.acount() == 5  # 3 grids + session clock + segment clock
    assert await Transformation.objects.filter(parent__isnull=True).acount() == 2  # a sampling law and a lookup; no startTime, so no offset

    res = await aexecute(DELETE_BLOCK, {"input": {"id": block_id}})
    assert not res.errors, res.errors
    assert res.data["deleteBlock"] == block_id
    assert not await Block.objects.filter(id=block_id).aexists()
    assert await AnalogSignal.objects.acount() == 0
    assert await ArrayDataset.objects.acount() == 3, "the block named these datasets; it never owned them"
    assert await CoordinateSystem.objects.acount() == 3, "the clocks go, the sample grids stay with their data"
    assert await Transformation.objects.acount() == 0, "and the edges onto those clocks go with them -- they were the block's claim, not the data's"

    # The datasets are free to be interpreted again.
    again = await aexecute(CREATE_BLOCK, {"input": {"name": "Again", "segments": [{"analogSignals": [{"dataset": v["id"], "samplingRate": "2 kHz"}]}]}})
    assert not again.errors, again.errors


async def test_deleting_a_signal_takes_its_timing_edge_and_leaves_its_dataset(aexecute, create_array_dataset):
    v = await create_array_dataset("v", [1000])
    created = await aexecute(CREATE_BLOCK, {"input": {"name": "B", "segments": [{"analogSignals": [{"dataset": v["id"], "samplingRate": "1 kHz"}]}]}})
    signal_id = created.data["createBlock"]["segments"][0]["analogSignals"][0]["id"]

    res = await aexecute("mutation ($input: DeleteInput!) { deleteAnalogSignal(input: $input) }", {"input": {"id": signal_id}})
    assert not res.errors, res.errors
    assert await ArrayDataset.objects.filter(pk=v["id"]).aexists()
    assert await Transformation.objects.acount() == 0, "the sampling law was the signal's claim; left behind it would keep the dataset on a clock no signal puts it on"


# --- negatives ---------------------------------------------------------------


async def test_delete_block_not_found(aexecute):
    res = await aexecute(DELETE_BLOCK, {"input": {"id": "999999"}})
    assert res.errors


async def test_create_block_bad_file(aexecute):
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "B", "file": "999999", "segments": []}})
    assert res.errors


async def test_a_refusal_anywhere_leaves_nothing_behind(aexecute, create_array_dataset):
    """The second signal's dataset has no TIME axis; the first signal, both clocks and the block must not survive it."""
    good = await create_array_dataset("good", [1000])
    bad = await create_array_dataset("bad", [1000], axes=SPIKES)
    signals = [{"dataset": good["id"], "samplingRate": "1 kHz"}, {"dataset": bad["id"], "samplingRate": "1 kHz"}]
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Half", "segments": [{"analogSignals": signals}]}})
    assert res.errors and "has no TIME axis, so there is nothing for a sampling law to act on" in str(res.errors[0])
    assert not await Block.objects.filter(name="Half").aexists()
    assert await CoordinateSystem.objects.acount() == 2, "the two datasets' grids, and no clock"
    assert await Transformation.objects.acount() == 0


async def test_one_dataset_is_timed_once_on_one_clock(aexecute, create_array_dataset):
    """Two edges between one grid and one clock are rivals, not two signals."""
    v = await create_array_dataset("v", [1000])
    twice = [{"dataset": v["id"], "samplingRate": "1 kHz"}, {"dataset": v["id"], "samplingRate": "2 kHz", "name": "again"}]
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Twice", "segments": [{"analogSignals": twice}]}})
    assert res.errors and "already timed against the clock" in str(res.errors[0])

    # Two segments with clocks of their own are two clocks, and so two honest edges.
    ok = await aexecute(CREATE_BLOCK, {"input": {"name": "Two sweeps", "segments": [{"analogSignals": [twice[0]]}, {"analogSignals": [twice[1]]}]}})
    assert not ok.errors, ok.errors


async def test_spike_times_in_another_unit_are_refused_rather_than_misread(aexecute, create_array_dataset):
    """A lookup states no numbers. Milliseconds read against a clock in seconds would put every spike a thousandfold early."""
    spikes = await create_array_dataset("unit", [10], axes=SPIKES, value_unit="ms")
    train = {"dataset": spikes["id"], "tStart": "0 s", "tStop": "1 s"}
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Mixed", "segments": [{"spikeTrains": [train]}]}})
    assert res.errors and "states no numbers, so it cannot convert" in str(res.errors[0])

    # The honest way to say it: the session counts in milliseconds.
    ok = await aexecute(CREATE_BLOCK, {"input": {"name": "Millis", "timeUnit": "ms", "segments": [{"spikeTrains": [train]}]}})
    assert not ok.errors, ok.errors


async def test_a_times_dataset_must_say_what_its_values_measure(aexecute, create_array_dataset):
    spikes = await create_array_dataset("unitless", [10], axes=SPIKES)
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Bare", "segments": [{"spikeTrains": [{"dataset": spikes["id"], "tStart": "0 s", "tStop": "1 s"}]}]}})
    assert res.errors and "dataset-wide `valueUnit` anchor" in str(res.errors[0])


async def test_sample_times_must_be_one_per_sample(aexecute, create_array_dataset):
    samples = await create_array_dataset("Ca", [500])
    times = await create_array_dataset("Ca/times", [499], value_unit="second")
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Short", "segments": [{"irregularlySampledSignals": [{"dataset": samples["id"], "timesDataset": times["id"]}]}]}})
    assert res.errors and "exactly one instant per sample" in str(res.errors[0])


async def test_a_session_relative_segment_has_no_start_of_its_own(aexecute):
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "B", "segments": [{"timebase": "SESSION", "startTime": "5 s"}]}})
    assert res.errors and "shares the session clock" in str(res.errors[0])


async def test_another_organization_cannot_build_a_block_from_this_ones_dataset_or_delete_its_block(aexecute, create_array_dataset, other_org_context):
    dataset = await create_array_dataset("mine", [100])
    stolen = await aexecute(CREATE_BLOCK, {"input": {"name": "Theirs", "segments": [{"analogSignals": [{"dataset": dataset["id"], "samplingRate": "1 kHz"}]}]}}, context=other_org_context)
    assert stolen.errors
    assert not await Block.objects.filter(name="Theirs").aexists()

    mine = await aexecute(CREATE_BLOCK, {"input": {"name": "Mine"}})
    deleted = await aexecute(DELETE_BLOCK, {"input": {"id": mine.data["createBlock"]["id"]}}, context=other_org_context)
    assert deleted.errors
    assert await Block.objects.filter(name="Mine").aexists()
