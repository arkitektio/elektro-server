"""Which geometric properties survive a map, and how that composes along a path.

Ported from mikro's ``tests/test_transform_invariance.py``. The classifier
(``graph.invariance_of``) and the path aggregate (``placementInvariance``) are vendored; the
only test of either here was one assertion on a time lookup in ``test_clocks.py``.

The graph already says whether a placement *exists* (`placement`) and how well it is
*known* (`placementValidity`). Neither answers the third question a client actually has
before it reports a number: does a duration, a distance or an angle measured on one side
still mean the same thing on the other. So every edge states its invariance class, derived
from its `kind` and never stored, and a view's is the **minimum** over its path. A minimum
for a stronger reason than caution: the classes are nested groups (isometry inside similarity
inside affine), so a composition belongs to the weakest group any of its factors belongs to.

The classification is deliberately conservative in one direction only. It reads no matrix:
an AFFINE edge reads AFFINE even when its numbers happen to be a rotation, because
separating those needs an SVD. Overstating the damage is safe; understating it is not.

The path-aggregate half keeps mikro's (z, y, x) fixtures, where "anisotropic" means something;
the experiments are built through the ORM (``_helpers.add_layer``), because `createExperiment`
lays out simulations and these tests are about an arbitrary dataset in an arbitrary world.
"""

import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import enums, models
from core.logic import graph as graph_logic
from tests import seed
from tests.coords._helpers import add_layer, counted, create_experiment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


#: A purely spatial grid. `seed.SIMPLE_AXES` leads with a CHANNEL axis, and an "isotropic"
#: scale over that would be scaling an acquisition index -- true of the classifier, which
#: does not look at what an axis means, but a confusing thing for a reader to check against.
SPATIAL_AXES = seed.ZYX_AXES

VIEW_INVARIANCE = """
query ViewInvariance($id: ID!) {
  experiment(id: $id) {
    layers { id placement placementInvariance placementValidity pathToWorld { transformation { id } } }
  }
}
"""

PATH_TO_WORLD = """
query PathToWorld($id: ID!) {
  experiment(id: $id) {
    layers { id placementInvariance pathToWorld { inverted transformation { id kind invariance } } }
  }
}
"""


def _edge(ctx: HttpContext, kind: str, params: dict | None = None, **kwargs) -> models.Transformation:
    """One bare edge, endpoints and all, built through the ORM.

    Directly, not through `createTransformation`: one of the kinds under test (SEQUENCE) is
    refused by that mutation on purpose -- the ingest writes it with its children -- and the
    classifier has to answer for it all the same.
    """
    return models.Transformation.objects.create(
        kind=kind,
        params=params or {},
        creator=ctx.request.user,
        organization=ctx.request.organization,
        **kwargs,
    )


async def _classify(ctx: HttpContext, kind: str, params: dict | None = None, **kwargs) -> str:
    def build_and_classify() -> str:
        return graph_logic.invariance_of(_edge(ctx, kind, params, **kwargs))

    return await sync_to_async(build_and_classify)()


async def _view(aexecute, experiment_id: int | str, query: str = VIEW_INVARIANCE) -> dict:  # noqa: ANN001 - the conftest fixture
    result = await aexecute(query, {"id": str(experiment_id)})
    assert not result.errors, result.errors
    (view,) = result.data["experiment"]["layers"]
    return view


# --- per-edge classification ------------------------------------------------------


@pytest.mark.parametrize("kind", ["IDENTITY", "TRANSLATION", "ROTATION", "MAP_AXIS"])
async def test_the_isometries_are_the_kinds_that_deform_nothing(authenticated_context, kind: str):
    """A relabelling, an offset and a rotation all leave every distance and angle where it was."""
    assert await _classify(authenticated_context, kind) == "ISOMETRY"


async def test_an_isotropic_scale_is_a_similarity(authenticated_context):
    """One factor on every axis: a circle is still a circle, so angles and length ratios survive."""
    assert await _classify(authenticated_context, "SCALE", {"scale": [0.5, 0.5, 0.5]}) == "SIMILARITY"


async def test_an_anisotropic_scale_is_only_affine(authenticated_context):
    """Different factors per axis: a circular bead arrives an ellipse, so no angle survives.

    ABLATION: drop the all-equal check and this reads SIMILARITY -- telling a client that a
    roundness measured in samples means something in world, which is exactly the silent
    wrong answer the class exists to prevent.
    """
    assert await _classify(authenticated_context, "SCALE", {"scale": [1.0, 0.325, 0.325]}) == "AFFINE"


async def test_an_affine_reads_affine_even_when_its_matrix_is_rigid(authenticated_context):
    """A 90-degree rotation written as a matrix is an isometry, and still reads AFFINE.

    The deliberate limit: proving it rigid needs an SVD, which is numerics inside a metadata
    answer. Both this and `is_invertible` err toward claiming less.
    """
    rigid = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0]]
    assert await _classify(authenticated_context, "AFFINE", {"affine": rigid}) == "AFFINE"


async def test_a_field_is_diffeomorphic_at_best(authenticated_context):
    """A map given by an array's values has a position-dependent Jacobian: nothing local transfers."""
    assert await _classify(authenticated_context, "FIELD") == "DIFFEOMORPHIC"


async def test_an_unmappable_edge_corresponds_to_nothing(authenticated_context):
    """The one kind that denies a correspondence denies every property with it."""
    assert await _classify(authenticated_context, "UNMAPPABLE") == "NONE"


async def test_an_unknown_kind_fails_safe():
    """A kind the classifier does not know reads NONE, the bottom -- never a claim of rigidity.

    Unsaved, because `kind` is a choices column and the database will not hold a kind that
    does not exist yet. That is the point: this pins what happens when someone *adds* one
    and forgets the table, so a new kind degrades a client's trust rather than inflating it.
    """
    assert graph_logic.invariance_of(models.Transformation(kind="SOME_FUTURE_KIND", params={})) == "NONE"


# --- composites -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scale", "expected"),
    [([2.0, 2.0, 2.0], "SIMILARITY"), ([1.0, 0.325, 0.325], "AFFINE")],
)
async def test_a_sequence_is_the_weakest_of_its_steps(authenticated_context, scale: list, expected: str):
    """A scale-then-translate sequence takes its class from the scale; the translation is rigid."""

    def build() -> str:
        sequence = _edge(authenticated_context, "SEQUENCE")
        _edge(authenticated_context, "SCALE", {"scale": scale}, parent=sequence, order=0)
        _edge(authenticated_context, "TRANSLATION", {"translation": [1.0, 1.0, 1.0]}, parent=sequence, order=1)
        return graph_logic.invariance_of(sequence)

    assert await sync_to_async(build)() == expected


async def test_a_childless_wrapper_reads_the_map_it_carries(authenticated_context):
    """A BY_DIMENSION with no children carries its map in its own params, and is read that way.

    The one place this must not mirror `is_invertible`, which answers True for a childless
    wrapper because invertibility does not depend on which params ride along. Invariance is
    nothing but that -- and a childless BY_DIMENSION carrying an `affine` is the shape every
    sampling law here is written as.

    ABLATION: return ISOMETRY for a childless wrapper and every sampling law in the system
    reads as rigid.
    """
    assert await _classify(authenticated_context, "BY_DIMENSION", {"affine": [[1.0, 0.5, 10.0], [0.0, 1.0, 20.0]]}) == "AFFINE"


async def test_a_childless_wrapper_with_no_map_is_an_isometry(authenticated_context):
    """Naming axes and nothing else is the identity on the axes named."""
    assert await _classify(authenticated_context, "BY_DIMENSION") == "ISOMETRY"


@pytest.mark.parametrize(
    ("scale", "expected"),
    [([2.0, 2.0], "SIMILARITY"), ([2.0, 3.0], "AFFINE")],
)
async def test_a_childless_wrapper_takes_the_weakest_map_it_carries(authenticated_context, scale: list, expected: str):
    """`_OPTIONAL_PARAMS_BY_KIND` lets one BY_DIMENSION carry several params: the weakest decides.

    ABLATION: return the first match rather than the minimum and an anisotropic scale riding
    beside a translation reads ISOMETRY, from the translation alone.
    """
    assert await _classify(authenticated_context, "BY_DIMENSION", {"scale": scale, "translation": [1.0, 1.0]}) == expected


# --- the path aggregate -----------------------------------------------------------


async def test_an_identity_registration_places_a_layer_isometrically(aexecute, authenticated_context):
    """Nothing on the path deforms anything, so a distance in the data IS a distance in world."""
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Rigid", SPATIAL_AXES, [8, 64, 64])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Rigid experiment")
    await seed.register_into_world(ctx, experiment.world, dataset)
    await add_layer(ctx, experiment, lens)

    assert (await _view(aexecute, experiment.pk))["placementInvariance"] == "ISOMETRY"


async def test_the_weakest_edge_on_the_path_decides(aexecute, authenticated_context):
    """An anisotropic calibration drags an otherwise rigid placement down to AFFINE.

    A **sliced** lens in an experiment over the dataset's physical space walks two edges: the
    crop into the sample grid (a translation -- ISOMETRY, rigid) and the calibration into the
    physical space (unequal steps -- AFFINE, deforming). One deforming step is enough,
    because the groups nest.

    The second hop is what makes this a test rather than a tautology, and it is what the
    ABLATION bites on: take the *first* edge instead of the minimum and this reads ISOMETRY,
    reporting a z-squashed placement as distance-preserving.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Anisotropic", SPATIAL_AXES, [8, 64, 64])
    calibration = await seed.create_physical_space(ctx, dataset, axes=seed.ZYX_WORLD_AXES, scale=[0.5, 0.325, 0.325])
    sliced = await seed.create_lens(ctx, dataset, slices=[{"axis": "y", "start": 8, "stop": 40}])
    experiment = await create_experiment(ctx, "Physical", world=calibration)
    await add_layer(ctx, experiment, sliced)

    view = await _view(aexecute, experiment.pk)
    assert len(view["pathToWorld"]) == 2, f"the minimum below asserts nothing over a one-edge path: {view['pathToWorld']}"
    assert view["placementInvariance"] == "AFFINE", "one anisotropic step decides the whole path"


async def test_an_isotropic_calibration_keeps_the_layer_similar(aexecute, authenticated_context):
    """Equal steps on every axis: shapes and angles survive, and one factor converts lengths."""
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Isotropic", SPATIAL_AXES, [8, 64, 64])
    calibration = await seed.create_physical_space(ctx, dataset, axes=seed.ZYX_WORLD_AXES, scale=[0.325, 0.325, 0.325])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Physical", world=calibration)
    await add_layer(ctx, experiment, lens)

    assert (await _view(aexecute, experiment.pk))["placementInvariance"] == "SIMILARITY", "a scalar length in world units is well defined from here up"


async def test_an_unplaced_layer_reads_none_and_says_why_elsewhere(aexecute, authenticated_context):
    """No path means nothing corresponds -- and `placement` is what distinguishes the two reasons.

    The conflation is deliberate and mirrors `placementValidity`'s UNKNOWN: a client that
    needs to know whether to go looking for a missing registration reads `placement`, not
    this field.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Unplaced", SPATIAL_AXES, [8, 64, 64])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Empty experiment")
    # Registered, viewed, then un-registered: an unplaced view is reached by deleting the
    # claim that placed it -- which is what un-registering *is*.
    edge = await seed.register_into_world(ctx, experiment.world, dataset)
    await add_layer(ctx, experiment, lens)
    await sync_to_async(edge.delete)()

    view = await _view(aexecute, experiment.pk)
    assert view["placementInvariance"] == "NONE"
    assert view["placementValidity"] == "UNKNOWN"
    assert view["placement"] == "UNREGISTERED", "the field that tells a gap from an impossibility"


async def test_an_inverted_step_does_not_change_the_class(aexecute, authenticated_context):
    """Every class here is closed under inversion, which is why the BFS's `inverted` flag needs no handling.

    The edge is authored world -> sample grid, against the direction a placement walks, so the
    path comes back with an inverted step. The inverse of a rotation is a rotation.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Backwards", SPATIAL_AXES, [8, 64, 64])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Backwards experiment")

    def author_reverse_edge() -> None:
        _edge(
            ctx,
            "ROTATION",
            {"affine": [[0.0, -1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]},
            input=experiment.world,
            output=dataset.coordinate_system,
        )

    await sync_to_async(author_reverse_edge)()
    await add_layer(ctx, experiment, lens)

    view = await _view(aexecute, experiment.pk, PATH_TO_WORLD)
    assert any(step["inverted"] for step in view["pathToWorld"]), "the edge points against the walk"
    assert view["placementInvariance"] == "ISOMETRY"


# --- cost and shape ---------------------------------------------------------------


async def test_placement_invariance_costs_no_query_beyond_placement_validity(aexecute, authenticated_context):
    """The class is read off columns and prefetches the graph already fetched.

    `kind` and `params` are local columns of an edge row, and every SceneGraph fetch site
    already prefetches `children` -- so asking for the class adds nothing. A regression here
    means the classification started following a relation, which on an experiment of many
    views is the N+1 that module exists to prevent.
    """
    ctx = authenticated_context
    dataset = await seed.create_dataset(ctx, "Counted", SPATIAL_AXES, [8, 64, 64])
    lens = await seed.create_lens(ctx, dataset)
    experiment = await create_experiment(ctx, "Counted experiment")
    await seed.register_into_world(ctx, experiment.world, dataset)
    await add_layer(ctx, experiment, lens)

    validity_only = "query Q($id: ID!) { experiment(id: $id) { layers { id placementValidity } } }"
    both = "query Q($id: ID!) { experiment(id: $id) { layers { id placementValidity placementInvariance } } }"

    # `counted` warms each document once first: in mikro the layer mutation above had already
    # paid the process' one-off costs (content types, auth), and here nothing has.
    counts = [(await counted(aexecute, query, {"id": str(experiment.pk)}))[1] for query in (validity_only, both)]

    assert counts[0] == counts[1], f"asking for the invariance cost {counts[1] - counts[0]} extra queries"


async def test_the_invariance_is_derived_not_stored():
    """No column, no TextChoices twin -- and the derived fields wear their two distinct names."""
    from elektro_server.schema import schema

    assert "invariance" not in {field.name for field in models.Transformation._meta.get_fields()}, "a stored class could contradict `params`"
    assert not hasattr(enums, "TransformInvarianceChoices"), "a Django choices twin exists only for a column, and there is no column"

    sdl = str(schema)
    assert "enum TransformInvariance" in sdl

    transformation = sdl[sdl.find("interface Transformation ") : sdl.find("\n}", sdl.find("interface Transformation "))]
    assert "invariance: TransformInvariance" in transformation, "the per-edge class lives on the edge"

    view = sdl[sdl.find("interface ExperimentLayer ") : sdl.find("\n}", sdl.find("interface ExperimentLayer "))]
    assert "placementInvariance(" in view and "): TransformInvariance!" in view, "the path aggregate lives on the view, under its own name and taking the coordinate to answer at"
    assert "\n  invariance" not in view, "the bare word belongs to the edge, not the view"
