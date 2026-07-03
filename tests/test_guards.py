"""Tests for the deletion guard (``core.guards``) and the generated deletes.

The predicate is exercised directly (admin / creator / bot-creator / anchor
delegation), since roles are sourced from the token at resolve time and can't
be injected through the fixtures. The new schema-level delete mutations are
exercised end-to-end for the cases that don't need injected roles: the creator
may delete, a user from another organization may not, and a sub-object defers
its permission check to its governing anchor.
"""

from types import SimpleNamespace

import pytest
from asgiref.sync import sync_to_async

from authentikate.models import User
from core import guards, models

pytestmark = pytest.mark.django_db(transaction=True)


def _info(user, organization, roles):
    """A minimal Info whose request carries the given identity and roles."""
    request = SimpleNamespace(
        user=user,
        organization=organization,
        membership=SimpleNamespace(roles=roles),
    )
    return SimpleNamespace(context=SimpleNamespace(request=request))


def _make_dataset(ctx):
    return models.Dataset.objects.create(
        name="DS",
        creator=ctx.request.user,
        organization=ctx.request.organization,
        membership=ctx.request.membership,
    )


# --- predicate: can_delete ---------------------------------------------------


def test_creator_can_delete(authenticated_context):
    ctx = authenticated_context
    ds = _make_dataset(ctx)
    info = _info(ctx.request.user, ctx.request.organization, roles=[])
    assert guards.can_delete(info, ds) is True


def test_non_creator_denied(authenticated_context):
    ctx = authenticated_context
    ds = _make_dataset(ctx)
    intruder = User.objects.create(username="intruder", sub="42", iss="static_issuer")
    info = _info(intruder, ctx.request.organization, roles=[])
    assert guards.can_delete(info, ds) is False


def test_admin_can_delete_others(authenticated_context):
    ctx = authenticated_context
    ds = _make_dataset(ctx)
    boss = User.objects.create(username="boss", sub="43", iss="static_issuer")
    info = _info(boss, ctx.request.organization, roles=["admin"])
    assert guards.can_delete(info, ds) is True


def test_bot_creator_denied(authenticated_context):
    # A bot that created the object cannot delete it; ownership belongs to the
    # task assigner (absent here), not the bot account.
    ctx = authenticated_context
    ds = _make_dataset(ctx)
    info = _info(ctx.request.user, ctx.request.organization, roles=["bot"])
    assert guards.can_delete(info, ds) is False


def test_anchor_defers_recording_to_simulation(authenticated_context):
    ctx = authenticated_context
    env = models.ModEnvironment.objects.create(
        name="env", organization=ctx.request.organization
    )
    nm = models.NeuronModel.objects.create(
        name="nm", hash="h1", json_model={}, creator=ctx.request.user, environment=env
    )
    tt = models.Trace.objects.create(
        name="t", creator=ctx.request.user, organization=ctx.request.organization
    )
    sim = models.Simulation.objects.create(
        model=nm, time_trace=tt, name="sim", duration=400.0, creator=ctx.request.user
    )
    rec = models.Recording.objects.create(
        simulation=sim, trace=tt, kind="VOLTAGE", cell="soma", location="0", position="0.5"
    )

    # The recording's governing anchor is its simulation.
    assert guards.resolve_anchor(rec) == sim

    # The simulation's creator may delete the recording...
    info = _info(ctx.request.user, ctx.request.organization, roles=[])
    assert guards.can_delete(info, rec) is True

    # ...an unrelated user may not.
    stranger = User.objects.create(username="stranger", sub="44", iss="static_issuer")
    info_other = _info(stranger, ctx.request.organization, roles=[])
    assert guards.can_delete(info_other, rec) is False


# --- schema-level: generated delete mutations --------------------------------


DELETE_DATASET = """
mutation ($input: DeleteDatasetInput!) { deleteDataset(input: $input) }
"""

DELETE_RECORDING = """
mutation ($input: DeleteInput!) { deleteRecording(input: $input) }
"""


@pytest.mark.asyncio
async def test_delete_denied_for_other_org(aexecute, authenticated_context, other_org_context):
    ds = await sync_to_async(_make_dataset)(authenticated_context)
    res = await aexecute(DELETE_DATASET, {"input": {"id": str(ds.id)}}, context=other_org_context)
    assert res.errors
    assert await models.Dataset.objects.filter(id=ds.id).aexists()


@pytest.mark.asyncio
async def test_delete_recording_defers_to_simulation(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    res = await aexecute(DELETE_RECORDING, {"input": {"id": str(chain.recording.id)}})
    assert not res.errors, res.errors
    assert res.data["deleteRecording"] == str(chain.recording.id)
    assert not await models.Recording.objects.filter(id=chain.recording.id).aexists()
