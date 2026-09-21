"""Coordinate anchors on a table dataset.

Ported from mikro's ``tests/test_table_anchor_spokes.py``, where the spokes are the
microscope state and the OME block; here they are the rig state, the acquisition metadata,
and the sites of a simulation.

A table's rows are scientific records, but the facts about how they were measured are the
same facts a recording carries, and they live in the same place: a ``CoordinateAnchor``,
pinned to values of the table's coordinate columns rather than to sample indices. One hub,
one set of spokes, two kinds of container; the anchor's check constraint keeps it exactly
one of the two. A value unit is the one spoke a table refuses: its units are its columns'.
"""

import pytest
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

CREATE_TABLE = """
mutation Create($input: CreateTableDatasetInput!) {
  createTableDataset(input: $input) { id }
}
"""

TABLE_ANCHORS = """
query Anchors($id: ID!) {
  tableDataset(id: $id) {
    anchors {
      id
      coordinates
      table { id }
      dataset { id }
      channelLabel { label }
      rig { state { mode } }
      acquisitionMetadata { metadata }
      recordingSite { kind label model { id } }
    }
  }
}
"""

LIST_ANCHORS = """
query List($table: ID!) {
  coordinateAnchors(filters: { table: { exact: $table } }) { id coordinates }
}
"""

CREATE_ANCHOR = """
mutation Attach($input: CreateCoordinateAnchorInput!) {
  createCoordinateAnchor(input: $input) { id coordinates table { id } channelLabel { label } acquisitionMetadata { id } }
}
"""

DELETE_TABLE = """
mutation Delete($input: DeleteTableDatasetInput!) { deleteTableDataset(input: $input) }
"""

#: A per-unit, per-trial table: two INDEX coordinate columns and one measurement.
UNITS = [
    {"name": "unit", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
    {"name": "trial", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
    {"name": "rate", "dtype": "DOUBLE", "role": "ATTRIBUTE"},
]

#: A pure measurement table: no coordinate columns, so its space is the synthetic INDEX axis.
MEASUREMENTS = [
    {"name": "amplitude", "dtype": "DOUBLE", "role": "ATTRIBUTE"},
]

RIG = {"mode": "VOLTAGE_CLAMP", "holdingPotential": "-70 mV", "devices": []}


async def _create(aexecute, ctx, name: str, columns: list[dict], anchors: list[dict] | None = None):
    payload = await seed.table_input(ctx, name, columns)
    if anchors is not None:
        payload["anchors"] = anchors
    return await aexecute(CREATE_TABLE, {"input": payload})


async def test_a_table_anchor_pins_spokes_to_its_coordinate_columns(aexecute, authenticated_context, make_neuron_model):
    """Anchors stated at create land on the table with the dataset side empty."""
    neuron_model = await make_neuron_model()
    result = await _create(
        aexecute,
        authenticated_context,
        "Anchored",
        UNITS,
        anchors=[
            {"axisAnchors": [{"axis": "unit", "value": 3}], "label": {"label": "pyramidal"}, "rig": RIG, "recordingSite": {"model": str(neuron_model.pk), "kind": "VOLTAGE"}},
            {"axisAnchors": [], "acquisitionMetadata": {"metadataString": '{"protocol": "IV"}'}},
        ],
    )
    assert not result.errors, result.errors
    table_id = int(result.data["createTableDataset"]["id"])

    anchors = [anchor async for anchor in models.CoordinateAnchor.objects.filter(table_id=table_id).order_by("pk")]
    assert [anchor.coordinates for anchor in anchors] == [{"unit": 3}, {}]
    assert all(anchor.dataset_id is None for anchor in anchors)
    assert all(anchor.organization_id == authenticated_context.request.organization.pk for anchor in anchors)

    label = await models.ChannelLabel.objects.aget(anchor__table_id=table_id)
    assert label.label == "pyramidal"
    assert await models.RigState.objects.filter(anchor__table_id=table_id).acount() == 1
    site = await models.RecordingSite.objects.aget(anchor__table_id=table_id)
    assert site.model_id == neuron_model.pk
    metadata = await models.AcquisitionMetadata.objects.aget(anchor__table_id=table_id)
    assert metadata.metadata == {"protocol": "IV"}


async def test_a_table_reads_its_anchors_back(aexecute, authenticated_context, other_org_context, make_neuron_model):
    """`TableDataset.anchors` and the `coordinateAnchors` list both serve them, within the tenant."""
    neuron_model = await make_neuron_model()
    result = await _create(
        aexecute,
        authenticated_context,
        "Readable",
        UNITS,
        anchors=[{"axisAnchors": [{"axis": "trial", "value": 1}], "label": {"label": "ctrl"}, "rig": RIG, "recordingSite": {"model": str(neuron_model.pk), "kind": "CURRENT"}}],
    )
    assert not result.errors, result.errors
    table_id = result.data["createTableDataset"]["id"]

    read = await aexecute(TABLE_ANCHORS, {"id": table_id})
    assert not read.errors, read.errors
    [anchor] = read.data["tableDataset"]["anchors"]
    assert anchor["coordinates"] == {"trial": 1}
    assert anchor["table"] == {"id": table_id}
    assert anchor["dataset"] is None
    assert anchor["channelLabel"] == {"label": "ctrl"}
    assert anchor["rig"]["state"]["mode"] == "VOLTAGE_CLAMP"
    assert anchor["recordingSite"]["kind"] == "CURRENT"
    assert anchor["recordingSite"]["model"] == {"id": str(neuron_model.pk)}

    listed = await aexecute(LIST_ANCHORS, {"table": table_id})
    assert not listed.errors, listed.errors
    assert [entry["coordinates"] for entry in listed.data["coordinateAnchors"]] == [{"trial": 1}]

    foreign = await aexecute(LIST_ANCHORS, {"table": table_id}, context=other_org_context)
    assert not foreign.errors, foreign.errors
    assert foreign.data["coordinateAnchors"] == []


async def test_an_anchor_must_name_a_coordinate_column(aexecute, authenticated_context):
    """A key that is not one of the table's axis-typed columns is refused, and nothing is written."""
    result = await _create(aexecute, authenticated_context, "Mispinned", UNITS, anchors=[{"axisAnchors": [{"axis": "sweep", "value": 0}], "label": {"label": "nope"}}])
    assert result.errors
    assert "['sweep']" in result.errors[0].message and "['unit', 'trial']" in result.errors[0].message
    assert not await models.TableDataset.objects.filter(name="Mispinned").aexists()


async def test_a_table_without_coordinate_columns_only_takes_global_anchors(aexecute, authenticated_context):
    """The synthetic `object` axis is not a column: nothing can be pinned along it."""
    refused = await _create(aexecute, authenticated_context, "Flat", MEASUREMENTS, anchors=[{"axisAnchors": [{"axis": "object", "value": 0}], "label": {"label": "nope"}}])
    assert refused.errors
    assert "only be global" in refused.errors[0].message

    accepted = await _create(aexecute, authenticated_context, "Flat", MEASUREMENTS, anchors=[{"axisAnchors": [], "label": {"label": "whole table"}}])
    assert not accepted.errors, accepted.errors
    anchor = await models.CoordinateAnchor.objects.aget(table_id=accepted.data["createTableDataset"]["id"])
    assert anchor.coordinates == {}


async def test_a_value_unit_is_array_only(aexecute, authenticated_context):
    """A table's units are its columns'; a value-unit spoke on it would be a second copy."""
    result = await _create(aexecute, authenticated_context, "Unitful", UNITS, anchors=[{"axisAnchors": [], "valueUnit": {"unit": "mV"}}])
    assert result.errors
    assert "array-only" in result.errors[0].message
    assert not await models.TableDataset.objects.filter(name="Unitful").aexists()


async def test_metadata_is_attached_to_an_existing_table_on_one_anchor(aexecute, authenticated_context):
    """`createCoordinateAnchor` get-or-creates on (table, coordinates) and replaces a restated spoke."""
    created = await _create(aexecute, authenticated_context, "Later", UNITS)
    assert not created.errors, created.errors
    table_id = created.data["createTableDataset"]["id"]

    first = await aexecute(CREATE_ANCHOR, {"input": {"table": table_id, "anchor": {"axisAnchors": [{"axis": "unit", "value": 3}], "label": {"label": "first"}}}})
    assert not first.errors, first.errors
    second = await aexecute(
        CREATE_ANCHOR,
        {"input": {"table": table_id, "anchor": {"axisAnchors": [{"axis": "unit", "value": 3}], "label": {"label": "second"}, "acquisitionMetadata": {"metadataString": "{}"}}}},
    )
    assert not second.errors, second.errors

    assert first.data["createCoordinateAnchor"]["id"] == second.data["createCoordinateAnchor"]["id"]
    assert second.data["createCoordinateAnchor"]["table"] == {"id": table_id}
    assert await models.CoordinateAnchor.objects.filter(table_id=table_id).acount() == 1
    label = await models.ChannelLabel.objects.aget(anchor__table_id=table_id)
    assert label.label == "second"
    assert await models.AcquisitionMetadata.objects.filter(anchor__table_id=table_id).acount() == 1

    unknown = await aexecute(CREATE_ANCHOR, {"input": {"table": table_id, "anchor": {"axisAnchors": [{"axis": "sweep", "value": 0}], "label": {"label": "nope"}}}})
    assert unknown.errors and "['sweep']" in unknown.errors[0].message


async def test_metadata_is_attached_to_an_existing_array_dataset_too(aexecute, authenticated_context):
    """The same mutation serves an array dataset, checked against its axes."""
    dataset = await seed.create_array_dataset(authenticated_context, "Array")

    result = await aexecute(CREATE_ANCHOR, {"input": {"dataset": str(dataset.pk), "anchor": {"axisAnchors": [{"axis": "c", "value": 1}], "label": {"label": "Vm"}}}})
    assert not result.errors, result.errors
    anchor = await models.CoordinateAnchor.objects.select_related("channel_label").aget(dataset=dataset)
    assert anchor.coordinates == {"c": 1}
    assert anchor.table_id is None
    assert anchor.organization_id == dataset.organization_id
    assert anchor.channel_label.label == "Vm"

    both = await aexecute(CREATE_ANCHOR, {"input": {"dataset": str(dataset.pk), "table": "1", "anchor": {"axisAnchors": [], "label": {"label": "nope"}}}})
    assert both.errors and "exactly one" in both.errors[0].message
    neither = await aexecute(CREATE_ANCHOR, {"input": {"anchor": {"axisAnchors": [], "label": {"label": "nope"}}}})
    assert neither.errors and "exactly one" in neither.errors[0].message


async def test_deleting_the_table_takes_its_anchors_with_it(aexecute, authenticated_context):
    """An anchor is part of its table: cascade, spokes included."""
    created = await _create(aexecute, authenticated_context, "Doomed", UNITS, anchors=[{"axisAnchors": [], "label": {"label": "gone"}}])
    assert not created.errors, created.errors
    table_id = created.data["createTableDataset"]["id"]
    assert await models.ChannelLabel.objects.filter(anchor__table_id=table_id).acount() == 1

    deleted = await aexecute(DELETE_TABLE, {"input": {"id": table_id}})
    assert not deleted.errors, deleted.errors
    assert await models.CoordinateAnchor.objects.filter(table_id=table_id).acount() == 0
    assert await models.ChannelLabel.objects.filter(anchor__table_id=table_id).acount() == 0


async def test_an_anchor_has_exactly_one_container(aexecute, authenticated_context):
    """The database refuses an anchor with neither container or both, and fills the organization itself."""
    dataset = await seed.create_array_dataset(authenticated_context, "Constrained")
    created = await _create(aexecute, authenticated_context, "Constrained", UNITS)
    assert not created.errors, created.errors
    table = await models.TableDataset.objects.aget(pk=created.data["createTableDataset"]["id"])
    organization = authenticated_context.request.organization

    def neither():
        with transaction.atomic():
            models.CoordinateAnchor.objects.create(coordinates={}, organization=organization)

    def both():
        with transaction.atomic():
            models.CoordinateAnchor.objects.create(dataset=dataset, table=table, coordinates={})

    with pytest.raises(IntegrityError):
        await sync_to_async(neither)()
    with pytest.raises(IntegrityError):
        await sync_to_async(both)()

    plain = await sync_to_async(models.CoordinateAnchor.objects.create)(dataset=dataset, coordinates={"c": 0})
    assert plain.organization_id == dataset.organization_id
    on_table = await sync_to_async(models.CoordinateAnchor.objects.create)(table=table, coordinates={})
    assert on_table.organization_id == table.organization_id
