"""Coordinate anchors on a sparse dataset.

Ported from mikro's ``tests/test_sparse_anchor_spokes.py``. The third container after the
array and the table: a matrix's axes are enumerations, so an anchor's coordinates are
positions along them -- ``{"unit": 12}`` is the twelfth unit, ``{}`` the whole matrix -- and
the spokes are the ones every container shares. A value unit is refused here as on a table.
"""

import pytest
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

CREATE_SPARSE = """
mutation Create($input: CreateSparseDatasetInput!) {
  createSparseDataset(input: $input) { id }
}
"""

SPARSE_ANCHORS = """
query Anchors($id: ID!) {
  sparseDataset(id: $id) {
    anchors { id coordinates sparse { id } dataset { id } table { id } channelLabel { label } rig { state { mode } } acquisitionMetadata { metadata } }
  }
}
"""

LIST_ANCHORS = """
query List($sparse: ID!) {
  coordinateAnchors(filters: { sparse: { exact: $sparse } }) { id coordinates }
}
"""

CREATE_ANCHOR = """
mutation Attach($input: CreateCoordinateAnchorInput!) {
  createCoordinateAnchor(input: $input) { id coordinates sparse { id } channelLabel { label } acquisitionMetadata { id } }
}
"""

DELETE_SPARSE = """
mutation Delete($input: DeleteSparseDatasetInput!) { deleteSparseDataset(input: $input) }
"""

SHAPE = [40, 12]
RIG = {"mode": "VOLTAGE_CLAMP", "holdingPotential": "-70 mV", "devices": []}


async def _index_table(aexecute, ctx, name: str, key: str) -> str:
    """A table one position of an axis identifies a row of: a single INDEX column."""
    result = await aexecute(
        "mutation Create($input: CreateTableDatasetInput!) { createTableDataset(input: $input) { id } }",
        {"input": await seed.table_input(ctx, name, [{"name": key, "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"}])},
    )
    assert not result.errors, result.errors
    return result.data["createTableDataset"]["id"]


async def _axes(aexecute, ctx, name: str) -> list[dict]:
    """The matrix's two axes, `unit` and `time`, each identified by a table of its own."""
    units = await _index_table(aexecute, ctx, f"{name} units", "unit_id")
    times = await _index_table(aexecute, ctx, f"{name} times", "time_id")
    return [
        {"name": "unit", "identifiedBy": [{"kind": "TABLE", "table": units}]},
        {"name": "time", "identifiedBy": [{"kind": "TABLE", "table": times}]},
    ]


async def _create(aexecute, ctx, name: str, anchors: list[dict] | None = None):
    store = await seed.create_sparse_store(ctx, f"{name}-store", axes=(0,), shape=SHAPE)
    payload: dict = {"name": name, "store": str(store.pk), "axes": await _axes(aexecute, ctx, name)}
    if anchors is not None:
        payload["anchors"] = anchors
    return await aexecute(CREATE_SPARSE, {"input": payload})


async def test_a_sparse_anchor_pins_spokes_to_its_axes(aexecute, authenticated_context):
    """Anchors stated at create land on the matrix with the other containers empty."""
    result = await _create(
        aexecute,
        authenticated_context,
        "Anchored",
        anchors=[
            {"axisAnchors": [{"axis": "unit", "value": 12}], "label": {"label": "pyramidal"}, "rig": RIG},
            {"axisAnchors": [], "acquisitionMetadata": {"metadataString": '{"protocol": "IV"}'}},
        ],
    )
    assert not result.errors, result.errors
    sparse_id = int(result.data["createSparseDataset"]["id"])

    anchors = [anchor async for anchor in models.CoordinateAnchor.objects.filter(sparse_id=sparse_id).order_by("pk")]
    assert [anchor.coordinates for anchor in anchors] == [{"unit": 12}, {}]
    assert all(anchor.dataset_id is None and anchor.table_id is None for anchor in anchors)
    assert all(anchor.organization_id == authenticated_context.request.organization.pk for anchor in anchors)

    label = await models.ChannelLabel.objects.aget(anchor__sparse_id=sparse_id)
    assert label.label == "pyramidal"
    assert await models.RigState.objects.filter(anchor__sparse_id=sparse_id).acount() == 1
    metadata = await models.AcquisitionMetadata.objects.aget(anchor__sparse_id=sparse_id)
    assert metadata.metadata == {"protocol": "IV"}


async def test_a_sparse_dataset_reads_its_anchors_back(aexecute, authenticated_context, other_org_context):
    """`SparseDataset.anchors` and the `coordinateAnchors` list both serve them, within the tenant."""
    result = await _create(aexecute, authenticated_context, "Readable", anchors=[{"axisAnchors": [{"axis": "time", "value": 1}], "label": {"label": "ctrl"}, "rig": RIG}])
    assert not result.errors, result.errors
    sparse_id = result.data["createSparseDataset"]["id"]

    read = await aexecute(SPARSE_ANCHORS, {"id": sparse_id})
    assert not read.errors, read.errors
    [anchor] = read.data["sparseDataset"]["anchors"]
    assert anchor["coordinates"] == {"time": 1}
    assert anchor["sparse"] == {"id": sparse_id}
    assert anchor["dataset"] is None and anchor["table"] is None
    assert anchor["channelLabel"] == {"label": "ctrl"}
    assert anchor["rig"]["state"]["mode"] == "VOLTAGE_CLAMP"

    listed = await aexecute(LIST_ANCHORS, {"sparse": sparse_id})
    assert not listed.errors, listed.errors
    assert [entry["coordinates"] for entry in listed.data["coordinateAnchors"]] == [{"time": 1}]

    foreign = await aexecute(LIST_ANCHORS, {"sparse": sparse_id}, context=other_org_context)
    assert not foreign.errors, foreign.errors
    assert foreign.data["coordinateAnchors"] == []


async def test_an_anchor_must_name_an_axis_of_the_matrix(aexecute, authenticated_context):
    """A key that is not one of the matrix's axes is refused, and nothing is written."""
    result = await _create(aexecute, authenticated_context, "Mispinned", anchors=[{"axisAnchors": [{"axis": "sweep", "value": 0}], "label": {"label": "nope"}}])
    assert result.errors
    assert "['sweep']" in result.errors[0].message and "['unit', 'time']" in result.errors[0].message
    assert not await models.SparseDataset.objects.filter(name="Mispinned").aexists()


async def test_a_value_unit_is_array_only(aexecute, authenticated_context):
    """A matrix's values have one unit stated elsewhere; the array-only spoke is refused."""
    result = await _create(aexecute, authenticated_context, "Unitful", anchors=[{"axisAnchors": [], "valueUnit": {"unit": "mV"}}])
    assert result.errors
    assert "array-only" in result.errors[0].message
    assert not await models.SparseDataset.objects.filter(name="Unitful").aexists()


async def test_metadata_is_attached_to_an_existing_matrix_on_one_anchor(aexecute, authenticated_context):
    """`createCoordinateAnchor` get-or-creates on (sparse, coordinates) and replaces a restated spoke."""
    matrix = await seed.create_sparse_dataset(authenticated_context, "Later")
    sparse_id = str(matrix.pk)
    axis = (await sync_to_async(lambda: matrix.axis_names)())[0]

    first = await aexecute(CREATE_ANCHOR, {"input": {"sparse": sparse_id, "anchor": {"axisAnchors": [{"axis": axis, "value": 3}], "label": {"label": "first"}}}})
    assert not first.errors, first.errors
    second = await aexecute(
        CREATE_ANCHOR,
        {"input": {"sparse": sparse_id, "anchor": {"axisAnchors": [{"axis": axis, "value": 3}], "label": {"label": "second"}, "acquisitionMetadata": {"metadataString": "{}"}}}},
    )
    assert not second.errors, second.errors

    assert first.data["createCoordinateAnchor"]["id"] == second.data["createCoordinateAnchor"]["id"]
    assert second.data["createCoordinateAnchor"]["sparse"] == {"id": sparse_id}
    assert await models.CoordinateAnchor.objects.filter(sparse_id=sparse_id).acount() == 1
    label = await models.ChannelLabel.objects.aget(anchor__sparse_id=sparse_id)
    assert label.label == "second"
    assert await models.AcquisitionMetadata.objects.filter(anchor__sparse_id=sparse_id).acount() == 1

    unknown = await aexecute(CREATE_ANCHOR, {"input": {"sparse": sparse_id, "anchor": {"axisAnchors": [{"axis": "sweep", "value": 0}], "label": {"label": "nope"}}}})
    assert unknown.errors and "['sweep']" in unknown.errors[0].message

    two = await aexecute(CREATE_ANCHOR, {"input": {"sparse": sparse_id, "table": "1", "anchor": {"axisAnchors": [], "label": {"label": "nope"}}}})
    assert two.errors and "exactly one" in two.errors[0].message


async def test_deleting_the_matrix_takes_its_anchors_with_it(aexecute, authenticated_context):
    """An anchor is part of its matrix: cascade, spokes included."""
    created = await _create(aexecute, authenticated_context, "Doomed", anchors=[{"axisAnchors": [], "label": {"label": "gone"}}])
    assert not created.errors, created.errors
    sparse_id = created.data["createSparseDataset"]["id"]
    assert await models.ChannelLabel.objects.filter(anchor__sparse_id=sparse_id).acount() == 1

    deleted = await aexecute(DELETE_SPARSE, {"input": {"id": sparse_id}})
    assert not deleted.errors, deleted.errors
    assert await models.CoordinateAnchor.objects.filter(sparse_id=sparse_id).acount() == 0
    assert await models.ChannelLabel.objects.filter(anchor__sparse_id=sparse_id).acount() == 0


async def test_an_anchor_has_exactly_one_container(authenticated_context):
    """The database refuses an anchor on a matrix and a dataset at once, and fills the organization itself."""
    dataset = await seed.create_array_dataset(authenticated_context, "Constrained")
    matrix = await seed.create_sparse_dataset(authenticated_context, "Constrained")

    def both():
        with transaction.atomic():
            models.CoordinateAnchor.objects.create(dataset=dataset, sparse=matrix, coordinates={})

    with pytest.raises(IntegrityError):
        await sync_to_async(both)()

    on_matrix = await sync_to_async(models.CoordinateAnchor.objects.create)(sparse=matrix, coordinates={"unit": 0})
    assert on_matrix.organization_id == matrix.organization_id
    assert (await sync_to_async(lambda: on_matrix.container)()) == matrix
