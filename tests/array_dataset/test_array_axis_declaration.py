"""The declared axes are checked against what the zarr itself says.

Ported from mikro's ``tests/test_array_axis_declaration.py``.

`ZarrStore.fill_info` has read `dimension_names` off the array since the field
existed, and it is published in the SDL. Nothing ever compared it to the caller's
`axes`. So a `(z, y, x)` store declared `(x, y, z)` was accepted -- and the failure is
not an error: everything downstream finds an axis by *name*, so a sampling law written
over `t` would run along the channels of a transposed `(t, c)` recording.

`axes` stays required regardless. `dimension_names` carries names only, and the *type*
is what the spec, the coarsening rule and the composition run on -- so mapping
`{x, y, z} -> SPACE` here would be convention-guessing. The name is redundant with the
bytes; the type is not. Declare the type, get the name checked for free.

mikro's version patches `ZarrStore.fill_info` and states `dimension_names` on the row.
This one does not: `zarr_store(shape=, dimension_names=)` writes a real `zarr.json` to the
compose RustFS and `createArrayDataset` reads it back, so the names compared are the ones
the bytes carry.
"""

import pytest

from core.models import ArrayDataset, CoordinateSystem

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE = """
mutation Create($input: CreateArrayDatasetInput!) {
  createArrayDataset(input: $input) { id intrinsicSystem { axes { name order } } }
}
"""

_ZYX = [
    {"name": "z", "type": "SPACE"},
    {"name": "y", "type": "SPACE"},
    {"name": "x", "type": "SPACE"},
]


async def _create(aexecute, zarr_store, name: str, dimension_names: list | None, axes: list, shape: list | None = None, scales: list | None = None):  # noqa: ANN001, ANN202
    store = await zarr_store(shape=shape or [8, 64, 64], dimension_names=dimension_names)
    return await aexecute(CREATE, {"input": {"name": name, "data": str(store.pk), "scales": scales or [], "axes": axes}})


async def test_axes_that_name_the_stores_dimensions_are_accepted(aexecute, zarr_store):
    result = await _create(aexecute, zarr_store, "agrees", ["z", "y", "x"], _ZYX)

    assert not result.errors, result.errors
    axes = result.data["createArrayDataset"]["intrinsicSystem"]["axes"]
    assert [a["name"] for a in axes] == ["z", "y", "x"]


@pytest.mark.parametrize(
    "dimension_names",
    [["z", "c", "y", "x"], ["c", "z", "y", "x"], ["z", "y", "c", "x"]],
    ids=["z-first", "c-first", "c-between"],
)
async def test_an_acquisitions_own_dimension_order_is_accepted(aexecute, zarr_store, dimension_names: list):
    """The orderings the RFC-5 type rule used to refuse, which is most real stores.

    A channel axis after a spatial one, or between two of them, is how acquisitions are
    ordinarily written. No ordering is required of a declaration: the channel axis is found
    by type, everything else by name.

    The store's own `dimension_names` still has to agree -- that is the check that means
    something, and `test_a_transposed_declaration_is_refused` covers it.
    """
    axes = [{"name": name, "type": "CHANNEL" if name == "c" else "SPACE"} for name in dimension_names]
    result = await _create(
        aexecute,
        zarr_store,
        f"acquisition-{'-'.join(dimension_names)}",
        dimension_names,
        axes,
        shape=[8, 3, 64, 64] if dimension_names[1] == "c" else [8, 64, 3, 64] if dimension_names[2] == "c" else [3, 8, 64, 64],
    )

    assert not result.errors, str(result.errors and result.errors[0])
    stored = result.data["createArrayDataset"]["intrinsicSystem"]["axes"]
    assert [a["name"] for a in stored] == dimension_names, "stored in the store's order, not sorted into the RFC-5 one"
    assert [a["order"] for a in stored] == list(range(len(dimension_names))), "order is the index into the shape"


async def test_a_recordings_own_dimension_order_is_accepted(aexecute, zarr_store):
    """The ephys reading of the case above: (t, c) and (c, t) are both ordinary ways to write a recording."""
    for names in (["t", "c"], ["c", "t"]):
        axes = [{"name": name, "type": "CHANNEL" if name == "c" else "TIME"} for name in names]
        shape = [1000, 4] if names[0] == "t" else [4, 1000]
        result = await _create(aexecute, zarr_store, f"recording-{'-'.join(names)}", names, axes, shape=shape)
        assert not result.errors, str(result.errors and result.errors[0])
        assert [a["name"] for a in result.data["createArrayDataset"]["intrinsicSystem"]["axes"]] == names


async def test_a_transposed_declaration_is_refused(aexecute, zarr_store):
    """The whole point: this used to be accepted and read the wrong samples.

    `(z, y, x)` in the store, `(x, y, z)` declared. Both are well-formed -- all three
    axes are SPACE, so no ordering rule separates them. Nothing raises, at any point,
    without this check.
    """
    result = await _create(
        aexecute,
        zarr_store,
        "transposed",
        ["z", "y", "x"],
        [
            {"name": "x", "type": "SPACE"},
            {"name": "y", "type": "SPACE"},
            {"name": "z", "type": "SPACE"},
        ],
    )

    assert result.errors, "a transposed declaration must not be accepted"
    message = str(result.errors[0])
    assert "dimension 0 is 'z' in the store and was declared 'x'" in message
    assert "dimension 2 is 'x' in the store and was declared 'z'" in message
    assert not await ArrayDataset.objects.filter(name="transposed").aexists()
    assert not await CoordinateSystem.objects.filter(name="transposed/intrinsic").aexists(), "refused before anything is written"


async def test_a_store_that_names_no_dimensions_is_not_refused(aexecute, zarr_store):
    """zarr v2, or an array written before the field existed.

    The check is on what the bytes say, and these bytes say nothing. Refusing here
    would make a schema addition retroactively invalidate every store predating it.
    """
    result = await _create(aexecute, zarr_store, "unnamed-store", None, _ZYX)

    assert not result.errors, result.errors


async def test_a_null_dimension_name_is_skipped_not_compared(aexecute, zarr_store):
    """zarr v3 permits a null per dimension -- the store declining to name that one.

    `ZarrMetadata.dimension_names` is typed `list[str | None] | None` for exactly this.
    A null is an absence, not a disagreement, so the named dimensions are still checked
    around it.
    """
    result = await _create(aexecute, zarr_store, "partly-named", ["z", None, "x"], _ZYX)
    assert not result.errors, result.errors

    wrong = await _create(
        aexecute,
        zarr_store,
        "partly-named-wrong",
        ["z", None, "x"],
        [
            {"name": "z", "type": "SPACE"},
            {"name": "y", "type": "SPACE"},
            {"name": "q", "type": "SPACE"},
        ],
    )
    assert wrong.errors, "the dimensions that ARE named are still compared"
    assert "dimension 2 is 'x' in the store and was declared 'q'" in str(wrong.errors[0])


async def test_a_rank_mismatch_is_prose_rather_than_an_assertion(aexecute, zarr_store):
    """It was a bare `assert` until 2026-08-20.

    Which vanishes under `-O` -- so the guard was off in exactly the deployment most
    likely to run that way -- and surfaced as `AssertionError` rather than as
    something a caller could act on.
    """
    result = await _create(
        aexecute,
        zarr_store,
        "rank-mismatch",
        ["z", "y", "x"],
        [{"name": "y", "type": "SPACE"}, {"name": "x", "type": "SPACE"}],
    )

    assert result.errors
    # The *type*, not the text: a bare `assert` still carries its message, so
    # grepping the string would pass either way and this test would be checking
    # nothing.
    assert not isinstance(result.errors[0].original_error, AssertionError)
    assert "3 dimensions but 2 axes were declared" in str(result.errors[0])


async def test_a_pyramid_level_is_checked_against_the_same_axes(aexecute, zarr_store):
    """A level is the same array at a coarser grid, so it has the same axes in the same order.

    A level whose zarr names its dimensions differently is the transposition bug one zoom
    down: the dataset reads correctly until a client crosses into that level, and then
    quietly does not. The per-level check was a second bare `assert`, on rank only.
    """
    level = await zarr_store(shape=[4, 32, 32], dimension_names=["z", "x", "y"])
    result = await _create(aexecute, zarr_store, "pyramid", ["z", "y", "x"], _ZYX, scales=[{"level": 1, "array": str(level.pk)}])

    assert result.errors, "a transposed pyramid level must not be accepted"
    message = str(result.errors[0])
    assert "Pyramid level 1" in message, "the level is named, since level 0 was fine"
    assert "dimension 1 is 'x' in the store and was declared 'y'" in message

    # One transaction here, which mikro's is not: level 0 was fine and had already been
    # written when level 1 was refused, and the refusal takes it back.
    assert not await ArrayDataset.objects.filter(name="pyramid").aexists()
    assert await CoordinateSystem.objects.acount() == 0, "neither the grid nor the level's space outlives the refusal"


async def test_a_pyramid_level_that_agrees_is_accepted(aexecute, zarr_store):
    """The same shape, passing -- so the test above is failing on the names, not the pyramid."""
    level = await zarr_store(shape=[4, 32, 32], dimension_names=["z", "y", "x"])
    result = await _create(aexecute, zarr_store, "good-pyramid", ["z", "y", "x"], _ZYX, scales=[{"level": 1, "array": str(level.pk)}])

    assert not result.errors, result.errors
