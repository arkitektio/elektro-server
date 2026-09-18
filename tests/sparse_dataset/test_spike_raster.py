"""A spike raster: a sparse dataset over (unit, t), placed on a clock by a sampling law.

elektro's one divergence in the vendored sparse path. mikro's sparse axes all enumerate, so its
``SparseAxisInput`` has no ``type``; a raster's sample axis has a metric -- it is sampled exactly
as the recording it was sorted from -- so here an axis may be TIME. What follows from that, and
is pinned below:

* a TIME axis is identified by nothing, and one that claims an identification is refused;
* there is at most one, and a matrix with no INDEX axis is refused;
* the TIME axis is *optional* for a FIELD keying the unit axis (``graph.self_placed_axes``): a
  per-sample assignment passes it through by name, a per-channel one leaves it alone, and
  neither is refused for it;
* a sampling law (``createSamplingLaw``) places it, exactly as it places an analog signal, and
  then it is in view on the clock and drawable as a SPIKES layer.

It replaces ``SpikeTrain``: one unit's spike times are one row of the raster, and the unit's
attributes (depth, channel, quality) are a row of the table identifying the unit axis.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_SPARSE = """
mutation ($input: CreateSparseDatasetInput!) {
  createSparseDataset(input: $input) {
    id
    name
    axisNames
    shape
    indexableAxes
    coordinateSystem { id axes { name type unit } }
    axisReferences { axis references { name } }
  }
}
"""

CREATE_SAMPLING_LAW = "mutation ($input: CreateSamplingLawInput!) { createSamplingLaw(input: $input) { id kind inputAxes outputAxes } }"

IN_VIEW = """
query InView($id: ID!, $region: BoundingBoxInput!) {
  coordinateSystem(id: $id) {
    inView(region: $region) {
      extentState
      source { __typename ... on SparseDataset { id name } ... on ArrayDataset { id name } }
      path { transformation { kind } }
    }
  }
}
"""

UNITS = [
    {"name": "unit_id", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
    {"name": "depth", "dtype": "DOUBLE", "role": "ATTRIBUTE", "unit": "micrometer"},
    {"name": "quality", "dtype": "VARCHAR", "role": "LABEL"},
]


async def _units(aexecute, ctx) -> str:  # noqa: ANN001
    """A sorter's unit table: one row per unit, keyed by its INDEX column."""
    created = await aexecute(
        "mutation ($input: CreateTableDatasetInput!) { createTableDataset(input: $input) { id } }",
        {"input": await seed.table_input(ctx, "units", UNITS)},
    )
    assert not created.errors, created.errors
    return created.data["createTableDataset"]["id"]


async def _raster(aexecute, ctx, *, units: str | None = None, axes: list | None = None, shape=(12, 30000), name: str = "sorted spikes"):  # noqa: ANN001, ANN201
    store = await seed.create_sparse_store(ctx, f"{name.replace(' ', '-')}-store", axes=(0, 1), shape=list(shape))
    if axes is None:
        axes = [
            {"name": "unit", "type": "INDEX", "identifiedBy": [{"kind": "TABLE", "table": units}]},
            {"name": "t", "type": "TIME"},
        ]
    return await aexecute(CREATE_SPARSE, {"input": {"name": name, "store": str(store.pk), "axes": axes}})


async def test_a_raster_has_a_unit_axis_and_a_time_axis(aexecute, authenticated_context):
    units = await _units(aexecute, authenticated_context)
    res = await _raster(aexecute, authenticated_context, units=units)
    assert not res.errors, res.errors
    raster = res.data["createSparseDataset"]

    assert raster["axisNames"] == ["unit", "t"] and raster["shape"] == [12, 30000]
    assert raster["coordinateSystem"]["axes"] == [{"name": "unit", "type": "INDEX", "unit": None}, {"name": "t", "type": "TIME", "unit": None}], "a sample axis is TIME with no unit: physical time enters through the sampling law"
    assert raster["axisReferences"] == [{"axis": "unit", "references": {"name": "units"}}], "a unit is a row of the unit table"
    assert set(raster["indexableAxes"]) == {"unit", "t"}, "CSR answers 'this unit', CSC answers 'this window'"


async def test_the_type_defaults_to_index_so_a_mikro_client_is_unaffected(aexecute, authenticated_context):
    units = await _units(aexecute, authenticated_context)
    res = await _raster(
        aexecute,
        authenticated_context,
        axes=[{"name": "unit", "identifiedBy": [{"kind": "TABLE", "table": units}]}, {"name": "gene", "identifiedBy": [{"kind": "TABLE", "table": units}]}],
    )
    assert not res.errors, res.errors
    assert [axis["type"] for axis in res.data["createSparseDataset"]["coordinateSystem"]["axes"]] == ["INDEX", "INDEX"]


async def test_a_time_axis_is_identified_by_nothing(aexecute, authenticated_context):
    units = await _units(aexecute, authenticated_context)
    res = await _raster(
        aexecute,
        authenticated_context,
        axes=[{"name": "unit", "identifiedBy": [{"kind": "TABLE", "table": units}]}, {"name": "t", "type": "TIME", "identifiedBy": [{"kind": "TABLE", "table": units}]}],
    )
    assert res.errors and "identifies its TIME axis" in str(res.errors[0])
    assert not await models.SparseDataset.objects.aexists()


async def test_one_time_axis_and_at_least_one_index_axis(aexecute, authenticated_context):
    two_clocks = await _raster(aexecute, authenticated_context, axes=[{"name": "t", "type": "TIME"}, {"name": "s", "type": "TIME"}], name="two")
    assert two_clocks.errors and "more than one TIME axis" in str(two_clocks.errors[0])

    spatial = await _raster(aexecute, authenticated_context, axes=[{"name": "x", "type": "SPACE"}, {"name": "t", "type": "TIME"}], name="spatial")
    assert spatial.errors and "INDEX or TIME" in str(spatial.errors[0])


async def test_an_index_axis_still_needs_an_identification(aexecute, authenticated_context):
    res = await _raster(aexecute, authenticated_context, axes=[{"name": "unit", "type": "INDEX"}, {"name": "t", "type": "TIME"}])
    assert res.errors and "empty `identifiedBy`" in str(res.errors[0])


async def test_a_sampling_law_places_the_raster_on_its_clock(aexecute, authenticated_context):
    """The same edge an analog signal gets: t = sample / 30 kHz + 2 s, on the session clock."""
    units = await _units(aexecute, authenticated_context)
    raster = (await _raster(aexecute, authenticated_context, units=units)).data["createSparseDataset"]
    session = await seed.create_clock(authenticated_context, "session")

    timed = await aexecute(CREATE_SAMPLING_LAW, {"input": {"source": raster["coordinateSystem"]["id"], "clock": str(session.pk), "samplingRate": "30 kHz", "tStart": "2 s"}})
    assert not timed.errors, timed.errors
    law = timed.data["createSamplingLaw"]
    assert (law["kind"], law["inputAxes"], law["outputAxes"]) == ("BY_DIMENSION", ["t"], ["t"]), "the law names the sample axis and says nothing about the units"
    edge = await models.Transformation.objects.aget(pk=law["id"])
    assert edge.params["affine"][0] == pytest.approx([1 / 30000, 2.0])

    seen = await aexecute(IN_VIEW, {"id": str(session.pk), "region": {"min": [0.0], "max": [10.0]}})
    assert not seen.errors, seen.errors
    sources = [(hit["source"]["__typename"], hit["source"].get("name")) for hit in seen.data["coordinateSystem"]["inView"]]
    assert ("SparseDataset", "sorted spikes") in sources, "the raster is in view on the clock it is timed on"


async def test_a_raster_is_drawn_as_a_spikes_layer(aexecute, authenticated_context):
    units = await _units(aexecute, authenticated_context)
    raster = (await _raster(aexecute, authenticated_context, units=units)).data["createSparseDataset"]
    session = await seed.create_clock(authenticated_context, "session")
    assert not (await aexecute(CREATE_SAMPLING_LAW, {"input": {"source": raster["coordinateSystem"]["id"], "clock": str(session.pk), "samplingRate": "30 kHz"}})).errors

    experiment = await aexecute("mutation ($input: CreateExperimentInput!) { createExperiment(input: $input) { id } }", {"input": {"name": "E", "coordinateSystem": str(session.pk)}})
    layer = await aexecute(
        """
        mutation ($input: CreateSpikesLayerInput!) {
          createSpikesLayer(input: $input) {
            kind name placement placementInvariance tickHeight rowOrderColumn valueMode rateBin
            unitTable { name }
            colorBys { table column colormap min max }
            activeColorBy
            asAffine { matrix inputAxes outputAxes }
          }
        }
        """,
        {
            "input": {
                "experiment": experiment.data["createExperiment"]["id"],
                "sparseDataset": raster["id"],
                "tickHeight": 0.6,
                "rowOrderColumn": "depth",
                "rateBin": "10 ms",
                "colorBys": [{"table": units, "column": "depth", "colormap": "VIRIDIS", "min": 0, "max": 1000}],
                "activeColorBy": 0,
            }
        },
    )
    assert not layer.errors, layer.errors
    drawn = layer.data["createSpikesLayer"]
    assert (drawn["kind"], drawn["name"], drawn["placement"], drawn["placementInvariance"]) == ("SPIKES", "sorted spikes", "PLACED", "AFFINE")
    assert (drawn["tickHeight"], drawn["rowOrderColumn"], drawn["valueMode"], drawn["rateBin"]) == (0.6, "depth", "PRESENCE", "10 ms")
    assert drawn["unitTable"] == {"name": "units"}
    assert drawn["colorBys"] == [{"table": units, "column": "depth", "colormap": "VIRIDIS", "min": 0.0, "max": 1000.0}] and drawn["activeColorBy"] == 0
    assert drawn["asAffine"]["inputAxes"] == ["unit", "t"] and drawn["asAffine"]["outputAxes"] == ["t"]
    assert drawn["asAffine"]["matrix"][0] == pytest.approx([0.0, 1 / 30000, 0.0]), "the law acts on the samples and says nothing about the units"


async def test_a_mask_can_still_key_the_units_of_a_raster(aexecute, authenticated_context):
    """The TIME axis is optional for the FIELD (`self_placed_axes`): passed through here, by name, because the assignment is per sample.

    The ephys case is a per-sample unit-assignment array (which unit each channel-sample belongs to), keying the raster's units.
    """
    assignment = await seed.create_array_dataset(authenticated_context, "assignment", seed.TC_AXES, [[30000, 4]])
    store = await seed.create_sparse_store(authenticated_context, "keyed-store", axes=(0,), shape=[12, 30000])
    res = await aexecute(
        CREATE_SPARSE,
        {"input": {"name": "keyed", "store": str(store.pk), "axes": [{"name": "unit", "identifiedBy": [{"kind": "DATASET", "dataset": str(assignment.pk)}]}, {"name": "t", "type": "TIME"}]}},
    )
    assert not res.errors, res.errors
    edge = await models.Transformation.objects.aget(input_id=assignment.coordinate_system_id, parent__isnull=True)
    assert (edge.kind, edge.input_axes, edge.output_axes) == ("FIELD", ["c"], ["unit"]), "t passes through by name; c is consumed into a unit id"


async def test_deleting_a_raster_takes_its_space_its_law_and_its_layers(aexecute, authenticated_context):
    units = await _units(aexecute, authenticated_context)
    raster = (await _raster(aexecute, authenticated_context, units=units)).data["createSparseDataset"]
    session = await seed.create_clock(authenticated_context, "session")
    assert not (await aexecute(CREATE_SAMPLING_LAW, {"input": {"source": raster["coordinateSystem"]["id"], "clock": str(session.pk), "samplingRate": "30 kHz"}})).errors
    staged = await aexecute("mutation ($input: CreateExperimentFromCoordinateSystemInput!) { createExperimentFromCoordinateSystem(input: $input) { layers { kind } } }", {"input": {"coordinateSystem": str(session.pk)}})
    assert staged.data["createExperimentFromCoordinateSystem"]["layers"] == [{"kind": "SPIKES"}]

    deleted = await aexecute("mutation ($input: DeleteSparseDatasetInput!) { deleteSparseDataset(input: $input) }", {"input": {"id": raster["id"]}})
    assert not deleted.errors, deleted.errors
    assert not await models.CoordinateSystem.objects.filter(pk=raster["coordinateSystem"]["id"]).aexists(), "the space it owned is swept, as a dataset's grid is"
    assert not await models.Transformation.objects.filter(output=session).aexists(), "and the sampling law with it"
    assert not await models.ExperimentLayer.objects.aexists(), "a layer of a raster that is gone is a layer of nothing"
    assert await models.CoordinateSystem.objects.filter(pk=session.pk).aexists(), "the session clock is an experiment's world, and stays"

    store = await sync_to_async(lambda: models.SparseStore.objects.get(key="sorted-spikes-store"))()
    assert store.orphaned_at is not None, "its store is flagged for the purge, not deleted"


async def test_the_unit_table_cannot_be_deleted_under_the_raster(aexecute, authenticated_context):
    units = await _units(aexecute, authenticated_context)
    assert not (await _raster(aexecute, authenticated_context, units=units)).errors
    res = await aexecute("mutation ($input: DeleteTableDatasetInput!) { deleteTableDataset(input: $input) }", {"input": {"id": units}})
    assert res.errors, "a unit id with no unit table behind it means nothing"
    assert await models.TableDataset.objects.filter(pk=units).aexists()


async def test_a_per_channel_assignment_keys_the_units_and_leaves_time_alone(aexecute, authenticated_context):
    """No `t` on the source at all: the raster's samples are placed by its own sampling law, so the edge need not mention them."""
    per_channel = await seed.create_array_dataset(authenticated_context, "channel map", [seed.axis("c", seed.enums.AxisType.CHANNEL)], [[4]])
    store = await seed.create_sparse_store(authenticated_context, "per-channel-store", axes=(0,), shape=[4, 30000])
    res = await aexecute(
        CREATE_SPARSE,
        {"input": {"name": "per channel", "store": str(store.pk), "axes": [{"name": "unit", "identifiedBy": [{"kind": "DATASET", "dataset": str(per_channel.pk)}]}, {"name": "t", "type": "TIME"}]}},
    )
    assert not res.errors, res.errors
    edge = await models.Transformation.objects.aget(input_id=per_channel.coordinate_system_id, parent__isnull=True)
    assert (edge.input_axes, edge.output_axes) == (["c"], ["unit"]), "one channel, one unit id; the samples are not the edge's business"


async def test_deleting_a_raster_flags_its_store_through_the_layouts(aexecute, authenticated_context):
    """A sparse store is referenced by the *layouts* (`SparseArray.store`), which cascade with the dataset -- the fast-delete shape `stores_orphaned_by` has to walk."""
    import io

    from django.core.management import call_command

    from core.logic import storage

    units = await _units(aexecute, authenticated_context)
    store = await seed.create_sparse_store(authenticated_context, "shared-store", axes=(0, 1), shape=[12, 30000])
    axes = [{"name": "unit", "identifiedBy": [{"kind": "TABLE", "table": units}]}, {"name": "t", "type": "TIME"}]
    first = await aexecute(CREATE_SPARSE, {"input": {"name": "one", "store": str(store.pk), "axes": axes}})
    second = await aexecute(CREATE_SPARSE, {"input": {"name": "two", "store": str(store.pk), "axes": axes}})
    assert not first.errors and not second.errors, (first.errors, second.errors)
    assert sum(count for _, count in await sync_to_async(storage.referrers_of)(store)) == 4, "two layouts per raster, two rasters"

    async def delete(created) -> None:  # noqa: ANN001
        res = await aexecute("mutation ($input: DeleteSparseDatasetInput!) { deleteSparseDataset(input: $input) }", {"input": {"id": created.data["createSparseDataset"]["id"]}})
        assert not res.errors, res.errors

    await delete(first)
    await store.arefresh_from_db()
    assert store.orphaned_at is not None, "seen through the fast-deleted layouts"
    await sync_to_async(call_command)("purge_orphaned_stores", older_than=0, stdout=io.StringIO())
    await store.arefresh_from_db()
    assert store.orphaned_at is None, "kept: the other raster's layouts still read it"

    await delete(second)
    await store.arefresh_from_db()
    assert store.orphaned_at is not None and await sync_to_async(storage.referrers_of)(store) == []
