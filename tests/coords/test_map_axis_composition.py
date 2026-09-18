"""A MAP_AXIS edge had no matrix, so an ROI drawn behind one came back in the wrong frame.

Ported from mikro's ``tests/test_map_axis_composition.py``. ``compute_intrinsic_bbox`` is
vendored, and a (t, c) recording transposed to (c, t) reaches its source by exactly this edge.

`to_matrix` handled identity, scale, translation, affine, rotation and sequence, and raised
`NonAffineTransformError` for everything else. That raise is *caught* by
`compute_intrinsic_bbox`, which treats it as "there is no chain to intrinsic" and returns
the box in the coordinates it was drawn in -- labelled as intrinsic. So an ROI on the far
side of an axis permutation was silently mislabelled rather than loudly rejected.

A permutation is trivially affine. The only reason it had no case is that its map lives in
the edge's `inputAxes`/`outputAxes` columns rather than in `params`, and `to_matrix` only
ever sees `params` -- so `_edge_params` writes the permutation out as an `affine`.
"""

import pytest
from asgiref.sync import sync_to_async

from core import enums, models
from core.logic import graph as graph_logic
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def test_an_roi_behind_a_map_axis_edge_is_permuted_not_mislabelled(authenticated_context):
    """The box is pushed through the permutation, rather than handed back untouched."""
    dataset = await seed.create_array_dataset(authenticated_context, "Volume")
    organization = authenticated_context.request.organization

    def build() -> models.CoordinateSystem:
        grid = dataset.coordinate_system  # (c, y, x)

        # A system whose axes are the same, transposed: y and x swapped. Data written in it
        # reaches the dataset's sample grid by an axis permutation and nothing else.
        transposed = models.CoordinateSystem.objects.create(name="Transposed", organization=organization)
        for index, (name, axis_type) in enumerate([("c", enums.AxisTypeChoices.CHANNEL.value), ("x", enums.AxisTypeChoices.SPACE.value), ("y", enums.AxisTypeChoices.SPACE.value)]):
            models.Axis.objects.create(coordinate_system=transposed, order=index, name=name, type=axis_type)

        models.Transformation.objects.create(
            kind=enums.TransformKindChoices.MAP_AXIS.value,
            name="transpose",
            input=transposed,
            output=grid,
            input_axes=["x", "y"],
            output_axes=["y", "x"],
            organization=organization,
        )
        return transposed

    transposed = await sync_to_async(build)()

    # A box that is NOT symmetric under the swap, so a permutation that silently did not
    # happen cannot pass for one that did.
    vectors = [[0.0, 0.0, 0.0], [2.0, 30.0, 10.0]]
    bbox = await sync_to_async(graph_logic.compute_intrinsic_bbox)(transposed, vectors)

    # Drawn as (c, x, y) = (2, 30, 10); in the dataset's (c, y, x) grid that is (2, 10, 30) --
    # the box pads by half a sample, as it always has. Before the fix it came back as
    # (2, 30, 10): the raw numbers, unpermuted, with an intrinsic label on them.
    assert bbox["max"][1] < bbox["max"][2], f"the y and x extents must have swapped: {bbox['max']}"
    assert bbox["max"] == [2.5, 10.5, 30.5]
    assert bbox["min"] == [-0.5, -0.5, -0.5]
