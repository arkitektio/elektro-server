"""Array dataset mutations executed against the schema (stores seeded in RustFS).

``createArrayDataset`` is mikro's, input and all, and it is the one way data enters this
service: the dataset, its sample grid, a data array per pyramid level with the edge placing
it, the derivation edges, and the anchors pinning metadata to its coordinates. What a
dataset *means* is said afterwards: when its samples were taken by an edge onto a clock
(``createSamplingLaw``), and how it is drawn by an experiment layer naming it by id.

mikro's own tests of this mutation are ported beside this file; what is here is the ephys
reading of it -- a (t, c) recording, a value unit, channel labels, the rig, a decimated level.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core.models import ArrayDataset, CoordinateAnchor, CoordinateSystem, DataArray, Transformation
from datalayer.models import ZarrStore

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


UPDATE = """
mutation ($input: UpdateArrayDatasetInput!) {
  updateArrayDataset(input: $input) { id name description provenanceEntries { id } }
}
"""

DELETE = "mutation ($input: DeleteArrayDatasetInput!) { deleteArrayDataset(input: $input) }"
DELETE_LEVEL = "mutation ($input: DeleteDataArrayInput!) { deleteDataArray(input: $input) }"

DETAIL = """
query ($id: ID!) {
  arrayDataset(id: $id) {
    name
    shape
    axisNames
    spec
    multiscale
    valueUnit
    valueDimension
    pyramidIsLabelCompliant
    intrinsicSystem { id name axes { order name type unit } residents { __typename } }
    dataArrays {
      level
      shape
      scaleMethod
      store { id }
      coordinateSystem { id name }
      toParent { kind inputAxes outputAxes ... on ByDimensionTransformation { transformations { kind ... on AffineTransformation { affine } ... on ScaleTransformation { scale } } } ... on AffineTransformation { affine } ... on ScaleTransformation { scale } }
    }
    anchors {
      coordinates
      channelLabel { label }
      valueUnit { unit dimension }
      valueHistogram { min max }
      acquisitionMetadata { metadata }
      rig { state { mode holdingPotential seriesResistance temperature devices { label kind settings { name quantity number flag } } } }
    }
    derivedFrom { kind valueRelation output { id } ... on ScaleTransformation { scale } }
  }
}
"""

TC = [{"name": "t", "type": "TIME"}, {"name": "c", "type": "CHANNEL"}]


async def _detail(aexecute, dataset_id: str) -> dict:
    result = await aexecute(DETAIL, {"id": dataset_id})
    assert not result.errors, result.errors
    return result.data["arrayDataset"]


# --- what a dataset is ----------------------------------------------------------------------------


async def test_a_recording_is_a_dataset_a_grid_and_one_level(aexecute, create_array_dataset):
    created = await create_array_dataset("probe", [30000, 4], value_unit="uV")
    dataset = await _detail(aexecute, created["id"])

    assert (dataset["shape"], dataset["axisNames"]) == ([30000, 4], ["t", "c"])
    assert dataset["spec"] == ["SCALAR", "TIMESERIES", "MULTICHANNEL"], "no SPACE axis, a TIME axis, a CHANNEL axis"
    assert dataset["multiscale"] is False
    assert dataset["intrinsicSystem"]["name"] == "probe/intrinsic"
    assert dataset["intrinsicSystem"]["axes"] == [{"order": 0, "name": "t", "type": "TIME", "unit": None}, {"order": 1, "name": "c", "type": "CHANNEL", "unit": None}], "a sample grid is typed and never carries a unit"
    assert [r["__typename"] for r in dataset["intrinsicSystem"]["residents"]] == ["ArrayDataset", "DataArray"], "level 0 IS the dataset's grid, so it lives there too"

    (level,) = dataset["dataArrays"]
    assert (level["level"], level["shape"], level["scaleMethod"], level["toParent"]) == (0, [30000, 4], None, None)
    assert level["coordinateSystem"]["id"] == dataset["intrinsicSystem"]["id"]
    assert created["folder"]["name"] == "Default", "with no folder named, the dataset is filed in the user's default"
    assert dataset["derivedFrom"] == []

    assert not [field.name for field in ArrayDataset._meta.get_fields() if field.name in ("store", "value_unit", "kind", "tags", "pinned_by")], "the store is the level's; the unit is an anchor's"


async def test_the_value_unit_is_an_anchor_not_a_column(aexecute, create_array_dataset):
    """Anchored to no coordinate it speaks for the dataset; anchored to a channel, for that channel."""
    anchors = [
        {"axisAnchors": [], "valueUnit": {"unit": "mV"}},
        {"axisAnchors": [{"axis": "c", "value": 1}], "valueUnit": {"unit": "pA"}, "label": {"label": "command"}},
    ]
    created = await create_array_dataset("paired", [1000, 2], anchors=anchors)
    dataset = await _detail(aexecute, created["id"])

    assert (dataset["valueUnit"], dataset["valueDimension"]) == ("mV", "[length] ** 2 * [mass] / [current] / [time] ** 3"), "the dataset-wide anchor, and only that one"
    by_coordinates = {str(anchor["coordinates"]): anchor for anchor in dataset["anchors"]}
    assert by_coordinates["{}"]["valueUnit"]["unit"] == "mV"
    assert by_coordinates["{'c': 1}"]["valueUnit"] == {"unit": "pA", "dimension": "[current]"}
    assert by_coordinates["{'c': 1}"]["channelLabel"]["label"] == "command"

    unstated = await _detail(aexecute, (await create_array_dataset("bare", [10]))["id"])
    assert (unstated["valueUnit"], unstated["valueDimension"]) == (None, None)


async def test_the_rig_state_round_trips_typed(aexecute, create_array_dataset):
    rig = {
        "mode": "VOLTAGE_CLAMP",
        "holdingPotential": "-70 mV",
        "seriesResistance": "12 Mohm",
        "temperature": "305.15 K",
        "devices": [{"label": "multiclamp-1", "kind": "amplifier", "settings": [{"name": "lowpass", "quantity": "10 kHz"}, {"name": "gain", "number": 20.0}, {"name": "whole-cell", "flag": True}]}],
    }
    metadata = {"axisAnchors": [], "rig": rig, "acquisitionMetadata": {"metadataString": '{"protocol": "IV", "sweeps": 12}'}, "valueHistogram": {"histogram": [1.0, 2.0], "bins": [-80.0, 40.0], "min": -80.0, "max": 40.0}}
    created = await create_array_dataset("cell 3", [1000], anchors=[metadata])
    (anchor,) = (await _detail(aexecute, created["id"]))["anchors"]

    state = anchor["rig"]["state"]
    assert (state["mode"], state["holdingPotential"], state["seriesResistance"]) == ("VOLTAGE_CLAMP", "-70 mV", "12 MΩ")
    (device,) = state["devices"]
    assert (device["label"], device["kind"]) == ("multiclamp-1", "amplifier")
    assert [(s["name"], s["number"], s["flag"]) for s in device["settings"]] == [("lowpass", None, None), ("gain", 20.0, None), ("whole-cell", None, True)]
    assert device["settings"][0]["quantity"] is not None
    assert anchor["acquisitionMetadata"]["metadata"] == {"protocol": "IV", "sweeps": 12}
    assert (anchor["valueHistogram"]["min"], anchor["valueHistogram"]["max"]) == (-80.0, 40.0)


async def test_a_rig_state_cannot_contradict_its_own_clamp_mode(aexecute, create_array_dataset):
    result = await create_array_dataset("bad", [10], anchors=[{"axisAnchors": [], "rig": {"mode": "CURRENT_CLAMP", "holdingPotential": "-70 mV"}}], raw=True)
    assert result.errors and "contradicts `mode: CURRENT_CLAMP`" in str(result.errors[0])
    assert not await ArrayDataset.objects.filter(name="bad").aexists()


async def test_a_decimated_level_is_placed_in_the_recordings_grid(aexecute, create_array_dataset):
    """An hour at 30 kHz, and a level decimated by 100 for the overview: mikro's pyramid, along time."""
    created = await create_array_dataset("long", [10000, 4], levels=[([100, 4], "MAX")])
    dataset = await _detail(aexecute, created["id"])

    assert dataset["multiscale"] is True and dataset["shape"] == [10000, 4], "the dataset's shape is level 0's"
    base, overview = dataset["dataArrays"]
    assert (overview["level"], overview["shape"], overview["scaleMethod"]) == (1, [100, 4], "MAX")
    assert overview["coordinateSystem"]["name"] == "long/1" and overview["coordinateSystem"]["id"] != base["coordinateSystem"]["id"]
    assert overview["toParent"] is not None and base["toParent"] is None

    def steps():
        edge = Transformation.objects.get(input_id=overview["coordinateSystem"]["id"], output_id=dataset["intrinsicSystem"]["id"], parent__isnull=True)
        return edge.kind, {child.kind: child.params for child in edge.children.order_by("order")}

    kind, children = await sync_to_async(steps)()
    assert kind == "SEQUENCE", "a scale, then the half-sample shift a decimation introduces"
    assert children["SCALE"]["scale"] == approx([100.0, 1.0]), "derived from the actual shapes, never supplied -- and the channel axis never shrinks"
    assert children["TRANSLATION"]["translation"] == approx([49.5, 0.0]), "sample 0 of the overview is the centre of samples 0..99"


async def test_a_pyramid_over_event_codes_may_not_be_averaged(aexecute, create_array_dataset):
    """An INDEX axis says the array enumerates things: a mean of two unit ids is a unit that does not exist."""
    axes = [{"name": "unit", "type": "INDEX"}, {"name": "t", "type": "TIME"}]
    refused = await create_array_dataset("rasters", [12, 1000], axes=axes, levels=[([12, 100], "AREA")], raw=True)
    assert refused.errors and "may not have been downsampled with AREA" in str(refused.errors[0])
    assert not await ArrayDataset.objects.filter(name="rasters").aexists()

    ok = await create_array_dataset("rasters", [12, 1000], axes=axes, levels=[([12, 100], "NEAREST")])
    assert (await _detail(aexecute, ok["id"]))["pyramidIsLabelCompliant"] is True


async def test_a_derived_dataset_records_how_its_grid_maps_back_into_its_source(aexecute, create_array_dataset):
    """A decimation by 4 as a *new dataset*: sample i of the child is sample 4i of the source."""
    raw = await create_array_dataset("raw", [8000])
    derived_from = [{"kind": "DATASET", "dataset": raw["id"], "valueRelation": "IDENTICAL", "transform": {"kind": "SCALE", "scale": [4.0]}}]
    small = await create_array_dataset("decimated", [2000], derived_from=derived_from)

    (edge,) = (await _detail(aexecute, small["id"]))["derivedFrom"]
    assert edge == {"kind": "SCALE", "valueRelation": "IDENTICAL", "output": {"id": raw["intrinsicSystem"]["id"]}, "scale": [4.0]}
    assert small["folder"]["name"] == "Default", "derived data is filed with its primary parent"

    back = await aexecute("query ($id: ID!) { arrayDataset(id: $id) { derivedDatasets { name } } }", {"id": raw["id"]})
    assert back.data["arrayDataset"]["derivedDatasets"] == [{"name": "decimated"}]


# --- the only two editable fields, and deletion ---------------------------------------------------


async def test_update_renames_and_redescribes_and_nothing_else(aexecute, create_array_dataset):
    dataset = await create_array_dataset("old", [10])
    res = await aexecute(UPDATE, {"input": {"id": dataset["id"], "name": "new", "description": "after rework"}})
    assert not res.errors, res.errors
    assert (res.data["updateArrayDataset"]["name"], res.data["updateArrayDataset"]["description"]) == ("new", "after rework")
    assert len(res.data["updateArrayDataset"]["provenanceEntries"]) >= 2, "the rename is audited"

    for fixed in ({"axes": TC}, {"tags": ["a"]}, {"valueUnit": "mV"}):
        refused = await aexecute(UPDATE, {"input": {"id": dataset["id"], **fixed}})
        assert refused.errors, fixed


async def test_deleting_a_dataset_takes_its_spaces_and_flags_its_stores(aexecute, create_array_dataset):
    dataset = await create_array_dataset("gone", [10000], levels=[([100], "MAX")])
    store_ids = await sync_to_async(lambda: list(DataArray.objects.filter(dataset_id=dataset["id"]).values_list("store_id", flat=True)))()
    assert len(store_ids) == 2

    res = await aexecute(DELETE, {"input": {"id": dataset["id"]}})
    assert not res.errors, res.errors
    assert res.data["deleteArrayDataset"] == dataset["id"]
    assert await CoordinateSystem.objects.acount() == 0, "a sample grid nothing lives in is not a space anyone can use -- the level's goes too"
    assert await Transformation.objects.acount() == 0
    assert await CoordinateAnchor.objects.acount() == 0

    stores = await sync_to_async(lambda: list(ZarrStore.objects.filter(pk__in=store_ids)))()
    assert len(stores) == 2, "no request does S3 work: the rows and the bytes outlive the delete"
    assert all(store.orphaned_at is not None for store in stores), "flagged for `purge_orphaned_stores`, which re-checks before it removes anything"


async def test_a_level_can_be_deleted_but_level_zero_is_the_dataset(aexecute, create_array_dataset):
    dataset = await create_array_dataset("long", [10000], levels=[([100], "MAX")])
    base, overview = await sync_to_async(lambda: list(DataArray.objects.filter(dataset_id=dataset["id"]).order_by("level")))()

    refused = await aexecute(DELETE_LEVEL, {"input": {"id": str(base.pk)}})
    assert refused.errors and "Delete the dataset instead" in str(refused.errors[0])

    res = await aexecute(DELETE_LEVEL, {"input": {"id": str(overview.pk)}})
    assert not res.errors, res.errors
    assert await DataArray.objects.filter(dataset_id=dataset["id"]).acount() == 1
    assert not await CoordinateSystem.objects.filter(pk=overview.coordinate_system_id).aexists(), "the level's own space and its edge go with it"
    assert await CoordinateSystem.objects.filter(pk=base.coordinate_system_id).aexists()


async def test_deleting_a_dataset_deletes_what_draws_it(aexecute, create_array_dataset, authenticated_context):
    """A layer of data that no longer exists is a layer of nothing: it goes with its lens. The experiment stays."""
    from core.models import Experiment, ExperimentLayer

    from tests import seed

    dataset = await create_array_dataset("v", [1000])
    clock = await seed.create_clock(authenticated_context, "session")
    grid = await CoordinateSystem.objects.aget(datasets__id=dataset["id"])
    await seed.time_on(authenticated_context, grid, clock, rate="1 kHz")
    staged = await aexecute("mutation ($input: CreateExperimentFromCoordinateSystemInput!) { createExperimentFromCoordinateSystem(input: $input) { id layers { kind } } }", {"input": {"coordinateSystem": str(clock.pk), "name": "E"}})
    assert not staged.errors, staged.errors
    assert staged.data["createExperimentFromCoordinateSystem"]["layers"] == [{"kind": "TRACE"}]

    res = await aexecute(DELETE, {"input": {"id": dataset["id"]}})
    assert not res.errors, res.errors
    assert await ExperimentLayer.objects.acount() == 0
    assert await Experiment.objects.filter(name="E").aexists(), "the experiment stays: it still composes over its clock, now with one layer fewer"


# --- negatives ------------------------------------------------------------------------------------


async def test_delete_not_found(aexecute):
    res = await aexecute(DELETE, {"input": {"id": "999999"}})
    assert res.errors


async def test_missing_zarr_metadata(aexecute, zarr_store):
    store = await zarr_store(seed=False)  # no zarr.json -> fill_info raises FileNotFoundError
    res = await aexecute("mutation ($input: CreateArrayDatasetInput!) { createArrayDataset(input: $input) { id } }", {"input": {"data": str(store.id), "scales": [], "name": "broken", "axes": [{"name": "t", "type": "TIME"}]}})
    assert res.errors
    assert not await ArrayDataset.objects.filter(name="broken").aexists()


async def test_the_axes_are_always_declared(aexecute, zarr_store):
    """(t, c) or (sweep, t)? Nothing in the bytes decides, so the caller must -- for every rank, as in mikro."""
    store = await zarr_store(shape=[1000])
    res = await aexecute("mutation ($input: CreateArrayDatasetInput!) { createArrayDataset(input: $input) { id } }", {"input": {"data": str(store.id), "scales": [], "name": "undeclared"}})
    assert res.errors and "axes" in str(res.errors[0])


async def test_declared_axes_must_match_the_rank_of_the_array(create_array_dataset, zarr_store, aexecute):
    store = await zarr_store(shape=[1000, 4])
    res = await aexecute("mutation ($input: CreateArrayDatasetInput!) { createArrayDataset(input: $input) { id } }", {"input": {"data": str(store.id), "scales": [], "name": "short", "axes": [{"name": "t", "type": "TIME"}]}})
    assert res.errors and "The data has 2 dimensions but 1 axis was declared" in str(res.errors[0])


async def test_declared_axes_must_agree_with_the_names_the_store_gives_its_dimensions(aexecute, zarr_store):
    """A transposed declaration would not raise anywhere downstream: a sampling law written over `t` would run along the channels."""
    store = await zarr_store(shape=[1000, 4], dimension_names=["t", "c"])
    axes = [{"name": "c", "type": "CHANNEL"}, {"name": "t", "type": "TIME"}]
    res = await aexecute("mutation ($input: CreateArrayDatasetInput!) { createArrayDataset(input: $input) { id } }", {"input": {"data": str(store.id), "scales": [], "name": "transposed", "axes": axes}})
    assert res.errors and "The declared axes do not describe this array" in str(res.errors[0])
    assert not await CoordinateSystem.objects.filter(name="transposed/intrinsic").aexists(), "refused before anything is written"


async def test_an_anchor_pins_the_axes_its_dataset_has(create_array_dataset):
    """`{ch: 3}` on a (t, c) dataset would not fail anywhere downstream: it would be a label that labels nothing."""
    unknown = await create_array_dataset("a", [100, 4], anchors=[{"axisAnchors": [{"axis": "ch", "value": 3}], "label": {"label": "ch3"}}], raw=True)
    assert unknown.errors and "['ch'] is not among ['t', 'c']" in str(unknown.errors[0])

    twice = [{"axisAnchors": [{"axis": "c", "value": 0}], "label": {"label": "a"}}, {"axisAnchors": [{"axis": "c", "value": 0}], "valueUnit": {"unit": "mV"}}]
    rivals = await create_array_dataset("b", [100, 4], anchors=twice, raw=True)
    assert rivals.errors and "Two anchors are pinned to the same coordinates" in str(rivals.errors[0])
    assert await ArrayDataset.objects.acount() == 0 and await CoordinateSystem.objects.acount() == 0


async def test_a_value_unit_must_be_a_unit(create_array_dataset):
    result = await create_array_dataset("bad", [10], value_unit="5 mV", raw=True)
    assert result.errors
    assert not await ArrayDataset.objects.filter(name="bad").aexists(), "one transaction: the refusal takes the dataset with it"


async def test_another_organization_cannot_touch_this_dataset_or_its_store(aexecute, create_array_dataset, zarr_store, other_org_context):
    dataset = await create_array_dataset("mine", [10])
    store = await zarr_store()

    renamed = await aexecute(UPDATE, {"input": {"id": dataset["id"], "name": "theirs"}}, context=other_org_context)
    assert renamed.errors
    deleted = await aexecute(DELETE, {"input": {"id": dataset["id"]}}, context=other_org_context)
    assert deleted.errors
    adopted = await aexecute(
        "mutation ($input: CreateArrayDatasetInput!) { createArrayDataset(input: $input) { id } }",
        {"input": {"data": str(store.id), "scales": [], "name": "stolen", "axes": [{"name": "t", "type": "TIME"}]}},
        context=other_org_context,
    )
    assert adopted.errors, "a store is scoped to the organization that requested it"

    assert await ArrayDataset.objects.filter(name="mine").aexists()
    assert not await ArrayDataset.objects.filter(name="stolen").aexists()
