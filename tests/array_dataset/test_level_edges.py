"""`DataArray.to_parent` and `Lens.to_parent` answer about their *own* edge, not any edge.

Ported from mikro's ``tests/test_level_edges.py``.

Both properties resolve the stored map from a level's (or a lens') own sample space back into the
dataset's intrinsic grid. Under residence a level-0 array and an unsliced lens *share* the
dataset's intrinsic system rather than owning one, so every physical-space edge, every sampling
law and every registration the dataset has also leaves that space. A filter on ``input`` alone
therefore returned whichever of those sorted first under ``Transformation.Meta.ordering`` -- a
registration into a world, presented as the pyramid edge, exactly where both docstrings promise
``None``.

The suite passed with that bug for as long as it existed, because nothing built the shape that
exposes it: a dataset that has *both* levels and a second edge out of intrinsic. These tests build
it.
"""

import pytest
from asgiref.sync import sync_to_async

from core import enums, models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


_PHYSICAL_AXES = [
    seed.physical_axis("c", enums.AxisType.CHANNEL, "a.u."),
    seed.physical_axis("y", enums.AxisType.SPACE, "micrometer"),
    seed.physical_axis("x", enums.AxisType.SPACE, "micrometer"),
]


async def test_level_zero_has_no_parent_edge_even_when_the_dataset_is_registered(authenticated_context):
    """Level 0's space IS intrinsic, so it has no edge -- however many edges leave that space."""
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Pyramid", shapes=[[3, 64, 64], [3, 32, 32]])

    # The edge that used to be returned in place of "none": a physical space registers the
    # dataset's intrinsic samples into itself, so it leaves the very space level 0 lives in.
    await seed.create_physical_space(ctx, dataset, axes=_PHYSICAL_AXES, scale=[1.0, 0.2, 0.2])

    level_zero = await sync_to_async(lambda: models.DataArray.objects.get(dataset=dataset, level=0))()
    assert await sync_to_async(lambda: level_zero.to_parent)() is None, "level 0 is in the intrinsic grid by definition; the physical-space edge is not its parent edge"


async def test_level_zero_of_a_timed_recording_has_no_parent_edge(authenticated_context):
    """The ephys reading of the same shape: a decimated (t, c) recording whose grid is registered onto a clock."""
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Recording", seed.TC_AXES, [[10000, 4], [100, 4]])
    clock = await seed.create_world(ctx, "Session")
    await seed.register_into_world(ctx, clock, dataset)

    level_zero, level_one = await sync_to_async(lambda: list(models.DataArray.objects.filter(dataset=dataset).order_by("level")))()
    assert await sync_to_async(lambda: level_zero.to_parent)() is None, "the registration onto the clock leaves the grid level 0 lives in, and is not its parent edge"

    edge = await sync_to_async(lambda: level_one.to_parent)()
    assert edge is not None and (edge.input_id, edge.output_id) == (level_one.coordinate_system_id, dataset.coordinate_system_id)


async def test_a_downsampled_level_returns_its_own_edge(authenticated_context):
    """A level that owns a space answers with the edge `create_level_edge` wrote for it."""
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Pyramid", shapes=[[3, 64, 64], [3, 32, 32]])
    await seed.create_physical_space(ctx, dataset, axes=_PHYSICAL_AXES, scale=[1.0, 0.2, 0.2])

    level_one = await sync_to_async(lambda: models.DataArray.objects.get(dataset=dataset, level=1))()
    edge = await sync_to_async(lambda: level_one.to_parent)()

    assert edge is not None
    assert edge.input_id == level_one.coordinate_system_id, "the edge leaves this level's own space"
    assert edge.output_id == dataset.coordinate_system_id, "and lands in the dataset's intrinsic grid"
    assert edge.parent_id is None, "a wrapper's child is a step within an edge, never the edge"


async def test_an_unsliced_lens_has_no_parent_edge(authenticated_context):
    """The lens half of the same rule: no slices, no shift, no edge -- and no borrowed one either."""
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Lensed")
    await seed.create_physical_space(ctx, dataset, axes=_PHYSICAL_AXES, scale=[1.0, 0.2, 0.2])

    lens = await seed.create_lens(ctx, dataset, slices=None)
    assert await sync_to_async(lambda: lens.to_parent)() is None
