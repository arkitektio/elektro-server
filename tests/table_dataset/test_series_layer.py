"""Series: one numeric column of a table with a TIME column, drawn as a line over time.

Behaviour and slow measurements arrive as rows -- a running wheel's speed, a pupil's diameter --
and are a table like any event list. What makes one a *series* is its value: one numeric
attribute that is not itself a time. A table with a label column or a stop column is a list of
events, and the bootstrap tells the two apart by exactly that.
"""

import pytest

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

CREATE_TABLE = "mutation ($input: CreateTableDatasetInput!) { createTableDataset(input: $input) { id coordinateSystem { id } } }"

CREATE_SERIES = """
mutation ($input: CreateSeriesLayerInput!) {
  createSeriesLayer(input: $input) { kind name timeColumn valueColumn interpolation laneColumn placement }
}
"""

WHEEL = [
    {"name": "t", "dtype": "DOUBLE", "role": "COORDINATE", "axisType": "TIME", "unit": "second"},
    {"name": "speed", "dtype": "DOUBLE", "role": "ATTRIBUTE", "unit": "centimeter / second"},
    {"name": "wheel", "dtype": "VARCHAR", "role": "GROUP_ID"},
]

TTL = [
    {"name": "t", "dtype": "DOUBLE", "role": "COORDINATE", "axisType": "TIME", "unit": "second"},
    {"name": "stop", "dtype": "DOUBLE", "role": "ATTRIBUTE", "unit": "second"},
    {"name": "line", "dtype": "VARCHAR", "role": "LABEL"},
]


async def _placed(aexecute, ctx, name: str, columns: list[dict], clock) -> dict:  # noqa: ANN001
    created = await aexecute(CREATE_TABLE, {"input": await seed.table_input(ctx, name, columns)})
    assert not created.errors, created.errors
    table = created.data["createTableDataset"]
    space = await models.CoordinateSystem.objects.aget(pk=table["coordinateSystem"]["id"])
    await seed.offset_onto(ctx, space, clock, "0 s")
    return table


async def test_a_wheel_table_is_drawn_as_a_line_over_time(aexecute, authenticated_context):
    clock = await seed.create_clock(authenticated_context, "session")
    wheel = await _placed(aexecute, authenticated_context, "wheel", WHEEL, clock)
    experiment = await models.Experiment.objects.acreate(name="E", world=clock, creator=authenticated_context.request.user, organization=authenticated_context.request.organization)

    res = await aexecute(CREATE_SERIES, {"input": {"experiment": str(experiment.pk), "tableDataset": wheel["id"], "interpolation": "STEP", "laneColumn": "wheel"}})
    assert not res.errors, res.errors
    layer = res.data["createSeriesLayer"]
    assert (layer["kind"], layer["timeColumn"], layer["valueColumn"], layer["interpolation"], layer["laneColumn"], layer["placement"]) == (
        "SERIES",
        "t",
        "speed",
        "STEP",
        "wheel",
        "PLACED",
    ), "the one numeric, non-time attribute is the value, defaulted"


@pytest.mark.parametrize(
    ("value", "refusal"),
    [("t", "the table's TIME column"), ("wheel", "whose type is VARCHAR"), ("nope", "declares")],
    ids=["time", "text", "missing"],
)
async def test_the_value_is_a_numeric_column_that_is_not_the_time(aexecute, authenticated_context, value, refusal):
    clock = await seed.create_clock(authenticated_context, "session")
    wheel = await _placed(aexecute, authenticated_context, "wheel", WHEEL, clock)
    experiment = await models.Experiment.objects.acreate(name="E", world=clock, creator=authenticated_context.request.user, organization=authenticated_context.request.organization)
    res = await aexecute(CREATE_SERIES, {"input": {"experiment": str(experiment.pk), "tableDataset": wheel["id"], "valueColumn": value}})
    assert res.errors and refusal in str(res.errors[0]), res.errors


async def test_a_table_with_no_single_value_needs_it_named(aexecute, authenticated_context):
    clock = await seed.create_clock(authenticated_context, "session")
    ttl = await _placed(aexecute, authenticated_context, "TTL", TTL, clock)
    experiment = await models.Experiment.objects.acreate(name="E", world=clock, creator=authenticated_context.request.user, organization=authenticated_context.request.organization)
    res = await aexecute(CREATE_SERIES, {"input": {"experiment": str(experiment.pk), "tableDataset": ttl["id"]}})
    assert res.errors and "name the `valueColumn`" in str(res.errors[0])


async def test_the_bootstrap_tells_a_series_from_a_list_of_events(aexecute, authenticated_context):
    clock = await seed.create_clock(authenticated_context, "session")
    await _placed(aexecute, authenticated_context, "wheel", WHEEL, clock)
    await _placed(aexecute, authenticated_context, "TTL", TTL, clock)
    res = await aexecute(
        """
        mutation ($input: CreateExperimentFromCoordinateSystemInput!) {
          createExperimentFromCoordinateSystem(input: $input) {
            layers { kind name ... on SeriesLayer { valueColumn } ... on EventsLayer { stopColumn labelColumn } }
          }
        }
        """,
        {"input": {"coordinateSystem": str(clock.pk)}},
    )
    assert not res.errors, res.errors
    assert res.data["createExperimentFromCoordinateSystem"]["layers"] == [
        {"kind": "SERIES", "name": "wheel", "valueColumn": "speed"},
        {"kind": "EVENTS", "name": "TTL", "stopColumn": "stop", "labelColumn": "line"},
    ], "a numeric value makes a series; a stop and a label make events"
