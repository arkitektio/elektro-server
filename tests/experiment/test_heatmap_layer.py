"""Heatmaps: a lens over an array dataset drawn as an image, time across and one other axis down.

mikro's intensity layer, for time series: a spectrogram `(t, f)` -- its FREQUENCY axis drawn down
the image -- or a depth / current-source-density plot `(t, c)`. What is pinned: the row axis
resolves FREQUENCY, then CHANNEL, then INDEX; a third axis with more than one position is refused
(an image, not a stack); the colormap is continuous; and a bootstrap draws a spectrogram as a
heatmap, its range read off the dataset's recorded value histogram.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

TF_AXES = [seed.axis("t", seed.enums.AxisType.TIME), seed.axis("f", seed.enums.AxisType.FREQUENCY)]
TCF_AXES = [seed.axis("t", seed.enums.AxisType.TIME), seed.axis("c", seed.enums.AxisType.CHANNEL), seed.axis("f", seed.enums.AxisType.FREQUENCY)]

CREATE_HEATMAP = """
mutation ($input: CreateHeatmapLayerInput!) {
  createHeatmapLayer(input: $input) { kind name rowAxis colormap climMin climMax gamma placement duration lens { shape } }
}
"""


async def _session(ctx, dataset) -> tuple:  # noqa: ANN001
    """A session clock the dataset is timed on at 1 kHz, and an experiment over it."""
    clock = await seed.create_clock(ctx, "session")
    await seed.time_on(ctx, dataset.coordinate_system, clock, rate="1 kHz")
    experiment = await models.Experiment.objects.acreate(name="E", world=clock, creator=ctx.request.user, organization=ctx.request.organization)
    return clock, experiment


def _histogram(dataset: models.ArrayDataset, p1: float, p99: float) -> None:
    anchor = models.CoordinateAnchor.objects.get_or_create(dataset=dataset, coordinates={})[0]
    models.ValueHistogram.objects.create(anchor=anchor, histogram=[1, 2, 1], bins=[0, 1, 2], min=p1 - 10, max=p99 + 10, p1=p1, p99=p99)


async def test_a_spectrogram_is_drawn_with_frequency_down_the_image(aexecute, authenticated_context):
    spectrogram = await seed.create_array_dataset(authenticated_context, "LFP spectrogram", TF_AXES, [[2000, 64]])
    _, experiment = await _session(authenticated_context, spectrogram)
    res = await aexecute(CREATE_HEATMAP, {"input": {"experiment": str(experiment.pk), "dataset": str(spectrogram.pk), "colormap": "MAGMA", "gamma": 0.5, "climMin": -60, "climMax": 0}})
    assert not res.errors, res.errors
    layer = res.data["createHeatmapLayer"]
    assert (layer["kind"], layer["rowAxis"], layer["colormap"], layer["gamma"]) == ("HEATMAP", "f", "MAGMA", 0.5), "FREQUENCY is the row axis by default"
    assert (layer["climMin"], layer["climMax"], layer["placement"], layer["duration"]) == (-60.0, 0.0, "PLACED", "2 s")


async def test_a_multichannel_recording_is_a_depth_plot(aexecute, authenticated_context):
    recording = await seed.create_array_dataset(authenticated_context, "LFP", seed.TC_AXES, [[2000, 32]])
    _, experiment = await _session(authenticated_context, recording)
    res = await aexecute(CREATE_HEATMAP, {"input": {"experiment": str(experiment.pk), "dataset": str(recording.pk)}})
    assert not res.errors, res.errors
    assert res.data["createHeatmapLayer"]["rowAxis"] == "c", "no FREQUENCY axis: CHANNEL is drawn down"


async def test_a_heatmap_is_one_image_not_a_stack(aexecute, authenticated_context):
    """(t, c, f) has two axes besides time; fix one of them to a single position and it draws."""
    cube = await seed.create_array_dataset(authenticated_context, "per-channel spectrogram", TCF_AXES, [[2000, 4, 64]])
    _, experiment = await _session(authenticated_context, cube)
    stacked = await aexecute(CREATE_HEATMAP, {"input": {"experiment": str(experiment.pk), "dataset": str(cube.pk)}})
    assert stacked.errors and "also spans ['c']" in str(stacked.errors[0])

    one_channel = await seed.create_lens(authenticated_context, cube, slices=[{"axis": "c", "start": 2, "stop": 3}])
    fixed = await aexecute(CREATE_HEATMAP, {"input": {"experiment": str(experiment.pk), "lens": str(one_channel.pk)}})
    assert not fixed.errors, fixed.errors
    assert (fixed.data["createHeatmapLayer"]["rowAxis"], fixed.data["createHeatmapLayer"]["lens"]["shape"]) == ("f", [2000, 1, 64])


@pytest.mark.parametrize(
    ("settings", "refusal"),
    [
        ({"rowAxis": "t"}, "is a TIME axis"),
        ({"rowAxis": "nope"}, "has axes"),
        ({"colormap": "HUES"}, "takes a continuous one"),
        ({"climMin": 1, "climMax": -1}, "runs from `climMin` to `climMax`"),
    ],
    ids=["time-down", "unknown-axis", "qualitative", "inverted-range"],
)
async def test_a_heatmap_setting_is_checked(aexecute, authenticated_context, settings, refusal):
    spectrogram = await seed.create_array_dataset(authenticated_context, "spectrogram", TF_AXES, [[2000, 64]])
    _, experiment = await _session(authenticated_context, spectrogram)
    res = await aexecute(CREATE_HEATMAP, {"input": {"experiment": str(experiment.pk), "dataset": str(spectrogram.pk), **settings}})
    assert res.errors and refusal in str(res.errors[0]), res.errors


async def test_the_bootstrap_draws_a_spectrogram_as_a_heatmap_in_its_recorded_range(aexecute, authenticated_context):
    spectrogram = await seed.create_array_dataset(authenticated_context, "spectrogram", TF_AXES, [[2000, 64]])
    trace = await seed.create_array_dataset(authenticated_context, "Vm", seed.T_AXES, [[2000]])
    await sync_to_async(_histogram)(spectrogram, -55.0, -5.0)
    await sync_to_async(_histogram)(trace, -70.0, 20.0)
    clock, _ = await _session(authenticated_context, spectrogram)
    await seed.time_on(authenticated_context, trace.coordinate_system, clock, rate="1 kHz")

    res = await aexecute(
        """
        mutation ($input: CreateExperimentFromCoordinateSystemInput!) {
          createExperimentFromCoordinateSystem(input: $input) {
            layers { kind name ... on HeatmapLayer { rowAxis colormap climMin climMax } ... on TraceLayer { climMin climMax } }
          }
        }
        """,
        {"input": {"coordinateSystem": str(clock.pk), "name": "staged"}},
    )
    assert not res.errors, res.errors
    heatmap, trace_layer = res.data["createExperimentFromCoordinateSystem"]["layers"]
    assert (heatmap["kind"], heatmap["rowAxis"], heatmap["colormap"], heatmap["climMin"], heatmap["climMax"]) == ("HEATMAP", "f", "VIRIDIS", -55.0, -5.0)
    assert (trace_layer["kind"], trace_layer["climMin"], trace_layer["climMax"]) == ("TRACE", -70.0, 20.0), "a trace's y range is read off its histogram too"

    only_traces = await aexecute(
        "mutation ($input: CreateExperimentFromCoordinateSystemInput!) { createExperimentFromCoordinateSystem(input: $input) { layers { kind } } }",
        {"input": {"coordinateSystem": str(clock.pk), "name": "traces", "policy": {"includeHeatmaps": False}}},
    )
    assert only_traces.data["createExperimentFromCoordinateSystem"]["layers"] == [{"kind": "TRACE"}]
