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
    return models.Folder.objects.create(
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


def test_anchor_defers_a_layer_to_its_experiment(authenticated_context):
    ctx = authenticated_context
    world = models.CoordinateSystem.objects.create(name="world", creator=ctx.request.user, organization=ctx.request.organization)
    experiment = models.Experiment.objects.create(name="e", world=world, creator=ctx.request.user, organization=ctx.request.organization)
    dataset = models.ArrayDataset.objects.create(name="t", creator=ctx.request.user, organization=ctx.request.organization)
    lens = models.Lens.objects.create(dataset=dataset)
    layer = models.ExperimentLayer.objects.create(experiment=experiment, kind="trace", lens=lens)

    # The layer's governing anchor is its experiment.
    assert guards.resolve_anchor(layer) == experiment

    # The experiment's creator may delete the layer...
    info = _info(ctx.request.user, ctx.request.organization, roles=[])
    assert guards.can_delete(info, layer) is True

    # ...an unrelated user may not.
    stranger = User.objects.create(username="stranger", sub="44", iss="static_issuer")
    info_other = _info(stranger, ctx.request.organization, roles=[])
    assert guards.can_delete(info_other, layer) is False


def test_anchor_defers_a_site_spoke_to_its_dataset(authenticated_context):
    ctx = authenticated_context
    dataset = models.ArrayDataset.objects.create(name="soma.v", creator=ctx.request.user, organization=ctx.request.organization)
    anchor = models.CoordinateAnchor.objects.create(dataset=dataset, coordinates={})
    environment = models.ModEnvironment.objects.create(name="env", organization=ctx.request.organization)
    neuron_model = models.NeuronModel.objects.create(name="soma", hash="soma", creator=ctx.request.user, environment=environment)
    site = models.RecordingSite.objects.create(anchor=anchor, model=neuron_model, kind="VOLTAGE", cell="soma", location="0", position=0.5)
    assert guards.resolve_anchor(site) == dataset


def test_anchor_defers_a_spoke_to_its_table(authenticated_context):
    """An anchor on a table is part of the table: whoever may delete the table may delete its spokes."""
    ctx = authenticated_context
    store = models.ParquetStore.objects.create(organization=ctx.request.organization, key="units.parquet", bucket="parquet", populated=True)
    table = models.TableDataset.objects.create(name="units", store=store, creator=ctx.request.user, organization=ctx.request.organization)
    anchor = models.CoordinateAnchor.objects.create(table=table, coordinates={})
    label = models.ChannelLabel.objects.create(anchor=anchor, label="pyramidal")
    assert guards.resolve_anchor(anchor) == table
    assert guards.resolve_anchor(label) == table


def test_anchor_defers_a_spoke_to_its_sparse_dataset(authenticated_context):
    """And likewise for a sparse matrix: the anchor is part of the matrix."""
    ctx = authenticated_context
    matrix = models.SparseDataset.objects.create(name="expression", creator=ctx.request.user, organization=ctx.request.organization)
    anchor = models.CoordinateAnchor.objects.create(sparse=matrix, coordinates={"feature": 3})
    label = models.ChannelLabel.objects.create(anchor=anchor, label="GAD1")
    assert guards.resolve_anchor(anchor) == matrix
    assert guards.resolve_anchor(label) == matrix


# --- schema-level: generated delete mutations --------------------------------


DELETE_DATASET = """
mutation ($input: DeleteFolderInput!) { deleteFolder(input: $input) }
"""

DELETE_LAYER = """
mutation ($input: DeleteInput!) { deleteLayer(input: $input) }
"""


@pytest.mark.asyncio
async def test_delete_denied_for_other_org(aexecute, authenticated_context, other_org_context):
    ds = await sync_to_async(_make_dataset)(authenticated_context)
    res = await aexecute(DELETE_DATASET, {"input": {"id": str(ds.id)}}, context=other_org_context)
    assert res.errors
    assert await models.Folder.objects.filter(id=ds.id).aexists()


@pytest.mark.asyncio
async def test_delete_layer_defers_to_its_experiment(aexecute, authenticated_context):
    from tests import seed
    from tests.coords._helpers import add_layer, create_experiment

    dataset = await seed.create_array_dataset(authenticated_context, "recording", seed.T_AXES, [[100]])
    experiment = await create_experiment(authenticated_context, axes=seed.CLOCK_AXES)
    layer = await add_layer(authenticated_context, experiment, await seed.create_lens(authenticated_context, dataset))
    res = await aexecute(DELETE_LAYER, {"input": {"id": str(layer.pk)}})
    assert not res.errors, res.errors
    assert res.data["deleteLayer"] == str(layer.pk)
    assert not await models.ExperimentLayer.objects.filter(pk=layer.pk).aexists()
    assert await models.ArrayDataset.objects.filter(pk=dataset.pk).aexists(), "a layer draws data; removing it removes nothing it drew"
