"""Synchronising two anchored clocks: a probe's against a DAQ's, with an offset and a drift.

Two clocks anchored to different wall-clock instants used to be unrelatable: `_assert_epochs_agree`
refused every edge between them, the TRANSLATION its own message asked for included. Now it
refuses only an edge that states no offset, and `createClockOffset` writes the one that does:
defaulted to the epochs' difference (the nominal sync), with the crystal's drift as its factor.
"""

import datetime

import pytest
from asgiref.sync import sync_to_async

from core.logic import clocks
from core.models import CoordinateSystem, Transformation
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

NINE = datetime.datetime(2026, 9, 18, 9, 0, 0, tzinfo=datetime.timezone.utc)

CREATE_CLOCK_OFFSET = "mutation ($input: CreateClockOffsetInput!) { createClockOffset(input: $input) { id kind } }"


async def test_a_probe_clock_is_synced_onto_the_daq_clock_by_its_epochs_and_its_drift(aexecute, authenticated_context):
    ctx = authenticated_context
    probe = await seed.create_clock(ctx, "probe", epoch=NINE)
    daq = await seed.create_clock(ctx, "daq", epoch=NINE + datetime.timedelta(milliseconds=250))
    recording = await seed.create_array_dataset(ctx, "AP band", seed.TC_AXES, [[30000, 4]])
    await seed.time_on(ctx, recording.coordinate_system, probe, rate="30 kHz")

    synced = await aexecute(CREATE_CLOCK_OFFSET, {"input": {"clock": str(probe.pk), "onto": str(daq.pk), "driftPpm": 12.0}})
    assert not synced.errors, synced.errors
    edge = await Transformation.objects.aget(pk=synced.data["createClockOffset"]["id"])
    assert edge.params["affine"][0] == pytest.approx([1.000012, -0.25]), "the probe started a quarter second before the DAQ, and runs 12 ppm fast"
    assert await sync_to_async(clocks.drift_of)(probe, daq) == pytest.approx(12.0)
    assert await sync_to_async(clocks.offset_of)(probe, daq) == pytest.approx(-250_000_000_000), "a quarter second, in picoseconds (round-tripped through the edge's float64 seconds)"

    experiment = await aexecute("mutation ($input: CreateExperimentFromCoordinateSystemInput!) { createExperimentFromCoordinateSystem(input: $input) { layers { kind placement asAffine { matrix } } } }", {"input": {"coordinateSystem": str(daq.pk)}})
    assert not experiment.errors, experiment.errors
    (layer,) = experiment.data["createExperimentFromCoordinateSystem"]["layers"]
    assert layer["placement"] == "PLACED"
    assert layer["asAffine"]["matrix"][0] == pytest.approx([1.000012 / 30000, 0.0, -0.25]), "sample -> probe time -> DAQ time, drift and all; the channel axis is untouched"


async def test_an_edge_stating_no_offset_between_differently_anchored_clocks_is_still_refused(authenticated_context):
    from core.logic import graph as graph_logic

    probe = await seed.create_clock(authenticated_context, "probe", epoch=NINE)
    daq = await seed.create_clock(authenticated_context, "daq", epoch=NINE + datetime.timedelta(seconds=1))
    with pytest.raises(ValueError, match="states no offset"):
        await sync_to_async(graph_logic.build_registration_edge)(input_system=probe, output_system=daq, kind="IDENTITY", ctx=seed._creation(authenticated_context))


async def test_an_unanchored_clock_needs_its_offset_stated(aexecute, authenticated_context):
    segment = await seed.create_clock(authenticated_context, "segment")
    session = await seed.create_clock(authenticated_context, "session", epoch=NINE)
    res = await aexecute(CREATE_CLOCK_OFFSET, {"input": {"clock": str(segment.pk), "onto": str(session.pk)}})
    assert res.errors and "State the `offset`" in str(res.errors[0])
    assert not await Transformation.objects.filter(input=segment).aexists()

    stated = await aexecute(CREATE_CLOCK_OFFSET, {"input": {"clock": str(segment.pk), "onto": str(session.pk), "offset": "12 s"}})
    assert not stated.errors, stated.errors
    assert (await Transformation.objects.aget(input=segment)).params == {"translation": [12.0]}, "no drift, one unit: a bare offset, as before"
    assert await CoordinateSystem.objects.filter(pk=segment.pk).aexists()
