"""Clocks, and the three edges that put samples onto them (``core.logic.clocks``).

Every time fact this service used to keep in a column -- a sampling rate, a start time, a
redundant vector of sample times, a per-view offset -- is one of these edges. These tests
pin that each is *one* edge, that it says what the column said, and that the graph refuses
the versions of it that would be silently wrong.
"""

import datetime

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core import enums
from core.logic import clocks, graph, space_graph
from core.models import Transformation
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

KHZ_30 = 30_000 * 10**9  # nanohertz
SECONDS_2 = 2 * 10**12  # picoseconds


def _clock(ctx, name="session", unit="second", epoch=None):
    return sync_to_async(clocks.create_clock)(name=name, unit=unit, epoch=epoch, ctx=seed._creation(ctx))


def _law(ctx, grid, clock, rate=KHZ_30, start=SECONDS_2):
    return sync_to_async(clocks.write_sampling_law)(grid=grid, clock=clock, sampling_rate=rate, t_start=start, ctx=seed._creation(ctx))


# --- the sampling law ---------------------------------------------------------------------------


@pytest.mark.parametrize("axes, shape", [(seed.T_AXES, [30000]), (seed.TC_AXES, [30000, 384])], ids=["t", "t,c"])
async def test_a_sampling_law_is_one_edge_whatever_the_rank(authenticated_context, axes, shape):
    """A (t) and a (t, c) dataset read identically: the law names the time axis and says nothing about channels."""
    dataset = await seed.create_dataset(authenticated_context, "Vm", axes, shape)
    clock = await _clock(authenticated_context)
    edge = await _law(authenticated_context, dataset.coordinate_system, clock)

    assert edge.kind == enums.TransformKindChoices.BY_DIMENSION.value
    assert (edge.input_axes, edge.output_axes) == (["t"], ["t"])
    assert edge.params["affine"][0] == approx([1 / 30000, 2.0])
    assert edge.validity == enums.PlacementValidityChoices.INFERRED.value, "read from acquisition metadata, so as right as the metadata is"

    top_level = await sync_to_async(lambda: Transformation.objects.filter(input=dataset.coordinate_system, output=clock, parent__isnull=True).count())()
    assert top_level == 1, "a scale edge beside a translation edge would be two rival maps, not a composition"


async def test_the_rate_and_start_are_read_back_off_the_edge(authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [30000])
    clock = await _clock(authenticated_context)
    await _law(authenticated_context, dataset.coordinate_system, clock)

    rate, start = await sync_to_async(clocks.sampling_of)(dataset.coordinate_system, clock)
    assert (rate, start) == (KHZ_30, SECONDS_2), "30 kHz round-trips exactly through its reciprocal"


async def test_the_law_is_written_in_the_clocks_unit(authenticated_context):
    """The same 30 kHz on a millisecond clock is a period of 1/30 ms -- and still reads back as 30 kHz."""
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [30000])
    clock = await _clock(authenticated_context, unit="millisecond")
    edge = await _law(authenticated_context, dataset.coordinate_system, clock)

    assert edge.params["affine"][0] == approx([1 / 30, 2000.0])
    assert await sync_to_async(clocks.sampling_of)(dataset.coordinate_system, clock) == (KHZ_30, SECONDS_2)


async def test_a_sampled_dataset_is_placeable_and_in_view_on_its_clock(authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.TC_AXES, [30000, 4])
    clock = await _clock(authenticated_context)
    await _law(authenticated_context, dataset.coordinate_system, clock)
    organization = authenticated_context.request.organization

    assert await sync_to_async(graph.is_placeable_in)(clock, dataset.coordinate_system, require_affine=True)

    def look():
        return space_graph.SpaceGraph(clock, organization=organization).in_view(space_graph.region_from_bounds(clock, [0.0], [10.0]), with_anchors=False)

    (hit,) = await sync_to_async(look)()
    assert hit.extent_state == enums.ExtentState.KNOWN.value
    assert hit.extent == {"t": approx([2.0 - 0.5 / 30000, 3.0 - 0.5 / 30000])}, "one second of data from t = 2 s, and nothing claimed about the channel axis"


async def test_a_sampling_law_needs_a_time_axis_to_act_on(authenticated_context):
    spikes = await seed.create_dataset(authenticated_context, "unit 3", seed.SPIKE_AXES, [412], value_unit="second")
    clock = await _clock(authenticated_context)
    with pytest.raises(ValueError, match="has no TIME axis"):
        await _law(authenticated_context, spikes.coordinate_system, clock)


async def test_a_sampling_rate_is_positive(authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [100])
    clock = await _clock(authenticated_context)
    with pytest.raises(ValueError, match="A sampling rate is positive"):
        await _law(authenticated_context, dataset.coordinate_system, clock, rate=0)


# --- the time lookup --------------------------------------------------------------------------------


async def test_an_irregular_signal_is_timed_by_a_lookup_through_its_times_dataset(authenticated_context):
    signal = await seed.create_dataset(authenticated_context, "Ca", seed.T_AXES, [500], value_unit="a.u.")
    times = await seed.create_dataset(authenticated_context, "Ca/times", seed.T_AXES, [500], value_unit="second")
    clock = await _clock(authenticated_context)

    edge = await sync_to_async(clocks.write_time_lookup)(grid=signal.coordinate_system, clock=clock, times=times, input_axis="t", ctx=seed._creation(authenticated_context))
    assert edge.kind == enums.TransformKindChoices.FIELD.value
    assert edge.field_id == times.coordinate_system_id
    assert await sync_to_async(graph.invariance_of)(edge) == enums.TransformInvariance.DIFFEOMORPHIC.value

    assert await sync_to_async(clocks.times_dataset_of)(signal.coordinate_system, clock) == times
    assert await sync_to_async(clocks.sampling_of)(signal.coordinate_system, clock) == (None, None), "a lookup has no rate"

    # Reachable, but not through one affine map: this is what an experiment view over it reports.
    assert await sync_to_async(graph.is_placeable_in)(clock, signal.coordinate_system, require_affine=False)
    assert not await sync_to_async(graph.is_placeable_in)(clock, signal.coordinate_system, require_affine=True)


async def test_a_spike_train_is_its_own_lookup(authenticated_context):
    """Its values ARE its times, so the field is the input -- stored as null, which keeps the dataset deletable."""
    spikes = await seed.create_dataset(authenticated_context, "unit 3", seed.SPIKE_AXES, [412], value_unit="second")
    clock = await _clock(authenticated_context)

    edge = await sync_to_async(clocks.write_time_lookup)(grid=spikes.coordinate_system, clock=clock, times=spikes, input_axis="spike", ctx=seed._creation(authenticated_context))
    assert edge.field_id is None
    assert await sync_to_async(lambda: edge.effective_field)() == spikes.coordinate_system
    assert await sync_to_async(clocks.times_dataset_of)(spikes.coordinate_system, clock) == spikes


async def test_a_lookup_cannot_convert_units_so_it_refuses_to(authenticated_context):
    """Milliseconds read against a clock in seconds would put every sample a thousandfold early, and nothing downstream could tell."""
    signal = await seed.create_dataset(authenticated_context, "Ca", seed.T_AXES, [500])
    times = await seed.create_dataset(authenticated_context, "Ca/times", seed.T_AXES, [500], value_unit="millisecond")
    clock = await _clock(authenticated_context)

    with pytest.raises(ValueError, match="states no numbers, so it cannot convert"):
        await sync_to_async(clocks.write_time_lookup)(grid=signal.coordinate_system, clock=clock, times=times, input_axis="t", ctx=seed._creation(authenticated_context))


@pytest.mark.parametrize("unit, message", [(None, "must say what its values measure"), ("millivolt", r"must measure \[time\]")], ids=["no unit", "not a time"])
async def test_a_times_dataset_holds_times(authenticated_context, unit, message):
    signal = await seed.create_dataset(authenticated_context, "Ca", seed.T_AXES, [500])
    times = await seed.create_dataset(authenticated_context, "Ca/times", seed.T_AXES, [500], value_unit=unit)
    clock = await _clock(authenticated_context)

    with pytest.raises(ValueError, match=message):
        await sync_to_async(clocks.write_time_lookup)(grid=signal.coordinate_system, clock=clock, times=times, input_axis="t", ctx=seed._creation(authenticated_context))


# --- the offset -----------------------------------------------------------------------------------------


async def test_an_offset_between_two_clocks_in_one_unit_is_a_translation(authenticated_context):
    segment = await _clock(authenticated_context, "segment 2")
    session = await _clock(authenticated_context, "session", epoch=datetime.datetime(2026, 9, 17, 9, 0, tzinfo=datetime.timezone.utc))

    edge = await sync_to_async(clocks.write_offset)(source=segment, target=session, offset=90 * 10**12, ctx=seed._creation(authenticated_context))
    assert edge.params == {"translation": [90.0]}
    assert await sync_to_async(graph.invariance_of)(edge) == enums.TransformInvariance.ISOMETRY.value
    assert await sync_to_async(clocks.offset_of)(segment, session) == 90 * 10**12


async def test_an_offset_between_two_units_states_the_factor(authenticated_context):
    """A simulation clock counts milliseconds; laid into a world in seconds, the edge must say 0.001 -- a bare translation cannot."""
    simulation = await _clock(authenticated_context, "simulation", unit="millisecond")
    world = await _clock(authenticated_context, "world")

    edge = await sync_to_async(clocks.write_offset)(source=simulation, target=world, offset=5 * 10**12, ctx=seed._creation(authenticated_context))
    assert edge.params["affine"][0] == approx([0.001, 5.0])
    assert await sync_to_async(clocks.offset_of)(simulation, world) == 5 * 10**12


async def test_a_recording_composes_through_its_clock_into_a_world(authenticated_context):
    """sample grid -> segment clock -> world: two edges, composed on read, stored nowhere."""
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    segment = await _clock(authenticated_context, "segment")
    world = await _clock(authenticated_context, "world")
    await _law(authenticated_context, dataset.coordinate_system, segment, rate=1000 * 10**9, start=0)
    await sync_to_async(clocks.write_offset)(source=segment, target=world, offset=10 * 10**12, ctx=seed._creation(authenticated_context))
    organization = authenticated_context.request.organization

    def look():
        return space_graph.SpaceGraph(world, organization=organization).in_view(space_graph.region_from_bounds(world, [0.0], [100.0]), with_anchors=False)

    (hit,) = await sync_to_async(look)()
    assert [edge.kind for edge, _ in hit.path] == ["BY_DIMENSION", "BY_DIMENSION"]
    assert hit.extent == {"t": approx([10.0 - 0.0005, 11.0 - 0.0005])}


# --- chains of frames ---------------------------------------------------------------------------
#
# Elektro's one addition to the vendored search (`graph.frames_into`). mikro roots a search at
# one space and fetches the edges touching it; here the chain of clocks is the ordinary layout.


async def test_a_recording_is_placed_through_a_three_clock_chain(authenticated_context):
    """sample grid -> segment clock -> session clock -> world: every hop past the first is frame-to-frame."""
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    segment = await _clock(authenticated_context, "segment")
    session = await _clock(authenticated_context, "session")
    world = await _clock(authenticated_context, "world")
    ctx = seed._creation(authenticated_context)
    await _law(authenticated_context, dataset.coordinate_system, segment, rate=1000 * 10**9, start=0)
    await sync_to_async(clocks.write_offset)(source=segment, target=session, offset=60 * 10**12, ctx=ctx)
    await sync_to_async(clocks.write_offset)(source=session, target=world, offset=5 * 10**12, ctx=ctx)
    organization = authenticated_context.request.organization

    assert await sync_to_async(graph.frames_into)(world) == {world.pk, session.pk, segment.pk}
    assert await sync_to_async(graph.is_placeable_in)(world, dataset.coordinate_system, require_affine=True)
    assert dataset.coordinate_system_id in await sync_to_async(graph.placeable_system_ids_in)(world)

    def look():
        return space_graph.SpaceGraph(world, organization=organization).in_view(space_graph.region_from_bounds(world, [0.0], [1000.0]), with_anchors=False)

    (hit,) = await sync_to_async(look)()
    assert len(hit.path) == 3
    assert hit.extent == {"t": approx([65.0 - 0.0005, 66.0 - 0.0005])}


async def test_a_shared_clock_does_not_leak_one_world_into_another(authenticated_context):
    """One session clock laid into two worlds: each sees the session's recording, neither sees what is only in the other.

    The chain is walked backwards only. Following the clock's *other* outgoing edge would drag
    everything laid out in the second world into the first.
    """
    shared = await seed.create_dataset(authenticated_context, "shared", seed.T_AXES, [1000])
    only_b = await seed.create_dataset(authenticated_context, "only in B", seed.T_AXES, [1000])
    session = await _clock(authenticated_context, "session")
    world_a = await _clock(authenticated_context, "world A")
    world_b = await _clock(authenticated_context, "world B")
    ctx = seed._creation(authenticated_context)
    await _law(authenticated_context, shared.coordinate_system, session, rate=1000 * 10**9, start=0)
    await sync_to_async(clocks.write_offset)(source=session, target=world_a, offset=0, ctx=ctx)
    await sync_to_async(clocks.write_offset)(source=session, target=world_b, offset=0, ctx=ctx)
    await _law(authenticated_context, only_b.coordinate_system, world_b, rate=1000 * 10**9, start=0)

    in_a = await sync_to_async(graph.placeable_system_ids_in)(world_a)
    in_b = await sync_to_async(graph.placeable_system_ids_in)(world_b)
    assert shared.coordinate_system_id in in_a and shared.coordinate_system_id in in_b
    assert only_b.coordinate_system_id in in_b
    assert only_b.coordinate_system_id not in in_a, "world A must not inherit world B's layout through the clock they share"
    assert world_b.pk not in await sync_to_async(graph.frames_into)(world_a)


async def test_a_chain_of_frames_may_be_a_cycle_without_hanging(authenticated_context):
    a = await _clock(authenticated_context, "a")
    b = await _clock(authenticated_context, "b")
    ctx = seed._creation(authenticated_context)
    await sync_to_async(clocks.write_offset)(source=a, target=b, offset=10**12, ctx=ctx)
    await sync_to_async(clocks.write_offset)(source=b, target=a, offset=-(10**12), ctx=ctx)
    assert await sync_to_async(graph.frames_into)(a) == {a.pk, b.pk}
