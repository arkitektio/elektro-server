"""Conformance tests for the coordinate arithmetic (``core.logic.coords``).

Ported from mikro's ``tests/test_coordinates.py`` -- the pure half, which touches no
database. They exist because the bugs this layer is built to prevent do not raise: a
nominal downsample factor, a dropped half-sample, a two-corner bounding box under a
rotation. None of them crash; they put things at the wrong instant, plausibly, and stay
there for years.

The pyramid fixture is mikro's on purpose, SPACE axes and all. The arithmetic is generic
over axis types, and keeping the numbers identical is what makes a regression here
comparable against the service it was vendored from. Read "voxel" as "sample": a
decimated dataset obeys the same half-sample rule a downsampled image does.
"""

import pytest
from pytest import approx

from core import enums
from core.logic import coords

# A realistic 5-D layout: t and c are not downsampled, z is 36 (not a power of two).
_AXIS_SPECS = [
    coords.AxisSpec(name="t", type=enums.AxisTypeChoices.TIME.value),
    coords.AxisSpec(name="c", type=enums.AxisTypeChoices.CHANNEL.value),
    coords.AxisSpec(name="z", type=enums.AxisTypeChoices.SPACE.value),
    coords.AxisSpec(name="y", type=enums.AxisTypeChoices.SPACE.value),
    coords.AxisSpec(name="x", type=enums.AxisTypeChoices.SPACE.value),
]


PYRAMID_SHAPES = [
    [10, 2, 36, 1024, 1024],
    [10, 2, 18, 512, 512],
    [10, 2, 9, 256, 256],
    [10, 2, 4, 128, 128],
    [10, 2, 2, 64, 64],
    [10, 2, 1, 32, 32],
]


def _level_transform(level: int) -> tuple[list[float], list[float]]:
    return coords.pyramid_transform(PYRAMID_SHAPES[0], PYRAMID_SHAPES[level], _AXIS_SPECS)


# --- 1. the assertion that matters ----------------------------------------


def test_extent_preserved():
    """Every level must cover the same pixel extent. This is THE assertion.

    ``scale[i] * shape[i]`` is the size of the array along axis i, in level-0
    pixels. If a level's scale is right, that size is the same at every level --
    the pyramid is the same object, sampled more coarsely. A nominal 2**level
    factor breaks this on any axis that does not halve cleanly, and breaks it
    silently.
    """
    for level in range(len(PYRAMID_SHAPES)):
        scale, _ = _level_transform(level)
        for i in range(len(_AXIS_SPECS)):
            assert scale[i] * PYRAMID_SHAPES[level][i] == approx(PYRAMID_SHAPES[0][i]), f"level {level} axis '{_AXIS_SPECS[i].name}' does not cover the same extent as level 0"


def test_z_factor_is_not_a_power_of_two():
    """The z scales must follow the real shapes, not the nominal 2**level chain.

    Level 3's z factor is 36/4 = 9, not 8. A model that stores nominal factors
    says 8, and every level from 3 up is then compressed in z -- with nothing
    anywhere to say so.
    """
    z = _AXIS_SPECS.index(next(a for a in _AXIS_SPECS if a.name == "z"))
    expected = [1.0, 2.0, 4.0, 9.0, 18.0, 36.0]

    for level, want in enumerate(expected):
        scale, _ = _level_transform(level)
        assert scale[z] == approx(want), f"level {level} z scale"

    nominal = [float(2**level) for level in range(6)]
    assert expected[3:] != nominal[3:], "the fixture must actually exercise a non-power-of-two axis, or this proves nothing"


def test_half_voxel_offset_is_recorded():
    """A downsample shifts the voxel centres, and the translation must say so.

    Level 1's voxels are centred half a level-0 voxel further in. Nothing recorded
    this before, so LOD 1 drew half a pixel off from LOD 0 -- visible only as a
    faint shimmer when the renderer crossed a level boundary.
    """
    _, translation = _level_transform(0)
    assert translation == [0.0] * len(_AXIS_SPECS), "level 0 is not downsampled and must not be offset"

    for level in range(1, len(PYRAMID_SHAPES)):
        _, translation = _level_transform(level)
        for i, spec in enumerate(_AXIS_SPECS):
            factor = PYRAMID_SHAPES[0][i] / PYRAMID_SHAPES[level][i]
            assert translation[i] == approx((factor - 1) / 2), f"level {level} axis '{spec.name}' half-voxel offset"


def test_categorical_axes_are_never_downsampled():
    """A fractional coordinate between two channels is meaningless, so a channel axis must keep its extent."""
    bad_shape = [10, 1, 36, 1024, 1024]  # c halved from 2 to 1
    with pytest.raises(ValueError, match="must not be downsampled"):
        coords.pyramid_transform(PYRAMID_SHAPES[0], bad_shape, _AXIS_SPECS)


def test_continuous_axes_may_be_downsampled():
    """Time and frequency are continuous: a decimated dataset or a re-binned spectrogram is legitimate.

    Striding a long recording to every other sample is as meaningful as spatial
    downsampling, and the half-sample arithmetic is identical. Only *categorical*
    axes (channel and friends) are protected.
    """
    strided_time = [5, 2, 18, 512, 512]  # t 10 -> 5, spatial halved too
    scale, translation = coords.pyramid_transform(PYRAMID_SHAPES[0], strided_time, _AXIS_SPECS)
    assert scale[0] == approx(2.0)
    assert translation[0] == approx(0.5)

    # A (t, c) recording decimated by 4 along time: the shape every ephys pipeline produces.
    dataset_axes = [
        coords.AxisSpec(name="t", type=enums.AxisTypeChoices.TIME.value),
        coords.AxisSpec(name="c", type=enums.AxisTypeChoices.CHANNEL.value),
    ]
    scale, translation = coords.pyramid_transform([30000, 384], [7500, 384], dataset_axes)
    assert scale == [approx(4.0), approx(1.0)]
    assert translation == [approx(1.5), approx(0.0)], "sample 0 of the decimated dataset sits at the centre of raw samples 0..3"


def test_a_frequency_axis_is_continuous():
    """A frequency axis samples a spectrum, so it may be re-binned.

    This is what separates FREQUENCY from CHANNEL: a channel axis' coordinates index
    *electrodes*, so halfway between two of them is nothing, while halfway between 40 Hz
    and 42 Hz is 41 Hz.
    """
    spectrogram_axes = [
        coords.AxisSpec(name="f", type=enums.AxisTypeChoices.FREQUENCY.value),
        coords.AxisSpec(name="t", type=enums.AxisTypeChoices.TIME.value),
    ]
    scale, translation = coords.pyramid_transform([32, 64], [16, 64], spectrogram_axes)
    assert scale[0] == approx(2.0), "re-binning a frequency axis must be allowed"
    assert translation[0] == approx(0.5)


def test_a_frequency_axis_carries_an_inverse_time_unit():
    """A frequency is one over a time. A frequency axis calibrated in seconds is not a
    slightly-off calibration, it is a lie the arithmetic would happily propagate."""
    coords.assert_unit_matches_type("f", enums.AxisTypeChoices.FREQUENCY.value, "kilohertz")
    coords.assert_unit_matches_type("f", enums.AxisTypeChoices.FREQUENCY.value, "1/ms")

    with pytest.raises(coords.AxisUnitError, match=r"must measure 1 / \[time\]"):
        coords.assert_unit_matches_type("f", enums.AxisTypeChoices.FREQUENCY.value, "millisecond")


def test_a_time_axis_refuses_a_value_unit():
    """The unit of a dataset's *values* (mV, pA) is never an axis unit: an axis says where a sample is, not what it measured."""
    coords.assert_unit_matches_type("t", enums.AxisTypeChoices.TIME.value, "millisecond")

    with pytest.raises(coords.AxisUnitError, match=r"must measure \[time\]"):
        coords.assert_unit_matches_type("t", enums.AxisTypeChoices.TIME.value, "millivolt")


def test_half_voxel_convention():
    """The voxel centre is the origin: voxel n occupies [n - 0.5, n + 0.5)."""
    low, high = coords.vectors_bbox([[340.0, 10.0, 10.0]])
    assert low == [339.5, 9.5, 9.5]
    assert high == [340.5, 10.5, 10.5]

    # A single-voxel cube at the origin has its vertices at +-0.5.
    low, high = coords.vectors_bbox([[0.0, 0.0, 0.0]])
    assert low == [-0.5, -0.5, -0.5]
    assert high == [0.5, 0.5, 0.5]


def test_bbox_uses_every_corner():
    """An affine-transformed AABB is not an AABB.

    Under a rotation, pushing only the min and max corners through the matrix
    gives a box that is not merely different but strictly *too small* -- so
    geometry that really is inside it tests as outside, and gets culled.
    """
    # 45 degrees about z. The unit square's diagonal is what min/max misses.
    c = 0.7071067811865476
    rotation = [[c, -c, 0.0, 0.0], [c, c, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]
    edges = [(enums.TransformKindChoices.AFFINE.value, {"affine": rotation})]

    mins, maxs = [0.0, 0.0, 0.0], [1.0, 1.0, 0.0]
    full = coords.transformed_bbox(mins, maxs, edges)

    # What the two-corner shortcut would have produced.
    matrix = coords.compose(edges, 3)
    shortcut_corners = [coords.apply(matrix, mins), coords.apply(matrix, maxs)]
    shortcut_low, shortcut_high = coords.aabb(shortcut_corners)

    # The rotated square spans [-c, c] in x: the corners (0,1) and (1,0) swing out
    # to either side, and neither of them is a corner of the original box.
    assert full["min"][0] == approx(-c)
    assert full["max"][0] == approx(c)
    assert full["max"][1] == approx(2 * c)

    # The two-corner shortcut only ever sees (0,0) and (1,1), which the rotation
    # maps to (0,0) and (0, 2c) -- so it reports a box of ZERO width in x. The
    # true box is 2c wide. Nothing about that is ill-formed; it is simply wrong,
    # and it culls every object in the half of the box it dropped.
    assert shortcut_low[0] == approx(0.0) and shortcut_high[0] == approx(0.0)
    assert full["min"][0] < shortcut_low[0]
    assert full["max"][0] > shortcut_high[0]


def test_eight_corners_in_3d():
    """A 3D box has eight corners, and all eight are transformed."""
    assert len(coords.bbox_corners([0.0, 0.0, 0.0], [1.0, 1.0, 1.0])) == 8


# --- 4. the lens edge -------------------------------------------------------


def test_lens_to_parent_is_a_translation_of_the_slice_starts():
    """A crop shifts voxel coordinates, and the edge must record the shift.

    Without it, an ROI drawn on a cropped lens has no defined path back to its
    dataset. That was a live correctness hole, not a hypothetical one.
    """
    slices = [coords.AxisSpec(name="z", type="SPACE")]  # placeholder, replaced below

    class _Slice:
        def __init__(self, axis, start=None, stop=None, step=None):
            self.axis, self.start, self.stop, self.step = axis, start, stop, step

    slices = [_Slice("z", start=4, stop=32)]
    kind, params = coords.lens_to_parent(["t", "c", "z", "y", "x"], slices)

    assert kind == enums.TransformKindChoices.TRANSLATION.value
    assert params["translation"] == [0.0, 0.0, 4.0, 0.0, 0.0]


def test_stepped_lens_rescales_as_well_as_offsets():
    """A stepped lens is a SEQUENCE, not a bare translation.

    A translation-only edge would mis-place every subsampled lens by a factor of
    the step -- silently, since nothing about it is ill-formed.
    """

    class _Slice:
        def __init__(self, axis, start=None, stop=None, step=None):
            self.axis, self.start, self.stop, self.step = axis, start, stop, step

    kind, params = coords.lens_to_parent(["z", "y", "x"], [_Slice("x", start=10, step=2)])

    assert kind == enums.TransformKindChoices.SEQUENCE.value
    assert params["scale"] == [1.0, 1.0, 2.0]
    assert params["translation"] == [0.0, 0.0, 10.0]


def test_lens_roundtrip():
    """A point in lens space, pushed to the parent and back, is where it started."""

    class _Slice:
        def __init__(self, axis, start=None, stop=None, step=None):
            self.axis, self.start, self.stop, self.step = axis, start, stop, step

    dims = ["z", "y", "x"]
    kind, params = coords.lens_to_parent(dims, [_Slice("z", start=4), _Slice("x", start=7)])

    forward = coords.compose([(kind, params)], 3)
    point = [3.0, 5.0, 2.0]
    in_parent = coords.apply(forward, point)

    assert in_parent == [7.0, 5.0, 9.0]

    # Invert by hand (a translation's inverse is its negation) and come back.
    inverse = coords.to_matrix(
        enums.TransformKindChoices.TRANSLATION.value,
        {"translation": [-value for value in params["translation"]]},
        3,
    )
    assert coords.apply(inverse, in_parent) == approx(point)


def test_lens_shape_follows_python_slice_semantics():
    """The lens' shape is derived, so it cannot drift from the slices that define it."""

    class _Slice:
        def __init__(self, axis, start=None, stop=None, step=None):
            self.axis, self.start, self.stop, self.step = axis, start, stop, step

    shape = coords.lens_shape([36, 1024, 1024], ["z", "y", "x"], [_Slice("z", start=4, stop=32), _Slice("x", step=2)])
    assert shape == [28, 1024, 512]




# --- 8. inverting a step, and condensing a path -------------------------------
#
# A placement path hands back `(edge, inverted)` pairs, and until now undoing the flagged
# ones was left entirely to the client -- so `Layer.asAffine` is the first thing here that
# has to invert a map at all. These pin the arithmetic against the forward composition it
# has to undo, because "obviously the inverse" is exactly how a sign or a transpose survives
# a review.


def _flat(matrix) -> list[float]:
    """One flat list, because `pytest.approx` refuses a nested one."""
    return [value for row in matrix for value in row]


def _apply_forms(forms: dict[str, coords.AxedForm], axes, point) -> dict[str, float]:
    """Push a point through composed functionals, one output axis at a time."""
    return {axis: sum(factor * value for factor, value in zip(form.coefficients, point)) + form.constant for axis, form in forms.items()}


def test_invert_matrix_is_the_inverse():
    """Round-tripped against `matmul`, not eyeballed: A @ A-1 must be the identity."""
    matrix = [
        [2.0, 0.5, 0.0, 3.0],
        [0.0, 4.0, 0.0, -1.0],
        [0.0, 0.0, 0.25, 7.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    product = coords.matmul(matrix, coords.invert_matrix(matrix))
    assert _flat(product) == approx(_flat(coords.identity_matrix(3)), abs=1e-9)


def test_invert_matrix_pivots_rather_than_failing_on_a_zero_diagonal():
    """An axis swap has zeros down its diagonal and is perfectly invertible.

    Without partial pivoting this raises `SingularTransformError` for a matrix that is not
    remotely singular -- and a y/x swap is an ordinary registration, not a corner case.
    """
    swap = [
        [0.0, 1.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    assert _flat(coords.invert_matrix(swap)) == approx(_flat(swap), abs=1e-12)


def test_a_singular_matrix_refuses_to_invert():
    """A projection written as a matrix: rank-deficient, and no determinant-free gate sees it."""
    projection = [
        [1.0, 1.0, 0.0],
        [2.0, 2.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    assert coords.is_singular([row[:-1] for row in projection[:-1]])
    with pytest.raises(coords.SingularTransformError):
        coords.invert_matrix(projection)


def test_singularity_is_judged_relative_to_the_matrix_own_scale():
    """A map stated in nanometres is small, not singular; a collapsed one is singular at any size.

    An absolute threshold gets both of these wrong, and in opposite directions -- and so does
    a determinant, which is why `is_singular` asks the elimination instead: the determinant
    of the first matrix here is 1e-14, which no fixed threshold can tell from a collapse.
    """
    tiny = [[1e-7, 0.0], [0.0, 1e-7]]
    assert not coords.is_singular(tiny), "a genuinely invertible map with small entries is not singular"

    huge_and_collapsed = [[1e7, 1e7], [1e7, 1e7]]
    assert coords.is_singular(huge_and_collapsed), "a collapsed map is singular however large its entries"

    # And the case a determinant gets exactly backwards: determinant 1.0, and still not a map
    # anything can invert -- fourteen orders of magnitude between the axes leaves float64 no
    # digits to answer with. Refusing it is the honest answer, not a conservative one.
    unusable = [[1e7, 0.0], [0.0, 1e-7]]
    assert coords.is_singular(unusable), "a determinant of 1.0 does not make a matrix usable"


@pytest.mark.parametrize(
    "step",
    [
        coords.AxedStep(kind=enums.TransformKindChoices.IDENTITY.value, params={}, input_axes=("y", "x"), output_axes=("y", "x")),
        coords.AxedStep(kind=enums.TransformKindChoices.TRANSLATION.value, params={"translation": [10.0, -4.0]}, input_axes=("y", "x"), output_axes=("y", "x")),
        coords.AxedStep(kind=enums.TransformKindChoices.SCALE.value, params={"scale": [0.5, 4.0]}, input_axes=("y", "x"), output_axes=("y", "x")),
        coords.AxedStep(kind=enums.TransformKindChoices.AFFINE.value, params={"affine": [[0.0, 1.0, 5.0], [1.0, 0.0, -2.0]]}, input_axes=("y", "x"), output_axes=("y", "x")),
        coords.AxedStep(
            kind=enums.TransformKindChoices.SEQUENCE.value,
            params={},
            input_axes=("y", "x"),
            output_axes=("y", "x"),
            children=((enums.TransformKindChoices.SCALE.value, {"scale": [2.0, 2.0]}), (enums.TransformKindChoices.TRANSLATION.value, {"translation": [0.5, 0.5]})),
        ),
        coords.AxedStep(
            kind=enums.TransformKindChoices.MAP_AXIS.value,
            params={},
            input_axes=("y", "x"),
            output_axes=("y", "x"),
            acts_on_input=("y", "x"),
            acts_on_output=("x", "y"),
        ),
        coords.AxedStep(
            kind=enums.TransformKindChoices.BY_DIMENSION.value,
            params={"scale": [2.0, 3.0], "translation": [1.0, -1.0]},
            input_axes=("y", "x"),
            output_axes=("y", "x"),
            acts_on_input=("y", "x"),
            acts_on_output=("y", "x"),
        ),
        # The `affine` branch of `_params_matrix`, which sizes its matrix at
        # `max(rank_in, rank_out)` -- equal here only because `assert_edge_rank` maps a
        # BY_DIMENSION's named axes one for one, so the inverse's row count rests on a
        # guarantee held in another module. Rotated, so a transposed inverse is visible.
        coords.AxedStep(
            kind=enums.TransformKindChoices.BY_DIMENSION.value,
            params={"affine": [[0.0, -2.0, 3.0], [0.5, 0.0, -1.0]]},
            input_axes=("y", "x"),
            output_axes=("y", "x"),
            acts_on_input=("y", "x"),
            acts_on_output=("y", "x"),
        ),
    ],
    ids=["identity", "translation", "scale", "affine", "sequence", "map_axis", "by_dimension", "by_dimension_affine"],
)
def test_inverting_a_step_undoes_it(step: coords.AxedStep):
    """Every invertible kind: forward then back is the identity on a point, not merely on paper.

    Checked by pushing a point through both, because that is what a client does with the
    answer -- a matrix that is right up to a transpose passes every structural assertion and
    still puts the data in the wrong place.
    """
    point = [7.0, -3.0]
    forward = coords.compose_forms([step], list(step.input_axes))
    moved = _apply_forms(forward, step.input_axes, point)

    inverse = coords.invert_step(step)
    back = coords.compose_forms([inverse], list(inverse.input_axes))
    returned = _apply_forms(back, inverse.input_axes, [moved[axis] for axis in inverse.input_axes])

    assert [returned[axis] for axis in step.input_axes] == approx(point, abs=1e-9)


@pytest.mark.parametrize("kind", [enums.TransformKindChoices.FIELD.value, enums.TransformKindChoices.UNMAPPABLE.value])
def test_the_kinds_with_no_inverse_refuse_to_be_inverted(kind: str):
    """Unreachable through the walk -- `is_reverse_traversable` excludes both -- and guarded anyway."""
    step = coords.AxedStep(kind=kind, params={}, input_axes=("y", "x"), output_axes=("y", "x"))
    with pytest.raises(coords.NonAffineTransformError):
        coords.invert_step(step)


def test_a_sequence_composes_its_children_rather_than_its_own_empty_params():
    """A SEQUENCE wrapper's map lives on its children, and reading `params` gets the identity.

    `graph._sequence` writes the scale on child 0 and the translation on child 1, leaving the
    wrapper's own `params` empty -- so `to_matrix(SEQUENCE, {}, rank)` finds neither key and
    returns the identity, silently. Every stepped lens and every offset pyramid level is such
    an edge, so this is the first hop to world of an ordinary multiscale layer: composing it
    as an identity drops the crop and the subsample without a word.
    """
    step = coords.AxedStep(
        kind=enums.TransformKindChoices.SEQUENCE.value,
        params={},
        input_axes=("y", "x"),
        output_axes=("y", "x"),
        children=((enums.TransformKindChoices.SCALE.value, {"scale": [2.0, 2.0]}), (enums.TransformKindChoices.TRANSLATION.value, {"translation": [0.5, 0.5]})),
    )
    forms = coords.compose_forms([step], ["y", "x"])
    assert _apply_forms(forms, ("y", "x"), [10.0, 20.0]) == approx({"y": 20.5, "x": 40.5})


def test_a_rank_changing_affine_composes_from_its_own_rows():
    """An AFFINE's rows *are* its output axes, so it states a rank change without BY_DIMENSION.

    `assert_edge_rank` admits M x (N+1) between spaces of different rank deliberately -- "an
    ordinary authored edge" -- but the composer used to route every non-BY_DIMENSION kind
    through `to_matrix`, which builds one square matrix at the *input* rank. A 3 x 3 affine
    out of a 2-axis space then either lost rows or ran off the end of that matrix, so an
    edge the write path accepts could not be read back.
    """
    step = coords.AxedStep(
        kind=enums.TransformKindChoices.AFFINE.value,
        # (y, x) -> (z, y, x): z is a real slope off y, not a zero row.
        params={"affine": [[0.25, 0.0, 3.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]},
        input_axes=("y", "x"),
        output_axes=("z", "y", "x"),
    )
    forms = coords.compose_forms([step], ["y", "x"])
    assert sorted(forms) == ["x", "y", "z"], "every output axis the matrix has a row for is constrained"
    assert _apply_forms(forms, ("y", "x"), [8.0, 5.0]) == approx({"z": 5.0, "y": 8.0, "x": 5.0})


def test_forms_to_matrix_gives_no_row_to_an_axis_the_path_says_nothing_about():
    """A partial registration is a partial matrix, never a zero-filled full-rank one.

    A zero row would pin the data at that axis' origin -- a claim nobody made -- and cull it
    out of every other slice. The row is simply absent, exactly as `AxisExtent` gives an
    unconstrained axis no entry.
    """
    step = coords.AxedStep(
        kind=enums.TransformKindChoices.BY_DIMENSION.value,
        params={"scale": [2.0, 2.0]},
        input_axes=("c", "y", "x"),
        output_axes=("t", "z", "y", "x"),
        acts_on_input=("y", "x"),
        acts_on_output=("y", "x"),
    )
    forms = coords.compose_forms([step], ["c", "y", "x"])
    matrix, rows = coords.forms_to_matrix(forms, ["t", "z", "y", "x"])

    assert rows == ["y", "x"], "the world's t and z are untouched by this registration, so they get no row"
    # Columns are the source axes (c, y, x), plus the translation column.
    assert _flat(matrix) == approx(_flat([[0.0, 2.0, 0.0, 0.0], [0.0, 0.0, 2.0, 0.0]]))





def test_an_identity_between_two_units_is_not_a_claim_that_they_are_equal():
    """An IDENTITY between a nanometre axis and a micrometre one used to say 1 nm = 1 um.

    The two spaces are the same space said twice, which is what an IDENTITY means -- so the
    *number* has to change when the unit does. It composed as coefficient 1.0 in both
    directions, and every extent, `asAffine` and `inView` answer downstream was 1000x out with
    nothing raising, because there is no error to raise on: both rows are individually
    well-formed. Proposals item 15, D1.
    """
    step = coords.AxedStep(
        kind=enums.TransformKindChoices.IDENTITY.value,
        params={},
        input_axes=("y", "x"),
        output_axes=("y", "x"),
        input_units=("nanometer", "nanometer"),
        output_units=("micrometer", "micrometer"),
    )
    forms = coords.step_forms(step)
    assert forms["y"].coefficients == approx((0.001, 0.0))
    assert forms["x"].coefficients == approx((0.0, 0.001))


def test_the_same_unit_on_both_sides_changes_nothing():
    """The whole safety argument for shipping the conversion: where the units agree -- or
    where either side has none, which is every stored edge in the deployment today -- the
    factor is exactly 1.0 and the answer is the one composed before there were units here."""
    for units in (("micrometer", "micrometer"), (None, "micrometer"), ("micrometer", None), (None, None)):
        step = coords.AxedStep(
            kind=enums.TransformKindChoices.IDENTITY.value,
            params={},
            input_axes=("x",),
            output_axes=("x",),
            input_units=(units[0],),
            output_units=(units[1],),
        )
        assert coords.step_forms(step)["x"].coefficients == approx((1.0,)), units


def test_a_by_dimension_converts_the_axes_it_passes_through_and_not_the_ones_it_maps():
    """The scope, stated as a test: a pass-through is a unit pair, a stated number is not.

    `z` is not named, so it passes through and its unit pair is the whole of what relates the
    two sides. `y` and `x` *are* named, and their scale is the author's own statement about
    two spaces they already knew the units of -- converting it too would double-count exactly
    the author who folded the factor in correctly, and nothing in the row says which kind of
    author wrote it.
    """
    step = coords.AxedStep(
        kind=enums.TransformKindChoices.BY_DIMENSION.value,
        params={"scale": [2.0, 2.0]},
        input_axes=("z", "y", "x"),
        output_axes=("z", "y", "x"),
        input_units=("nanometer", "nanometer", "nanometer"),
        output_units=("micrometer", "micrometer", "micrometer"),
        acts_on_input=("y", "x"),
        acts_on_output=("y", "x"),
    )
    forms = coords.step_forms(step)
    assert forms["z"].coefficients == approx((0.001, 0.0, 0.0)), "the unnamed axis converts"
    assert forms["y"].coefficients == approx((0.0, 2.0, 0.0)), "the named axis keeps the author's number"


def test_two_units_with_no_conversion_between_them_leave_the_axis_unplaced():
    """A nanosecond axis facing a micrometre one is not a pass-through, and there is no number
    that makes it one. Absent, not one -- the same rule as `_by_dimension_forms`' "absent is
    not zero", and for the same reason: a wrong number places the data somewhere, and a
    missing form leaves it unconstrained, which is the truth."""
    step = coords.AxedStep(
        kind=enums.TransformKindChoices.IDENTITY.value,
        params={},
        input_axes=("t", "x"),
        output_axes=("t", "x"),
        input_units=("nanosecond", "micrometer"),
        output_units=("micrometer", "micrometer"),
    )
    forms = coords.step_forms(step)
    assert "t" not in forms, "an impossible conversion must not be given a number"
    assert forms["x"].coefficients == approx((0.0, 1.0)), "its neighbour is unaffected"


def test_an_inverted_step_converts_the_other_way():
    """`invert_step` swaps the axes; the units have to swap with them or the reciprocal is
    never taken and a round trip comes back 1000000x out."""
    step = coords.AxedStep(
        kind=enums.TransformKindChoices.IDENTITY.value,
        params={},
        input_axes=("x",),
        output_axes=("x",),
        input_units=("nanometer",),
        output_units=("micrometer",),
    )
    assert coords.step_forms(coords.invert_step(step))["x"].coefficients == approx((1000.0,))


def test_an_arbitrary_unit_declines_the_claim_rather_than_conflicting_with_it():
    """"a.u." means *no* calibration claim, and `assert_unit_matches_type` already reads it that
    way -- it short-circuits and checks nothing. Reading it as an incompatible dimension here
    would make one function treat the same string as "no claim" and the next as "these axes
    cannot be related", and would leave merely-uncalibrated data unplaced.

    `dimensionless` is deliberately on the other side of that line: a real pint unit and a real
    claim, with genuinely no conversion to a micrometre."""
    def factor(source, target):
        step = coords.AxedStep(
            kind=enums.TransformKindChoices.IDENTITY.value,
            params={},
            input_axes=("x",),
            output_axes=("x",),
            input_units=(source,),
            output_units=(target,),
        )
        return coords.step_forms(step).get("x")

    assert factor("a.u.", "micrometer").coefficients == approx((1.0,))
    assert factor("micrometer", "a.u.").coefficients == approx((1.0,))
    assert factor("dimensionless", "micrometer") is None, "a real unit with no conversion stays absent"
