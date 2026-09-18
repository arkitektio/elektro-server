"""Waveform templates: an array dataset (unit, c, w) derived from a spike raster, drawn in peri-spike time.

The CS-first answer to "where is a waveform in time": its `w` axis is timed by a sampling law onto
a **peri-spike clock** -- a clock whose zero is the spike -- with a negative start, so sample 0 is a
millisecond before the spike. That clock is not the session's, and nothing forces it to be: a
waveform layer lives in an experiment over the peri-spike clock. Its units are the raster's, so
its colour and order come from the raster's units table, reached through the templates'
derivation edge.
"""

import pytest

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

TEMPLATE_AXES = [{"name": "unit", "type": "INDEX"}, {"name": "c", "type": "CHANNEL"}, {"name": "w", "type": "TIME"}]


async def _templates(aexecute, ctx, create_array_dataset):  # noqa: ANN001, ANN202
    """A units table, a raster identified by it, templates derived from the raster, and a peri-spike clock the templates' `w` is timed on."""
    units = await seed.create_table_dataset(
        ctx,
        "units",
        columns=[
            {"name": "unit_id", "axis_type": seed.enums.AxisType.INDEX, "dtype": "BIGINT"},
            {"name": "depth", "unit": "micrometer"},
            {"name": "quality", "role": "LABEL", "dtype": "VARCHAR"},
        ],
    )
    raster = await seed.create_sparse_dataset(ctx, "spikes", units=units)
    templates = await create_array_dataset(
        "templates", [8, 4, 60], axes=TEMPLATE_AXES, derived_from=[{"kind": "COORDINATE_SYSTEM", "coordinateSystem": str(raster.coordinate_system_id)}]
    )
    peri = await seed.create_clock(ctx, "peri-spike", unit="millisecond")
    timed = await aexecute(
        "mutation ($input: CreateSamplingLawInput!) { createSamplingLaw(input: $input) { id } }",
        {"input": {"source": templates["intrinsicSystem"]["id"], "clock": str(peri.pk), "samplingRate": "30 kHz", "tStart": "-1 ms"}},
    )
    assert not timed.errors, timed.errors
    return units, raster, templates, peri


WAVEFORM_FIELDS = "kind name unitAxis unitTable { name } duration placement asAffine { matrix inputAxes outputAxes } colorBys { column colormap } activeColorBy"


async def test_templates_are_drawn_in_peri_spike_time(aexecute, authenticated_context, create_array_dataset):
    units, _, templates, peri = await _templates(aexecute, authenticated_context, create_array_dataset)
    experiment = await models.Experiment.objects.acreate(name="waveforms", world=peri, creator=authenticated_context.request.user, organization=authenticated_context.request.organization)
    res = await aexecute(
        "mutation ($input: CreateWaveformLayerInput!) { createWaveformLayer(input: $input) { %s } }" % WAVEFORM_FIELDS,
        {"input": {"experiment": str(experiment.pk), "dataset": templates["id"], "colorBys": [{"table": str(units.pk), "column": "depth", "colormap": "VIRIDIS"}], "activeColorBy": 0}},
    )
    assert not res.errors, res.errors
    layer = res.data["createWaveformLayer"]
    assert (layer["kind"], layer["unitAxis"], layer["unitTable"], layer["placement"], layer["duration"]) == ("WAVEFORM", "unit", {"name": "units"}, "PLACED", "2 ms")
    assert layer["colorBys"] == [{"column": "depth", "colormap": "VIRIDIS"}] and layer["activeColorBy"] == 0
    assert layer["asAffine"]["inputAxes"] == ["unit", "c", "w"] and layer["asAffine"]["outputAxes"] == ["t"]
    assert layer["asAffine"]["matrix"][0] == pytest.approx([0.0, 0.0, 1 / 30, -1.0]), "sample 0 of a template is a millisecond before the spike"


async def test_the_bootstrap_draws_templates_as_waveforms(aexecute, authenticated_context, create_array_dataset):
    _, _, templates, peri = await _templates(aexecute, authenticated_context, create_array_dataset)
    res = await aexecute(
        "mutation ($input: CreateExperimentFromCoordinateSystemInput!) { createExperimentFromCoordinateSystem(input: $input) { layers { kind name ... on WaveformLayer { unitTable { name } } } } }",
        {"input": {"coordinateSystem": str(peri.pk)}},
    )
    assert not res.errors, res.errors
    (layer,) = res.data["createExperimentFromCoordinateSystem"]["layers"]
    assert (layer["kind"], layer["name"], layer["unitTable"]) == ("WAVEFORM", "templates", {"name": "units"}), "an INDEX axis and a raster for a parent make templates"


async def test_an_array_not_derived_from_a_raster_has_no_units_table(aexecute, authenticated_context, create_array_dataset):
    """Drawn as waveforms on request, but nothing to colour its units by: the pickers are refused rather than guessed."""
    loose = await create_array_dataset("loose templates", [8, 4, 60], axes=TEMPLATE_AXES)
    peri = await seed.create_clock(authenticated_context, "peri-spike", unit="millisecond")
    assert not (
        await aexecute(
            "mutation ($input: CreateSamplingLawInput!) { createSamplingLaw(input: $input) { id } }",
            {"input": {"source": loose["intrinsicSystem"]["id"], "clock": str(peri.pk), "samplingRate": "30 kHz"}},
        )
    ).errors
    experiment = await models.Experiment.objects.acreate(name="w", world=peri, creator=authenticated_context.request.user, organization=authenticated_context.request.organization)
    plain = await aexecute("mutation ($input: CreateWaveformLayerInput!) { createWaveformLayer(input: $input) { unitTable { name } } }", {"input": {"experiment": str(experiment.pk), "dataset": loose["id"]}})
    assert not plain.errors, plain.errors
    assert plain.data["createWaveformLayer"]["unitTable"] is None
    coloured = await aexecute(
        "mutation ($input: CreateWaveformLayerInput!) { createWaveformLayer(input: $input) { id } }",
        {"input": {"experiment": str(experiment.pk), "dataset": loose["id"], "colorBys": [{"table": "1", "column": "depth"}]}},
    )
    assert coloured.errors and "has no table to colour by" in str(coloured.errors[0])


async def test_a_template_has_one_unit_axis(aexecute, authenticated_context, create_array_dataset):
    two = await create_array_dataset("two index axes", [8, 4, 60], axes=[{"name": "unit", "type": "INDEX"}, {"name": "sweep", "type": "INDEX"}, {"name": "w", "type": "TIME"}])
    peri = await seed.create_clock(authenticated_context, "peri-spike", unit="millisecond")
    experiment = await models.Experiment.objects.acreate(name="w", world=peri, creator=authenticated_context.request.user, organization=authenticated_context.request.organization)
    res = await aexecute("mutation ($input: CreateWaveformLayerInput!) { createWaveformLayer(input: $input) { id } }", {"input": {"experiment": str(experiment.pk), "dataset": two["id"]}})
    assert res.errors and "2 INDEX axes" in str(res.errors[0])
