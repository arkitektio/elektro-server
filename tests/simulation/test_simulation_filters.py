"""GraphQL-level tests for the provenance/creator filters on ``simulations``.

The ``mine``/``createdBy`` cases exercise the universal ``CreatorFilterMixin``
(direct ``creator`` FK, no history). The provenance cases exercise
``ProvenanceFilterMixin`` against Simulation's ``provenance_entries`` history
(added alongside these filters) and assert the ``.distinct()`` collapsing.
"""

import uuid

import pytest
from asgiref.sync import sync_to_async

from core import models

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


SIMULATIONS = """
query ($filters: SimulationFilter) {
  simulations(filters: $filters) { id name }
}
"""


@sync_to_async
def _make_sim(ctx, *, name, creator):
    """A Simulation in the context's org (scoping reaches org via time_trace)."""
    env = models.ModEnvironment.objects.create(
        name=f"env-{uuid.uuid4().hex}", organization=ctx.request.organization
    )
    nm = models.NeuronModel.objects.create(
        name="nm", hash=uuid.uuid4().hex, json_model={}, creator=creator, environment=env
    )
    trace = models.Trace.objects.create(
        name="t", creator=creator, organization=ctx.request.organization
    )
    return models.Simulation.objects.create(
        model=nm, time_trace=trace, name=name, duration=400.0, creator=creator
    )


@sync_to_async
def _other_user():
    from authentikate.models import User

    user, _ = User.objects.get_or_create(
        sub="2", iss="static_issuer", defaults={"username": "static_issuer_2"}
    )
    return user


@sync_to_async
def _attach_task(sim, **task_kwargs):
    """Point the sim's creation history row at a fresh provenance Task."""
    from koherent.models import Task

    defaults = dict(
        task_id=f"task-{uuid.uuid4().hex}",
        root_task_id=f"root-{uuid.uuid4().hex}",
        assigner_sub="s",
        caller_sub="s",
        agent_sub="s",
        agent_client_id="agent-client",
        issuer="iss",
        token_id=f"tok-{uuid.uuid4().hex}",
        args_hash="h",
        args_hash_algorithm="a",
        organization=sim.time_trace.organization,
    )
    defaults.update(task_kwargs)
    task = Task.objects.create(**defaults)
    entry = sim.provenance_entries.order_by("history_date").first()
    entry.task = task
    entry.save()
    return task


async def test_mine_and_created_by(aexecute, authenticated_context):
    me = authenticated_context.request.user
    other = await _other_user()
    await _make_sim(authenticated_context, name="mine", creator=me)
    await _make_sim(authenticated_context, name="theirs", creator=other)

    res = await aexecute(SIMULATIONS, {"filters": {"mine": True}})
    assert not res.errors, res.errors
    assert [s["name"] for s in res.data["simulations"]] == ["mine"]

    res = await aexecute(SIMULATIONS, {"filters": {"mine": False}})
    assert not res.errors, res.errors
    assert [s["name"] for s in res.data["simulations"]] == ["theirs"]

    res = await aexecute(SIMULATIONS, {"filters": {"createdBy": str(other.id)}})
    assert not res.errors, res.errors
    assert [s["name"] for s in res.data["simulations"]] == ["theirs"]


async def test_provenance_root_task_and_agent(aexecute, authenticated_context):
    me = authenticated_context.request.user
    with_task = await _make_sim(authenticated_context, name="from-run", creator=me)
    await _make_sim(authenticated_context, name="manual", creator=me)
    task = await _attach_task(with_task)

    res = await aexecute(SIMULATIONS, {"filters": {"provenanceRootTask": task.root_task_id}})
    assert not res.errors, res.errors
    assert [s["name"] for s in res.data["simulations"]] == ["from-run"]

    # createdWith matches the task's executing agent client id.
    res = await aexecute(SIMULATIONS, {"filters": {"createdWith": "agent-client"}})
    assert not res.errors, res.errors
    assert [s["name"] for s in res.data["simulations"]] == ["from-run"]

    # createdByAgent partitions task-backed vs human/direct-API records.
    res = await aexecute(SIMULATIONS, {"filters": {"createdByAgent": True}})
    assert not res.errors, res.errors
    assert [s["name"] for s in res.data["simulations"]] == ["from-run"]

    res = await aexecute(SIMULATIONS, {"filters": {"createdByAgent": False}})
    assert not res.errors, res.errors
    assert [s["name"] for s in res.data["simulations"]] == ["manual"]

    # A bogus root task matches nothing.
    res = await aexecute(SIMULATIONS, {"filters": {"provenanceRootTask": "nope"}})
    assert not res.errors, res.errors
    assert res.data["simulations"] == []


async def test_provenance_filter_is_distinct(aexecute, authenticated_context):
    """Two history rows under the same task must not duplicate the instance."""
    me = authenticated_context.request.user
    sim = await _make_sim(authenticated_context, name="edited", creator=me)
    task = await _attach_task(sim)

    @sync_to_async
    def _second_entry_same_task():
        sim.name = "edited-again"
        sim.save()
        entry = sim.provenance_entries.order_by("-history_date").first()
        entry.task = task
        entry.save()

    await _second_entry_same_task()

    res = await aexecute(SIMULATIONS, {"filters": {"provenanceRootTask": task.root_task_id}})
    assert not res.errors, res.errors
    assert len(res.data["simulations"]) == 1
