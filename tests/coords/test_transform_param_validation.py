"""The transform input union: the member is the kind, and nothing rides along.

Ported from mikro's ``tests/test_transform_param_validation.py`` and reseeded onto datasets.
The write-time gates on an edge are vendored code, and until this file nothing in this
service exercised them: a port that dropped one would have shipped silently.

An authored edge arrives as the flat ``TransformInput`` -- a ``kind`` plus the union of
every kind's parameter fields -- and is matched to a strict per-kind member model that
forbids what is not its own. So a parameter that contradicts the kind (a `translation`
on a SCALE edge, a `reason` on anything but UNMAPPABLE, axis names on a kind that acts
on every axis) is an **error naming both**, where it used to be silently dropped -- and
in the axes case silently *wrong*, because stored axis names override what
``edge_axis_names`` reports as the parameter ordering.

The same contract holds at every altitude: the parse layer for the API, and the
logic-layer writers (`build_registration_edge`, `write_relation_edge`) for callers below
it -- the tests here pin both, so removing either gate makes something fail. The member
inputs published under ``@unionElementOf`` are codegen's copy of the same truth.

The fixtures keep mikro's (y, x) grids: the arithmetic is generic over axis types, and a
square two-axis case is what tells the rank rules from the singularity rules.
"""

import datetime

import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import enums, models
from core.input_unions import parse_union_member
from core.inputs.coords import TRANSFORM_MEMBERS, FieldTransformInputModel, MapAxisTransformInputModel
from core.logic import graph as graph_logic
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_TRANSFORM = """
mutation Create($input: CreateTransformationInput!) {
  createTransformation(input: $input) { id kind inputAxes outputAxes }
}
"""

UPDATE_TRANSFORM = """
mutation Update($input: UpdateTransformationInput!) {
  updateTransformation(input: $input) { id version }
}
"""

CREATE_CS = """
mutation CreateCS($input: CreateCoordinateSystemInput!) {
  createCoordinateSystem(input: $input) { id }
}
"""

WORLD_AXES = [
    {"name": "y", "type": "SPACE", "unit": "micrometer"},
    {"name": "x", "type": "SPACE", "unit": "micrometer"},
]


async def _yx_dataset(ctx: HttpContext, name: str = "ArrayDataset") -> models.ArrayDataset:
    """A (y, x) dataset: mikro's 64x64 image, which is all these rules need of their input."""
    return await seed.create_dataset(ctx, name, seed.YX_AXES, [64, 64])


async def _world(aexecute, name: str, axes: list[dict]) -> str:  # noqa: ANN001 - the conftest fixture
    """A space of the given axes, with nothing registered into it."""
    result = await aexecute(CREATE_CS, {"input": {"name": name, "axes": axes, "registrations": []}})
    assert not result.errors, result.errors
    return str(result.data["createCoordinateSystem"]["id"])


async def _space_world(aexecute, name: str, axes=("z", "y", "x")) -> str:  # noqa: ANN001
    """A world of the named SPACE axes, with nothing registered into it."""
    return await _world(aexecute, name, [{"name": n, "type": "SPACE", "unit": "micrometer"} for n in axes])


async def _dataset_and_world(aexecute, ctx: HttpContext) -> tuple[str, str]:  # noqa: ANN001
    """A y/x dataset's sample grid, and a y/x world with nothing registered into it."""
    dataset = await _yx_dataset(ctx)
    return str(dataset.coordinate_system_id), await _world(aexecute, "World", WORLD_AXES)


async def _create(aexecute, input_id: str, output_id: str, transform: dict):  # noqa: ANN001, ANN202
    return await aexecute(CREATE_TRANSFORM, {"input": {"input": input_id, "output": output_id, "transform": transform}})


async def _update(aexecute, edge_id: str, **params):  # noqa: ANN001, ANN202
    return await aexecute(UPDATE_TRANSFORM, {"input": {"id": edge_id, **params}})


# --- the parse layer: a parameter that is not the kind's own ------------------------------------


@pytest.mark.parametrize(
    ("transform", "phrase"),
    [
        # A parameter of some other member: named, not dropped.
        ({"kind": "SCALE", "scale": [1.0, 1.0], "translation": [1.0, 1.0]}, "A SCALE transformation does not read `translation`"),
        ({"kind": "SCALE", "scale": [1.0, 1.0], "affine": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]}, "A SCALE transformation does not read `affine`"),
        ({"kind": "TRANSLATION", "translation": [1.0, 1.0], "scale": [2.0, 2.0]}, "A TRANSLATION transformation does not read `scale`"),
        ({"kind": "AFFINE", "affine": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "scale": [2.0, 2.0]}, "An AFFINE transformation does not read `scale`"),
        ({"kind": "ROTATION", "affine": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "translation": [1.0, 1.0]}, "A ROTATION transformation does not read `translation`"),
        ({"kind": "MAP_AXIS", "inputAxes": ["y", "x"], "outputAxes": ["x", "y"], "scale": [1.0, 1.0]}, "A MAP_AXIS transformation does not read `scale`"),
        # IDENTITY reads nothing at all.
        ({"kind": "IDENTITY", "scale": [1.0, 1.0]}, "takes no parameters at all"),
        # Axis names on a kind that acts on every axis: the silently-wrong case.
        ({"kind": "SCALE", "scale": [1.0, 1.0], "inputAxes": ["y", "x"]}, "A SCALE transformation does not read `inputAxes`"),
        ({"kind": "AFFINE", "affine": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "outputAxes": ["y", "x"]}, "An AFFINE transformation does not read `outputAxes`"),
        # `reason` belongs to UNMAPPABLE, `field` to FIELD.
        ({"kind": "SCALE", "scale": [1.0, 1.0], "reason": "because"}, "A SCALE transformation does not read `reason`"),
        ({"kind": "UNMAPPABLE", "scale": [1.0, 1.0]}, "An UNMAPPABLE transformation does not read `scale`"),
        # Missing the one parameter the kind requires.
        ({"kind": "SCALE"}, "A SCALE transformation requires `scale`"),
        ({"kind": "AFFINE"}, "An AFFINE transformation requires `affine`"),
        ({"kind": "ROTATION"}, "A ROTATION transformation requires `affine`"),
        ({"kind": "FIELD", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"]}, "A FIELD transformation requires `field`"),
        ({"kind": "MAP_AXIS", "inputAxes": ["y", "x"]}, "A MAP_AXIS transformation requires `outputAxes`"),
        ({"kind": "BY_DIMENSION", "outputAxes": ["y"]}, "A BY_DIMENSION transformation requires `inputAxes`"),
    ],
)
async def test_a_parameter_that_contradicts_the_kind_is_an_error_not_a_drop(aexecute, authenticated_context, transform: dict, phrase: str):
    """Every mismatch is named after both the kind and the field, and nothing is written."""
    grid, world = await _dataset_and_world(aexecute, authenticated_context)
    before = await models.Transformation.objects.acount()

    result = await _create(aexecute, grid, world, transform)

    assert result.errors, f"expected an error for {transform}"
    assert phrase in str(result.errors[0]), str(result.errors[0])
    assert await models.Transformation.objects.acount() == before, "a refused edge must write nothing"


@pytest.mark.parametrize(
    ("transform", "phrase"),
    [
        # A zero factor collapses its axis onto a point. `_scale_invariance` classifies a
        # scale by whether its entries are *equal*, so [0, 0] used to be reported as a
        # SIMILARITY -- angles and length ratios preserved -- for a map that preserves
        # nothing, and `is_invertible` is kind-only, so the client was then handed an
        # `inverted: true` step it could not honour.
        ({"kind": "SCALE", "scale": [0.0, 1.0]}, "no factor may be zero"),
        ({"kind": "SCALE", "scale": [0.0, 0.0]}, "no factor may be zero"),
        ({"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"], "scale": [1.0, 0.0]}, "no factor may be zero"),
        # A row whose linear part is all zeros sends every input to one value. The last
        # column is the translation and is excluded: an offset does not un-collapse a row.
        ({"kind": "AFFINE", "affine": [[0.0, 0.0, 5.0], [0.0, 1.0, 0.0]]}, "no row's linear part may be all zeros"),
        ({"kind": "ROTATION", "affine": [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]]}, "no row's linear part may be all zeros"),
    ],
)
async def test_a_map_that_collapses_an_axis_is_refused(aexecute, authenticated_context, transform: dict, phrase: str):
    """The value rules, at the API altitude. Only a collapse -- never a merely odd number."""
    grid, world = await _dataset_and_world(aexecute, authenticated_context)
    before = await models.Transformation.objects.acount()

    result = await _create(aexecute, grid, world, transform)

    assert result.errors, f"expected an error for {transform}"
    assert phrase in str(result.errors[0]), str(result.errors[0])
    assert await models.Transformation.objects.acount() == before, "a refused edge must write nothing"


async def test_a_refinement_cannot_collapse_an_axis_either(aexecute, authenticated_context):
    """`updateTransformation` gates values exactly as creation does, and nearly did not.

    It is the one write that reaches neither gate on its own: its parameters arrive flat --
    there is no `TransformInput`, so the union members' validators never run -- and it
    assembles its params dict by hand rather than through `_assemble_edge_params`. Refining
    a good SCALE edge to `[0, 0]` was the way left to store a collapsing map.
    """
    grid, world = await _dataset_and_world(aexecute, authenticated_context)

    result = await _create(aexecute, grid, world, {"kind": "SCALE", "scale": [0.5, 0.5]})
    assert not result.errors, result.errors
    edge_id = result.data["createTransformation"]["id"]

    result = await _update(aexecute, edge_id, scale=[0.0, 0.5])
    assert result.errors and "no factor may be zero" in str(result.errors[0]), str(result.errors and result.errors[0])

    edge = await models.Transformation.objects.aget(pk=edge_id)
    assert edge.params == {"scale": [0.5, 0.5]}, "a refused refinement writes nothing"
    assert await edge.provenance_entries.acount() == 1, "and leaves no history row behind either"


async def test_a_mirrored_axis_and_an_offset_of_zero_are_left_alone(aexecute, authenticated_context):
    """The boundary of the rule above: a negative factor is a flip, and zero is an offset.

    A sign flip cannot produce a stored `min > max` -- `form_interval` takes min/max per
    term and `transformed_bbox` enumerates every corner -- so there is nothing to protect
    against, and refusing it would refuse a real acquisition geometry.
    """
    grid, world = await _dataset_and_world(aexecute, authenticated_context)

    result = await _create(aexecute, grid, world, {"kind": "SCALE", "scale": [-1.0, 1.0]})
    assert not result.errors, result.errors

    result = await _create(aexecute, grid, world, {"kind": "TRANSLATION", "translation": [0.0, 0.0]})
    assert not result.errors, result.errors


async def test_a_per_axis_edge_cannot_cross_a_rank_boundary(aexecute, authenticated_context):
    """A scale carries one number per input axis, so its matrix is square at that rank.

    Only the *input* rank was checked, so a two-entry scale from a (y,x) grid into a
    four-axis world was written without complaint -- and surfaced nowhere near its author:
    `to_matrix` raises `NonAffineTransformError`, which the extent walk swallows into
    `ExtentState.NON_AFFINE`, leaving the source unboundable in every spatial query over
    that space forever.

    An AFFINE is deliberately *not* held to this: its matrix is M x (N+1) and rectangular
    by design, which is exactly how a rank-crossing edge is written.
    """
    dataset = await _yx_dataset(authenticated_context)
    grid = str(dataset.coordinate_system_id)
    world = await _world(aexecute, "Big", [{"name": "t", "type": "TIME", "unit": "second"}, {"name": "z", "type": "SPACE", "unit": "micrometer"}, *WORLD_AXES])

    result = await _create(aexecute, grid, world, {"kind": "SCALE", "scale": [0.1, 0.1]})
    assert result.errors and "relates spaces of equal rank" in str(result.errors[0]), str(result.errors and result.errors[0])

    # The same pair, said the way the model provides for: name the axes it acts on.
    result = await _create(aexecute, grid, world, {"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"], "scale": [0.1, 0.1]})
    assert not result.errors, result.errors

    # And a whole matrix crosses ranks unbothered: 4 rows out, 2+1 columns in.
    result = await _create(aexecute, grid, world, {"kind": "AFFINE", "affine": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]})
    assert result.errors and "all zeros" in str(result.errors[0]), "the zero rows are caught, not the rank"


async def test_a_scale_edge_also_gets_a_field_named_as_not_its_own(aexecute, authenticated_context):
    """`field` is the FIELD member's alone; on any other kind it is a named stray."""
    grid, world = await _dataset_and_world(aexecute, authenticated_context)
    result = await _create(aexecute, grid, world, {"kind": "SCALE", "scale": [1.0, 1.0], "field": world})
    assert result.errors and "A SCALE transformation does not read `field`" in str(result.errors[0]), str(result.errors and result.errors[0])


async def test_wrapper_kinds_are_not_in_the_creatable_enum(aexecute, authenticated_context):
    """SEQUENCE is unrepresentable in TransformInput, not merely refused.

    The ingest builds it together with its children; a client naming it gets an enum coercion
    error before any resolver runs. The logic-layer gate for internal callers is pinned
    separately below.
    """
    grid, world = await _dataset_and_world(aexecute, authenticated_context)
    result = await _create(aexecute, grid, world, {"kind": "SEQUENCE"})
    assert result.errors, "SEQUENCE must not be creatable"
    assert "CreatableTransformKind" in str(result.errors[0]), str(result.errors[0])


async def test_a_registration_entry_is_validated_like_a_transformation(aexecute, authenticated_context):
    """`registrations` lowers through the same union, so the same strays are refused."""
    dataset = await _yx_dataset(authenticated_context)

    result = await aexecute(
        CREATE_CS,
        {"input": {"name": "World", "axes": WORLD_AXES, "registrations": [{"dataset": str(dataset.pk), "transform": {"kind": "SCALE", "scale": [1.0, 1.0], "translation": [2.0, 2.0]}}]}},
    )
    assert result.errors and "A SCALE transformation does not read `translation`" in str(result.errors[0]), str(result.errors and result.errors[0])
    assert not await models.CoordinateSystem.objects.filter(name="World").aexists(), "a refused registration must roll the space back with it"


async def test_an_omitted_transform_registers_an_identity(aexecute, authenticated_context):
    """Omitting `transform` on a registration entry means IDENTITY, as the docs promise."""
    dataset = await _yx_dataset(authenticated_context)

    result = await aexecute(CREATE_CS, {"input": {"name": "World", "axes": WORLD_AXES, "registrations": [{"dataset": str(dataset.pk)}]}})
    assert not result.errors, result.errors

    edge = await models.Transformation.objects.aget(input_id=dataset.coordinate_system_id, output_id=result.data["createCoordinateSystem"]["id"])
    assert edge.kind == enums.TransformKindChoices.IDENTITY.value
    assert edge.params == {}


async def test_each_member_persists_exactly_its_own_shape(aexecute, authenticated_context):
    """The row holds what the kind reads: params for the metric kinds, axes only for the axis kinds."""
    grid, world = await _dataset_and_world(aexecute, authenticated_context)

    result = await _create(aexecute, grid, world, {"kind": "SCALE", "scale": [0.5, 0.5]})
    assert not result.errors, result.errors
    edge = await models.Transformation.objects.aget(pk=result.data["createTransformation"]["id"])
    assert edge.params == {"scale": [0.5, 0.5]}
    assert edge.input_axes is None and edge.output_axes is None, "a metric edge stores no axis names: stored names would override the systems' ordering"

    result = await _create(aexecute, world, world, {"kind": "MAP_AXIS", "inputAxes": ["y", "x"], "outputAxes": ["x", "y"]})
    assert not result.errors, result.errors
    edge = await models.Transformation.objects.aget(pk=result.data["createTransformation"]["id"])
    assert edge.params == {} and edge.input_axes == ["y", "x"] and edge.output_axes == ["x", "y"]

    result = await _create(aexecute, grid, world, {"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"], "affine": [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0]]})
    assert not result.errors, result.errors
    edge = await models.Transformation.objects.aget(pk=result.data["createTransformation"]["id"])
    assert edge.params == {"affine": [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0]]}, "a BY_DIMENSION's optional matrix rides in params"

    result = await _create(aexecute, grid, world, {"kind": "UNMAPPABLE", "reason": "one row per object"})
    assert not result.errors, result.errors
    edge = await models.Transformation.objects.aget(pk=result.data["createTransformation"]["id"])
    assert edge.params == {"reason": "one row per object"} and edge.input_axes is None


# --- refinement: the one write with no union in front of it -------------------------------------


async def test_a_refinement_must_match_the_edges_kind(aexecute, authenticated_context):
    """`updateTransformation` gates parameters exactly as creation does.

    Before this gate a stray `affine` merged onto any edge was stored, never read by
    `to_matrix` -- and on a childless composite it demoted the reported invariance,
    because `invariance_of` classifies those by params keys.
    """
    grid, world = await _dataset_and_world(aexecute, authenticated_context)
    result = await _create(aexecute, grid, world, {"kind": "SCALE", "scale": [0.5, 0.5]})
    assert not result.errors, result.errors
    edge_id = result.data["createTransformation"]["id"]

    result = await _update(aexecute, edge_id, translation=[1.0, 1.0])
    assert result.errors and "A SCALE transformation does not read `translation`" in str(result.errors[0]), str(result.errors and result.errors[0])
    assert "refining it would write a number nothing reads" in str(result.errors[0])

    result = await _update(aexecute, edge_id, scale=[0.51, 0.51])
    assert not result.errors, result.errors
    edge = await models.Transformation.objects.aget(pk=edge_id)
    assert edge.params == {"scale": [0.51, 0.51]}
    assert await edge.provenance_entries.acount() == 2, "the refused refinement leaves no history row; the accepted one does -- creation plus one refinement"


def _build_sequence(ctx: HttpContext, grid: str, world: str) -> models.Transformation:
    """A SEQUENCE wrapper (scale, then translation) between two spaces, as the ingest builds one."""
    return graph_logic._sequence(
        input_system=models.CoordinateSystem.objects.get(pk=grid),
        output_system=models.CoordinateSystem.objects.get(pk=world),
        scale=[2.0, 2.0],
        translation=[0.5, 0.5],
        ctx=seed._creation(ctx),
    )


async def test_a_wrapper_refuses_refinement_toward_its_children(aexecute, authenticated_context):
    """A SEQUENCE's parameters live on its children, and the update mutation says so."""
    grid, world = await _dataset_and_world(aexecute, authenticated_context)
    wrapper = await sync_to_async(_build_sequence)(authenticated_context, grid, world)

    result = await _update(aexecute, str(wrapper.pk), scale=[1.0, 1.0])
    assert result.errors and "its parameters live on its children" in str(result.errors[0]), str(result.errors and result.errors[0])


@pytest.mark.parametrize(
    ("transform", "phrase"),
    [
        # Rank-deficient with no zero row anywhere: `assert_no_collapsed_rows` cannot see
        # it, and `is_invertible` is kind-only -- so this edge used to be written, offered
        # for backwards traversal, and handed to a client as an `inverted: true` step it
        # could not honour. `is_invertible`'s own docstring named it as uncaught.
        ({"kind": "AFFINE", "affine": [[1.0, 1.0, 0.0], [2.0, 2.0, 0.0]]}, "is singular"),
        ({"kind": "ROTATION", "affine": [[1.0, 1.0, 0.0], [1.0, 1.0, 0.0]]}, "is singular"),
        # The case most worth catching: a BY_DIMENSION maps its named axes one for one, so
        # its matrix is always square and a childless one is invertible *by kind*.
        ({"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"], "affine": [[1.0, 1.0, 0.0], [2.0, 2.0, 0.0]]}, "is singular"),
    ],
)
async def test_a_singular_map_is_refused_though_no_row_of_it_is_zero(aexecute, authenticated_context, transform: dict, phrase: str):
    """A projection written as a full matrix: no zero factor, no zero row, and no inverse."""
    grid, world = await _dataset_and_world(aexecute, authenticated_context)
    before = await models.Transformation.objects.acount()

    result = await _create(aexecute, grid, world, transform)

    assert result.errors, f"expected an error for {transform}"
    assert phrase in str(result.errors[0]), str(result.errors[0])
    assert await models.Transformation.objects.acount() == before, "a refused edge must write nothing"


async def test_a_rank_changing_affine_is_still_accepted(aexecute, authenticated_context):
    """The negative of the singularity rule, and why it reads the shape rather than the kind.

    An AFFINE is rectangular *by design* -- `assert_edge_rank` admits M x (N+1) between
    spaces of different rank deliberately -- so its linear part is not square and there is
    no inverse to ask about. A check keyed on `kind == AFFINE` would refuse this, which is
    an ordinary authored registration.
    """
    dataset = await _yx_dataset(authenticated_context)
    world = await _space_world(aexecute, "Volume")

    # Three rows (the world's z, y, x), three columns (the dataset's y, x, plus translation),
    # so the linear part is 3 x 2 and has no determinant to take. The z row is a real slope,
    # not a zero row -- a tilted section, and `assert_no_collapsed_rows` would refuse a zero
    # one anyway, on the older rule that a dropped axis is stated with BY_DIMENSION.
    result = await _create(aexecute, str(dataset.coordinate_system_id), world, {"kind": "AFFINE", "affine": [[0.5, 0.0, 5.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]})
    assert not result.errors, result.errors


async def test_a_rotation_between_spaces_of_different_rank_is_refused(aexecute, authenticated_context):
    """A rotation is an element of one space's orthogonal group; there is no such thing between two.

    `_PER_AXIS_KINDS` holds only SCALE and TRANSLATION, so a ROTATION carrying a whole
    matrix escaped that rule and landed in the rectangular M x (N+1) check, which happily
    accepted a "rotation" from a 2-axis grid into a 3-axis world.
    """
    dataset = await _yx_dataset(authenticated_context)
    world = await _space_world(aexecute, "Volume")

    result = await _create(aexecute, str(dataset.coordinate_system_id), world, {"kind": "ROTATION", "affine": [[0.5, 0.0, 0.0], [0.0, -1.0, 0.0], [1.0, 0.0, 0.0]]})
    assert result.errors, "a rotation between spaces of different rank is not a rotation"
    assert "A ROTATION is a rotation *of* a space" in str(result.errors[0]), str(result.errors[0])


async def test_a_map_axis_between_different_axis_sets_is_refused(aexecute, authenticated_context):
    """A permutation relabels; it does not reshape -- and the read path could only say so with a stack dataset.

    This used to pass every write check and then raise `NonAffineTransformError` from inside
    `permutation_matrix`, at read, in a message about a matrix rather than about the edge
    somebody authored. It is also the precondition `invert_step` relies on to invert a
    MAP_AXIS by swapping its two lists rather than solving anything.
    """
    dataset = await _yx_dataset(authenticated_context)
    grid = str(dataset.coordinate_system_id)
    elsewhere = await _space_world(aexecute, "Elsewhere", axes=("a", "b"))

    result = await _create(aexecute, grid, elsewhere, {"kind": "MAP_AXIS", "inputAxes": ["y", "x"], "outputAxes": ["a", "b"]})
    assert result.errors, "a MAP_AXIS between disjoint axis sets is not a permutation"
    assert "permutes the axes of one coordinate vector" in str(result.errors[0]), str(result.errors[0])

    # The same pair, stated as what it actually is, is accepted.
    ok = await _create(aexecute, grid, elsewhere, {"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["a", "b"]})
    assert not ok.errors, ok.errors


# --- the logic layer, for callers below the API -------------------------------------------------


async def test_the_logic_layer_holds_the_same_line_for_internal_callers(authenticated_context):
    """The writers below the API refuse what the union makes unrepresentable above it.

    The parse layer is the API's gate; these are the same checks in
    `build_registration_edge` / `write_relation_edge`, so an internal caller cannot
    reintroduce the silent drop the union removed.
    """
    ctx = seed._creation(authenticated_context)

    def check() -> None:
        def system(name: str, axes: list = seed.YX_AXES) -> models.CoordinateSystem:
            made = models.CoordinateSystem.objects.create(name=name, creator=ctx.user, organization=ctx.organization)
            graph_logic.create_pixel_axes(made, axes)
            return made

        a, b = system("a"), system("b")

        with pytest.raises(ValueError, match="does not read `translation`"):
            graph_logic.build_registration_edge(input_system=a, output_system=b, kind="SCALE", scale=[1.0, 1.0], translation=[1.0, 1.0], ctx=ctx)
        with pytest.raises(ValueError, match="takes no `inputAxes`"):
            graph_logic.build_registration_edge(input_system=a, output_system=b, kind="SCALE", scale=[1.0, 1.0], input_axes=["y", "x"], ctx=ctx)
        with pytest.raises(ValueError, match="belongs to an UNMAPPABLE edge"):
            graph_logic.build_registration_edge(input_system=a, output_system=b, kind="SCALE", scale=[1.0, 1.0], reason="because", ctx=ctx)
        with pytest.raises(ValueError, match="cannot be created directly"):
            graph_logic.build_registration_edge(input_system=a, output_system=b, kind="SEQUENCE", ctx=ctx)
        with pytest.raises(ValueError, match="does not read `affine`"):
            graph_logic.write_relation_edge(name="d", input_system=a, output_system=b, kind="IDENTITY", affine=[[1.0]], ctx=ctx)

        # The value rules hold here too: the union makes a collapsing map unrepresentable
        # through GraphQL, and nothing makes it unrepresentable to an internal writer.
        with pytest.raises(ValueError, match="no factor may be zero"):
            graph_logic.build_registration_edge(input_system=a, output_system=b, kind="SCALE", scale=[0.0, 1.0], ctx=ctx)
        with pytest.raises(ValueError, match="no row's linear part may be all zeros"):
            graph_logic.write_relation_edge(name="d", input_system=a, output_system=b, kind="AFFINE", affine=[[0.0, 0.0, 1.0], [0.0, 1.0, 0.0]], ctx=ctx)

        # Including the collapse no zero row betrays: rank-deficient, every row non-zero.
        with pytest.raises(ValueError, match="is singular"):
            graph_logic.build_registration_edge(input_system=a, output_system=b, kind="AFFINE", affine=[[1.0, 1.0, 0.0], [2.0, 2.0, 0.0]], ctx=ctx)

        # And the two rank rules, which only the endpoints can decide and so live only here.
        three = system("cyx", seed.SIMPLE_AXES)
        with pytest.raises(ValueError, match="ROTATION is a rotation"):
            graph_logic.build_registration_edge(input_system=a, output_system=three, kind="ROTATION", affine=[[0.5, 0.0, 0.0], [0.0, -1.0, 0.0], [1.0, 0.0, 0.0]], ctx=ctx)
        with pytest.raises(ValueError, match="permutes the axes of one coordinate vector"):
            graph_logic.build_registration_edge(input_system=a, output_system=three, kind="MAP_AXIS", input_axes=["y", "x"], output_axes=["y", "x"], ctx=ctx)

        # The one deliberate loosening: a BY_DIMENSION derivation's optional parameters now
        # persist, exactly as the registration path always stored them.
        edge = graph_logic.write_relation_edge(name="projection", input_system=a, output_system=b, kind="BY_DIMENSION", input_axes=["y", "x"], output_axes=["y", "x"], scale=[2.0, 2.0], ctx=ctx)
        assert edge.params == {"scale": [2.0, 2.0]}

    await sync_to_async(check)()


async def test_a_derivation_may_state_any_creatable_kind():
    """The derivation subset is gone: one union, and MAP_AXIS/FIELD parse like any member.

    This is the parse every ``TransformInput.to_pydantic`` runs -- derivations included,
    since ``DerivedFromInput`` carries the same union.
    """
    member = parse_union_member(TRANSFORM_MEMBERS, {"kind": "MAP_AXIS", "input_axes": ["x", "y"], "output_axes": ["y", "x"]}, noun="transformation")
    assert isinstance(member, MapAxisTransformInputModel)

    member = parse_union_member(TRANSFORM_MEMBERS, {"kind": "FIELD", "field": "1", "input_axes": ["y", "x"], "output_axes": ["i"]}, noun="transformation")
    assert isinstance(member, FieldTransformInputModel)


async def test_the_union_is_published_for_codegen():
    """The SDL carries the members, their annotations, and the flat unions they describe.

    The member inputs are referenced by no field -- dropping them from `types=[...]`
    would silently erase them from the SDL, so their presence is pinned here, exactly
    like the polymorphic read-side subtypes.
    """
    from elektro_server.schema import schema

    sdl = str(schema)
    assert "directive @unionElementOf(union: String!, discriminator: String!, key: String!) repeatable on INPUT_OBJECT" in sdl
    for member in [
        # IDENTITY included: the discriminator is a field, so the input is not empty,
        # and a client that cannot build this member can only say "same grid" by
        # omitting the transform -- which a derivation reads as UNMAPPABLE, the opposite.
        "IdentityTransformInput",
        "ScaleTransformInput",
        "TranslationTransformInput",
        "AffineTransformInput",
        "RotationTransformInput",
        "ByDimensionTransformInput",
        "UnmappableTransformInput",
        "MapAxisTransformInput",
        "FieldTransformInput",
    ]:
        start = sdl.find(f"input {member} ")
        assert start >= 0, f"{member} missing from the SDL"
        header = sdl[start : sdl.find("{", start)]
        assert '@unionElementOf(union: "TransformInput", discriminator: "kind", key: ' in header, f"{member} lacks its annotation"

        # A member declares the parent's common fields as well as its own -- for this union
        # that is `kind` alone, and it defaults to the member's own key. GraphQL input types
        # have no inheritance, so a member that omits it generates a type a client cannot
        # construct without threading the discriminator in by hand.
        body = sdl[start : sdl.find("\n}", start)]
        key = header[header.find('key: "') + 6 : header.rfind('"')]
        assert f"kind: CreatableTransformKind! = {key}" in body, f"{member} does not declare `kind` defaulting to {key}"

    assert "RelationInput" not in sdl, "the derivation subset is gone: one union input, everywhere"
    assert "transform: TransformInput!" in sdl, "createTransformation requires its transform"
    assert "transform: TransformInput" in sdl
    creatable = sdl[sdl.find("enum CreatableTransformKind") : sdl.find("}", sdl.find("enum CreatableTransformKind"))]
    assert "SEQUENCE" not in creatable, "wrapper kinds stay out of the creatable enum"
    assert "BIJECTION" not in creatable and "BIJECTION" not in sdl, "the deleted kind is gone from the whole published schema"


# --- a wrapper's children answer to the wrapper -----------------------------------------------


async def test_a_sequence_child_answers_to_its_wrappers_rank(aexecute, authenticated_context):
    """A wrapper child has no endpoints, and that used to mean no rank check at all.

    `updateTransformation` guarded `assert_edge_rank` with `if transformation.input and
    transformation.output:`. `_sequence` creates its children with both null -- *"The children
    omit input and output: the wrapping sequence supplies them"* -- so the guard was false for
    every one of them, and `updatable_params` reads the *child's* kind, so a SCALE child
    accepted a vector of any length. `to_matrix` then wrote a two-entry scale's last number
    into `matrix[1][1]` and left the remaining axes unscaled: no error, wrong picture.

    Every stepped lens here is such a wrapper, with its children's ids exposed through
    `SequenceTransformation.transformations`.
    """
    grid, world = await _dataset_and_world(aexecute, authenticated_context)
    wrapper = await sync_to_async(_build_sequence)(authenticated_context, grid, world)
    child = await wrapper.children.aget(kind="SCALE")

    result = await _update(aexecute, str(child.pk), scale=[3.0])
    assert result.errors, "a one-entry scale on a two-axis wrapper must be refused"
    assert "one entry per input axis: expected 2, got 1" in str(result.errors[0]), str(result.errors[0])

    result = await _update(aexecute, str(child.pk), scale=[3.0, 3.0])
    assert not result.errors, result.errors
    refreshed = await models.Transformation.objects.aget(pk=child.pk)
    assert refreshed.params == {"scale": [3.0, 3.0]}


def _by_dimension_with_scale_child(ctx: HttpContext, input_system: models.CoordinateSystem, output_system: models.CoordinateSystem, acts_on: list[str]) -> models.Transformation:
    """A BY_DIMENSION wrapper over ``acts_on`` holding one SCALE child, written as rows.

    Rows rather than a writer, as in mikro: what is on trial is what ``updateTransformation``
    does with a child, and no public writer produces this shape without also checking it.
    """
    creation = seed._creation(ctx)
    wrapper = models.Transformation.objects.create(
        kind=enums.TransformKindChoices.BY_DIMENSION.value,
        input=input_system,
        output=output_system,
        input_axes=acts_on,
        output_axes=acts_on,
        params={},
        creator=creation.user,
        organization=creation.organization,
    )
    models.Transformation.objects.create(
        kind=enums.TransformKindChoices.SCALE.value,
        parent=wrapper,
        order=0,
        params={"scale": [1.0] * len(acts_on)},
        creator=creation.user,
        organization=creation.organization,
    )
    return wrapper


def _system_with_axes(ctx: HttpContext, name: str, axes: list[tuple[str, str, str | None]]) -> models.CoordinateSystem:
    """A space whose axes are written as rows: ``(name, type, unit)`` each."""
    creation = seed._creation(ctx)
    system = models.CoordinateSystem.objects.create(name=name, creator=creation.user, organization=creation.organization)
    models.Axis.objects.bulk_create([models.Axis(coordinate_system=system, order=index, name=axis_name, type=axis_type, unit=unit) for index, (axis_name, axis_type, unit) in enumerate(axes)])
    return system


@pytest.mark.parametrize(
    "world_axes",
    [
        # Different rank: isolates the equal-rank refusal, which recommends BY_DIMENSION by name.
        ["t", "z", "y", "x"],
        # Same rank, different names: isolates the same-names refusal. Without this case the
        # rank half of the subset rule carries the whole test and the name half ships unproven --
        # every live BY_DIMENSION wrapper names its full axis set, so nothing else would catch it.
        ["z", "y", "x"],
    ],
    ids=["rank-differs", "names-differ"],
)
async def test_a_by_dimension_child_answers_to_the_named_subset_not_the_whole_space(aexecute, authenticated_context, world_axes: list[str]):
    """The anti-regression test, and the reason the fix reads the *parent's* kind.

    A BY_DIMENSION applies its children to the axes it names: `_sub_matrix` composes them at
    `len(acts_on_input)` and `_by_dimension_forms` labels the rows by `acts_on_output`. So a
    child's parameters are bound to that subset, not to the full space.

    Inheriting the parent's endpoints *without* that distinction is the obvious fix and it is
    wrong: the child's own kind is SCALE, so `assert_edge_rank` takes the per-axis branch and
    derives `rank_in` from the parent's whole system -- rejecting a perfectly good two-entry
    scale over `["y", "x"]` inside a three-axis wrapper.

    **The two systems differ in rank *and* in ordered names, deliberately.** A wrapper from
    the same system to itself would make the subset rule the only thing under test, and the
    two name-comparing guards -- the equal-rank refusal and the same-names refusal -- would
    both pass for free because a system trivially matches itself. Relating ``(c,y,x)`` to
    ``(t,z,y,x)`` over the two axes they share is the ordinary registration BY_DIMENSION
    exists to express, and the error messages of both those guards recommend it by name.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "ArrayDataset", seed.SIMPLE_AXES, [3, 64, 64])

    def build() -> models.Transformation:
        time, space = enums.AxisTypeChoices.TIME.value, enums.AxisTypeChoices.SPACE.value
        world = _system_with_axes(ctx, "Volume", [(name, time if name == "t" else space, "second" if name == "t" else "micrometer") for name in world_axes])
        return _by_dimension_with_scale_child(ctx, models.CoordinateSystem.objects.get(pk=dataset.coordinate_system_id), world, ["y", "x"])

    wrapper = await sync_to_async(build)()
    child = await wrapper.children.aget(kind="SCALE")

    # Two entries, for the two named axes -- not the three the system has.
    result = await _update(aexecute, str(child.pk), scale=[2.0, 2.0])
    assert not result.errors, f"a subset-rank scale must be accepted: {result.errors}"

    result = await _update(aexecute, str(child.pk), scale=[2.0, 2.0, 2.0])
    assert result.errors, "three entries is the whole space, not the named subset"
    assert "expected 2, got 3" in str(result.errors[0]), str(result.errors[0])


async def test_an_identity_child_still_dies_before_the_rank_check(aexecute, authenticated_context):
    """Guard ordering, pinned: the parameter gate runs before the rank gate.

    `updatable_params("IDENTITY")` is empty, so an IDENTITY child is refused for taking a
    parameter at all. Resolving endpoints from the parent must not move that refusal.
    """
    ctx = authenticated_context
    dataset = await _yx_dataset(ctx)

    def build() -> models.Transformation:
        creation = seed._creation(ctx)
        system = models.CoordinateSystem.objects.get(pk=dataset.coordinate_system_id)
        wrapper = models.Transformation.objects.create(
            kind=enums.TransformKindChoices.BY_DIMENSION.value, input=system, output=system, input_axes=["y", "x"], output_axes=["y", "x"], params={}, creator=creation.user, organization=creation.organization
        )
        models.Transformation.objects.create(kind=enums.TransformKindChoices.IDENTITY.value, parent=wrapper, order=0, params={}, creator=creation.user, organization=creation.organization)
        return wrapper

    wrapper = await sync_to_async(build)()
    child = await wrapper.children.aget(kind="IDENTITY")

    result = await _update(aexecute, str(child.pk), scale=[2.0, 2.0])
    assert result.errors
    assert "takes no parameters at all" in str(result.errors[0]), str(result.errors[0])


# --- names, not just ranks ----------------------------------------------------------------------


async def test_a_per_axis_edge_between_differently_ordered_spaces_is_refused(aexecute, authenticated_context):
    """A SCALE binds its i-th number to the i-th axis of each system, so their orders are the whole of what the numbers mean.

    `(z,y,x)` into `(x,y,z)` was accepted and the factor meant for z landed on x -- no error at
    write, none at read, and the transposition then rode into every extent, `asAffine` and
    `inView` answer. IDENTITY already held itself to ordered equality; this closes the gap.
    """
    dataset = await _yx_dataset(authenticated_context)
    # The same two axes, named the other way round -- both SPACE, both micrometer, same rank.
    world = await _space_world(aexecute, "Reordered", axes=("x", "y"))

    result = await _create(aexecute, str(dataset.coordinate_system_id), world, {"kind": "SCALE", "scale": [2.0, 3.0]})
    assert result.errors, "a SCALE between differently-ordered axis names must be refused"
    message = str(result.errors[0])
    assert "must name their axes the same way" in message
    assert "BY_DIMENSION" in message, "point at the kind that can state a reorder honestly"


async def test_a_name_changing_affine_is_still_accepted(aexecute, authenticated_context):
    """The anti-over-fix test. AFFINE must NOT get the name rule.

    `_forms_from_matrix` labels an affine's rows by the output axes and its columns by the
    input axes -- both orders are the author's explicit statement, and a rank- and
    name-changing AFFINE is legal by design. Applying the per-axis rule to it would be a guess
    dressed as a check, and would break an ordinary `(c,y,x) -> (v,u)` registration.
    """
    dataset = await seed.create_dataset(authenticated_context, "ArrayDataset", seed.SIMPLE_AXES, [3, 64, 64])
    world = await _space_world(aexecute, "Two axis", axes=("v", "u"))

    # Two output axes, three input axes plus the translation column.
    result = await _create(aexecute, str(dataset.coordinate_system_id), world, {"kind": "AFFINE", "affine": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]})
    assert not result.errors, f"a rank-changing AFFINE is legal by design: {result.errors}"


async def test_a_rotation_between_differently_named_spaces_of_equal_rank_is_refused(aexecute, authenticated_context):
    """ROTATION's line in the name rule, on its own, so it can be reverted on its own.

    ROTATION is the one entry in `_NAME_ORDERED_KINDS` that carries a whole matrix rather than
    one number per axis, so it does not follow from SCALE's argument and is not covered by
    SCALE's test. It is included on a different ground: a rotation is an element of *one*
    space's orthogonal group, so its two endpoints are the same space -- and two spaces that
    name their axes differently are not the same space, whatever their rank.
    """
    dataset = await _yx_dataset(authenticated_context)
    physical = await _space_world(aexecute, "Slide", axes=("v", "u"))

    # A genuine 90-degree rotation: orthonormal, square, and the right rank on both sides.
    # Nothing about the matrix is wrong -- only what it claims to relate.
    result = await _create(aexecute, str(dataset.coordinate_system_id), physical, {"kind": "ROTATION", "affine": [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0]]})
    assert result.errors, "a ROTATION between two differently-named spaces must be refused"
    message = str(result.errors[0])
    assert "must name their axes the same way" in message, message
    assert "BY_DIMENSION" in message, "point at the kind that can state a reorder honestly"


# --- INDEX axes have no metric ------------------------------------------------------------------

_INDEX = enums.AxisTypeChoices.INDEX.value
_SPACE = enums.AxisTypeChoices.SPACE.value


async def test_a_by_dimension_child_is_not_refused_for_an_index_axis_its_parent_left_alone(aexecute, authenticated_context):
    """The INDEX guard follows the same subset rule as the three checks below it.

    `_METRIC_KINDS` refuses arithmetic on an INDEX axis, and rightly: the distance between
    object 3 and object 4 means nothing. But a refinement is checked against the *child's*
    kind, so a SCALE child under a BY_DIMENSION wrapper reached that guard with its parent's
    whole systems -- and was refused for an axis its parent deliberately did not name.
    """
    ctx = authenticated_context

    def build() -> models.Transformation:
        objects = _system_with_axes(ctx, "Objects", [("object_id", _INDEX, None), ("y", _SPACE, "micrometer"), ("x", _SPACE, "micrometer")])
        physical = _system_with_axes(ctx, "Slide", [("y", _SPACE, "micrometer"), ("x", _SPACE, "micrometer")])
        return _by_dimension_with_scale_child(ctx, objects, physical, ["y", "x"])

    wrapper = await sync_to_async(build)()
    child = await wrapper.children.aget(kind="SCALE")

    result = await _update(aexecute, str(child.pk), scale=[0.5, 0.5])
    assert not result.errors, f"the child scales y and x, and touches no INDEX axis: {result.errors}"


async def test_an_index_axis_the_edge_does_act_on_is_still_refused(aexecute, authenticated_context):
    """The negative of the rule above: narrowing the scan to the subset must not disarm it.

    Same shape, but the wrapper names `object_id` -- so the child's first number really
    does scale an index, and the guard must still fire.
    """
    ctx = authenticated_context

    def build() -> models.Transformation:
        objects = _system_with_axes(ctx, "Objects", [("object_id", _INDEX, None), ("y", _SPACE, "micrometer")])
        elsewhere = _system_with_axes(ctx, "Elsewhere", [("object_id", _INDEX, None), ("y", _SPACE, "micrometer")])
        return _by_dimension_with_scale_child(ctx, objects, elsewhere, ["object_id", "y"])

    wrapper = await sync_to_async(build)()
    child = await wrapper.children.aget(kind="SCALE")

    result = await _update(aexecute, str(child.pk), scale=[2.0, 2.0])
    assert result.errors, "object 3 x 2 = object 6 is not a thing, and the wrapper named the axis"
    assert "is an INDEX axis" in str(result.errors[0]), str(result.errors[0])


# --- the deleted kind, units, axis kinds and epochs ---------------------------------------------


async def test_the_deleted_kind_is_gone_from_both_enums():
    """BIJECTION is removed, not merely uncreatable.

    Pinned on the *storage* enum as well as the published one. An inverse that cannot be
    derived is still expressible, as a FIELD whose values are the map in whichever direction
    the author needs.
    """
    assert not hasattr(enums.TransformKindChoices, "BIJECTION"), "the storage enum still carries the deleted kind"
    assert not hasattr(enums.TransformKind, "BIJECTION"), "the GraphQL enum still carries the deleted kind"
    assert "BIJECTION" not in {choice.value for choice in enums.TransformKindChoices}


async def test_a_number_free_edge_may_not_relate_two_different_units(authenticated_context):
    """An IDENTITY between a micrometre space and a nanometre one is a claim that they are equal.

    It used to be accepted, because the IDENTITY branch compared axis *names* and nothing on the
    write path ever read `Axis.unit`. The two composers then disagreed about that one edge by a
    factor of 1000, so the edge is refused rather than a second composer taught about units.
    """
    ctx = seed._creation(authenticated_context)

    def space(name: str, unit: str) -> models.CoordinateSystem:
        made = models.CoordinateSystem.objects.create(name=name, creator=ctx.user, organization=ctx.organization)
        graph_logic.create_physical_axes(made, [seed.physical_axis("y", enums.AxisType.SPACE, unit), seed.physical_axis("x", enums.AxisType.SPACE, unit)])
        return made

    microns, nanos = await sync_to_async(space)("Microns", "micrometer"), await sync_to_async(space)("Nanos", "nanometer")

    with pytest.raises(ValueError, match="carries no numbers"):
        await sync_to_async(graph_logic.build_registration_edge)(input_system=microns, output_system=nanos, kind="IDENTITY", ctx=ctx)

    # The repair the message names: a map that *states* its factor is allowed to relate them.
    await sync_to_async(graph_logic.build_registration_edge)(input_system=microns, output_system=nanos, kind="SCALE", scale=[1000.0, 1000.0], ctx=ctx)

    # And two spaces that agree, or decline to claim, are untouched.
    same = await sync_to_async(space)("AlsoMicrons", "micrometer")
    await sync_to_async(graph_logic.build_registration_edge)(input_system=microns, output_system=same, kind="IDENTITY", ctx=ctx)


async def test_a_correspondence_may_not_cross_axis_kinds(authenticated_context):
    """`inputAxes: ["c"] -> outputAxes: ["z"]` maps a channel index onto a position. It is refused.

    The named-subset rules establish that the axes exist and pair one for one; none of them looked
    at what the axes *were*, so a channel could be mapped onto a spatial axis and nothing
    downstream could catch it -- by then it is two names and a matrix.

    INDEX stays exempt on either side, because where an enumeration's objects sit is not a
    property it carries but the thing a registration establishes.
    """
    ctx = seed._creation(authenticated_context)

    def space(name: str, axes: list) -> models.CoordinateSystem:
        made = models.CoordinateSystem.objects.create(name=name, creator=ctx.user, organization=ctx.organization)
        graph_logic.create_pixel_axes(made, axes)
        return made

    channelled = await sync_to_async(space)("Channelled", seed.SIMPLE_AXES)
    volume = await sync_to_async(space)("Volume", seed.ZYX_AXES)

    with pytest.raises(ValueError, match="relates two different kinds of axis"):
        await sync_to_async(graph_logic.build_registration_edge)(input_system=channelled, output_system=volume, kind="BY_DIMENSION", input_axes=["c"], output_axes=["z"], ctx=ctx)

    # Same-kind correspondences are unaffected, whatever the axes are named.
    await sync_to_async(graph_logic.build_registration_edge)(input_system=channelled, output_system=volume, kind="BY_DIMENSION", input_axes=["y", "x"], output_axes=["y", "x"], ctx=ctx)

    # An INDEX axis is the deliberate wildcard: this is the ordinary product-space placement.
    objects = await sync_to_async(space)("Objects", [seed.axis("i", enums.AxisType.INDEX)])
    await sync_to_async(graph_logic.build_registration_edge)(input_system=objects, output_system=volume, kind="BY_DIMENSION", input_axes=["i"], output_axes=["z"], ctx=ctx)


async def test_two_clocks_anchored_differently_are_related_only_by_a_stated_offset(authenticated_context):
    """`epoch` says `wall_clock = epoch + t * unit`, and nothing ever read it.

    So a path across two spaces with different epochs treated their `t = 0` as the same instant:
    a 09:00 acquisition aligned against an 11:00 one was two hours wrong, with no error anywhere.
    Refused rather than composed -- an offset folded in from a column neither endpoint's
    parameters mention is a fact stored where no query can find it. Say it as a TRANSLATION, or an
    AFFINE when the clocks also drift; both are accepted (they used to be refused as well).
    """
    ctx = seed._creation(authenticated_context)

    def clock(name: str, epoch: datetime.datetime | None) -> models.CoordinateSystem:
        made = models.CoordinateSystem.objects.create(name=name, epoch=epoch, creator=ctx.user, organization=ctx.organization)
        graph_logic.create_physical_axes(made, seed.CLOCK_AXES)
        return made

    nine = datetime.datetime(2026, 8, 21, 9, 0, tzinfo=datetime.timezone.utc)
    eleven = datetime.datetime(2026, 8, 21, 11, 0, tzinfo=datetime.timezone.utc)

    morning, later = await sync_to_async(clock)("Morning", nine), await sync_to_async(clock)("Later", eleven)
    with pytest.raises(ValueError, match="anchor it to different instants"):
        await sync_to_async(graph_logic.build_registration_edge)(input_system=morning, output_system=later, kind="IDENTITY", ctx=ctx)

    # Sharing an epoch, or declining to name one, is unaffected.
    same = await sync_to_async(clock)("AlsoMorning", nine)
    await sync_to_async(graph_logic.build_registration_edge)(input_system=morning, output_system=same, kind="IDENTITY", ctx=ctx)
    unanchored = await sync_to_async(clock)("Unanchored", None)
    await sync_to_async(graph_logic.build_registration_edge)(input_system=morning, output_system=unanchored, kind="IDENTITY", ctx=ctx)

    # Stating the offset is what the refusal asks for, and it is accepted: a TRANSLATION, and an
    # AFFINE whose factor is a few ppm off one -- which is how drift between two clocks is written.
    await sync_to_async(graph_logic.build_registration_edge)(input_system=morning, output_system=later, kind="TRANSLATION", translation=[-7200.0], ctx=ctx)
    drifting = await sync_to_async(clock)("Drifting", eleven)
    await sync_to_async(graph_logic.build_registration_edge)(input_system=morning, output_system=drifting, kind="AFFINE", affine=[[1.000012, -7200.0]], ctx=ctx)
    # What states no offset still asserts that the two zeros coincide, and stays refused.
    scaled = await sync_to_async(clock)("Scaled", eleven)
    with pytest.raises(ValueError, match="states no offset"):
        await sync_to_async(graph_logic.build_registration_edge)(input_system=morning, output_system=scaled, kind="SCALE", scale=[1.000012], ctx=ctx)
    with pytest.raises(ValueError, match="states no offset"):
        await sync_to_async(graph_logic.build_registration_edge)(
            input_system=morning, output_system=scaled, kind="BY_DIMENSION", input_axes=["t"], output_axes=["t"], scale=[1.000012], ctx=ctx
        )
