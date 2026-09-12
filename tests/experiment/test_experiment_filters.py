"""GraphQL-level tests for the provenance/creator filters on ``experiments``.

``mine``/``createdBy`` exercise the universal ``CreatorFilterMixin``; the
provenance case exercises ``ProvenanceFilterMixin`` over Experiment's existing
``provenance_entries`` history.
"""

import uuid

import pytest
from asgiref.sync import sync_to_async

from core import models

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


EXPERIMENTS = """
query ($filters: ExperimentFilter) {
  experiments(filters: $filters) { id name }
}
"""


@sync_to_async
def _make_experiment(ctx, *, name, creator):
    trace = models.Trace.objects.create(
        name="t", creator=creator, organization=ctx.request.organization
    )
    return models.Experiment.objects.create(name=name, creator=creator, time_trace=trace)


@sync_to_async
def _other_user():
    from authentikate.models import User

    user, _ = User.objects.get_or_create(
        sub="2", iss="static_issuer", defaults={"username": "static_issuer_2"}
    )
    return user


@sync_to_async
def _attach_task(exp):
    from koherent.models import Task

    task = Task.objects.create(
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
        organization=exp.time_trace.organization,
    )
    entry = exp.provenance_entries.order_by("history_date").first()
    entry.task = task
    entry.save()
    return task


async def test_mine_and_created_by(aexecute, authenticated_context):
    me = authenticated_context.request.user
    other = await _other_user()
    await _make_experiment(authenticated_context, name="mine", creator=me)
    await _make_experiment(authenticated_context, name="theirs", creator=other)

    res = await aexecute(EXPERIMENTS, {"filters": {"mine": True}})
    assert not res.errors, res.errors
    assert [e["name"] for e in res.data["experiments"]] == ["mine"]

    res = await aexecute(EXPERIMENTS, {"filters": {"createdBy": str(other.id)}})
    assert not res.errors, res.errors
    assert [e["name"] for e in res.data["experiments"]] == ["theirs"]


async def test_provenance_root_task(aexecute, authenticated_context):
    me = authenticated_context.request.user
    with_task = await _make_experiment(authenticated_context, name="from-run", creator=me)
    await _make_experiment(authenticated_context, name="manual", creator=me)
    task = await _attach_task(with_task)

    res = await aexecute(EXPERIMENTS, {"filters": {"provenanceRootTask": task.root_task_id}})
    assert not res.errors, res.errors
    assert [e["name"] for e in res.data["experiments"]] == ["from-run"]

    res = await aexecute(EXPERIMENTS, {"filters": {"createdByAgent": False}})
    assert not res.errors, res.errors
    assert [e["name"] for e in res.data["experiments"]] == ["manual"]
