"""Annotations executed against the schema: events, epochs and measurements, and the space they are drawn in.

An annotation replaced the ROI, which hung off one dataset by a foreign key and kept its extent
in two integer columns of sample indices: it could mark one dataset and nothing else, in one
unit and no other. An annotation belongs to a *collection*, the collection owns its drawing
space, and what that space is related to decides what the marks mean -- so these tests draw on
each of the three surfaces a client has: a dataset, a segment's clock, an experiment's timeline.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_COLLECTION = """
mutation ($input: CreateAnnotationCollectionInput!) {
  createAnnotationCollection(input: $input) {
    id
    name
    description
    experiment { id }
    coordinateSystem { id name axes { name type unit } residents { __typename } }
    derivedFrom { kind output { id } }
    annotations { id }
  }
}
"""

ANNOTATION_FIELDS = """
    id
    name
    description
    kind
    vectors
    coordinates { name value }
    intrinsicBbox { min max }
    strokeColor
    fillColor
    strokeWidth
    filled
    createdWithTransforms
    collection { id name }
    coordinateSystem { id }
"""

CREATE_ANNOTATION = "mutation ($input: CreateAnnotationInput!) { createAnnotation(input: $input) { %s } }" % ANNOTATION_FIELDS
CREATE_ANNOTATIONS = "mutation ($input: CreateAnnotationsInput!) { createAnnotations(input: $input) { %s } }" % ANNOTATION_FIELDS
UPDATE_ANNOTATION = "mutation ($input: UpdateAnnotationInput!) { updateAnnotation(input: $input) { %s } }" % ANNOTATION_FIELDS
DELETE_ANNOTATION = "mutation ($input: DeleteAnnotationInput!) { deleteAnnotation(input: $input) }"
DELETE_COLLECTION = "mutation ($input: DeleteAnnotationCollectionInput!) { deleteAnnotationCollection(input: $input) }"
ANNOTATIONS = "query ($filters: AnnotationFilter) { annotations(filters: $filters) { name kind } }"

T = [{"name": "t", "type": "TIME"}]
OVER_T = {"kind": "BY_DIMENSION", "inputAxes": ["t"], "outputAxes": ["t"]}


async def _collection(aexecute, name="marks", axes=None, derived_from=None, context=None):
    res = await aexecute(CREATE_COLLECTION, {"input": {"name": name, "axes": axes or T, "derivedFrom": derived_from}}, context=context)
    assert not res.errors, res.errors
    return res.data["createAnnotationCollection"]


# --- the SDL ----------------------------------------------------------------------------


async def test_the_kinds_are_electrophysiologys_and_the_roi_is_gone():
    from elektro_server.schema import schema

    sdl = schema.as_str()
    kinds = sdl[sdl.index("enum AnnotationKind {") :].split("}")[0]
    assert [line.strip() for line in kinds.splitlines() if line.strip().isupper()] == ["EVENT", "EVENTS", "EPOCH", "LINE", "PATH", "POLYGON"]
    for gone in ("type ROI", "RoiKind", "createRoi", "updateRoi", "deleteRoi", "pinRoi", "rois"):
        assert gone not in sdl, f"'{gone}' survived the removal of the ROI"
    assert "union Resident = ArrayDataset | DataArray | Lens | TableDataset | AnnotationCollection | SparseDataset" in sdl


# --- drawn over a dataset: marks in samples ---------------------------------------------------


async def test_a_collection_drawn_over_a_dataset_marks_it_in_samples(aexecute, authenticated_context):
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [30000])
    collection = await _collection(aexecute, "detected spikes", derived_from=[{"kind": "DATASET", "dataset": str(dataset.pk), "transform": OVER_T}])

    assert collection["coordinateSystem"]["name"] == "detected spikes/drawing"
    assert collection["coordinateSystem"]["axes"] == [{"name": "t", "type": "TIME", "unit": None}]
    assert collection["coordinateSystem"]["residents"] == [{"__typename": "AnnotationCollection"}], "the collection lives in the space it owns"
    assert collection["derivedFrom"] == [{"kind": "BY_DIMENSION", "output": {"id": str(dataset.coordinate_system_id)}}]

    res = await aexecute(CREATE_ANNOTATION, {"input": {"collection": collection["id"], "kind": "EVENT", "name": "spike", "vectors": [[340]]}})
    assert not res.errors, res.errors
    event = res.data["createAnnotation"]
    assert (event["kind"], event["vectors"], event["name"]) == ("EVENT", [[340.0]], "spike")
    assert event["intrinsicBbox"] == {"min": [339.5], "max": [340.5]}, "a vertex over a sample grid names a sample, and sample n covers [n - 0.5, n + 0.5)"
    assert event["strokeColor"] == [255, 255, 255, 255] and event["filled"] is False

    # The dataset answers for the marks made on it -- from the graph: the collection keeps no dataset column.
    asked = await aexecute("query ($id: ID!) { arrayDataset(id: $id) { annotationCollections { name annotations { name } } } }", {"id": str(dataset.pk)})
    assert not asked.errors, asked.errors
    assert asked.data["arrayDataset"]["annotationCollections"] == [{"name": "detected spikes", "annotations": [{"name": "spike"}]}]
    assert not [field.name for field in models.AnnotationCollection._meta.get_fields() if field.name == "dataset"]

    by_dataset = await aexecute(ANNOTATIONS, {"filters": {"dataset": str(dataset.pk)}})
    assert by_dataset.data["annotations"] == [{"name": "spike", "kind": "EVENT"}]


async def test_an_epoch_is_two_corners_whatever_axes_the_space_has(aexecute):
    """One kind, stored one way: an interval in (t), an interval over a run of channels in (t, c), over a range of values in (t, v)."""
    plain = await _collection(aexecute, "bursts")
    res = await aexecute(CREATE_ANNOTATION, {"input": {"collection": plain["id"], "kind": "EPOCH", "name": "burst", "vectors": [[3.0], [4.5]]}})
    assert not res.errors, res.errors
    assert res.data["createAnnotation"]["intrinsicBbox"] == {"min": [3.0], "max": [4.5]}, "a freestanding space has no grid to have cells of: no padding"

    wide = await _collection(aexecute, "artifacts", axes=[{"name": "t", "type": "TIME"}, {"name": "c", "type": "CHANNEL"}])
    res = await aexecute(CREATE_ANNOTATION, {"input": {"collection": wide["id"], "kind": "EPOCH", "name": "movement", "vectors": [[10.0, 3], [12.0, 7]]}})
    assert not res.errors, res.errors
    assert res.data["createAnnotation"]["intrinsicBbox"] == {"min": [10.0, 3.0], "max": [12.0, 7.0]}


async def test_a_measurement_is_drawn_against_a_value_axis(aexecute):
    """A line from baseline to peak needs somewhere to be drawn: the VALUE axis, which only a drawing space has."""
    collection = await _collection(aexecute, "amplitudes", axes=[{"name": "t", "type": "TIME"}, {"name": "v", "type": "VALUE"}])
    assert [axis["type"] for axis in collection["coordinateSystem"]["axes"]] == ["TIME", "VALUE"]

    res = await aexecute(CREATE_ANNOTATION, {"input": {"collection": collection["id"], "kind": "LINE", "name": "EPSP amplitude", "vectors": [[12.0, -65.0], [14.5, -58.2]]}})
    assert not res.errors, res.errors
    assert res.data["createAnnotation"]["intrinsicBbox"] == {"min": [12.0, -65.0], "max": [14.5, -58.2]}


# --- drawn on a clock: marks every signal of the segment ----------------------------------------


async def test_a_collection_drawn_on_a_clock_marks_everything_timed_against_it(aexecute, authenticated_context):
    """What Neo's events and epochs are: they belong to the segment, not to one signal of it."""
    from core.logic import clocks

    ctx = seed._creation(authenticated_context)
    clock = await sync_to_async(clocks.create_clock)(name="segment clock", ctx=ctx)
    for name in ("Vm", "Im"):
        dataset = await seed.create_dataset(authenticated_context, name, seed.T_AXES, [1000])
        await sync_to_async(clocks.write_sampling_law)(grid=dataset.coordinate_system, clock=clock, sampling_rate=1000 * 10**9, t_start=0, ctx=ctx)

    collection = await _collection(aexecute, "protocol", derived_from=[{"kind": "COORDINATE_SYSTEM", "coordinateSystem": str(clock.pk), "transform": OVER_T}])
    res = await aexecute(CREATE_ANNOTATION, {"input": {"collection": collection["id"], "kind": "EVENT", "name": "stimulus onset", "vectors": [[0.25]]}})
    assert not res.errors, res.errors
    assert res.data["createAnnotation"]["intrinsicBbox"] == {"min": [0.25], "max": [0.25]}, "on a clock a vertex is an instant, and an instant has no width"

    asked = await aexecute("query ($id: ID!) { coordinateSystem(id: $id) { annotations { name } } }", {"id": str(clock.pk)})
    assert not asked.errors, asked.errors
    assert asked.data["coordinateSystem"]["annotations"] == [{"name": "stimulus onset"}]

    over_clock = await aexecute("query ($f: AnnotationCollectionFilter) { annotationCollections(filters: $f) { name } }", {"f": {"drawnOver": str(clock.pk)}})
    assert over_clock.data["annotationCollections"] == [{"name": "protocol"}]


# --- drawn on an experiment: marks on the timeline ----------------------------------------------


EXPERIMENT_ANNOTATIONS = """
query ($id: ID!) {
  experiment(id: $id) {
    annotationCollection { id name coordinateSystem { axes { name type unit } } annotations { name } }
    layers {
      kind
      order
      visible
      ... on AnnotationLayer { annotationCollection { name } }
      placement
      placementValidity
      placementInvariance
      pathToWorld { inverted transformation { kind validity } }
      asAffine { matrix inputAxes outputAxes }
    }
    world { annotations { name } registrations { input { name } } }
  }
}
"""


async def _experiment_with_a_trace(aexecute, chain, name: str) -> dict:  # noqa: ANN001
    """An experiment over a minted world, the run's clock placed on it at zero, and a trace of its recording."""
    created = await aexecute("mutation ($input: CreateExperimentInput!) { createExperiment(input: $input) { id world { id } } }", {"input": {"name": name}})
    assert not created.errors, created.errors
    experiment = created.data["createExperiment"]
    placed = await aexecute(
        "mutation ($input: CreateClockOffsetInput!) { createClockOffset(input: $input) { id } }",
        {"input": {"clock": str(chain.clock.pk), "onto": experiment["world"]["id"], "offset": "0 s"}},
    )
    assert not placed.errors, placed.errors
    traced = await aexecute("mutation ($input: CreateTraceLayerInput!) { createTraceLayer(input: $input) { id } }", {"input": {"experiment": experiment["id"], "dataset": str(chain.recording.pk)}})
    assert not traced.errors, traced.errors
    return experiment


async def test_drawing_on_an_experiment_mints_its_collection_once(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    experiment_id = (await _experiment_with_a_trace(aexecute, chain, "Paired pulse"))["id"]

    first = await aexecute(CREATE_ANNOTATION, {"input": {"experiment": experiment_id, "kind": "EPOCH", "name": "baseline", "vectors": [[0.0], [0.01]]}})
    assert not first.errors, first.errors
    second = await aexecute(CREATE_ANNOTATION, {"input": {"experiment": experiment_id, "kind": "EVENT", "name": "pulse 1", "vectors": [[0.012]]}})
    assert not second.errors, second.errors
    assert first.data["createAnnotation"]["collection"] == second.data["createAnnotation"]["collection"], "the first draw mints the collection, every later one appends to it"
    assert first.data["createAnnotation"]["collection"]["name"] == "Paired pulse/annotations"
    assert first.data["createAnnotation"]["intrinsicBbox"] == {"min": [0.0], "max": [0.01]}, "drawn in the world's seconds: no half-second padding"

    asked = await aexecute(EXPERIMENT_ANNOTATIONS, {"id": experiment_id})
    assert not asked.errors, asked.errors
    experiment = asked.data["experiment"]
    assert experiment["annotationCollection"]["coordinateSystem"]["axes"] == [{"name": "t", "type": "TIME", "unit": None}], "the world's axes, copied; the identity edge is what makes the numbers seconds"
    assert sorted(a["name"] for a in experiment["annotationCollection"]["annotations"]) == ["baseline", "pulse 1"]

    (view,) = [layer for layer in experiment["layers"] if layer["kind"] == "ANNOTATION"]
    assert (view["annotationCollection"]["name"], view["visible"], view["order"]) == ("Paired pulse/annotations", True, 1), "after the trace layer"
    assert (view["placement"], view["placementValidity"], view["placementInvariance"]) == ("PLACED", "VALIDATED", "ISOMETRY"), "an identity between two spaces with the same axes is exact"
    assert view["pathToWorld"] == [{"inverted": False, "transformation": {"kind": "BY_DIMENSION", "validity": "VALIDATED"}}]
    assert view["asAffine"]["matrix"][0] == approx([1.0, 0.0])

    assert sorted(a["name"] for a in experiment["world"]["annotations"]) == ["baseline", "pulse 1"]
    assert await models.AnnotationCollection.objects.filter(experiment_id=experiment_id).acount() == 1


async def test_deleting_the_experiment_keeps_what_was_drawn_on_it(aexecute, make_simulation_chain):
    """An annotation belongs to a collection, never to an experiment: the space it is drawn in has not gone anywhere."""
    chain = await make_simulation_chain()
    experiment = await _experiment_with_a_trace(aexecute, chain, "Short lived")
    drawn = await aexecute(CREATE_ANNOTATION, {"input": {"experiment": experiment["id"], "kind": "EVENT", "name": "kept", "vectors": [[0.002]]}})
    assert not drawn.errors, drawn.errors

    deleted = await aexecute("mutation ($input: DeleteInput!) { deleteExperiment(input: $input) }", {"input": {"id": experiment["id"]}})
    assert not deleted.errors, deleted.errors

    assert await models.Annotation.objects.filter(name="kept").aexists()
    collection = await models.AnnotationCollection.objects.aget(name="Short lived/annotations")
    assert collection.experiment_id is None, "only the bookkeeping link is cleared"
    asked = await aexecute("query ($id: ID!) { coordinateSystem(id: $id) { annotations { name } } }", {"id": experiment["world"]["id"]})
    assert asked.data["coordinateSystem"]["annotations"] == [{"name": "kept"}], "and it is still placed in the surviving world"


# --- search ---------------------------------------------------------------------------------------


async def test_range_search_is_an_index_scan_within_one_frame(aexecute):
    collection = await _collection(aexecute, "events")
    specs = [
        {"kind": "EVENT", "name": "a", "vectors": [[1.0]]},
        {"kind": "EVENT", "name": "b", "vectors": [[2.0]], "coordinates": [{"name": "c", "value": 3}]},
        {"kind": "EPOCH", "name": "long", "vectors": [[1.5], [9.0]]},
        {"kind": "EVENTS", "name": "train", "vectors": [[20.0], [20.1], [20.2]]},
    ]
    drawn = await aexecute(CREATE_ANNOTATIONS, {"input": {"collection": collection["id"], "annotations": specs}})
    assert not drawn.errors, drawn.errors
    assert [a["name"] for a in drawn.data["createAnnotations"]] == ["a", "b", "long", "train"]
    assert drawn.data["createAnnotations"][3]["intrinsicBbox"] == {"min": [20.0], "max": [20.2]}, "several instants, one box"

    async def names(filters):
        res = await aexecute(ANNOTATIONS, {"filters": {"collection": collection["id"], **filters}})
        assert not res.errors, res.errors
        return sorted(a["name"] for a in res.data["annotations"])

    assert await names({"intersects": {"min": [1.8], "max": [2.5]}}) == ["b", "long"]
    assert await names({"containsPoint": [5.0]}) == ["long"], "the epochs in force at one instant"
    assert await names({"pinnedTo": [{"name": "c", "value": 3}]}) == ["b"]
    assert await names({"kind": "EVENT"}) == ["a", "b"]
    assert await names({"search": "tra"}) == ["train"]

    nearest = await aexecute("query ($c: ID!) { nearestAnnotations(collection: $c, point: [19.0], limit: 2) { name } }", {"c": collection["id"]})
    assert not nearest.errors, nearest.errors
    assert [a["name"] for a in nearest.data["nearestAnnotations"]] == ["train", "long"]


async def test_a_range_query_must_say_which_frame_it_is_in(aexecute):
    """Boxes only compare within one frame: unscoped, this would compare samples with seconds and call the mismatches results."""
    res = await aexecute(ANNOTATIONS, {"filters": {"intersects": {"min": [0.0], "max": [1.0]}}})
    assert res.errors and "compares boxes within one frame" in str(res.errors[0])


# --- editing ------------------------------------------------------------------------------------------


async def test_moving_an_annotation_moves_its_box(aexecute):
    """The box is a cache of the vectors. The ROI's `min_t`/`max_t` were written at creation only, so a dragged ROI kept answering range queries from where it was first drawn."""
    collection = await _collection(aexecute)
    drawn = await aexecute(CREATE_ANNOTATION, {"input": {"collection": collection["id"], "kind": "EPOCH", "vectors": [[1.0], [2.0]]}})
    annotation_id = drawn.data["createAnnotation"]["id"]

    moved = await aexecute(UPDATE_ANNOTATION, {"input": {"id": annotation_id, "vectors": [[30.0], [45.0]], "name": "moved", "strokeColor": [255, 0, 0, 255]}})
    assert not moved.errors, moved.errors
    assert moved.data["updateAnnotation"]["intrinsicBbox"] == {"min": [30.0], "max": [45.0]}
    assert (moved.data["updateAnnotation"]["name"], moved.data["updateAnnotation"]["strokeColor"]) == ("moved", [255, 0, 0, 255])

    renamed = await aexecute(UPDATE_ANNOTATION, {"input": {"id": annotation_id, "description": "still there"}})
    assert renamed.data["updateAnnotation"]["intrinsicBbox"] == {"min": [30.0], "max": [45.0]}, "an edit that does not move it leaves its box alone"

    found = await aexecute(ANNOTATIONS, {"filters": {"collection": collection["id"], "containsPoint": [40.0]}})
    assert [a["name"] for a in found.data["annotations"]] == ["moved"]


async def test_delete_annotation_and_collection(aexecute):
    collection = await _collection(aexecute, "temporary")
    drawn = await aexecute(CREATE_ANNOTATION, {"input": {"collection": collection["id"], "kind": "EVENT", "vectors": [[1.0]]}})
    annotation_id = drawn.data["createAnnotation"]["id"]

    res = await aexecute(DELETE_ANNOTATION, {"input": {"id": annotation_id}})
    assert not res.errors, res.errors
    assert not await models.Annotation.objects.filter(pk=annotation_id).aexists()
    assert await models.AnnotationCollection.objects.filter(pk=collection["id"]).aexists(), "its collection, and the space it was drawn in, stay"

    res = await aexecute(DELETE_COLLECTION, {"input": {"id": collection["id"]}})
    assert not res.errors, res.errors
    assert not await models.CoordinateSystem.objects.filter(pk=collection["coordinateSystem"]["id"]).aexists(), "a drawing space nothing is drawn in is not a space anyone can use"


async def test_deleting_a_dataset_keeps_the_marks_made_on_it_and_the_frame_their_boxes_are_in(aexecute, authenticated_context):
    """The collection outlives the dataset it was drawn over -- and its stored boxes must not be silently relabelled."""
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    collection = await _collection(aexecute, "kept marks", derived_from=[{"kind": "DATASET", "dataset": str(dataset.pk), "transform": {"kind": "IDENTITY"}}])
    drawn = await aexecute(CREATE_ANNOTATION, {"input": {"collection": collection["id"], "kind": "EVENT", "name": "spike", "vectors": [[340]]}})
    assert not drawn.errors, drawn.errors

    res = await aexecute("mutation ($input: DeleteArrayDatasetInput!) { deleteArrayDataset(input: $input) }", {"input": {"id": str(dataset.pk)}})
    assert not res.errors, res.errors
    assert not await models.ArrayDataset.objects.filter(pk=dataset.pk).aexists()
    assert await models.Annotation.objects.filter(name="spike").aexists()


# --- negatives ---------------------------------------------------------------


@pytest.mark.parametrize(
    "spec, message",
    [
        ({"kind": "EPOCH", "vectors": [[1.0]]}, "An epoch is drawn from at least 2 vertices"),
        ({"kind": "POLYGON", "vectors": [[1.0, 0.0], [2.0, 0.0]]}, "A polygon is drawn from at least 3 vertices"),
        ({"kind": "PATH", "vectors": [[1.0, 0.0], [2.0]]}, "mixes widths [1, 2]"),
        ({"kind": "EVENT", "vectors": [[1.0]], "strokeColor": [255, 0, 0]}, "takes exactly 4 components"),
        ({"kind": "EVENT", "vectors": [[1.0]], "fillColor": [255, 0, 0, 300]}, "components run from 0 to 255"),
    ],
    ids=["one-corner epoch", "two-point polygon", "ragged vertices", "rgb not rgba", "colour out of range"],
)
async def test_a_shape_its_vertices_cannot_describe_is_refused(aexecute, spec, message):
    collection = await _collection(aexecute)
    res = await aexecute(CREATE_ANNOTATION, {"input": {"collection": collection["id"], **spec}})
    assert res.errors and message in str(res.errors[0])
    assert await models.Annotation.objects.acount() == 0


@pytest.mark.parametrize("target", [{}, {"collection": "1", "experiment": "1"}], ids=["neither", "both"])
async def test_an_annotation_is_drawn_into_exactly_one_place(aexecute, target):
    res = await aexecute(CREATE_ANNOTATION, {"input": {**target, "kind": "EVENT", "vectors": [[1.0]]}})
    assert res.errors and "Provide exactly one of `collection` or `experiment`" in str(res.errors[0])


async def test_a_collection_that_cannot_be_related_to_its_source_is_not_left_behind(aexecute, authenticated_context):
    """The edge names an axis the dataset does not have; the collection row written before it must not survive."""
    dataset = await seed.create_dataset(authenticated_context, "Vm", seed.T_AXES, [1000])
    bad = {"kind": "BY_DIMENSION", "inputAxes": ["t"], "outputAxes": ["nope"]}
    res = await aexecute(CREATE_COLLECTION, {"input": {"name": "orphan", "axes": T, "derivedFrom": [{"kind": "DATASET", "dataset": str(dataset.pk), "transform": bad}]}})
    assert res.errors
    assert not await models.AnnotationCollection.objects.filter(name="orphan").aexists()
    assert not await models.CoordinateSystem.objects.filter(name="orphan/drawing").aexists()


async def test_another_organization_sees_and_touches_none_of_it(aexecute, other_org_context):
    collection = await _collection(aexecute, "mine")
    drawn = await aexecute(CREATE_ANNOTATION, {"input": {"collection": collection["id"], "kind": "EVENT", "name": "private", "vectors": [[1.0]]}})
    annotation_id = drawn.data["createAnnotation"]["id"]

    listed = await aexecute("{ annotations { name } annotationCollections { name } }", context=other_org_context)
    assert not listed.errors, listed.errors
    assert listed.data == {"annotations": [], "annotationCollections": []}

    for document, variables in (
        (CREATE_ANNOTATION, {"input": {"collection": collection["id"], "kind": "EVENT", "vectors": [[2.0]]}}),
        (UPDATE_ANNOTATION, {"input": {"id": annotation_id, "name": "theirs"}}),
        (DELETE_ANNOTATION, {"input": {"id": annotation_id}}),
        (DELETE_COLLECTION, {"input": {"id": collection["id"]}}),
        ("query ($c: ID!) { nearestAnnotations(collection: $c, point: [1.0]) { name } }", {"c": collection["id"]}),
    ):
        res = await aexecute(document, variables, context=other_org_context)
        assert res.errors, f"another organization got through: {document[:40]}"

    annotation = await models.Annotation.objects.aget(pk=annotation_id)
    assert annotation.name == "private"
    assert await models.Annotation.objects.filter(collection_id=collection["id"]).acount() == 1
