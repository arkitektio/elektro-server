"""The layers of an experiment: mikro's ``Layer``, one table discriminated by kind.

What is pinned here is the contract, not any one kind's rendering: a layer has exactly the
source its kind draws (checked by the mutations *and* by a database constraint), every create
and every rebind is gated on reachability, the generic mutations restyle compositing only, the
per-kind ones refuse a layer of another kind, and nothing a layer draws goes with it.
"""

import pytest
from django.db import IntegrityError
from asgiref.sync import sync_to_async

from core import models
from tests import seed
from tests.coords._helpers import add_layer

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_LAYER = "mutation ($input: CreateLayerInput!) { createLayer(input: $input) { id kind name order blending opacity visible } }"
UPDATE_LAYER = "mutation ($input: UpdateLayerInput!) { updateLayer(input: $input) { id name order blending opacity visible } }"
DELETE_LAYER = "mutation ($input: DeleteInput!) { deleteLayer(input: $input) }"
UPDATE_TRACE = "mutation ($input: UpdateTraceLayerInput!) { updateTraceLayer(input: $input) { id channelIndex color lineWidth climMin climMax lens { id } } }"
UPDATE_SPIKES = "mutation ($input: UpdateSpikesLayerInput!) { updateSpikesLayer(input: $input) { id tickHeight valueMode sparseDataset { name } } }"
CREATE_ANNOTATION_LAYER = "mutation ($input: CreateAnnotationLayerInput!) { createAnnotationLayer(input: $input) { id kind } }"

LAYERS = """
query ($id: ID!, $filters: ExperimentLayerFilter) {
  layers(filters: $filters) { id kind }
  experiment(id: $id) { layers { __typename kind order } }
}
"""


async def _staged(ctx):  # noqa: ANN001, ANN202
    """A session clock with a (t, c) recording and a raster timed on it, and an experiment over the clock."""
    session = await seed.create_clock(ctx, "session")
    vm = await seed.create_array_dataset(ctx, "Vm", seed.TC_AXES, [[3000, 2]])
    await seed.time_on(ctx, vm.coordinate_system, session, rate="30 kHz")
    raster = await seed.create_sparse_dataset(ctx, "spikes")
    await seed.time_on(ctx, raster.coordinate_system, session, rate="30 kHz")
    experiment = await models.Experiment.objects.acreate(name="E", world=session, creator=ctx.request.user, organization=ctx.request.organization)
    lens = await seed.create_lens(ctx, vm)
    return experiment, vm, lens, raster


async def test_the_generic_create_adds_a_layer_of_any_kind(aexecute, authenticated_context):
    experiment, _, lens, raster = await _staged(authenticated_context)
    trace = await aexecute(CREATE_LAYER, {"input": {"experiment": str(experiment.pk), "kind": "TRACE", "lens": str(lens.pk)}})
    assert not trace.errors, trace.errors
    spikes = await aexecute(CREATE_LAYER, {"input": {"experiment": str(experiment.pk), "kind": "SPIKES", "sparseDataset": str(raster.pk), "opacity": 0.5}})
    assert not spikes.errors, spikes.errors

    assert trace.data["createLayer"] == {"id": trace.data["createLayer"]["id"], "kind": "TRACE", "name": "Vm", "order": 0, "blending": "NORMAL", "opacity": 1.0, "visible": True}
    assert (spikes.data["createLayer"]["order"], spikes.data["createLayer"]["opacity"]) == (1, 0.5), "appended, top to bottom"

    listed = await aexecute(LAYERS, {"id": str(experiment.pk), "filters": {"kind": "SPIKES"}})
    assert not listed.errors, listed.errors
    assert [layer["kind"] for layer in listed.data["layers"]] == ["SPIKES"]
    assert [(layer["__typename"], layer["order"]) for layer in listed.data["experiment"]["layers"]] == [("TraceLayer", 0), ("SpikesLayer", 1)], "resolved to the concrete type by kind"


@pytest.mark.parametrize(
    ("kind", "source", "refusal"),
    [
        ("TRACE", "sparseDataset", "names exactly one source, its `lens`"),
        ("SPIKES", "lens", "names exactly one source, its `sparse_dataset`"),
    ],
)
async def test_a_kind_names_the_one_source_it_draws(aexecute, authenticated_context, kind, source, refusal):
    experiment, _, lens, raster = await _staged(authenticated_context)
    ids = {"lens": str(lens.pk), "sparseDataset": str(raster.pk)}
    res = await aexecute(CREATE_LAYER, {"input": {"experiment": str(experiment.pk), "kind": kind, source: ids[source]}})
    assert res.errors and refusal in str(res.errors[0])


async def test_the_database_refuses_a_layer_with_the_wrong_source(authenticated_context):
    """The mutations check it first, to say it in a sentence; the constraint is what holds for a write that goes around them."""
    experiment, _, lens, raster = await _staged(authenticated_context)
    with pytest.raises(IntegrityError):
        await sync_to_async(models.ExperimentLayer.objects.create)(experiment=experiment, kind="spikes", lens=lens)
    with pytest.raises(IntegrityError):
        await sync_to_async(models.ExperimentLayer.objects.create)(experiment=experiment, kind="trace", lens=lens, sparse_dataset=raster)


async def test_a_raster_with_no_time_axis_is_not_drawn_as_spikes(aexecute, authenticated_context):
    experiment, *_ = await _staged(authenticated_context)
    matrix = await seed.create_sparse_dataset(authenticated_context, "genes", axes=[seed.axis("cell", seed.enums.AxisType.INDEX), seed.axis("gene", seed.enums.AxisType.INDEX)])
    res = await aexecute(CREATE_LAYER, {"input": {"experiment": str(experiment.pk), "kind": "SPIKES", "sparseDataset": str(matrix.pk)}})
    assert res.errors and "is not a spike raster" in str(res.errors[0])


async def test_the_generic_update_restyles_compositing_only(aexecute, authenticated_context):
    experiment, _, lens, _ = await _staged(authenticated_context)
    layer = await add_layer(authenticated_context, experiment, lens)
    res = await aexecute(UPDATE_LAYER, {"input": {"id": str(layer.pk), "name": "membrane", "blending": "ADDITIVE", "opacity": 0.25, "visible": False, "order": 3}})
    assert not res.errors, res.errors
    assert res.data["updateLayer"] == {"id": str(layer.pk), "name": "membrane", "order": 3, "blending": "ADDITIVE", "opacity": 0.25, "visible": False}

    bad = await aexecute(UPDATE_LAYER, {"input": {"id": str(layer.pk), "opacity": 2.0}})
    assert bad.errors, "opacity is 0 to 1"


async def test_a_per_kind_update_refuses_a_layer_of_another_kind(aexecute, authenticated_context):
    experiment, _, lens, _ = await _staged(authenticated_context)
    layer = await add_layer(authenticated_context, experiment, lens)
    res = await aexecute(UPDATE_SPIKES, {"input": {"id": str(layer.pk), "tickHeight": 0.5}})
    assert res.errors and "is a trace layer, not a spikes one" in str(res.errors[0])


async def test_a_trace_layer_is_restyled_and_checked_against_its_lens(aexecute, authenticated_context):
    experiment, _, lens, _ = await _staged(authenticated_context)
    layer = await add_layer(authenticated_context, experiment, lens)
    res = await aexecute(UPDATE_TRACE, {"input": {"id": str(layer.pk), "channelIndex": 1, "color": [255, 0, 0, 255], "lineWidth": 1.5, "climMin": -80, "climMax": 40}})
    assert not res.errors, res.errors
    assert res.data["updateTraceLayer"] == {"id": str(layer.pk), "channelIndex": 1, "color": [255, 0, 0, 255], "lineWidth": 1.5, "climMin": -80.0, "climMax": 40.0, "lens": {"id": str(lens.pk)}}

    for update, refusal in (
        ({"channelIndex": 2}, "selects 2 channel(s)"),
        ({"color": [255, 0, 0]}, "RGBA, four components"),
        ({"climMin": 10, "climMax": -10}, "runs from `climMin` to `climMax`"),
    ):
        bad = await aexecute(UPDATE_TRACE, {"input": {"id": str(layer.pk), **update}})
        assert bad.errors and refusal in str(bad.errors[0]), (update, bad.errors)


async def test_rebinding_a_layer_is_gated_like_creating_one(aexecute, authenticated_context):
    """A rebind is a create of the same layer over another source: a raster no route reaches is refused."""
    experiment, _, lens, raster = await _staged(authenticated_context)
    layer = await sync_to_async(models.ExperimentLayer.objects.create)(experiment=experiment, kind="spikes", sparse_dataset=raster)
    floating = await seed.create_sparse_dataset(authenticated_context, "floating")
    res = await aexecute(UPDATE_SPIKES, {"input": {"id": str(layer.pk), "sparseDataset": str(floating.pk)}})
    assert res.errors and "Nothing relates" in str(res.errors[0])

    moved = await aexecute(UPDATE_SPIKES, {"input": {"id": str(layer.pk), "valueMode": "AMPLITUDE"}})
    assert not moved.errors, moved.errors
    assert moved.data["updateSpikesLayer"] == {"id": str(layer.pk), "tickHeight": None, "valueMode": "AMPLITUDE", "sparseDataset": {"name": "spikes"}}


async def test_one_annotation_layer_per_collection_per_experiment(aexecute, authenticated_context):
    """Drawing on an experiment mints its collection and its one layer; a second layer of it is refused."""
    experiment, *_ = await _staged(authenticated_context)
    drawn = await aexecute(
        "mutation ($input: CreateAnnotationInput!) { createAnnotation(input: $input) { collection { id } } }",
        {"input": {"experiment": str(experiment.pk), "kind": "EVENT", "name": "stim", "vectors": [[0.5]]}},
    )
    assert not drawn.errors, drawn.errors
    collection = drawn.data["createAnnotation"]["collection"]["id"]
    assert await models.ExperimentLayer.objects.filter(annotation_collection_id=collection, kind="annotation").acount() == 1

    second = await aexecute(CREATE_ANNOTATION_LAYER, {"input": {"experiment": str(experiment.pk), "annotationCollection": collection}})
    assert second.errors and "already drawn" in str(second.errors[0])


async def test_deleting_a_layer_deletes_nothing_it_drew(aexecute, authenticated_context):
    experiment, vm, lens, raster = await _staged(authenticated_context)
    trace = await add_layer(authenticated_context, experiment, lens)
    spikes = await sync_to_async(models.ExperimentLayer.objects.create)(experiment=experiment, kind="spikes", sparse_dataset=raster, order=1)
    for layer in (trace, spikes):
        res = await aexecute(DELETE_LAYER, {"input": {"id": str(layer.pk)}})
        assert not res.errors, res.errors
    assert not await models.ExperimentLayer.objects.aexists()
    assert await models.Lens.objects.filter(pk=lens.pk).aexists() and await models.SparseDataset.objects.filter(pk=raster.pk).aexists()


async def test_a_raster_a_picker_names_cannot_be_deleted(aexecute, authenticated_context):
    """The PROTECT half for JSON: a picker entry naming a matrix by id has no foreign key to cascade. Written through the ORM, the way only a future SPARSE colouring could."""
    experiment, _, lens, raster = await _staged(authenticated_context)
    await sync_to_async(models.ExperimentLayer.objects.create)(experiment=experiment, kind="trace", lens=lens, event_color_bys=[{"kind": "SPARSE", "dataset": str(raster.pk)}])
    res = await aexecute("mutation ($input: DeleteSparseDatasetInput!) { deleteSparseDataset(input: $input) }", {"input": {"id": str(raster.pk)}})
    assert res.errors and "colour by a slice of it" in str(res.errors[0]) and "experiment 'E'" in str(res.errors[0])
    assert await models.SparseDataset.objects.filter(pk=raster.pk).aexists()
