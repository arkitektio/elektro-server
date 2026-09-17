"""A label pyramid may only have been built by picking, never by averaging.

Ported from the label-compliance block of mikro's ``tests/test_derived_datasets.py`` (the rest of
that file is in ``tests/coords/test_derived_datasets.py``).

The damage an averaged mask pyramid does is silent and permanent: level 1 holds 41.5 where
objects 41 and 42 meet, an id belonging to no object, along every boundary. Here the ids are as
often unit ids or event codes as mask labels -- a sorted-spike raster decimated by averaging
holds a unit 41.5 wherever two units fired in one window. The array is well-formed and it
plots; the phantom ids only surface as objects that cannot be looked up. So the one moment it
can be caught is when the levels are written, and on two signals: the primary derivation's
CATEGORIZED statement, and an INDEX axis.

mikro's helpers patch ``ZarrStore.fill_info``; these go through the ``create_array_dataset``
fixture, which writes a real ``zarr.json`` per level to the compose RustFS.
"""

import pytest

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


COMPLIANCE = "query D($id: ID!) { arrayDataset(id: $id) { pyramidIsLabelCompliant dataArrays { level scaleMethod } } }"

_YX = [{"name": "y", "type": "SPACE"}, {"name": "x", "type": "SPACE"}]

#: (object, y, x): a per-object stack. The first axis enumerates, the other two measure.
_OBJECT_YX = [{"name": "object", "type": "INDEX"}, {"name": "y", "type": "SPACE"}, {"name": "x", "type": "SPACE"}]


async def _create_with_pyramid(create_array_dataset, name: str, *, axes: list, shapes: list[list[int]], scale_method: str | None, derived_from: list | None = None):  # noqa: ANN001, ANN202
    """Run `createArrayDataset` over a pyramid of `shapes`, stating how each level above 0 was built (or not).

    Every level but the first becomes a `scales` entry, so a single-entry `shapes` is an
    unpyramided dataset -- the case where there is nothing a scale method could be wrong about.
    """
    return await create_array_dataset(name, shapes[0], axes=axes, levels=[(shape, scale_method) for shape in shapes[1:]], derived_from=derived_from, raw=True)


async def _derive_with_pyramid(create_array_dataset, ctx, name: str, *, value_relation: str, scale_method: str | None, axes: list | None = None, shapes: list[list[int]] | None = None):  # noqa: ANN001, ANN202
    """A two-level dataset derived from a fresh (y, x) source, stating how level 1 was downsampled (or not)."""
    source = await seed.create_array_dataset(ctx, "Raw", axes=seed.YX_AXES, shapes=[[64, 64]])
    lens = await seed.create_lens(ctx, source, slices=[])
    return await _create_with_pyramid(
        create_array_dataset,
        name,
        axes=axes or _YX,
        shapes=shapes or [[64, 64], [32, 32]],
        scale_method=scale_method,
        derived_from=[{"kind": "LENS", "lens": str(lens.pk), "transform": {"kind": "IDENTITY"}, "valueRelation": value_relation}],
    )


async def _compliance(aexecute, dataset_id: str) -> dict:  # noqa: ANN001
    read = await aexecute(COMPLIANCE, {"id": dataset_id})
    assert not read.errors, read.errors
    return read.data["arrayDataset"]


async def test_a_categorized_pyramid_refuses_an_averaged_level(create_array_dataset, authenticated_context):
    """AREA over ids returns a number that was in neither source sample."""
    result = await _derive_with_pyramid(create_array_dataset, authenticated_context, "Mask", value_relation="CATEGORIZED", scale_method="AREA")
    assert result.errors, "expected an averaged pyramid over a CATEGORIZED dataset to be refused"
    assert "may not have been downsampled with AREA" in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Mask").aexists(), "the refusal ran before anything was written"


@pytest.mark.parametrize("method", ["MAX", "MIN", "LINEAR", "CUBIC", "GAUSSIAN"])
async def test_a_categorized_pyramid_refuses_every_method_that_is_not_a_pick(create_array_dataset, authenticated_context, method: str):
    """MAX and MIN return a real id but not the *right* one; the interpolations invent one. Only NEAREST and MODE answer "which object is here"."""
    result = await _derive_with_pyramid(create_array_dataset, authenticated_context, "Mask", value_relation="CATEGORIZED", scale_method=method)
    assert result.errors and f"may not have been downsampled with {method}" in str(result.errors[0])
    assert "MODE, NEAREST" in str(result.errors[0]), "the refusal says what would have been accepted"


async def test_a_categorized_pyramid_must_say_how_it_was_built(create_array_dataset, authenticated_context):
    """Silence is not compliance: nothing about two arrays says whether one was averaged.

    The value could not be derived even in principle, so an unstated method over data
    already declared to be ids is refused rather than assumed benign.
    """
    result = await _derive_with_pyramid(create_array_dataset, authenticated_context, "Mask", value_relation="CATEGORIZED", scale_method=None)
    assert result.errors, "expected an undeclared method over a CATEGORIZED dataset to be refused"
    assert "must say how it was downsampled" in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Mask").aexists()


async def test_a_label_compliant_pyramid_is_stored_and_reported(aexecute, create_array_dataset, authenticated_context):
    """MODE is accepted, stored on the level, and read back through the dataset.

    The stored value is the point: `scaleMethod` has been on `ScaleInput` since the initial
    schema, described as recorded, and was dropped by `to_pydantic()` before any resolver
    saw it. This is the assertion that it now survives the round trip.
    """
    result = await _derive_with_pyramid(create_array_dataset, authenticated_context, "Mask", value_relation="CATEGORIZED", scale_method="MODE")
    assert not result.errors, result.errors

    data = await _compliance(aexecute, result.data["createArrayDataset"]["id"])
    assert data["pyramidIsLabelCompliant"] is True
    assert sorted((array["level"], array["scaleMethod"]) for array in data["dataArrays"]) == [(0, None), (1, "MODE")], "level 0 was downsampled from nothing"


async def test_an_intensity_pyramid_may_be_averaged(aexecute, create_array_dataset, authenticated_context):
    """The guard is about the values, not about pyramids: averaging a measurement is correct.

    And the reported compliance is False rather than an error: it is true of the levels,
    whatever the values later turn out to be, and it is the field that would say they
    cannot be trusted as ids.
    """
    result = await _derive_with_pyramid(create_array_dataset, authenticated_context, "Filtered", value_relation="TRANSFORMED", scale_method="AREA")
    assert not result.errors, result.errors

    data = await _compliance(aexecute, result.data["createArrayDataset"]["id"])
    assert data["pyramidIsLabelCompliant"] is False, "true of the levels, whatever the values turn out to be"


async def test_an_unstated_pyramid_reports_null_not_compliant(aexecute, create_array_dataset, authenticated_context):
    """Null is its own answer: nobody said, which is not the same as nobody averaged.

    Every level written before `scaleMethod` was stored reads this way, and collapsing it
    into either true or false would manufacture an answer out of a gap in the record.
    """
    result = await _derive_with_pyramid(create_array_dataset, authenticated_context, "Unstated", value_relation="TRANSFORMED", scale_method=None)
    assert not result.errors, result.errors

    data = await _compliance(aexecute, result.data["createArrayDataset"]["id"])
    assert data["pyramidIsLabelCompliant"] is None


async def test_an_unpyramided_dataset_is_trivially_compliant(aexecute, authenticated_context):
    """One level, nothing downsampled, nothing that could be wrong."""
    dataset = await seed.create_array_dataset(authenticated_context, "Flat", axes=seed.YX_AXES, shapes=[[64, 64]])

    data = await _compliance(aexecute, str(dataset.pk))
    assert data["pyramidIsLabelCompliant"] is True


# ---------------------------------------------------------------------------
# An INDEX axis is the second door into the same guard. A dimension that
# enumerates objects says the array is not measurements as loudly as CATEGORIZED
# does, and it says it for an array that arrives with no derivation at all -- the
# ingest the value_relation signal can never see. The axis never shrinks between
# levels (`_DOWNSAMPLABLE_TYPES` refuses that), so the pyramids below keep the
# object axis at full length and downsample y and x.
# ---------------------------------------------------------------------------


async def test_an_index_axis_refuses_an_averaged_pyramid_with_no_derivation(create_array_dataset):
    """The case the CATEGORIZED signal cannot reach: an ingest that declares no derivation.

    Nothing about this dataset says what its values are except its axes, and one of them
    enumerates objects. Before this guard the AREA level was written without a word.
    """
    result = await _create_with_pyramid(create_array_dataset, "Masks", axes=_OBJECT_YX, shapes=[[8, 64, 64], [8, 32, 32]], scale_method="AREA")
    assert result.errors, "expected an averaged pyramid over an INDEX-axis dataset to be refused"
    message = str(result.errors[0])
    assert "may not have been downsampled with AREA" in message
    assert "'object'" in message, "the refusal has to name the axis it is about"
    assert not await models.ArrayDataset.objects.filter(name="Masks").aexists(), "the refusal ran before anything was written"


async def test_an_index_axis_refuses_an_averaged_pyramid_whatever_the_derivation_says(create_array_dataset, authenticated_context):
    """TRANSFORMED does not buy an INDEX-axis dataset an average: the two signals are independent."""
    result = await _derive_with_pyramid(
        create_array_dataset,
        authenticated_context,
        "Crops",
        value_relation="TRANSFORMED",
        scale_method="AREA",
        axes=_OBJECT_YX,
        shapes=[[8, 64, 64], [8, 32, 32]],
    )
    assert result.errors, "expected the axis trigger to fire independently of the value relation"
    assert "may not have been downsampled with AREA" in str(result.errors[0])


async def test_an_index_axis_pyramid_must_say_how_it_was_built(create_array_dataset):
    """Silence is not compliance here either -- the same strictness the CATEGORIZED case gets."""
    result = await _create_with_pyramid(create_array_dataset, "Silent", axes=_OBJECT_YX, shapes=[[8, 64, 64], [8, 32, 32]], scale_method=None)
    assert result.errors, "expected an undeclared method over an INDEX-axis dataset to be refused"
    assert "must say how it was downsampled" in str(result.errors[0])


async def test_an_index_axis_pyramid_built_by_picking_is_accepted(aexecute, create_array_dataset):
    """MODE is what the guard is asking for, and the level reads back saying so."""
    result = await _create_with_pyramid(create_array_dataset, "Picked", axes=_OBJECT_YX, shapes=[[8, 64, 64], [8, 32, 32]], scale_method="MODE")
    assert not result.errors, result.errors

    data = await _compliance(aexecute, result.data["createArrayDataset"]["id"])
    assert data["pyramidIsLabelCompliant"] is True
    assert sorted((array["level"], array["scaleMethod"]) for array in data["dataArrays"]) == [(0, None), (1, "MODE")]


async def test_an_unpyramided_index_axis_dataset_is_accepted(create_array_dataset):
    """The guard is about levels, not about axes: with nothing downsampled there is nothing to state.

    The negative that keeps it honest -- an INDEX axis must not become a reason to refuse an
    ordinary single-level ingest, which here is every spike train's times dataset.
    """
    result = await _create_with_pyramid(create_array_dataset, "Flat objects", axes=_OBJECT_YX, shapes=[[8, 64, 64]], scale_method=None)
    assert not result.errors, result.errors

    spikes = await _create_with_pyramid(create_array_dataset, "spike times", axes=[{"name": "spike", "type": "INDEX"}], shapes=[[412]], scale_method=None)
    assert not spikes.errors, spikes.errors
