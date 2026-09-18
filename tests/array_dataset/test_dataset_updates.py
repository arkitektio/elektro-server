"""A dataset's name and description are editable, audited, and the whole of what can change.

Ported from mikro's ``tests/test_dataset_updates.py``.

Everything that says where the data *is* -- the arrays, the axes, the systems built from them
-- is written at creation and never after. `Axis.order` is written by enumeration and the rest
of the graph is measured against it, so an axis edit is a different space rather than a
correction, and `updateCoordinateSystem` refuses a dataset's own system for exactly that
reason: it serves shared spaces alone.

That leaves a rename as the only mutable fact about a dataset, which is precisely why it is
worth knowing who performed it. `ProvenanceField` records a history row per save, attributed
to the client, user and task the change happened under. These tests pin all three claims --
the surface, the refusal, and the trail -- because the last time this went unasserted the
docstrings drifted into claiming the opposite.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

UPDATE = """
mutation Update($input: UpdateArrayDatasetInput!) {
  updateArrayDataset(input: $input) {
    id
    name
    description
    provenanceEntries { kind user { id } }
  }
}
"""


async def test_a_dataset_can_be_renamed_and_redescribed(aexecute, authenticated_context):
    """The two fields that are editable, edited."""
    dataset = await seed.create_dataset(authenticated_context, "raw")

    result = await aexecute(UPDATE, {"input": {"id": str(dataset.pk), "name": "soma voltage", "description": "the soma channel, low-pass filtered"}})
    assert not result.errors, result.errors

    updated = result.data["updateArrayDataset"]
    assert updated["name"] == "soma voltage"
    assert updated["description"] == "the soma channel, low-pass filtered"

    stored = await sync_to_async(lambda: models.ArrayDataset.objects.get(pk=dataset.pk))()
    assert stored.name == "soma voltage", "the mutation writes through, it does not merely echo"


async def test_a_rename_is_audited(aexecute, authenticated_context):
    """The point of routing a rename through a mutation rather than leaving the column writable.

    Attribution comes from `authentikate.vars.user_var`, which `AuthentikateExtension` sets per
    request and `koherent.signals.add_history_app` reads into `history_instance.history_user` on
    `pre_create_historical_record`. mikro's test sets `user_var` by hand, because its fixture
    context never passes through that extension; here every `aexecute` authenticates the static
    "test" token at resolve time, so the trail asserted is the one the code wrote.

    ABLATION: drop `provenance = ProvenanceField()` from ArrayDataset and no row is written at all --
    the rename still succeeds, and nothing records that it happened.
    """
    dataset = await seed.create_dataset(authenticated_context, "raw")
    before = await sync_to_async(lambda: dataset.provenance_entries.count())()
    user = await sync_to_async(lambda: authenticated_context.request.user)()

    result = await aexecute(UPDATE, {"input": {"id": str(dataset.pk), "name": "renamed once"}})
    assert not result.errors, result.errors

    entries = result.data["updateArrayDataset"]["provenanceEntries"]
    assert len(entries) > before, "a save must leave a history row behind"

    # Selected by kind, not by position: simple_history orders newest-first, so an
    # `entries[-1]` here reaches the CREATE row that `seed.create_dataset` wrote outside
    # any request -- which is legitimately unattributed, and would fail this for the wrong
    # reason.
    renames = [entry for entry in entries if entry["kind"] == "UPDATE"]
    assert len(renames) == 1, f"one rename, one UPDATE row -- got {[e['kind'] for e in entries]}"
    assert renames[0]["user"] is not None, "an unattributed audit trail is not an audit trail"
    assert renames[0]["user"]["id"] == str(user.pk), "and it must name the user who actually did it"

    # A second edit is a second row: the trail accumulates rather than overwriting.
    again = await aexecute(UPDATE, {"input": {"id": str(dataset.pk), "name": "renamed twice"}})
    assert not again.errors, again.errors

    after = await sync_to_async(lambda: dataset.provenance_entries.count())()
    assert after == before + 2, f"two renames, two rows -- got {after - before}"


async def test_a_dataset_update_cannot_reach_its_geometry():
    """The surface itself is the guarantee: there is no field to smuggle an array or an axis through."""
    from elektro_server.schema import schema

    sdl = schema.as_str()
    definition = sdl[sdl.find("input UpdateArrayDatasetInput ") : sdl.find("\n}", sdl.find("input UpdateArrayDatasetInput "))]
    fields = {line.strip().split(":")[0] for line in definition.split("\n") if ":" in line and not line.strip().startswith('"')}
    assert fields == {"id", "name", "description"}, f"updateArrayDataset must not reach the arrays, the axes or the systems, but takes {fields}"


async def test_a_datasets_own_coordinate_system_is_not_updatable(aexecute, authenticated_context):
    """`updateCoordinateSystem` serves shared spaces alone: every other system is named by its owner.

    The refusal that makes "no updates on its coordinate system" true rather than merely
    intended -- a sample grid has data living in it, so it has no lifecycle of its own.
    """
    dataset = await seed.create_dataset(authenticated_context, "raw")
    intrinsic = await sync_to_async(lambda: dataset.intrinsic_coordinate_system)()

    result = await aexecute(
        "mutation Update($input: UpdateCoordinateSystemInput!) { updateCoordinateSystem(input: $input) { id name } }",
        {"input": {"id": str(intrinsic.pk), "name": "hijacked"}},
    )
    assert result.errors, "a dataset's sample grid is not a space with a lifecycle of its own"
    assert "data lives in it" in str(result.errors[0])

    unchanged = await sync_to_async(lambda: models.CoordinateSystem.objects.get(pk=intrinsic.pk))()
    assert unchanged.name != "hijacked"


async def test_another_organization_cannot_rename_this_dataset(aexecute, authenticated_context, other_org_context):
    """Every by-id lookup is organization-scoped here, so the rename fails before it is a rename."""
    dataset = await seed.create_dataset(authenticated_context, "raw")
    result = await aexecute(UPDATE, {"input": {"id": str(dataset.pk), "name": "theirs"}}, context=other_org_context)
    assert result.errors
    assert (await models.ArrayDataset.objects.aget(pk=dataset.pk)).name == "raw"
