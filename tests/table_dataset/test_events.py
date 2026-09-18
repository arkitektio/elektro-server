"""Events: a table dataset with a TIME coordinate column, placed on a clock and drawn as an events layer.

Bulk and imported events -- TTL edges, trial tables, stimulus onsets, Neo's Event and Epoch --
are rows, so they are a table: its TIME column is an axis of the table's own space, an offset
edge places that space on a clock, and an events layer draws a mark per row (an interval per row
with a stop column). Hand-drawn marks stay annotations; the two are different kinds of fact.
"""

import pytest

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_TABLE = """
mutation ($input: CreateTableDatasetInput!) {
  createTableDataset(input: $input) { id name coordinateSystem { id axes { name type unit } } columns { name role references { id } } }
}
"""

CREATE_EVENTS_LAYER = """
mutation ($input: CreateEventsLayerInput!) {
  createEventsLayer(input: $input) {
    id kind name placement placementInvariance
    timeColumn stopColumn labelColumn laneColumn
    colorBys { table column joinPath { table column } colormap }
    filterBys { table column values exclude }
    activeColorBy activeFilterBys
    asAffine { matrix inputAxes outputAxes }
  }
}
"""

TRIALS = [
    {"name": "start", "dtype": "DOUBLE", "role": "COORDINATE", "axisType": "TIME", "unit": "second"},
    {"name": "stop", "dtype": "DOUBLE", "role": "ATTRIBUTE", "unit": "second"},
    {"name": "condition", "dtype": "VARCHAR", "role": "LABEL"},
    {"name": "stimulus_id", "dtype": "BIGINT", "role": "ID"},
]

STIMULI = [
    {"name": "stimulus_id", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
    {"name": "contrast", "dtype": "DOUBLE", "role": "ATTRIBUTE"},
]


async def _table(aexecute, ctx, name: str, columns: list[dict], **extra) -> dict:  # noqa: ANN001, ANN003
    created = await aexecute(CREATE_TABLE, {"input": await seed.table_input(ctx, name, columns, **extra)})
    assert not created.errors, created.errors
    return created.data["createTableDataset"]


async def _session(aexecute, ctx, table: dict, offset: str = "0 s") -> str:  # noqa: ANN001
    """A session clock, the table's space placed on it, and an experiment over the clock."""
    session = await seed.create_clock(ctx, "session")
    space = await models.CoordinateSystem.objects.aget(pk=table["coordinateSystem"]["id"])
    await seed.offset_onto(ctx, space, session, offset)
    experiment = await aexecute("mutation ($input: CreateExperimentInput!) { createExperiment(input: $input) { id } }", {"input": {"name": "E", "coordinateSystem": str(session.pk)}})
    assert not experiment.errors, experiment.errors
    return experiment.data["createExperiment"]["id"]


async def test_a_time_column_makes_a_table_placeable_on_a_clock(aexecute, authenticated_context):
    trials = await _table(aexecute, authenticated_context, "trials", TRIALS)
    assert trials["coordinateSystem"]["axes"] == [{"name": "start", "type": "TIME", "unit": "second"}], "the TIME column is the table's one axis; the rest is data"

    experiment = await _session(aexecute, authenticated_context, trials, offset="12 s")
    res = await aexecute(CREATE_EVENTS_LAYER, {"input": {"experiment": experiment, "tableDataset": trials["id"], "stopColumn": "stop", "labelColumn": "condition", "laneColumn": "condition"}})
    assert not res.errors, res.errors
    layer = res.data["createEventsLayer"]
    assert (layer["kind"], layer["name"], layer["placement"], layer["placementInvariance"]) == ("EVENTS", "trials", "PLACED", "ISOMETRY")
    assert (layer["timeColumn"], layer["stopColumn"], layer["labelColumn"], layer["laneColumn"]) == ("start", "stop", "condition", "condition")
    assert layer["asAffine"]["matrix"][0] == pytest.approx([1.0, 12.0]), "the table's seconds are the session's, 12 s in"


async def test_a_stop_column_ends_an_interval_in_the_same_unit_of_time(aexecute, authenticated_context):
    trials = await _table(
        aexecute,
        authenticated_context,
        "trials",
        [TRIALS[0], {"name": "stop", "dtype": "DOUBLE", "role": "ATTRIBUTE", "unit": "volt"}, TRIALS[2]],
    )
    experiment = await _session(aexecute, authenticated_context, trials)
    res = await aexecute(CREATE_EVENTS_LAYER, {"input": {"experiment": experiment, "tableDataset": trials["id"], "stopColumn": "stop"}})
    assert res.errors and "one unit of time" in str(res.errors[0])

    itself = await aexecute(CREATE_EVENTS_LAYER, {"input": {"experiment": experiment, "tableDataset": trials["id"], "stopColumn": "start"}})
    assert itself.errors and "is an instant" in str(itself.errors[0])

    missing = await aexecute(CREATE_EVENTS_LAYER, {"input": {"experiment": experiment, "tableDataset": trials["id"], "labelColumn": "nope"}})
    assert missing.errors and "declares" in str(missing.errors[0])
    assert not await models.ExperimentLayer.objects.aexists()


async def test_a_table_with_no_time_column_is_not_an_event_table(aexecute, authenticated_context):
    units = await _table(aexecute, authenticated_context, "stimuli", STIMULI)
    experiment = await aexecute("mutation ($input: CreateExperimentInput!) { createExperiment(input: $input) { id } }", {"input": {"name": "E"}})
    res = await aexecute(CREATE_EVENTS_LAYER, {"input": {"experiment": experiment.data["createExperiment"]["id"], "tableDataset": units["id"]}})
    assert res.errors and "no TIME coordinate column" in str(res.errors[0])


async def test_events_are_coloured_through_a_reference(aexecute, authenticated_context):
    """A trial's stimulus id references the stimulus table: colour trials by contrast, one hop away."""
    stimuli = await _table(aexecute, authenticated_context, "stimuli", STIMULI)
    trials = await _table(
        aexecute,
        authenticated_context,
        "trials",
        [*TRIALS[:3], {"name": "stimulus_id", "dtype": "BIGINT", "role": "ID", "references": stimuli["id"]}],
    )
    experiment = await _session(aexecute, authenticated_context, trials)

    res = await aexecute(
        CREATE_EVENTS_LAYER,
        {
            "input": {
                "experiment": experiment,
                "tableDataset": trials["id"],
                "colorBys": [
                    {"table": stimuli["id"], "column": "contrast", "joinPath": [{"table": trials["id"], "column": "stimulus_id"}], "colormap": "VIRIDIS"},
                    {"table": trials["id"], "column": "condition", "colormap": "HUES"},
                ],
                "filterBys": [{"table": trials["id"], "column": "condition", "values": ["catch"], "exclude": True}],
                "activeColorBy": 0,
                "activeFilterBys": [0],
            }
        },
    )
    assert not res.errors, res.errors
    layer = res.data["createEventsLayer"]
    assert layer["colorBys"][0] == {"table": stimuli["id"], "column": "contrast", "joinPath": [{"table": trials["id"], "column": "stimulus_id"}], "colormap": "VIRIDIS"}
    assert (layer["activeColorBy"], layer["activeFilterBys"]) == (0, [0])

    guarded = await aexecute("mutation ($input: DeleteTableDatasetInput!) { deleteTableDataset(input: $input) }", {"input": {"id": stimuli["id"]}})
    assert guarded.errors, "the stimulus table is referenced by the trials' column and named by a picker"


@pytest.mark.parametrize(
    ("entry", "refusal"),
    [
        ({"column": "contrast", "colormap": "VIRIDIS"}, "join path ends at table"),
        ({"column": "condition", "colormap": "VIRIDIS", "own": True}, "takes a qualitative colormap"),
        ({"column": "stop", "colormap": "HUES", "own": True}, "takes a continuous colormap"),
        ({"column": "nope", "own": True}, "declares no column"),
    ],
    ids=["unreachable", "category-needs-palette", "measure-needs-ramp", "no-such-column"],
)
async def test_a_picker_entry_is_checked_against_the_tables(aexecute, authenticated_context, entry, refusal):
    stimuli = await _table(aexecute, authenticated_context, "stimuli", STIMULI)
    trials = await _table(aexecute, authenticated_context, "trials", TRIALS)
    experiment = await _session(aexecute, authenticated_context, trials)
    entry = dict(entry)
    table = trials["id"] if entry.pop("own", False) else stimuli["id"]
    res = await aexecute(CREATE_EVENTS_LAYER, {"input": {"experiment": experiment, "tableDataset": trials["id"], "colorBys": [{"table": table, **entry}]}})
    assert res.errors and refusal in str(res.errors[0]), res.errors


async def test_an_active_index_points_at_an_entry(aexecute, authenticated_context):
    trials = await _table(aexecute, authenticated_context, "trials", TRIALS)
    experiment = await _session(aexecute, authenticated_context, trials)
    res = await aexecute(CREATE_EVENTS_LAYER, {"input": {"experiment": experiment, "tableDataset": trials["id"], "activeColorBy": 0}})
    assert res.errors and "`activeColorBy` is 0" in str(res.errors[0])


async def test_deleting_an_event_table_sweeps_its_space_and_its_layer(aexecute, authenticated_context):
    trials = await _table(aexecute, authenticated_context, "trials", TRIALS)
    experiment = await _session(aexecute, authenticated_context, trials)
    assert not (await aexecute(CREATE_EVENTS_LAYER, {"input": {"experiment": experiment, "tableDataset": trials["id"]}})).errors

    deleted = await aexecute("mutation ($input: DeleteTableDatasetInput!) { deleteTableDataset(input: $input) }", {"input": {"id": trials["id"]}})
    assert not deleted.errors, deleted.errors
    assert not await models.CoordinateSystem.objects.filter(pk=trials["coordinateSystem"]["id"]).aexists(), "the space it owned is swept, and the offset with it"
    assert not await models.ExperimentLayer.objects.aexists()
    assert await models.Experiment.objects.aexists()


async def test_a_shared_parquet_store_survives_the_purge_until_its_last_table_goes(aexecute, authenticated_context):
    """`TableDataset.store` is seen by `stores_orphaned_by`; a flag is a candidate, and the purge's `referrers_of` re-check keeps a store another table still reads."""
    import io

    from asgiref.sync import sync_to_async
    from django.core.management import call_command

    from core.logic import storage

    payload = await seed.table_input(authenticated_context, "trials", TRIALS)
    first = await aexecute(CREATE_TABLE, {"input": payload})
    second = await aexecute(CREATE_TABLE, {"input": {**payload, "name": "trials again"}})
    assert not first.errors and not second.errors, (first.errors, second.errors)
    store = await models.ParquetStore.objects.aget(pk=payload["data"])

    async def delete(table: dict) -> None:
        res = await aexecute("mutation ($input: DeleteTableDatasetInput!) { deleteTableDataset(input: $input) }", {"input": {"id": table["createTableDataset"]["id"]}})
        assert not res.errors, res.errors

    await delete(first.data)
    await store.arefresh_from_db()
    assert store.orphaned_at is not None, "a candidate: flagged by the delete that removed a referrer"
    await sync_to_async(call_command)("purge_orphaned_stores", older_than=0, stdout=io.StringIO())
    await store.arefresh_from_db()
    assert store.orphaned_at is None, "kept and un-flagged: the second table still reads it"

    await delete(second.data)
    await store.arefresh_from_db()
    assert store.orphaned_at is not None and await sync_to_async(storage.referrers_of)(store) == [], "the last reader gone, it is collectable"
