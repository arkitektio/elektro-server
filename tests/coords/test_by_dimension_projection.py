"""A BY_DIMENSION publishes its own map as child rows, so a client can read it at all.

Ported from mikro's ``tests/test_by_dimension_projection.py``, and it matters more here than
there: **every sampling law and every clock offset in this service is a BY_DIMENSION carrying
an ``affine``** (``core.logic.clocks``). The last test below is this service's own and pins
exactly that.

`ByDimensionTransformation` exposes ``transformations`` and nothing else -- no ``affine``, no
``scale``, no ``translation`` -- while `AffineTransformation` beside it resolves the very same
``params['affine']``. So a BY_DIMENSION written as one childless row had its matrix stored, used
server-side, and **unreadable by any client**. Every consumer that composes a path client-side
folds over the empty child list and comes back with an identity.

The fix is a projection, and the invariant that makes it safe is that it is **only** a projection:
`_sub_matrix` reads a params-carried map in preference to children, so what the server composes is
byte-identical whether the rows are there or not, and a refinement through `updateTransformation`
cannot be out-voted by a stale copy of itself.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core import enums, models
from core.logic import coords as coords_logic
from core.logic import graph as graph_logic
from tests import seed
from tests.seed import axis

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


#: mikro's fixture, a real lattice fit: rows (y, x), columns (row, col, 1). Its linear part is
#: symmetric and its determinant negative -- a rotation with a reflection -- so a transposed or
#: sign-dropped copy of it still looks plausible. That is exactly why the numbers have to travel.
LATTICE = [
    [-58.4281240, -0.389111, 24102.7386],
    [-0.3888420, 58.4299340, 257.103715],
]


async def _systems(ctx) -> tuple[models.CoordinateSystem, models.CoordinateSystem]:  # noqa: ANN001
    """Two datasets' sample grids: a (row, col) lattice and a (c, y, x) slide."""
    lattice = await seed.create_dataset(ctx, "Lattice", [axis("row", enums.AxisType.SPACE), axis("col", enums.AxisType.SPACE)], [412, 400])
    slide = await seed.create_dataset(ctx, "Slide", seed.SIMPLE_AXES, [3, 21943, 23618])
    return (
        await sync_to_async(lambda: lattice.coordinate_system)(),
        await sync_to_async(lambda: slide.coordinate_system)(),
    )


def _edge(ctx, input_system, output_system, **params) -> models.Transformation:  # noqa: ANN001
    return graph_logic.build_registration_edge(
        input_system=input_system,
        output_system=output_system,
        kind=enums.TransformKind.BY_DIMENSION.value,
        input_axes=["row", "col"],
        output_axes=["y", "x"],
        ctx=ctx,
        **params,
    )


def _children(edge: models.Transformation) -> list[tuple[str, dict]]:
    return [(child.kind, child.params) for child in edge.children.order_by("order")]


async def test_an_affine_reaches_a_client_as_a_child(authenticated_context):
    """The matrix is on a child row, in a type that publishes it."""
    ctx = seed._creation(authenticated_context)
    lattice, slide = await _systems(authenticated_context)

    edge = await sync_to_async(_edge)(ctx, lattice, slide, affine=LATTICE)

    children = await sync_to_async(_children)(edge)
    assert children == [(enums.TransformKind.AFFINE.value, {"affine": LATTICE})]
    # And verbatim, not multiplied into something equivalent: a client rendering the reflection
    # as a rotation is the failure this exists to stop, and rounding it would hide that.
    assert edge.params["affine"] == LATTICE


async def test_the_projection_does_not_change_what_the_server_composes(authenticated_context):
    """A projected edge and a childless one compose to the same matrix.

    The whole safety argument: if these two ever disagree, the projection has become a second
    source of truth and every placement is a coin toss between them.
    """
    ctx = seed._creation(authenticated_context)
    lattice, slide = await _systems(authenticated_context)
    edge = await sync_to_async(_edge)(ctx, lattice, slide, affine=LATTICE)

    def _both() -> tuple[list, list]:
        step = coords_logic.AxedStep(
            kind=enums.TransformKind.BY_DIMENSION.value,
            params=edge.params,
            input_axes=["row", "col"],
            output_axes=["y", "x"],
            acts_on_input=["row", "col"],
            acts_on_output=["y", "x"],
            children=tuple((child.kind, child.params) for child in edge.children.order_by("order")),
        )
        childless = coords_logic.AxedStep(**{**step.__dict__, "children": ()})
        return coords_logic._sub_matrix(step), coords_logic._sub_matrix(childless)

    projected, childless = await sync_to_async(_both)()
    assert projected == childless
    # Pinned against the fit itself, so a change to either path has to face the real numbers.
    assert projected[0][:3] == approx(LATTICE[0])
    assert projected[1][:3] == approx(LATTICE[1])


async def test_scale_and_translation_project_in_the_order_they_apply(authenticated_context):
    """`_params_matrix` applies scale then translation, so the children say so in that order."""
    ctx = seed._creation(authenticated_context)
    lattice, slide = await _systems(authenticated_context)

    edge = await sync_to_async(_edge)(ctx, lattice, slide, scale=[2.0, 3.0], translation=[5.0, 7.0])

    assert await sync_to_async(_children)(edge) == [
        (enums.TransformKind.SCALE.value, {"scale": [2.0, 3.0]}),
        (enums.TransformKind.TRANSLATION.value, {"translation": [5.0, 7.0]}),
    ]


async def test_an_affine_wins_over_scale_and_translation(authenticated_context):
    """`_params_matrix` ignores scale/translation when an affine is present; so does this.

    Projecting all three would publish a composition the server never performs.
    """
    ctx = seed._creation(authenticated_context)
    lattice, slide = await _systems(authenticated_context)

    edge = await sync_to_async(_edge)(ctx, lattice, slide, affine=LATTICE, scale=[2.0, 3.0])

    assert await sync_to_async(_children)(edge) == [(enums.TransformKind.AFFINE.value, {"affine": LATTICE})]


async def test_a_wrapper_with_no_map_of_its_own_is_left_alone(authenticated_context):
    """`create_identity_registration` writes `params={}` and one IDENTITY child, where the child IS the map.

    Regenerating children there would erase the edge's entire content, so a params-less
    BY_DIMENSION must not be touched.
    """
    ctx = seed._creation(authenticated_context)
    lattice, slide = await _systems(authenticated_context)

    def _build() -> list[tuple[str, dict]]:
        edge = models.Transformation.objects.create(
            kind=enums.TransformKind.BY_DIMENSION.value,
            input=lattice,
            output=slide,
            input_axes=["row", "col"],
            output_axes=["row", "col"],
            params={},
            creator=ctx.user,
            organization=ctx.organization,
        )
        models.Transformation.objects.create(kind=enums.TransformKind.IDENTITY.value, parent=edge, order=0, params={}, creator=ctx.user, organization=ctx.organization)
        graph_logic._project_by_dimension_children(edge, ctx)
        return _children(edge)

    assert await sync_to_async(_build)() == [(enums.TransformKind.IDENTITY.value, {})]


# --- this service's own: the sampling law is the edge every client has to read -------------------

SAMPLING_LAW = """
query ($id: ID!) {
  coordinateSystem(id: $id) {
    registrations {
      kind
      ... on ByDimensionTransformation { inputAxes outputAxes transformations { kind ... on AffineTransformation { affine } } }
    }
  }
}
"""


async def test_a_sampling_law_is_readable_by_a_client(aexecute, make_simulation_chain):
    """Not in mikro. A sampling law is a BY_DIMENSION, so its period and start reach a client only as a child.

    10 kHz from t = 0 on a millisecond clock: t_ms = sample * 0.1.
    """
    chain = await make_simulation_chain()

    result = await aexecute(SAMPLING_LAW, {"id": str(chain.clock.pk)})
    assert not result.errors, result.errors
    # One law per dataset of the run -- the recording's and the stimulus' -- and they agree.
    laws = result.data["coordinateSystem"]["registrations"]
    assert len(laws) == 2 and laws[0] == laws[1]
    law = laws[0]
    assert (law["kind"], law["inputAxes"], law["outputAxes"]) == ("BY_DIMENSION", ["t"], ["t"])
    (child,) = law["transformations"]
    assert child["kind"] == "AFFINE"
    assert child["affine"][0] == approx([0.1, 0.0])
