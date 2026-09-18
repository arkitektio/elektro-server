"""The graph primitives over a dataset: its sample grid, a lens' derived edge, and a clock.

These go through the ORM builders in ``tests/seed.py`` rather than GraphQL: they pin what
the *logic* writes, so a failure here is a failure of the port and not of a resolver.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core import enums
from core.logic import graph
from core.models import Transformation
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def test_a_dataset_lives_in_a_sample_grid_with_no_units(authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.TC_AXES, [30000, 4])

    axes = await sync_to_async(lambda: [(a.order, a.name, a.type, a.unit) for a in dataset.axes])()
    assert axes == [(0, "t", "TIME", None), (1, "c", "CHANNEL", None)], "order is the store's dimension order, and a sample grid never carries a unit"
    assert await sync_to_async(lambda: dataset.shape_list)() == [30000, 4]

    residents = await sync_to_async(lambda: graph.container_map([dataset.coordinate_system_id]))()
    assert residents == {dataset.coordinate_system_id: ("dataset", dataset.pk)}


async def test_an_unsliced_lens_shares_the_grid_and_a_sliced_one_records_the_shift(authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.TC_AXES, [30000, 4])

    whole = await seed.create_lens(authenticated_context, dataset)
    assert whole.coordinate_system_id == dataset.coordinate_system_id, "selecting everything is the grid itself: no second node, no identity edge"
    assert await sync_to_async(lambda: whole.to_parent)() is None

    window = await seed.create_lens(authenticated_context, dataset, [{"axis": "t", "start": 6000, "stop": 9000}])
    assert window.coordinate_system_id != dataset.coordinate_system_id
    assert await sync_to_async(lambda: window.shape_list)() == [3000, 4]

    edge = await sync_to_async(lambda: window.to_parent)()
    assert edge.kind == enums.TransformKindChoices.TRANSLATION.value
    assert edge.params["translation"] == approx([6000.0, 0.0]), "sample 0 of the window is sample 6000 of the recording"
    assert edge.validity == enums.PlacementValidityChoices.VALIDATED.value, "derived from the slices, so it cannot be wrong"


async def test_a_lens_refuses_an_axis_its_dataset_does_not_have(authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    with pytest.raises(ValueError, match=r"\['c'\] is not among \['t'\]"):
        await seed.create_lens(authenticated_context, dataset, [{"axis": "c", "start": 0, "stop": 1}])


async def test_a_sampling_law_is_one_affine_edge_onto_a_clock(authenticated_context):
    """30 kHz starting 2 s in: t_seconds = sample / 30000 + 2, stated once, on one edge."""
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [30000])
    clock = await seed.create_physical_space(authenticated_context, dataset, seed.CLOCK_AXES, affine=[[1 / 30000, 2.0]], name="clock")

    edges = await sync_to_async(lambda: list(Transformation.objects.filter(input=dataset.coordinate_system, output=clock, parent__isnull=True)))()
    assert len(edges) == 1, "a scale edge beside a translation edge would be two rival maps, not a composition"
    assert edges[0].kind == enums.TransformKindChoices.AFFINE.value
    assert edges[0].validity == enums.PlacementValidityChoices.INFERRED.value


async def test_a_metric_edge_is_refused_over_an_index_axis(authenticated_context):
    """Spike number has no metric, so a spike train cannot be given a sampling rate."""
    spikes = await seed.create_dataset(authenticated_context, "unit 3", seed.SPIKE_AXES, [412], value_unit="second")
    with pytest.raises(ValueError, match="is an INDEX axis, which has no metric"):
        await seed.create_physical_space(authenticated_context, spikes, [seed.physical_axis("spike", enums.AxisType.INDEX, "a.u.")], scale=[0.001])


# --- the FIELD rule ---------------------------------------------------------------------


async def test_a_times_dataset_alone_in_its_system_can_be_a_field(authenticated_context):
    times = await seed.create_dataset(authenticated_context, "times", seed.T_AXES, [500], value_unit="second")
    await sync_to_async(graph.assert_field_is_dereferenceable)(times.coordinate_system)


async def test_a_system_two_datasets_share_cannot_be_a_field(authenticated_context):
    """Co-sampled datasets may share a grid, and then "the array whose values are the map" is not a function of the system."""
    first = await seed.create_dataset(authenticated_context, "soma.v", seed.T_AXES, [500])
    await seed.create_dataset(authenticated_context, "dend.v", seed.T_AXES, [500], system=first.coordinate_system)

    with pytest.raises(ValueError, match="More than one dataset lives in coordinate system"):
        await sync_to_async(graph.assert_field_is_dereferenceable)(first.coordinate_system)


async def test_an_empty_space_cannot_be_a_field(authenticated_context):
    world = await seed.create_world(authenticated_context)
    with pytest.raises(ValueError, match="No dataset lives in coordinate system"):
        await sync_to_async(graph.assert_field_is_dereferenceable)(world)


# --- what is in view of a clock -----------------------------------------------------------


async def test_a_clock_sees_the_datasets_sampled_onto_it_and_where_they_sit(authenticated_context):
    """A 1 s recording at 1 kHz starting at t = 2 s occupies [2 s, 3 s) of its clock -- derived from the shape and the edge, stored nowhere."""
    from core.logic import space_graph

    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    clock = await seed.create_physical_space(authenticated_context, dataset, seed.CLOCK_AXES, affine=[[0.001, 2.0]], name="clock")
    organization = authenticated_context.request.organization

    def look(low: float, high: float) -> list:
        graph_ = space_graph.SpaceGraph(clock, organization=organization)
        return graph_.in_view(space_graph.region_from_bounds(clock, [low], [high]), with_anchors=False)

    hits = await sync_to_async(look)(0.0, 10.0)
    assert [hit.source.container.pk for hit in hits] == [dataset.pk]
    assert hits[0].extent_state == enums.ExtentState.KNOWN.value
    # Half-open around the sample centre: sample 0 spans [-0.5, 0.5) samples, i.e. [1.9995 s, 2.0005 s).
    assert hits[0].extent["t"] == approx([2.0 - 0.0005, 3.0 - 0.0005])

    assert await sync_to_async(look)(5.0, 6.0) == [], "a window after the recording ended sees nothing"


async def test_a_window_is_in_view_through_its_own_edge(authenticated_context):
    """A sliced lens composes lens -> grid -> clock, so its box is the window's, not the recording's."""
    from core.logic import space_graph

    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    clock = await seed.create_physical_space(authenticated_context, dataset, seed.CLOCK_AXES, affine=[[0.001, 0.0]], name="clock")
    window = await seed.create_lens(authenticated_context, dataset, [{"axis": "t", "start": 250, "stop": 500}])
    organization = authenticated_context.request.organization

    def place() -> "space_graph.Hit | None":
        graph_ = space_graph.SpaceGraph(clock, organization=organization)
        source = space_graph.Source(container=window, system=window.coordinate_system, dataset_id=dataset.pk, container_key=graph_.universe.container_of(window.coordinate_system_id))
        return graph_.placement(source, space_graph.region_from_bounds(clock, [0.0], [10.0]))

    hit = await sync_to_async(place)()
    assert hit is not None and hit.extent_state == enums.ExtentState.KNOWN.value
    assert hit.extent["t"] == approx([0.25 - 0.0005, 0.5 - 0.0005])
    assert [edge.kind for edge, _ in hit.path] == ["TRANSLATION", "AFFINE"]
