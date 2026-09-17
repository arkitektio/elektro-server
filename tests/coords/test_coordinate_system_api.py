"""The coordinate space's own API surface: what a space says about itself, and its lifecycle.

Ported from mikro's ``tests/test_coordinate_system_api.py``, minus what
``test_coordinate_api.py`` already pins (the ``uninhabited`` filter, tenancy, deleting an
empty world). What is here is the rest: ``residents``, renaming and anchoring, the
refusals a delete makes, and the audit trail a refinement leaves.

``residents`` is what a space says about itself: the data living in it. A space with **no**
residents is a pure reference frame -- a clock, a world -- and it is exactly those that have
a lifecycle here, because they answer to nobody: experiments adopt one but never own it, so
no experiment's deletion removes a space, and without ``deleteCoordinateSystem`` a mistyped
clock would outlive every correction anyone could make to it. A space data lives in is
described by that data, so renaming or deleting it is refused: it is not an edit of the
space but of the data.

The creator-deletes tests run as ``other_org_context``, the one non-admin identity this
service's static tokens offer: ``can_delete`` waves org admins through before it ever reads
the creator, so an admin-only test cannot tell a working guard from a broken one.
"""

from types import SimpleNamespace

import pytest
from asgiref.sync import sync_to_async

from authentikate.models import Membership, User
from core import enums, guards, models
from tests import seed
from tests.coords._helpers import create_experiment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_CS = """
mutation CreateCS($input: CreateCoordinateSystemInput!) {
  createCoordinateSystem(input: $input) { id name residents { __typename } }
}
"""

UPDATE_CS = """
mutation UpdateCS($input: UpdateCoordinateSystemInput!) {
  updateCoordinateSystem(input: $input) { id name epoch }
}
"""

DELETE_CS = """
mutation DeleteCS($input: DeleteCoordinateSystemInput!) {
  deleteCoordinateSystem(input: $input)
}
"""

SYSTEM = """
query System($id: ID!) {
  coordinateSystem(id: $id) {
    id
    creator { id }
    residents {
      __typename
      ... on ArrayDataset { id name }
      ... on Lens { id }
    }
  }
}
"""

AUDIT = """
query ($id: ID!) {
  transformation(id: $id) {
    id version creator { id }
    ... on ScaleTransformation { scale }
    provenanceEntries { kind }
  }
}
"""

ATLAS_AXES = [
    {"name": "y", "type": "SPACE", "unit": "micrometer"},
    {"name": "x", "type": "SPACE", "unit": "micrometer"},
]


async def _create_space(aexecute, name: str = "Atlas", axes=None, registrations=None, context=None) -> dict:  # noqa: ANN001
    result = await aexecute(CREATE_CS, {"input": {"name": name, "axes": axes if axes is not None else ATLAS_AXES, "registrations": registrations or []}}, context=context)
    assert not result.errors, result.errors
    return result.data["createCoordinateSystem"]


async def _system(aexecute, system_id) -> dict:  # noqa: ANN001
    result = await aexecute(SYSTEM, {"id": str(system_id)})
    assert not result.errors, result.errors
    return result.data["coordinateSystem"]


# --- residents --------------------------------------------------------------------------------


async def test_a_scenes_world_is_an_ordinary_shared_space(aexecute, authenticated_context):
    """A world an experiment composes over is the same thing as an atlas: a space nothing lives in.

    Experiments never own a space, so other experiments may adopt it and it outlives them
    all -- exactly like a space created directly with `createCoordinateSystem`.
    """
    atlas = await _create_space(aexecute, "Atlas")
    assert atlas["residents"] == [], "a space created to be registered into holds no data of its own"

    experiment = await create_experiment(authenticated_context, "Bare")
    shared = await _system(aexecute, experiment.world_id)
    assert shared["residents"] == [], "an experiment adopts its world; nothing of the experiment lives in it"


async def test_a_lens_lives_in_its_own_space_and_a_scene_may_root_there(aexecute, authenticated_context):
    """A lens' crop is a space like any other, related to the dataset's grid by an edge."""
    dataset = await seed.create_dataset(authenticated_context, "A", seed.YX_AXES, [64, 64])

    owned = await _system(aexecute, dataset.coordinate_system_id)
    assert [resident["__typename"] for resident in owned["residents"]] == ["ArrayDataset", "DataArray"], "the dataset, and the level-0 array that IS its grid"

    lens = await seed.create_lens(authenticated_context, dataset, slices=[{"axis": "y", "start": 8, "stop": 40}])
    assert lens.coordinate_system_id != dataset.coordinate_system_id, "a sliced lens gets a space of its own"

    sliced = await _system(aexecute, lens.coordinate_system_id)
    assert [resident["__typename"] for resident in sliced["residents"]] == ["Lens"]

    # And composing there is unusual rather than wrong: an experiment may adopt it as its world.
    experiment = await create_experiment(authenticated_context, "Rooted in a crop", world=await sync_to_async(lambda: lens.coordinate_system)())
    assert experiment.world_id == lens.coordinate_system_id


async def test_residents_name_the_data_living_in_a_space(aexecute, authenticated_context):
    """`residents` resolves to the data itself, and a calibrated space has none.

    The sharpest case is the calibration -- here, a clock. It is simply a space with an edge
    into it -- **nothing lives there** -- which is why it reads exactly like an atlas, and
    why the edge is the only thing relating it to anything.
    """
    dataset = await seed.create_dataset(authenticated_context, "Owned", seed.YX_AXES, [64, 64])

    residents = (await _system(aexecute, dataset.coordinate_system_id))["residents"]
    named = {resident["__typename"]: resident for resident in residents}
    assert named["ArrayDataset"]["name"] == "Owned"

    calibration = await seed.create_physical_space(
        authenticated_context,
        dataset,
        axes=[seed.physical_axis("y", enums.AxisType.SPACE, "micrometer"), seed.physical_axis("x", enums.AxisType.SPACE, "micrometer")],
        scale=[0.325, 0.325],
    )
    physical = await _system(aexecute, calibration.pk)
    assert physical["residents"] == [], "a calibrated space is a space with an edge into it, not a thing a dataset owns"

    experiment = await create_experiment(authenticated_context, "Bare")
    assert (await _system(aexecute, experiment.world_id))["residents"] == []

    atlas = await _create_space(aexecute, "Atlas")
    assert (await _system(aexecute, atlas["id"]))["residents"] == []


async def test_a_dataset_is_listed_before_a_lens_over_it(aexecute, authenticated_context):
    """`residents` is in `graph.CONTAINERS` order: the outermost thing first."""
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    await seed.create_lens(authenticated_context, dataset)

    residents = (await _system(aexecute, dataset.coordinate_system_id))["residents"]
    assert [resident["__typename"] for resident in residents] == ["ArrayDataset", "DataArray", "Lens"]


# --- renaming and anchoring ---------------------------------------------------------------------


async def test_a_shared_space_can_be_renamed_and_its_clock_anchored(aexecute):
    """The fields that describe the space itself. Where its data sits stays an edge."""
    space = await _create_space(aexecute, "Atals")  # the typo this mutation exists for

    result = await aexecute(UPDATE_CS, {"input": {"id": space["id"], "name": "Atlas", "epoch": "2026-07-16T00:00:00+00:00"}})
    assert not result.errors, result.errors
    assert result.data["updateCoordinateSystem"]["name"] == "Atlas"
    assert result.data["updateCoordinateSystem"]["epoch"] is not None

    # Partial: a rename does not clear the clock someone just anchored.
    result = await aexecute(UPDATE_CS, {"input": {"id": space["id"], "name": "Atlas v2"}})
    assert not result.errors, result.errors
    assert result.data["updateCoordinateSystem"]["epoch"] is not None


async def test_a_space_data_lives_in_cannot_be_renamed_or_deleted_directly(aexecute, authenticated_context):
    """Both mutations refuse a space with residents: it is described by the data in it.

    The guard asks the thing directly -- does anything live here -- and the error names the
    resident. (The delete half is also pinned in ``test_coordinate_api.py``; it is kept here
    because the point is that the two mutations share one guard.)
    """
    dataset = await seed.create_dataset(authenticated_context, "A", seed.YX_AXES, [64, 64])
    grid = str(dataset.coordinate_system_id)

    renamed = await aexecute(UPDATE_CS, {"input": {"id": grid, "name": "nope"}})
    assert renamed.errors and "data lives in it" in str(renamed.errors[0])
    assert "ArrayDataset" in str(renamed.errors[0]), "the refusal names what is in the way"

    deleted = await aexecute(DELETE_CS, {"input": {"id": grid}})
    assert deleted.errors and "data lives in it" in str(deleted.errors[0])
    assert await models.CoordinateSystem.objects.filter(pk=grid).aexists(), "the dataset's graph survives"
    assert (await models.CoordinateSystem.objects.aget(pk=grid)).name == "A/intrinsic"


# --- deleting -----------------------------------------------------------------------------------


async def test_an_unused_space_is_deletable_by_its_creator(aexecute, other_org_context):
    """The whole point: a space created by mistake can be taken back.

    Runs as a non-admin, so `can_delete` actually consults the creator rather than
    short-circuiting on the admin role.
    """
    space = await _create_space(aexecute, "Mistake", context=other_org_context)

    result = await aexecute(DELETE_CS, {"input": {"id": space["id"]}}, context=other_org_context)
    assert not result.errors, result.errors
    assert result.data["deleteCoordinateSystem"] == space["id"]
    assert not await models.CoordinateSystem.objects.filter(pk=space["id"]).aexists()


async def test_a_space_someone_else_created_is_not_yours_to_delete(aexecute, authenticated_context):
    """The ownership guard, reached only because the caller is not an org admin.

    mikro runs this through the mutation as a second, non-admin user of the same
    organization. No static token here resolves to one, and roles come off the token at
    resolve time, so the predicate is asked directly -- the way ``tests/test_guards.py`` asks
    it -- about a space the mutation really created.
    """
    space = await _create_space(aexecute, "Theirs")

    def may_delete() -> bool:
        colleague = User.objects.create(username="colleague", sub="77", iss="static_issuer")
        organization = authenticated_context.request.organization
        Membership.objects.get_or_create(user=colleague, organization=organization)
        request = SimpleNamespace(user=colleague, organization=organization, membership=SimpleNamespace(roles=[]))
        return guards.can_delete(SimpleNamespace(context=SimpleNamespace(request=request)), models.CoordinateSystem.objects.get(pk=space["id"]))

    assert await sync_to_async(may_delete)() is False
    assert await models.CoordinateSystem.objects.filter(pk=space["id"]).aexists()


async def test_a_space_in_use_is_refused_rather_than_cascaded_away(aexecute, other_org_context):
    """Each refusal guards a CASCADE that would take something the caller never named."""
    dataset = await seed.create_dataset(other_org_context, "A", seed.YX_AXES, [64, 64])
    registration = {"dataset": str(dataset.pk), "transform": {"kind": "BY_DIMENSION", "inputAxes": ["y", "x"], "outputAxes": ["y", "x"]}}
    space = await _create_space(aexecute, "Populated", registrations=[registration], context=other_org_context)

    # An edge registered into it: deleting the space would delete a placement someone authored.
    result = await aexecute(DELETE_CS, {"input": {"id": space["id"]}}, context=other_org_context)
    assert result.errors and "transformation edge" in str(result.errors[0])

    # Remove the registration, and the same space goes.
    edge = await models.Transformation.objects.aget(output__pk=space["id"], parent__isnull=True)
    await edge.adelete()
    result = await aexecute(DELETE_CS, {"input": {"id": space["id"]}}, context=other_org_context)
    assert not result.errors, result.errors


async def test_a_space_a_scene_composes_over_is_refused(aexecute, authenticated_context):
    """Experiment.world is RESTRICT; the mutation names the experiments instead of raising an IntegrityError.

    The prose is this service's, not mikro's ("is the world of N scene(s)"): four relations
    can lay something out over a space here (`graph.WORLD_RELATIONS`), so the refusal names
    the model it found.
    """
    space = await _create_space(aexecute, "Adopted", axes=[{"name": "t", "type": "TIME", "unit": "second"}])
    world = await models.CoordinateSystem.objects.aget(pk=space["id"])
    experiment = await create_experiment(authenticated_context, "Over it", world=world)

    result = await aexecute(DELETE_CS, {"input": {"id": space["id"]}})
    assert result.errors and "are laid out in" in str(result.errors[0])
    assert f"1 Experiment(s) are laid out in ({experiment.pk})" in str(result.errors[0]), "the refusal names what is in the way"
    assert await models.CoordinateSystem.objects.filter(pk=space["id"]).aexists()


# --- the audit trail ------------------------------------------------------------------------


async def test_refining_an_edge_leaves_a_readable_audit_trail(aexecute, authenticated_context):
    """"updateTransformation refines an edge in place; provenance holds the history" is only true if a client can read it.

    A refinement rewrites the row, so the audit trail is the *only* place the placement's
    earlier states exist. The field is on the Transformation interface, so a concrete kind
    (here SCALE) inherits it.
    """
    dataset = await seed.create_dataset(authenticated_context, "A", seed.YX_AXES, [64, 64])
    space = await _create_space(aexecute, "Atlas")

    created = await aexecute(
        "mutation ($input: CreateTransformationInput!) { createTransformation(input: $input) { id version } }",
        {"input": {"input": str(dataset.coordinate_system_id), "output": space["id"], "transform": {"kind": "SCALE", "scale": [0.5, 0.5]}}},
    )
    assert not created.errors, created.errors
    edge_id = created.data["createTransformation"]["id"]

    refined = await aexecute(
        "mutation ($input: UpdateTransformationInput!) { updateTransformation(input: $input) { id version } }",
        {"input": {"id": edge_id, "scale": [0.51, 0.51]}},
    )
    assert not refined.errors, refined.errors
    assert refined.data["updateTransformation"]["version"] == 2

    result = await aexecute(AUDIT, {"id": edge_id})
    assert not result.errors, result.errors
    edge = result.data["transformation"]

    assert edge["scale"] == [0.51, 0.51], "the row itself carries only the current truth"
    # Two states of one placement, sequentially, in the audit trail: the create and the refine.
    kinds = [entry["kind"] for entry in edge["provenanceEntries"]]
    assert len(kinds) == 2, f"expected a CREATE and an UPDATE entry, got {kinds}"
    assert edge["creator"] is not None


# --- axes -----------------------------------------------------------------------------------


async def test_a_shared_space_takes_its_axes_as_given_but_must_have_some(aexecute):
    """No type ordering is asked of a shared space; a space with no axes is still not a space.

    Having *no* axes is the different case -- such a space composes into nothing and every
    edge into it fails the rank check, so it is refused at the door and rolled back.
    """
    unordered = await aexecute(
        CREATE_CS,
        {"input": {"name": "Space before time", "axes": [{"name": "x", "type": "SPACE", "unit": "micrometer"}, {"name": "t", "type": "TIME", "unit": "second"}], "registrations": []}},
    )
    assert not unordered.errors, str(unordered.errors and unordered.errors[0])

    empty = await aexecute(CREATE_CS, {"input": {"name": "Empty", "axes": [], "registrations": []}})
    assert empty.errors and "no axes" in str(empty.errors[0])
    assert not await models.CoordinateSystem.objects.filter(name="Empty").aexists(), "the rollback leaves no permanent zero-axis space"
