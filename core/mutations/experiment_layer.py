"""Adding, restyling and rebinding the layers of an experiment: mikro's layer mutations, over time.

One generic pair (``createLayer`` / ``updateLayer``, compositing only) and one pair per kind
carrying that kind's render settings -- mikro's shape. Every create and every rebind goes
through the same two checks (:mod:`core.logic.experiment`): the kind can draw the source, and
the source *reaches* the experiment's world. Reaches, not "condenses into one affine map" -- a
raster or a trace timed by a lookup is drawn all the same (``core/DESIGN.md``, divergence 2).

``createTraceLayer`` keeps one piece of input sugar, ``window``: a stretch of time on the
dataset's own clock, lowered to a lens by inverting its sampling law. A lens is a pure
selection and cannot disagree with anything, so the sugar is safe. There is no ``offset``:
where a clock sits is ``createClockOffset``'s, stated once for everything timed on it.
"""

import strawberry
from django.db import transaction
from kante.types import Info
from pydantic import BaseModel, Field, model_validator

import kante
from kanne_server import scalars as quantities

from core import enums, models, types
from core.base_models.slices import SliceInputModel
from core.creation import CreationContext
from core.logic import clocks, ephys_pickers
from core.logic import coordinate_system as coordinate_system_logic
from core.logic import experiment as experiment_logic
from core.render import pickers as picker_models
from core.scoping import get_for_org

_KIND = enums.ExperimentLayerKindChoices


# --- shared -------------------------------------------------------------------------------------


class _Compositing(BaseModel):
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    visible: bool | None = None
    order: int | None = None


def _compositing(parsed: _Compositing) -> dict:
    """The compositing fields a caller stated, as model columns. Omitted ones keep their defaults."""
    values = {"name": parsed.name, "opacity": parsed.opacity, "visible": parsed.visible, "order": parsed.order}
    if parsed.blending is not None:
        values["blending"] = parsed.blending.value
    return {key: value for key, value in values.items() if value is not None}


def _rgba(color: list[int] | None) -> list[int] | None:
    if color is None:
        return None
    if len(color) != 4 or any(not 0 <= channel <= 255 for channel in color):
        raise ValueError(f"A colour is RGBA, four components each 0..255, but got {color}.")
    return list(color)


def _apply(layer: "models.ExperimentLayer", values: dict) -> "models.ExperimentLayer":
    for key, value in values.items():
        setattr(layer, key, value)
    layer.save()
    return layer


def _get_layer(info: Info, identifier: str, kind: str | None = None) -> "models.ExperimentLayer":
    layer = get_for_org(models.ExperimentLayer, info, id=identifier)
    if kind is not None and layer.kind != kind:
        raise ValueError(f"Layer {layer.pk} is a {layer.kind} layer, not a {kind} one. Use update{layer.kind.capitalize()}Layer, or the generic updateLayer for compositing.")
    return layer


# --- generic ------------------------------------------------------------------------------------


class CreateLayerInputModel(_Compositing):
    experiment: str
    kind: enums.ExperimentLayerKind
    lens: str | None = None
    sparse_dataset: str | None = None
    table_dataset: str | None = None
    annotation_collection: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "CreateLayerInputModel":
        given = [name for name in ("lens", "sparse_dataset", "table_dataset", "annotation_collection") if getattr(self, name) is not None]
        wanted = experiment_logic.SOURCE_FIELD[self.kind.value]
        if given != [wanted]:
            raise ValueError(f"A {self.kind.value} layer names exactly one source, its `{wanted}`, but {given or 'none'} {'was' if len(given) == 1 else 'were'} given.")
        return self


@kante.pydantic_input(CreateLayerInputModel, description="Add a layer of any kind with default render settings: exactly one source, the one its kind draws. The per-kind mutations set the render settings too")
class CreateLayerInput:
    experiment: strawberry.ID
    kind: enums.ExperimentLayerKind
    lens: strawberry.ID | None = strawberry.field(default=None, description="(TRACE) The lens over an array dataset to draw")
    sparse_dataset: strawberry.ID | None = strawberry.field(default=None, description="(SPIKES) The spike raster to draw")
    table_dataset: strawberry.ID | None = strawberry.field(default=None, description="(EVENTS) The event table to draw")
    annotation_collection: strawberry.ID | None = strawberry.field(default=None, description="(ANNOTATION) The annotation collection to draw")
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = strawberry.field(default=None, description="The position top to bottom. Omit to append")


_SOURCE_MODELS = {"lens": models.Lens, "sparse_dataset": models.SparseDataset, "table_dataset": models.TableDataset, "annotation_collection": models.AnnotationCollection}


def create_layer(info: Info, input: CreateLayerInput) -> types.ExperimentLayer:
    """Add a layer of any kind, with default render settings."""
    parsed = input.to_pydantic()
    experiment = get_for_org(models.Experiment, info, id=parsed.experiment)
    field = experiment_logic.SOURCE_FIELD[parsed.kind.value]
    source = get_for_org(_SOURCE_MODELS[field], info, id=getattr(parsed, field))
    with transaction.atomic():
        return experiment_logic.create_layer(experiment, kind=parsed.kind.value, source=source, **_compositing(parsed))


class UpdateLayerInputModel(_Compositing):
    id: str


@kante.pydantic_input(UpdateLayerInputModel, description="Restyle any layer's compositing: its name, blending, opacity, visibility and position. Its source and render settings are the per-kind update's")
class UpdateLayerInput:
    id: strawberry.ID
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = None


def update_layer(info: Info, input: UpdateLayerInput) -> types.ExperimentLayer:
    """Restyle a layer's compositing, whatever its kind."""
    parsed = input.to_pydantic()
    return _apply(_get_layer(info, parsed.id), _compositing(parsed))


# --- trace --------------------------------------------------------------------------------------


class WindowInputModel(BaseModel):
    start: int | None = None
    stop: int | None = None


@kante.pydantic_input(WindowInputModel, description="A stretch of time on the dataset's OWN clock, e.g. the first 200 ms of a sweep. Lowered to a lens by inverting the sampling law, so it needs one")
class WindowInput:
    start: quantities.Duration | None = strawberry.field(default=None, description="The first instant shown, on the dataset's own clock. Omit to start at the first sample")
    stop: quantities.Duration | None = strawberry.field(default=None, description="The instant the layer stops before, on the dataset's own clock. Omit to run to the last sample")


class _TraceSettings(_Compositing):
    channel_index: int | None = Field(default=None, ge=0)
    color: list[int] | None = None
    line_width: float | None = Field(default=None, gt=0)
    clim_min: float | None = None
    clim_max: float | None = None


class CreateTraceLayerInputModel(_TraceSettings):
    experiment: str
    lens: str | None = None
    dataset: str | None = None
    window: WindowInputModel | None = None
    clock: str | None = None

    @model_validator(mode="after")
    def _one_selection(self) -> "CreateTraceLayerInputModel":
        if (self.lens is None) == (self.dataset is None):
            raise ValueError("A trace layer draws one selection: name an existing `lens`, or a `dataset` (optionally with a `window`) to have one cut for you -- exactly one of the two.")
        if self.lens is not None and (self.window is not None or self.clock is not None):
            raise ValueError("`window` and `clock` cut a lens out of `dataset`; an existing `lens` is already cut.")
        return self


@kante.pydantic_input(
    CreateTraceLayerInputModel,
    description="Draw an array dataset -- a recording, a stimulus, any signal -- as a trace: a lens over it, and how the lines look. Name a `lens`, or a `dataset` with an optional `window` of time",
)
class CreateTraceLayerInput:
    experiment: strawberry.ID
    lens: strawberry.ID | None = strawberry.field(default=None, description="An existing lens to draw. Exactly one of `lens` and `dataset`")
    dataset: strawberry.ID | None = strawberry.field(default=None, description="An array dataset to draw, through its whole-dataset lens or the one `window` cuts. Exactly one of `lens` and `dataset`")
    window: WindowInput | None = strawberry.field(
        default=None,
        description="Draw only a stretch of time, given on the dataset's own clock. Lowered to a sliced lens by inverting the sampling law -- refused over a time lookup, which has no closed-form inverse: cut a lens in sample indices with createLens instead",
    )
    clock: strawberry.ID | None = strawberry.field(default=None, description="The clock `window` is given on, when the dataset is timed on more than one. Omit when it is timed on one")
    channel_index: int | None = strawberry.field(default=None, description="Draw only this channel of the lens' CHANNEL axis. Omit to draw every channel, stacked")
    color: list[int] | None = strawberry.field(default=None, description="The base colour as RGBA, 0-255")
    line_width: float | None = strawberry.field(default=None, description="The line width, in screen pixels")
    clim_min: float | None = strawberry.field(default=None, description="The bottom of the value range, in the dataset's value unit")
    clim_max: float | None = strawberry.field(default=None, description="The top of the value range, in the dataset's value unit")
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = strawberry.field(default=None, description="The position top to bottom. Omit to append")


def _trace_settings(parsed: _TraceSettings) -> dict:
    if parsed.clim_min is not None and parsed.clim_max is not None and parsed.clim_min > parsed.clim_max:
        raise ValueError(f"A value range runs from `climMin` to `climMax`, but {parsed.clim_min} > {parsed.clim_max}.")
    values = {"channel_index": parsed.channel_index, "color": _rgba(parsed.color), "line_width": parsed.line_width, "clim_min": parsed.clim_min, "clim_max": parsed.clim_max}
    return {key: value for key, value in values.items() if value is not None}


def _assert_channel(lens: "models.Lens", channel_index: int | None) -> None:
    if channel_index is None:
        return
    axis = lens.dataset.coordinate_system.axes.filter(type=enums.AxisTypeChoices.CHANNEL.value).first() if lens.dataset.coordinate_system_id else None
    if axis is None:
        raise ValueError(f"`channelIndex` picks a channel, but dataset '{lens.dataset.name}' has no CHANNEL axis.")
    size = lens.get_size_of_axis(axis.name)
    if not 0 <= channel_index < size:
        raise ValueError(f"`channelIndex` is {channel_index}, but lens {lens.pk} selects {size} channel(s) along '{axis.name}'.")


def _window_lens(dataset: "models.ArrayDataset", window: WindowInputModel, clock_id: str | None, info: Info, ctx: CreationContext) -> "models.Lens":
    """The lens a window lowers to: the samples between two instants, found by inverting the sampling law."""
    grid = clocks.grid_of(dataset)
    if clock_id is not None:
        clock = get_for_org(models.CoordinateSystem, info, id=clock_id)
    else:
        timing = clocks.timing_clocks_of(grid)
        if not timing:
            raise ValueError(f"A `window` is a stretch of time on the dataset's clock, but '{dataset.name}' is timed on no clock. Give it a sampling law (`createSamplingLaw`) first.")
        if len(timing) > 1:
            raise ValueError(f"'{dataset.name}' is timed on {len(timing)} clocks ({', '.join(repr(c.name) for c in timing)}), so a `window` alone does not say whose time it is in. Name the `clock`.")
        clock = timing[0]
    rate, t_start = clocks.sampling_of(grid, clock)
    if rate is None:
        raise ValueError(
            f"A `window` is a stretch of time, found by inverting the sampling law -- but '{dataset.name}' is timed on '{clock.name}' by a lookup (or not at all), "
            "which has no closed-form inverse. Cut a lens in sample indices with createLens and pass it as `lens`."
        )
    sample_axis = clocks.time_axis(grid)
    size = dataset.shape_list[dataset.axis_names.index(sample_axis.name)]

    def sample_at(instant: int | None, default: int) -> int:
        if instant is None:
            return default
        # picoseconds -> samples: (t - t_start) * rate, with the rate in nanohertz.
        return max(0, min(size, round((instant - t_start) * rate / 1e21)))

    start, stop = sample_at(window.start, 0), sample_at(window.stop, size)
    if stop <= start:
        raise ValueError(f"The window over '{dataset.name}' selects no samples: it runs from sample {start} to sample {stop} of {size}.")
    return coordinate_system_logic.create_lens(dataset, [SliceInputModel(axis=sample_axis.name, start=start, stop=stop)], ctx)


def create_trace_layer(info: Info, input: CreateTraceLayerInput) -> types.TraceLayer:
    """Draw an array dataset as a trace."""
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)
    experiment = get_for_org(models.Experiment, info, id=parsed.experiment)
    with transaction.atomic():
        if parsed.lens is not None:
            lens = get_for_org(models.Lens, info, id=parsed.lens)
        else:
            dataset = get_for_org(models.ArrayDataset, info, id=parsed.dataset)
            window = parsed.window
            if window is None or (window.start is None and window.stop is None):
                lens = experiment_logic.whole_lens(dataset, ctx)
            else:
                lens = _window_lens(dataset, window, parsed.clock, info, ctx)
        _assert_channel(lens, parsed.channel_index)
        return experiment_logic.create_layer(experiment, kind=_KIND.TRACE.value, source=lens, **_compositing(parsed), **_trace_settings(parsed))


class UpdateTraceLayerInputModel(_TraceSettings):
    id: str
    lens: str | None = None


@kante.pydantic_input(UpdateTraceLayerInputModel, description="Restyle a trace layer, or point it at another lens. Only the supplied fields change")
class UpdateTraceLayerInput:
    id: strawberry.ID
    lens: strawberry.ID | None = strawberry.field(default=None, description="Draw this lens instead. It must reach the experiment's world")
    channel_index: int | None = None
    color: list[int] | None = None
    line_width: float | None = None
    clim_min: float | None = None
    clim_max: float | None = None
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = None


def update_trace_layer(info: Info, input: UpdateTraceLayerInput) -> types.TraceLayer:
    """Restyle or rebind a trace layer."""
    parsed = input.to_pydantic()
    layer = _get_layer(info, parsed.id, _KIND.TRACE.value)
    values = {**_compositing(parsed), **_trace_settings(parsed)}
    lens = layer.lens
    if parsed.lens is not None:
        lens = get_for_org(models.Lens, info, id=parsed.lens)
        experiment_logic.assert_reaches(layer.experiment.world, lens)
        values["lens"] = lens
    _assert_channel(lens, parsed.channel_index)
    return _apply(layer, values)


# --- spikes -------------------------------------------------------------------------------------


class _PickerSettings(_Compositing):
    color: list[int] | None = None
    colormap: enums.ColorMap | None = None
    color_bys: list[picker_models.ColorByModel] | None = None
    filter_bys: list[picker_models.FilterByModel] | None = None
    active_color_by: int | None = None
    active_filter_bys: list[int] | None = None


class _SpikeSettings(_PickerSettings):
    tick_height: float | None = Field(default=None, gt=0.0, le=1.0)
    row_order_column: str | None = None
    value_mode: enums.SpikeValueMode | None = None
    rate_bin: int | None = Field(default=None, gt=0)
    clim_min: float | None = None
    clim_max: float | None = None


def _picker_values(parsed: _PickerSettings, root: "models.TableDataset | None", layer: "models.ExperimentLayer | None", prefix: str) -> dict:
    """The picker columns a caller stated, checked against the layer's root table."""
    values: dict = {}
    color_bys = ephys_pickers.validate_color_bys(parsed.color_bys, root) if parsed.color_bys is not None else (getattr(layer, f"{prefix}_color_bys", None) or [])
    filter_bys = ephys_pickers.validate_filter_bys(parsed.filter_bys, root) if parsed.filter_bys is not None else (getattr(layer, f"{prefix}_filter_bys", None) or [])
    if parsed.color_bys is not None:
        values[f"{prefix}_color_bys"] = color_bys
    if parsed.filter_bys is not None:
        values[f"{prefix}_filter_bys"] = filter_bys
    active = parsed.active_color_by if parsed.active_color_by is not None else getattr(layer, "active_color_by", None)
    ephys_pickers.assert_active_color_by(active, color_bys)
    if parsed.active_color_by is not None:
        values["active_color_by"] = parsed.active_color_by
    actives = parsed.active_filter_bys if parsed.active_filter_bys is not None else (getattr(layer, "active_filter_bys", None) or [])
    ephys_pickers.assert_active_filter_bys(actives, filter_bys)
    if parsed.active_filter_bys is not None:
        values["active_filter_bys"] = list(parsed.active_filter_bys)
    if parsed.color is not None:
        values["color"] = _rgba(parsed.color)
    if parsed.colormap is not None:
        values["colormap"] = parsed.colormap.value
    return values


def _spike_values(parsed: _SpikeSettings, raster: "models.SparseDataset", layer: "models.ExperimentLayer | None") -> dict:
    root = ephys_pickers.spike_root(raster)
    values = _picker_values(parsed, root, layer, "spike")
    experiment_logic.assert_column(root, parsed.row_order_column, "rowOrderColumn")
    if parsed.clim_min is not None and parsed.clim_max is not None and parsed.clim_min > parsed.clim_max:
        raise ValueError(f"An amplitude range runs from `climMin` to `climMax`, but {parsed.clim_min} > {parsed.clim_max}.")
    for key in ("tick_height", "row_order_column", "rate_bin", "clim_min", "clim_max"):
        if getattr(parsed, key) is not None:
            values[key] = getattr(parsed, key)
    if parsed.value_mode is not None:
        values["value_mode"] = parsed.value_mode.value
    return values


class CreateSpikesLayerInputModel(_SpikeSettings):
    experiment: str
    sparse_dataset: str


_COLOR_BYS = "The colour picker: columns of the layer's table, or of tables it references along `joinPath`. Replaces the whole picker"
_FILTER_BYS = "The filter picker: columns of the layer's table, or of tables it references along `joinPath`. Replaces the whole picker"


@strawberry.input(description="One colour picker entry to store: a column of a table the layer reaches, and how it becomes colour. mikro's COLUMN colour-by input, field for field")
class ColorByInput:
    table: strawberry.ID
    column: str
    join_path: list["JoinStepInput"] | None = None
    colormap: enums.ColorMap | None = None
    min: float | None = None
    max: float | None = None
    label: str | None = None

    def to_pydantic(self) -> picker_models.ColorByModel:
        return picker_models.ColorByModel(
            table=str(self.table), column=self.column, join_path=[step.to_pydantic() for step in self.join_path or []], colormap=self.colormap, min=self.min, max=self.max, label=self.label
        )


@strawberry.input(description="One filter picker entry to store: a column of a table the layer reaches, and the range or values to keep")
class FilterByInput:
    table: strawberry.ID
    column: str
    join_path: list["JoinStepInput"] | None = None
    min: float | None = None
    max: float | None = None
    values: list[str] | None = None
    exclude: bool = False
    label: str | None = None

    def to_pydantic(self) -> picker_models.FilterByModel:
        return picker_models.FilterByModel(
            table=str(self.table),
            column=self.column,
            join_path=[step.to_pydantic() for step in self.join_path or []],
            min=self.min,
            max=self.max,
            values=self.values,
            exclude=self.exclude,
            label=self.label,
        )


@strawberry.input(description="One reference hop: the column, in the table it stands in, whose values identify rows of the next table")
class JoinStepInput:
    table: strawberry.ID
    column: str

    def to_pydantic(self) -> picker_models.JoinStepModel:
        return picker_models.JoinStepModel(table=str(self.table), column=self.column)


def _pickers_of(input) -> dict:  # noqa: ANN001 - a strawberry input with color_bys / filter_bys
    """The picker lists of a strawberry input, lowered to their models (strawberry inputs are not pydantic-backed here)."""
    values = {}
    if getattr(input, "color_bys", None) is not None:
        values["color_bys"] = [entry.to_pydantic() for entry in input.color_bys]
    if getattr(input, "filter_bys", None) is not None:
        values["filter_bys"] = [entry.to_pydantic() for entry in input.filter_bys]
    return values


@strawberry.input(description="Draw a spike raster -- a sparse dataset over (unit, t) -- as a tick per spike and a row per unit, or as a rate histogram. Colour and order come from the table identifying its unit axis")
class CreateSpikesLayerInput:
    experiment: strawberry.ID
    sparse_dataset: strawberry.ID = strawberry.field(description="The spike raster to draw. It needs a TIME axis, placed on a clock that reaches the world")
    tick_height: float | None = strawberry.field(default=None, description="A spike tick's height as a fraction of its unit's row, 0 to 1")
    row_order_column: str | None = strawberry.field(default=None, description="A column of the unit table to order the rows by (depth, channel)")
    value_mode: enums.SpikeValueMode | None = strawberry.field(default=None, description="PRESENCE (every nonzero is a spike) or AMPLITUDE (the value is drawn through `colormap`)")
    rate_bin: quantities.Duration | None = strawberry.field(default=None, description="Draw a firing-rate histogram at this bin width instead of a raster")
    clim_min: float | None = None
    clim_max: float | None = None
    color: list[int] | None = strawberry.field(default=None, description="The base colour as RGBA, 0-255")
    colormap: enums.ColorMap | None = None
    color_bys: list[ColorByInput] | None = strawberry.field(default=None, description=_COLOR_BYS)
    filter_bys: list[FilterByInput] | None = strawberry.field(default=None, description=_FILTER_BYS)
    active_color_by: int | None = None
    active_filter_bys: list[int] | None = None
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = strawberry.field(default=None, description="The position top to bottom. Omit to append")

    def to_pydantic(self) -> CreateSpikesLayerInputModel:
        return CreateSpikesLayerInputModel(**{**_plain(self, CreateSpikesLayerInputModel), **_pickers_of(self)})


def _plain(input, model: type[BaseModel]) -> dict:  # noqa: ANN001 - a strawberry input
    """The scalar fields of a strawberry input the pydantic model declares, pickers aside."""
    return {name: getattr(input, name) for name in model.model_fields if name not in ("color_bys", "filter_bys") and hasattr(input, name)}


def create_spikes_layer(info: Info, input: CreateSpikesLayerInput) -> types.SpikesLayer:
    """Draw a spike raster."""
    parsed = input.to_pydantic()
    experiment = get_for_org(models.Experiment, info, id=parsed.experiment)
    raster = get_for_org(models.SparseDataset, info, id=parsed.sparse_dataset)
    with transaction.atomic():
        return experiment_logic.create_layer(experiment, kind=_KIND.SPIKES.value, source=raster, **_compositing(parsed), **_spike_values(parsed, raster, None))


class UpdateSpikesLayerInputModel(_SpikeSettings):
    id: str
    sparse_dataset: str | None = None


@strawberry.input(description="Restyle a spikes layer, or point it at another raster. Only the supplied fields change; a picker is replaced whole")
class UpdateSpikesLayerInput:
    id: strawberry.ID
    sparse_dataset: strawberry.ID | None = None
    tick_height: float | None = None
    row_order_column: str | None = None
    value_mode: enums.SpikeValueMode | None = None
    rate_bin: quantities.Duration | None = None
    clim_min: float | None = None
    clim_max: float | None = None
    color: list[int] | None = None
    colormap: enums.ColorMap | None = None
    color_bys: list[ColorByInput] | None = strawberry.field(default=None, description=_COLOR_BYS)
    filter_bys: list[FilterByInput] | None = strawberry.field(default=None, description=_FILTER_BYS)
    active_color_by: int | None = None
    active_filter_bys: list[int] | None = None
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = None

    def to_pydantic(self) -> UpdateSpikesLayerInputModel:
        return UpdateSpikesLayerInputModel(**{**_plain(self, UpdateSpikesLayerInputModel), **_pickers_of(self)})


def update_spikes_layer(info: Info, input: UpdateSpikesLayerInput) -> types.SpikesLayer:
    """Restyle or rebind a spikes layer."""
    parsed = input.to_pydantic()
    layer = _get_layer(info, parsed.id, _KIND.SPIKES.value)
    raster = layer.sparse_dataset
    values: dict = {}
    if parsed.sparse_dataset is not None:
        raster = get_for_org(models.SparseDataset, info, id=parsed.sparse_dataset)
        experiment_logic.assert_kind(_KIND.SPIKES.value, raster)
        experiment_logic.assert_reaches(layer.experiment.world, raster)
        values["sparse_dataset"] = raster
    values.update(_compositing(parsed))
    values.update(_spike_values(parsed, raster, layer))
    return _apply(layer, values)


# --- events -------------------------------------------------------------------------------------


class _EventSettings(_PickerSettings):
    stop_column: str | None = None
    label_column: str | None = None
    lane_column: str | None = None


def _event_values(parsed: _EventSettings, table: "models.TableDataset", layer: "models.ExperimentLayer | None") -> dict:
    values = _picker_values(parsed, table, layer, "event")
    for key, what in (("stop_column", "stopColumn"), ("label_column", "labelColumn"), ("lane_column", "laneColumn")):
        experiment_logic.assert_column(table, getattr(parsed, key), what)
        if getattr(parsed, key) is not None:
            values[key] = getattr(parsed, key)
    if parsed.stop_column is not None:
        _assert_stop_column(table, parsed.stop_column)
    return values


def _assert_stop_column(table: "models.TableDataset", name: str) -> None:
    """A stop column ends an interval begun at the TIME column, so it counts in an interchangeable unit."""
    from core.logic import coords as coords_logic

    start = experiment_logic.time_column(table)
    stop = table.columns.get(name=name)
    if start is not None and start.name == stop.name:
        raise ValueError(f"`stopColumn` is '{name}', the table's own TIME column: an interval from each instant to itself is an instant. Omit it to draw instants.")
    if start is not None and start.unit and stop.unit and not coords_logic.units_are_interchangeable(start.unit, stop.unit):
        raise ValueError(f"`stopColumn` '{name}' is in '{stop.unit}' but the TIME column '{start.name}' is in '{start.unit}': an interval's two ends are in one unit of time.")


class CreateEventsLayerInputModel(_EventSettings):
    experiment: str
    table_dataset: str


@strawberry.input(description="Draw an event table -- a table with a TIME coordinate column -- as a mark per row, or an interval per row with `stopColumn`")
class CreateEventsLayerInput:
    experiment: strawberry.ID
    table_dataset: strawberry.ID = strawberry.field(description="The event table to draw. It needs a TIME coordinate column, and its space must reach the world")
    stop_column: str | None = strawberry.field(default=None, description="A column ending each row's interval, in the TIME column's unit. Omit to draw instants")
    label_column: str | None = strawberry.field(default=None, description="A column naming each row")
    lane_column: str | None = strawberry.field(default=None, description="A categorical column giving each distinct value its own lane")
    color: list[int] | None = strawberry.field(default=None, description="The base colour as RGBA, 0-255")
    colormap: enums.ColorMap | None = None
    color_bys: list[ColorByInput] | None = strawberry.field(default=None, description=_COLOR_BYS)
    filter_bys: list[FilterByInput] | None = strawberry.field(default=None, description=_FILTER_BYS)
    active_color_by: int | None = None
    active_filter_bys: list[int] | None = None
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = strawberry.field(default=None, description="The position top to bottom. Omit to append")

    def to_pydantic(self) -> CreateEventsLayerInputModel:
        return CreateEventsLayerInputModel(**{**_plain(self, CreateEventsLayerInputModel), **_pickers_of(self)})


def create_events_layer(info: Info, input: CreateEventsLayerInput) -> types.EventsLayer:
    """Draw an event table."""
    parsed = input.to_pydantic()
    experiment = get_for_org(models.Experiment, info, id=parsed.experiment)
    table = get_for_org(models.TableDataset, info, id=parsed.table_dataset)
    with transaction.atomic():
        experiment_logic.assert_kind(_KIND.EVENTS.value, table)
        return experiment_logic.create_layer(experiment, kind=_KIND.EVENTS.value, source=table, **_compositing(parsed), **_event_values(parsed, table, None))


class UpdateEventsLayerInputModel(_EventSettings):
    id: str
    table_dataset: str | None = None


@strawberry.input(description="Restyle an events layer, or point it at another table. Only the supplied fields change; a picker is replaced whole")
class UpdateEventsLayerInput:
    id: strawberry.ID
    table_dataset: strawberry.ID | None = None
    stop_column: str | None = None
    label_column: str | None = None
    lane_column: str | None = None
    color: list[int] | None = None
    colormap: enums.ColorMap | None = None
    color_bys: list[ColorByInput] | None = strawberry.field(default=None, description=_COLOR_BYS)
    filter_bys: list[FilterByInput] | None = strawberry.field(default=None, description=_FILTER_BYS)
    active_color_by: int | None = None
    active_filter_bys: list[int] | None = None
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = None

    def to_pydantic(self) -> UpdateEventsLayerInputModel:
        return UpdateEventsLayerInputModel(**{**_plain(self, UpdateEventsLayerInputModel), **_pickers_of(self)})


def update_events_layer(info: Info, input: UpdateEventsLayerInput) -> types.EventsLayer:
    """Restyle or rebind an events layer."""
    parsed = input.to_pydantic()
    layer = _get_layer(info, parsed.id, _KIND.EVENTS.value)
    table = layer.table_dataset
    values: dict = {}
    if parsed.table_dataset is not None:
        table = get_for_org(models.TableDataset, info, id=parsed.table_dataset)
        experiment_logic.assert_kind(_KIND.EVENTS.value, table)
        experiment_logic.assert_reaches(layer.experiment.world, table)
        values["table_dataset"] = table
    values.update(_compositing(parsed))
    values.update(_event_values(parsed, table, layer))
    return _apply(layer, values)


# --- annotation ---------------------------------------------------------------------------------


class CreateAnnotationLayerInputModel(_Compositing):
    experiment: str
    annotation_collection: str


@kante.pydantic_input(CreateAnnotationLayerInputModel, description="Draw an annotation collection's marks in an experiment. One layer per collection per experiment")
class CreateAnnotationLayerInput:
    experiment: strawberry.ID
    annotation_collection: strawberry.ID
    name: str | None = None
    blending: enums.Blending | None = None
    opacity: float | None = None
    visible: bool | None = None
    order: int | None = strawberry.field(default=None, description="The position top to bottom. Omit to append")


def create_annotation_layer(info: Info, input: CreateAnnotationLayerInput) -> types.AnnotationLayer:
    """Draw an annotation collection."""
    parsed = input.to_pydantic()
    experiment = get_for_org(models.Experiment, info, id=parsed.experiment)
    collection = get_for_org(models.AnnotationCollection, info, id=parsed.annotation_collection)
    with transaction.atomic():
        return experiment_logic.create_layer(experiment, kind=_KIND.ANNOTATION.value, source=collection, **_compositing(parsed))

