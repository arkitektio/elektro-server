"""What is in a space, and how a space leaves: `inView` over lookup-timed data, `clearCoordinateSystem`, and the orphan sweep.

The first is a decision this service made against mikro: an irregularly sampled signal or a
variable-step run reaches its clock across a FIELD, which no single matrix expresses. mikro's
pickers leave such data out, and so did `inView` here -- a recording absent from its own clock
while an experiment would happily draw it. It is listed now, badged, and only the *pickers*
stay strict.

The other two are mikro's ``tests/test_space_helpers.py``, which had no counterpart: both
mutations delete spaces nobody named, so what they must *not* take matters more than what they do.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models
from core.logic import clocks
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

IN_VIEW = """
query ($id: ID!, $region: BoundingBoxInput!) {
  coordinateSystem(id: $id) {
    inView(region: $region) {
      source { __typename ... on ArrayDataset { name } }
      extentState
      invariance
      extent { axis }
      path { transformation { kind } }
    }
    placedSystems { id }
  }
}
"""

CLEAR = "mutation ($input: ClearCoordinateSystemInput!) { clearCoordinateSystem(input: $input) }"
SWEEP = "mutation { deleteOrphanedCoordinateSystems }"


# --- inView over a time lookup ------------------------------------------------------------------


async def test_a_lookup_timed_run_is_in_view_of_its_own_clock_without_a_box(aexecute, make_simulation_chain):
    chain = await make_simulation_chain(timing="lookup")
    res = await aexecute(IN_VIEW, {"id": str(chain.clock.pk), "region": {"min": [0.0], "max": [1000.0]}})
    assert not res.errors, res.errors
    space = res.data["coordinateSystem"]

    hits = {hit["source"]["name"]: hit for hit in space["inView"]}
    assert set(hits) == {"sim/soma.v", "sim/iclamp"}, "the recording and the stimulus share the run's grid, and both reach the clock"
    for hit in hits.values():
        assert (hit["extentState"], hit["invariance"]) == ("NON_AFFINE", "DIFFEOMORPHIC")
        assert hit["extent"] == [], "a lookup gives its map as the values of an array: there is no closed form to push a box through"
        assert [step["transformation"]["kind"] for step in hit["path"]] == ["FIELD"]

    # The pickers stay strict: what can be laid out with one map. Only the clock itself qualifies.
    assert [system["id"] for system in space["placedSystems"]] == [str(chain.clock.pk)]


async def test_a_sampled_run_still_has_its_box(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    res = await aexecute(IN_VIEW, {"id": str(chain.clock.pk), "region": {"min": [0.0], "max": [1000.0]}})
    assert not res.errors, res.errors
    assert {hit["extentState"] for hit in res.data["coordinateSystem"]["inView"]} == {"KNOWN"}
    assert str(chain.grid.pk) in {system["id"] for system in res.data["coordinateSystem"]["placedSystems"]}


# --- clearCoordinateSystem ------------------------------------------------------------------------


async def test_clearing_a_world_removes_what_was_laid_into_it_and_nothing_else(aexecute, authenticated_context):
    ctx = seed._creation(authenticated_context)
    world = await seed.create_world(authenticated_context, "timeline")
    wider = await seed.create_world(authenticated_context, "wider")
    session = await sync_to_async(clocks.create_clock)(name="session", ctx=ctx)
    into = await sync_to_async(clocks.write_offset)(source=session, target=world, offset=10**12, ctx=ctx)
    out_of = await sync_to_async(clocks.write_offset)(source=world, target=wider, offset=0, ctx=ctx)

    res = await aexecute(CLEAR, {"input": {"id": str(world.pk)}})
    assert not res.errors, res.errors
    assert res.data["clearCoordinateSystem"] == [str(into.pk)]
    assert not await models.Transformation.objects.filter(pk=into.pk).aexists()
    assert await models.Transformation.objects.filter(pk=out_of.pk).aexists(), "an edge OUT of the space is its own claim into a wider one, and stays"
    assert await models.CoordinateSystem.objects.filter(pk__in=[world.pk, session.pk]).acount() == 2


async def test_a_space_data_lives_in_cannot_be_cleared(aexecute, authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [100])
    res = await aexecute(CLEAR, {"input": {"id": str(dataset.coordinate_system_id)}})
    assert res.errors and "data lives in it" in str(res.errors[0])


# --- the orphan sweep -------------------------------------------------------------------------------


async def test_the_sweep_takes_only_spaces_that_are_nobodys(aexecute, authenticated_context, make_simulation_chain, make_neuron_model):
    """Nothing living in it, nothing laid out over it, no edge touching it, nothing naming it."""
    ctx = seed._creation(authenticated_context)
    orphan = await seed.create_world(authenticated_context, "forgotten")
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [100])
    chain = await make_simulation_chain()  # a clock something is laid out on, and a grid data lives in
    run_clock = await sync_to_async(clocks.create_clock)(name="run clock", ctx=ctx)
    await models.Simulation.objects.acreate(name="R", model=await make_neuron_model(), duration=0, clock=run_clock)
    lonely_experiment_world = await seed.create_world(authenticated_context, "empty experiment")
    await models.Experiment.objects.acreate(name="E", organization=authenticated_context.request.organization, world=lonely_experiment_world)

    res = await aexecute(SWEEP)
    assert not res.errors, res.errors
    assert res.data["deleteOrphanedCoordinateSystems"] == [str(orphan.pk)]

    survivors = {dataset.coordinate_system_id, chain.clock.pk, chain.grid.pk, run_clock.pk, lonely_experiment_world.pk}
    assert await models.CoordinateSystem.objects.filter(pk__in=survivors).acount() == len(survivors), "a clock with no edges is still a run's clock; a world with no layers is still an experiment's"


async def test_the_sweep_leaves_a_space_a_lookup_still_reads_through(aexecute, authenticated_context):
    """Delete a times dataset and its system is empty and touched by no edge's *endpoints* -- but the signal's lookup still names it as its field, under PROTECT. One such row used to be able to fail the whole sweep."""
    ctx = seed._creation(authenticated_context)
    signal = await seed.create_dataset(authenticated_context, "Ca", seed.T_AXES, [50])
    times = await seed.create_dataset(authenticated_context, "Ca/times", seed.T_AXES, [50], value_unit="second")
    clock = await sync_to_async(clocks.create_clock)(name="segment", ctx=ctx)
    await sync_to_async(clocks.write_time_lookup)(grid=signal.coordinate_system, clock=clock, times=times, input_axis="t", ctx=ctx)
    field_system = times.coordinate_system_id

    deleted = await aexecute("mutation ($input: DeleteArrayDatasetInput!) { deleteArrayDataset(input: $input) }", {"input": {"id": str(times.pk)}})
    assert not deleted.errors, deleted.errors

    res = await aexecute(SWEEP)
    assert not res.errors, res.errors
    assert str(field_system) not in res.data["deleteOrphanedCoordinateSystems"]
    assert await models.CoordinateSystem.objects.filter(pk=field_system).aexists()


async def test_another_organization_sweeps_and_clears_nothing_here(aexecute, authenticated_context, other_org_context):
    orphan = await seed.create_world(authenticated_context, "mine, and forgotten")

    swept = await aexecute(SWEEP, context=other_org_context)
    assert not swept.errors, swept.errors
    assert swept.data["deleteOrphanedCoordinateSystems"] == []
    cleared = await aexecute(CLEAR, {"input": {"id": str(orphan.pk)}}, context=other_org_context)
    assert cleared.errors
    assert await models.CoordinateSystem.objects.filter(pk=orphan.pk).aexists()
