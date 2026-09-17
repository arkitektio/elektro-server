"""The coordinate graph through GraphQL: a clock, a sampling law, a lens, and who may see them.

The logic is pinned in ``test_dataset_graph_smoke.py``; this pins what a *client* gets, which
is where a port of this kind actually breaks -- a concrete transformation type missing from
the SDL, a list that forgot its organization, a filter that reads ``null`` as ``false``.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_SYSTEM = """
mutation ($input: CreateCoordinateSystemInput!) {
  createCoordinateSystem(input: $input) {
    id
    name
    axes { order name type unit }
    residents { __typename }
    registrations {
      __typename
      kind
      validity
      invariance
      input { id }
      ... on AffineTransformation { affine }
    }
  }
}
"""

CREATE_LENS = """
mutation ($input: CreateLensInput!) {
  createLens(input: $input) {
    id
    shape
    axisNames
    slices { axis start stop step }
    dataset { id }
    coordinateSystem { id residents { __typename } }
    toParent { kind ... on TranslationTransformation { translation } }
  }
}
"""

SYSTEMS = """
query ($filters: CoordinateSystemFilter) {
  coordinateSystems(filters: $filters) { id name }
}
"""

SYSTEM = """
query ($id: ID!) { coordinateSystem(id: $id) { id } }
"""

DELETE_SYSTEM = """
mutation ($input: DeleteCoordinateSystemInput!) { deleteCoordinateSystem(input: $input) }
"""

IN_VIEW = """
query ($id: ID!, $region: BoundingBoxInput!) {
  coordinateSystem(id: $id) {
    inView(region: $region) {
      source { __typename ... on ArrayDataset { id } }
      extentState
      validity
      invariance
      extent { axis min max }
      path { inverted transformation { kind } }
    }
  }
}
"""


def _clock_input(dataset, period: float, start: float) -> dict:
    return {
        "name": "session clock",
        "axes": [{"name": "t", "type": "TIME", "unit": "second"}],
        "registrations": [{"dataset": str(dataset.pk), "validity": "INFERRED", "transform": {"kind": "AFFINE", "affine": [[period, start]]}}],
    }


# --- the SDL ----------------------------------------------------------------------------


async def test_every_transformation_kind_and_union_member_is_in_the_sdl():
    """A type reachable only through an interface vanishes from the SDL without an error unless it is registered by hand."""
    from elektro_server.schema import schema

    sdl = str(schema)
    for kind in ("Identity", "Scale", "Translation", "Affine", "Rotation", "MapAxis", "Sequence", "ByDimension", "Field", "Unmappable"):
        assert f"type {kind}Transformation implements Transformation" in sdl, f"{kind}Transformation is missing from the SDL"
        if kind != "Sequence":  # a wrapper is never authored directly
            assert f"input {kind}TransformInput" in sdl, f"{kind}TransformInput is missing from the SDL"
    assert "union Resident = ArrayDataset | DataArray | Lens" in sdl
    for member in ("LensDerivedFromInput", "DatasetDerivedFromInput", "CoordinateSystemDerivedFromInput"):
        assert f"input {member}" in sdl
    assert "directive @unionElementOf" in sdl
    for leftover in ("MICROTIME", "SPECTRUM", "TABLE_DATASET", "MeshCollection", "OptikitState", "LightPath", "Phasor"):
        assert leftover not in sdl, f"mikro's '{leftover}' leaked into the schema"
    # The data layer is mikro's, by name: nothing of the old vocabulary is left beside it.
    for gone in ("type Trace ", "TraceLike", "fromTraceLike", "type Dataset ", "AnalogSignalChannel", "TRACE"):
        assert gone not in sdl, f"'{gone}' is still in the schema"


# --- a clock and a sampling law ---------------------------------------------------------------


async def test_a_clock_is_created_with_the_sampling_law_that_registers_a_dataset_onto_it(aexecute, authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [30000])

    res = await aexecute(CREATE_SYSTEM, {"input": _clock_input(dataset, 1 / 30000, 2.0)})
    assert not res.errors, res.errors
    clock = res.data["createCoordinateSystem"]

    assert clock["axes"] == [{"order": 0, "name": "t", "type": "TIME", "unit": "second"}]
    assert clock["residents"] == [], "a clock is a pure reference frame: nothing lives in it"

    (edge,) = clock["registrations"]
    assert edge["__typename"] == "AffineTransformation"
    assert edge["affine"][0] == approx([1 / 30000, 2.0])
    assert (edge["validity"], edge["invariance"]) == ("INFERRED", "AFFINE")
    assert edge["input"]["id"] == str(dataset.coordinate_system_id)


async def test_a_unit_that_does_not_measure_time_is_refused_on_a_time_axis(aexecute):
    res = await aexecute(CREATE_SYSTEM, {"input": {"name": "bad", "axes": [{"name": "t", "type": "TIME", "unit": "millivolt"}]}})
    assert res.errors and "must measure [time]" in str(res.errors[0])


async def test_in_view_reports_where_a_recording_sits_on_its_clock(aexecute, authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    created = await aexecute(CREATE_SYSTEM, {"input": _clock_input(dataset, 0.001, 2.0)})
    clock_id = created.data["createCoordinateSystem"]["id"]

    res = await aexecute(IN_VIEW, {"id": clock_id, "region": {"min": [0.0], "max": [10.0]}})
    assert not res.errors, res.errors
    (hit,) = res.data["coordinateSystem"]["inView"]
    assert hit["source"] == {"__typename": "ArrayDataset", "id": str(dataset.pk)}
    assert (hit["extentState"], hit["validity"], hit["invariance"]) == ("KNOWN", "INFERRED", "AFFINE")
    assert hit["extent"] == [{"axis": "t", "min": approx(1.9995), "max": approx(2.9995)}]
    assert hit["path"] == [{"inverted": False, "transformation": {"kind": "AFFINE"}}]

    later = await aexecute(IN_VIEW, {"id": clock_id, "region": {"min": [5.0], "max": [6.0]}})
    assert later.data["coordinateSystem"]["inView"] == []


# --- lenses -----------------------------------------------------------------------------


async def test_create_lens_derives_shape_system_and_edge_from_the_slices(aexecute, authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.TC_AXES, [30000, 4])

    res = await aexecute(CREATE_LENS, {"input": {"dataset": str(dataset.pk), "slices": [{"axis": "t", "start": 6000, "stop": 9000}, {"axis": "c", "start": 1, "stop": 3}]}})
    assert not res.errors, res.errors
    lens = res.data["createLens"]

    assert lens["shape"] == [3000, 2]
    assert lens["axisNames"] == ["t", "c"]
    assert lens["dataset"]["id"] == str(dataset.pk)
    assert lens["coordinateSystem"]["id"] != str(dataset.coordinate_system_id)
    assert lens["coordinateSystem"]["residents"] == [{"__typename": "Lens"}]
    assert lens["toParent"]["kind"] == "TRANSLATION"
    assert lens["toParent"]["translation"] == approx([6000.0, 1.0])


async def test_an_unsliced_lens_lives_in_its_datasets_grid(aexecute, authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])

    res = await aexecute(CREATE_LENS, {"input": {"dataset": str(dataset.pk)}})
    assert not res.errors, res.errors
    lens = res.data["createLens"]
    assert lens["coordinateSystem"]["id"] == str(dataset.coordinate_system_id)
    assert lens["toParent"] is None
    assert sorted(r["__typename"] for r in lens["coordinateSystem"]["residents"]) == ["ArrayDataset", "DataArray", "Lens"]


async def test_a_dataset_without_axes_cannot_be_given_a_lens(aexecute, make_dataset):
    """A dataset created before it was given axes is not in the graph, and says so rather than failing on a null."""
    dataset = await make_dataset()
    res = await aexecute(CREATE_LENS, {"input": {"dataset": str(dataset.pk)}})
    assert res.errors and "was created without axes" in str(res.errors[0])


# --- lifecycle --------------------------------------------------------------------------------


async def test_a_space_data_lives_in_cannot_be_deleted_directly(aexecute, authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    res = await aexecute(DELETE_SYSTEM, {"input": {"id": str(dataset.coordinate_system_id)}})
    assert res.errors and "data lives in it" in str(res.errors[0])
    assert "ArrayDataset" in str(res.errors[0]), "the refusal names what is in the way"
    assert await models.CoordinateSystem.objects.filter(pk=dataset.coordinate_system_id).aexists()


async def test_a_clock_with_a_registration_is_not_deleted_out_from_under_it(aexecute, authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    created = await aexecute(CREATE_SYSTEM, {"input": _clock_input(dataset, 0.001, 0.0)})
    res = await aexecute(DELETE_SYSTEM, {"input": {"id": created.data["createCoordinateSystem"]["id"]}})
    assert res.errors and "transformation edge(s) and cannot be deleted" in str(res.errors[0])


async def test_an_empty_world_can_be_deleted(aexecute, authenticated_context):
    world = await seed.create_world(authenticated_context, "scratch")
    res = await aexecute(DELETE_SYSTEM, {"input": {"id": str(world.pk)}})
    assert not res.errors, res.errors
    assert not await models.CoordinateSystem.objects.filter(pk=world.pk).aexists()


# --- tenancy ------------------------------------------------------------------------------------
#
# mikro leaves `coordinateSystems` and `transformations` unscoped; this service scopes every read.


async def test_another_organization_sees_none_of_this_graph(aexecute, authenticated_context, other_org_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    created = await aexecute(CREATE_SYSTEM, {"input": _clock_input(dataset, 0.001, 0.0)})
    clock_id = created.data["createCoordinateSystem"]["id"]

    mine = await aexecute(SYSTEMS)
    assert clock_id in {row["id"] for row in mine.data["coordinateSystems"]}

    theirs = await aexecute(SYSTEMS, context=other_org_context)
    assert not theirs.errors, theirs.errors
    assert theirs.data["coordinateSystems"] == []

    edges = await aexecute("{ transformations { id } }", context=other_org_context)
    assert edges.data["transformations"] == []

    by_id = await aexecute(SYSTEM, {"id": clock_id}, context=other_org_context)
    assert by_id.errors, "a by-id lookup must not cross organizations either"


async def test_another_organization_cannot_register_into_or_delete_this_graph(aexecute, authenticated_context, other_org_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    world = await seed.create_world(authenticated_context, "mine")

    stolen = await aexecute(CREATE_SYSTEM, {"input": _clock_input(dataset, 0.001, 0.0)}, context=other_org_context)
    assert stolen.errors, "naming another organization's dataset as a source must fail"

    lens = await aexecute(CREATE_LENS, {"input": {"dataset": str(dataset.pk)}}, context=other_org_context)
    assert lens.errors

    deleted = await aexecute(DELETE_SYSTEM, {"input": {"id": str(world.pk)}}, context=other_org_context)
    assert deleted.errors
    assert await models.CoordinateSystem.objects.filter(pk=world.pk).aexists()


# --- filters ------------------------------------------------------------------------------------


async def test_uninhabited_separates_clocks_from_sample_grids_and_null_means_no_constraint(aexecute, authenticated_context):
    """This service runs strawberry-django's deprecated filters, where an explicit null reaches the resolver.

    mikro's resolver is ``condition if value else ~condition``, which would read ``uninhabited: null``
    as ``false`` and silently drop every clock from the answer.
    """
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    world = await seed.create_world(authenticated_context, "clock")
    grid_id, world_id = str(dataset.coordinate_system_id), str(world.pk)

    async def ids(filters):
        res = await aexecute(SYSTEMS, {"filters": filters})
        assert not res.errors, res.errors
        return {row["id"] for row in res.data["coordinateSystems"]}

    assert await ids({"uninhabited": True}) == {world_id}
    assert await ids({"uninhabited": False}) == {grid_id}
    assert await ids({"uninhabited": None}) == {grid_id, world_id}
    assert await ids({"dataset": str(dataset.pk)}) == {grid_id}
    assert await ids({"search": "cloc"}) == {world_id}


async def test_lenses_placeable_in_a_clock_are_those_of_the_datasets_sampled_onto_it(aexecute, authenticated_context):
    sampled = await seed.create_dataset(authenticated_context, "sampled", seed.T_AXES, [1000])
    floating = await seed.create_dataset(authenticated_context, "floating", seed.T_AXES, [1000])
    clock = await seed.create_physical_space(authenticated_context, sampled, seed.CLOCK_AXES, affine=[[0.001, 0.0]], name="clock")
    placed = await seed.create_lens(authenticated_context, sampled, [{"axis": "t", "start": 0, "stop": 100}])
    await seed.create_lens(authenticated_context, floating)

    res = await aexecute("query ($f: LensFilter) { lenses(filters: $f) { id } }", {"f": {"placeableIn": {"space": str(clock.pk)}}})
    assert not res.errors, res.errors
    assert [row["id"] for row in res.data["lenses"]] == [str(placed.pk)]

    residents = await sync_to_async(lambda: list(clock.datasets.all()))()
    assert residents == [], "the clock still holds nothing: placement is an edge, not residence"
