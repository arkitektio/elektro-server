"""Points in space: a probe's channel map, drawn in an experiment over the probe's space.

An experiment's world is a timeline or a *place*: a clock, or a space with SPACE axes. A table
whose coordinate columns are SPACE -- a channel map `(x, y)` in micrometres, with a channel id and
a shank label beside -- is placed there by a registration of its own space, and drawn as a point
per row (mikro's point layer). The x and y columns are the table's declaration, read by name.
"""

import pytest

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

PROBE_AXES = [seed.physical_axis("y", seed.enums.AxisType.SPACE, "micrometer"), seed.physical_axis("x", seed.enums.AxisType.SPACE, "micrometer")]

CHANNEL_MAP = [
    {"name": "x", "axis_type": seed.enums.AxisType.SPACE, "unit": "micrometer"},
    {"name": "y", "axis_type": seed.enums.AxisType.SPACE, "unit": "micrometer"},
    {"name": "channel", "role": "ID", "dtype": "BIGINT"},
    {"name": "shank", "role": "LABEL", "dtype": "VARCHAR"},
    {"name": "impedance", "unit": "kiloohm"},
]

CREATE_POINTS = """
mutation ($input: CreatePointLayerInput!) {
  createPointLayer(input: $input) { kind name xColumn yColumn zColumn pointSize sizeColumn labelColumn placement colorBys { column colormap } }
}
"""


async def _probe(ctx):  # noqa: ANN001, ANN202
    """A probe space, a channel map registered into it, and an experiment over the space."""
    probe = await seed.create_world(ctx, "probe", axes=PROBE_AXES)
    channels = await seed.create_table_dataset(ctx, "channel map", columns=CHANNEL_MAP)
    await seed.register_into_world(ctx, probe, system=channels.coordinate_system)
    experiment = await models.Experiment.objects.acreate(name="probe", world=probe, creator=ctx.request.user, organization=ctx.request.organization)
    return probe, channels, experiment


async def test_a_channel_map_is_drawn_in_the_probe_space(aexecute, authenticated_context):
    _, channels, experiment = await _probe(authenticated_context)
    res = await aexecute(
        CREATE_POINTS,
        {
            "input": {
                "experiment": str(experiment.pk),
                "tableDataset": str(channels.pk),
                "pointSize": 6,
                "sizeColumn": "impedance",
                "labelColumn": "channel",
                "colorBys": [{"table": str(channels.pk), "column": "shank", "colormap": "HUES"}],
            }
        },
    )
    assert not res.errors, res.errors
    layer = res.data["createPointLayer"]
    assert (layer["kind"], layer["xColumn"], layer["yColumn"], layer["zColumn"], layer["placement"]) == ("POINT", "x", "y", None, "PLACED"), "x and y by name; no third SPACE column"
    assert (layer["pointSize"], layer["sizeColumn"], layer["labelColumn"]) == (6.0, "impedance", "channel")
    assert layer["colorBys"] == [{"column": "shank", "colormap": "HUES"}]


@pytest.mark.parametrize(
    ("settings", "refusal"),
    [({"sizeColumn": "shank"}, "whose type is VARCHAR"), ({"labelColumn": "nope"}, "declares"), ({"pointSize": 0}, "greater than 0")],
    ids=["size-by-text", "missing-label", "zero-size"],
)
async def test_a_point_setting_is_checked(aexecute, authenticated_context, settings, refusal):
    _, channels, experiment = await _probe(authenticated_context)
    res = await aexecute(CREATE_POINTS, {"input": {"experiment": str(experiment.pk), "tableDataset": str(channels.pk), **settings}})
    assert res.errors and refusal in str(res.errors[0]), res.errors


async def test_a_table_with_a_time_column_is_not_a_place(aexecute, authenticated_context):
    probe, _, experiment = await _probe(authenticated_context)
    events = await seed.create_table_dataset(authenticated_context, "TTL")
    res = await aexecute(CREATE_POINTS, {"input": {"experiment": str(experiment.pk), "tableDataset": str(events.pk)}})
    assert res.errors and "rows are events, not places" in str(res.errors[0])

    flat = await seed.create_table_dataset(authenticated_context, "depths", columns=[{"name": "depth", "axis_type": seed.enums.AxisType.SPACE, "unit": "micrometer"}])
    res = await aexecute(CREATE_POINTS, {"input": {"experiment": str(experiment.pk), "tableDataset": str(flat.pk)}})
    assert res.errors and "fewer than two SPACE coordinate columns" in str(res.errors[0])


async def test_the_bootstrap_draws_a_channel_map_as_points(aexecute, authenticated_context):
    probe, _, _ = await _probe(authenticated_context)
    res = await aexecute(
        "mutation ($input: CreateExperimentFromCoordinateSystemInput!) { createExperimentFromCoordinateSystem(input: $input) { name layers { kind name ... on PointLayer { xColumn yColumn } } } }",
        {"input": {"coordinateSystem": str(probe.pk)}},
    )
    assert not res.errors, res.errors
    staged = res.data["createExperimentFromCoordinateSystem"]
    assert staged["name"] == probe.name, "named for the space"
    assert staged["layers"] == [{"kind": "POINT", "name": "channel map", "xColumn": "x", "yColumn": "y"}], "a table placed in space, and nothing timed, over a probe's space"


async def test_units_at_their_positions_are_coloured_through_the_units_table(aexecute, authenticated_context):
    """The documented shape for units in space: a positions table whose (x, y) are SPACE axes and whose `unit_id` references the units table.

    The units table itself stays keyed by its one INDEX `unit_id` -- the raster's axis reference
    needs exactly that -- so it cannot also be placed; the positions table is placed instead, and a
    point layer over it colours each unit by a column of the units table, one hop away.
    """
    probe, _, experiment = await _probe(authenticated_context)
    units = await seed.create_table_dataset(
        authenticated_context,
        "units",
        columns=[{"name": "unit_id", "axis_type": seed.enums.AxisType.INDEX, "dtype": "BIGINT"}, {"name": "quality", "role": "LABEL", "dtype": "VARCHAR"}],
    )
    positions = await seed.create_table_dataset(
        authenticated_context,
        "unit positions",
        columns=[
            {"name": "x", "axis_type": seed.enums.AxisType.SPACE, "unit": "micrometer"},
            {"name": "y", "axis_type": seed.enums.AxisType.SPACE, "unit": "micrometer"},
            {"name": "unit_id", "role": "ID", "dtype": "BIGINT", "references": units},
        ],
    )
    await seed.register_into_world(authenticated_context, probe, system=positions.coordinate_system)
    res = await aexecute(
        CREATE_POINTS,
        {
            "input": {
                "experiment": str(experiment.pk),
                "tableDataset": str(positions.pk),
                "colorBys": [{"table": str(units.pk), "column": "quality", "joinPath": [{"table": str(positions.pk), "column": "unit_id"}], "colormap": "DISTINCT"}],
            }
        },
    )
    assert not res.errors, res.errors
    assert res.data["createPointLayer"]["colorBys"] == [{"column": "quality", "colormap": "DISTINCT"}]


async def test_unnamed_space_columns_are_read_by_position(aexecute, authenticated_context):
    """mikro's fallback when no column is named x or y: the last SPACE column is x, the one before it y (array order, z-y-x)."""
    probe = await seed.create_world(authenticated_context, "probe", axes=[seed.physical_axis("depth", seed.enums.AxisType.SPACE, "micrometer"), seed.physical_axis("lateral", seed.enums.AxisType.SPACE, "micrometer")])
    sites = await seed.create_table_dataset(
        authenticated_context,
        "sites",
        columns=[{"name": "depth", "axis_type": seed.enums.AxisType.SPACE, "unit": "micrometer"}, {"name": "lateral", "axis_type": seed.enums.AxisType.SPACE, "unit": "micrometer"}],
    )
    await seed.register_into_world(authenticated_context, probe, system=sites.coordinate_system)
    experiment = await models.Experiment.objects.acreate(name="probe", world=probe, creator=authenticated_context.request.user, organization=authenticated_context.request.organization)
    res = await aexecute(CREATE_POINTS, {"input": {"experiment": str(experiment.pk), "tableDataset": str(sites.pk)}})
    assert not res.errors, res.errors
    layer = res.data["createPointLayer"]
    assert (layer["xColumn"], layer["yColumn"], layer["zColumn"]) == ("lateral", "depth", None), "the last is x, the one before it y; two columns have no z"
