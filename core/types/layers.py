"""GraphQL types for the layers of an experiment: mikro's ``Layer`` interface, for time series.

One table (:class:`core.models.ExperimentLayer`) discriminated by ``kind``, one interface
(:class:`ExperimentLayer`) carrying what every kind shares -- compositing, and the placement
fields vendored from mikro's ``Layer`` -- and one concrete type per kind, resolved by
``is_type_of`` on the row's ``kind`` exactly as mikro's are:

* :class:`TraceLayer` -- a lens over an array dataset (a recording, a stimulus, any signal);
* :class:`SpikesLayer` -- a sparse dataset with a TIME axis, drawn as a raster;
* :class:`EventsLayer` -- a table dataset with a TIME column, drawn as marks or intervals;
* :class:`AnnotationLayer` -- an annotation collection's hand-drawn marks;
* :class:`HeatmapLayer` -- a lens drawn as an image, time across and one other axis down;
* :class:`SeriesLayer` -- a numeric table column drawn as a line over time;
* :class:`WaveformLayer` -- per-unit templates in peri-spike time;
* :class:`PointLayer` -- a table placed in space, a point per row.

A concrete type reachable only through the interface is not auto-discovered by strawberry, so
:data:`layer_types` is registered in the schema's ``types=``. Drop one and it vanishes from the
SDL without an error.
"""

from typing import TYPE_CHECKING, Annotated, List, Optional

import strawberry
from strawberry import auto

import kante
from kante.types import Info
from kanne_server import scalars as quantities

from core import enums, filters, models, order, scalars
from core.inputs.coords import CoordinateInput, at_map
from core.logic import clocks, ephys_pickers, scene_graph
from core.render import pickers as picker_models
from core.types._shared import build_prescoped_queryset
from core.types.annotation import AnnotationCollection
from core.types.array_dataset import DataArray, Lens
from core.types.coords import AffinePlacement, PlacementStep
from core.types.sparse_dataset import SparseDataset
from core.types.table_dataset import TableDataset

if TYPE_CHECKING:
    from core.types.experiment import Experiment


# --- the pickers --------------------------------------------------------------------------------


@kante.pydantic_type(picker_models.JoinStepModel, description="One reference hop of a picker's join path: the column, in the table it stands in, whose values identify rows of the next table")
class JoinStep:
    table: strawberry.ID
    column: str


@kante.pydantic_type(
    picker_models.ColorByModel,
    description="One entry of a spikes or events layer's colour picker: a column of a table the layer's rows (events) or units (spikes) reach, and how it becomes colour. mikro's COLUMN colour-by, field for field",
)
class ColorBy:
    kind: str
    table: strawberry.ID
    column: str
    join_path: List[JoinStep]
    colormap: enums.ColorMap | None
    min: float | None
    max: float | None
    label: str | None


@kante.pydantic_type(
    picker_models.FilterByModel,
    description="One entry of a spikes or events layer's filter picker: a column of a table the layer's rows reach, and which of its values to keep (or, with `exclude`, drop). mikro's COLUMN filter-by, field for field",
)
class FilterBy:
    kind: str
    table: strawberry.ID
    column: str
    join_path: List[JoinStep]
    min: float | None
    max: float | None
    values: List[str] | None
    exclude: bool
    label: str | None


def _color_bys(stored: list | None) -> List[ColorBy]:
    return [ColorBy.from_pydantic(picker_models.ColorByModel(**entry)) for entry in (stored or [])]


def _filter_bys(stored: list | None) -> List[FilterBy]:
    return [FilterBy.from_pydantic(picker_models.FilterByModel(**entry)) for entry in (stored or [])]


# --- the interface ------------------------------------------------------------------------------


@kante.django_interface(
    models.ExperimentLayer,
    description=(
        "One thing drawn in an experiment, alpha-blended over the layers below it. mikro's Layer, over time. It carries view state only: where its data sits on the timeline "
        "is a coordinate system and the edges out of it, and every placement question a layer answers -- `pathToWorld`, `placement`, `placementValidity`, `placementInvariance` "
        "-- is derived from the graph on read and stored nowhere, so correcting one sampling law moves every layer that looks through it. The concrete kind carries its own "
        "source and render settings: TraceLayer and HeatmapLayer (a lens over an array dataset, as lines or as an image), SpikesLayer (a spike raster), WaveformLayer (per-unit "
        "templates in peri-spike time), EventsLayer and SeriesLayer (a table with a TIME column, as marks or as a line), PointLayer (a table placed in space), AnnotationLayer (hand-drawn marks)"
    ),
)
class ExperimentLayer:
    """What every layer of an experiment shares. No time fields."""

    id: auto
    kind: enums.ExperimentLayerKind
    name: str | None
    experiment: Annotated["Experiment", strawberry.lazy("core.types.experiment")]
    blending: enums.Blending
    opacity: float
    visible: bool
    order: int

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):  # noqa: ANN001, ANN206 - strawberry_django's hook
        """Tenant-scope, and select the relations the placement logic reads in Python.

        The optimizer prefetches what the *selection set* names, and a client asking only for
        ``pathToWorld`` names none of these. The axes come as a ``prefetch_related`` because
        they are a reverse relation: ``asAffine`` reads the source system's axis order.
        """
        scoped = build_prescoped_queryset(info, queryset)
        return scoped.select_related(*scene_graph.LAYER_PLACEMENT_RELATIONS).prefetch_related(*scene_graph.LAYER_SOURCE_AXIS_PREFETCH)

    @kante.django_field(
        description=(
            "The path of transformation edges from this layer's source coordinate system to its experiment's world. A layer belongs to exactly one experiment, so this is the one "
            "'to world' question with a single right answer -- the path uses the data's own facts (a lens shift, a sampling law or time lookup) plus the world's registrations and "
            "the clocks chained into it. Null when the layer is unregistered or has no source system; empty when the source already is the world. Every step is here in full, with "
            "its own validity, invariance and provenance; `asAffine` is the same path composed"
        ),
    )
    def path_to_world(self, info: Info, at: List[CoordinateInput] | None = None) -> List[PlacementStep] | None:
        """The layer's placement path, as (edge, inverted) steps."""
        steps = scene_graph.for_request(info, self.experiment).placement_path(self, at=at_map(at))
        if steps is None:
            return None
        return [PlacementStep(transformation=edge, inverted=inverted) for edge, inverted in steps]

    @kante.django_field(
        description=(
            "This layer's whole `pathToWorld` composed into one affine map -- the same path, same edges, same order, with the flagged steps inverted. For a sampled recording or a "
            "spike raster it reads `t_world = sample * period + start`, the sampling law and every clock offset multiplied out. Derived on read and stored nowhere. **Null when "
            "`pathToWorld` is null.** It errors rather than returning null when a path exists but does not condense: a FIELD step (an irregularly sampled signal, a variable-step "
            "run) has no closed form, and the error names the transformation that stopped it. Pass `strict: true` to be refused a partial map instead of handed one"
        ),
    )
    def as_affine(self, info: Info, strict: bool = False, at: List[CoordinateInput] | None = None) -> AffinePlacement | None:
        """The layer's placement path composed into one labelled affine map."""
        condensed = scene_graph.for_request(info, self.experiment).condensed_placement(self, at=at_map(at))
        if condensed is None:
            return None
        if strict and not condensed.total:
            world = self.experiment.world
            world_axes = [axis.name for axis in world.axes.all()] if world else []
            missing = [axis for axis in world_axes if axis not in condensed.output_axes]
            raise ValueError(
                f"This layer's placement does not constrain every axis of its experiment's world: it maps onto {condensed.output_axes} and says nothing about {missing}. "
                "That is an honest partial registration, not a failure -- drop `strict` to read the map over the axes it does name, or author a registration that places the data along the rest."
            )
        return AffinePlacement(matrix=condensed.matrix, input_axes=condensed.input_axes, output_axes=condensed.output_axes, total=condensed.total)

    @kante.django_field(
        description=(
            "Whether this layer has a place on its experiment's timeline, and if not, why not. UNREGISTERED is a gap to close (nobody has related this data's clock to the world); "
            "UNMAPPABLE is a fact to badge; CONDITIONAL is a placement to ask again for with `at`. Derived, never stored"
        ),
    )
    def placement(self, info: Info, at: List[CoordinateInput] | None = None) -> enums.PlacementState:
        """PLACED, CONDITIONAL, UNREGISTERED or UNMAPPABLE."""
        return enums.PlacementState(scene_graph.for_request(info, self.experiment).placement_state(self, at=at_map(at)))

    @kante.django_field(
        description=(
            "How much this layer's placement is actually known: the weakest edge on its path to world. INFERRED when it rests on a sampling law read from metadata, MANUAL once "
            "someone authored an offset, VALIDATED once it was checked, UNKNOWN when there is no path at all. Derived, never stored"
        ),
    )
    def placement_validity(self, info: Info, at: List[CoordinateInput] | None = None) -> enums.PlacementValidity:
        """The weakest validity on the layer's placement path."""
        return enums.PlacementValidity(scene_graph.for_request(info, self.experiment).placement_validity(self, at=at_map(at)))

    @kante.django_field(
        description=(
            "Which geometric properties survive the whole walk from this layer's data to its experiment's world: the weakest edge on its path. AFFINE or stronger means a duration "
            "measured in samples is a duration on the timeline up to one factor; DIFFEOMORPHIC means the path crosses a time lookup; NONE means there is no path. Derived, never stored"
        ),
    )
    def placement_invariance(self, info: Info, at: List[CoordinateInput] | None = None) -> enums.TransformInvariance:
        """The weakest invariance class on the layer's placement path."""
        return enums.TransformInvariance(scene_graph.for_request(info, self.experiment).placement_invariance(self, at=at_map(at)))


# --- the kinds ----------------------------------------------------------------------------------


@kante.type(description="The placement of one pyramid level in a trace layer's experiment: the level, and its path to the world")
class LevelPlacement:
    data_array: DataArray = strawberry.field(description="The pyramid level being placed")
    path: List[PlacementStep] | None = strawberry.field(description="The path from this level's sample grid to the experiment's world, or null when the dataset is not placed in it")


def _lens_duration(lens: "models.Lens") -> int | None:
    """How much time a lens shows: its extent along the sample axis over the sampling law's rate. None over a lookup or on no clock."""
    grid = lens.dataset.coordinate_system
    timing = clocks.timing_clocks_of(grid)
    sample_axis = clocks.time_axis(grid) if grid is not None else None
    if not timing or sample_axis is None:
        return None
    rate, _ = clocks.sampling_of(grid, timing[0])
    if rate is None:
        return None
    samples = lens.get_size_of_axis(sample_axis.name)
    step = next((entry.step or 1 for entry in lens.slices_list if entry.axis == sample_axis.name), 1)
    # samples * step / rate, in picoseconds, with the rate in nanohertz.
    return int(round(samples * step * 1e21 / rate))


def _level_paths(layer, info: Info) -> List["LevelPlacement"]:  # noqa: ANN001 - a lens-backed layer row
    """One placement per pyramid level of a lens-backed layer's dataset: mikro's ``_level_placements``."""
    return [
        LevelPlacement(data_array=array, path=None if steps is None else [PlacementStep(transformation=edge, inverted=inverted) for edge, inverted in steps])
        for array, steps in scene_graph.for_request(info, layer.experiment).level_placements(layer)
    ]


@kante.django_type(
    models.ExperimentLayer,
    filters=filters.ExperimentLayerFilter,
    ordering=order.ExperimentLayerOrder,
    pagination=True,
    description=(
        "A trace: a lens over an array dataset, drawn as a line per channel -- a recording, a stimulus, an analog or irregularly sampled signal alike. What it shows is the lens' "
        "selection (a window, a channel range); where it sits is the path from the lens' space to the world. What was recorded where is the dataset's own `recordingSite` spokes"
    ),
)
class TraceLayer(ExperimentLayer):
    """A trace layer: a lens over an array dataset."""

    id: auto
    lens: Lens = kante.django_field(description="The selection this layer draws: a lens over the dataset. Unsliced when the layer shows everything")
    channel_index: int | None = kante.django_field(description="The one channel of the lens' CHANNEL axis to draw; null draws every channel, stacked")
    clim_min: float | None = kante.django_field(description="The bottom of the value range, in the dataset's value unit. Null reads it from the value histogram")
    clim_max: float | None = kante.django_field(description="The top of the value range, in the dataset's value unit. Null reads it from the value histogram")
    line_width: float | None = kante.django_field(description="The line width, in screen pixels")

    @kante.django_field(description="The base colour as RGBA, 0-255. Null lets the viewer choose")
    def color(self, info: Info) -> scalars.RGBAColor | None:
        return self.color

    @kante.django_field(
        description="How much time this layer shows: its lens' extent along the sample axis over the sampling law's rate. Null when the dataset is timed by a lookup (a sample count is not a duration there) or on no clock at all"
    )
    def duration(self, info: Info) -> quantities.Duration | None:
        """The shown extent along time: samples over rate."""
        return _lens_duration(self.lens)

    @kante.django_field(
        description="Per pyramid level, the path from that level's sample grid to this experiment's world. What a client zoomed out over an hour of data reads: pick a level by zoom and use its path"
    )
    def level_paths(self, info: Info) -> List[LevelPlacement]:
        """One placement per pyramid level of the lens' dataset."""
        return _level_paths(self, info)

    @classmethod
    def is_type_of(cls, obj, info) -> bool:  # noqa: ANN001 - strawberry's hook
        return getattr(obj, "kind", None) == enums.ExperimentLayerKind.TRACE.value


@kante.django_type(
    models.ExperimentLayer,
    filters=filters.ExperimentLayerFilter,
    ordering=order.ExperimentLayerOrder,
    pagination=True,
    description=(
        "Spikes: a sparse dataset with a TIME axis -- a raster of units by samples, one nonzero per spike -- drawn as a tick per spike and a row per unit, or as a firing-rate "
        "histogram when `rateBin` is set. The raster is placed by its sampling law, exactly as the recording it was sorted from; a unit's colour and row order come from the "
        "table identifying the raster's unit axis (`unitTable`)"
    ),
)
class SpikesLayer(ExperimentLayer):
    """A spikes layer: a spike raster."""

    id: auto
    sparse_dataset: SparseDataset = kante.django_field(description="The spike raster this layer draws: a sparse dataset over (unit, t)")
    tick_height: float | None = kante.django_field(description="A spike tick's height as a fraction of its unit's row, 0 to 1")
    row_order_column: str | None = kante.django_field(description="A column of `unitTable` the rows are ordered by (depth, channel); null keeps unit index order")
    value_mode: enums.SpikeValueMode = kante.django_field(description="What a nonzero value means: one spike (PRESENCE), or its amplitude (AMPLITUDE, drawn through `colormap`)")
    rate_bin: quantities.Duration | None = kante.django_field(description="Draw a firing-rate histogram at this bin width instead of a raster. Null draws the raster")
    colormap: enums.ColorMap | None = kante.django_field(description="The colormap an amplitude or the active colour-by is drawn through")
    clim_min: float | None = kante.django_field(description="(AMPLITUDE) The amplitude at the bottom of the colormap")
    clim_max: float | None = kante.django_field(description="(AMPLITUDE) The amplitude at the top of the colormap")
    active_color_by: int | None = kante.django_field(description="Which entry of `colorBys` is drawn, as an index into it. Null draws every unit in `color`")
    active_filter_bys: List[int] = kante.django_field(description="Which entries of `filterBys` apply, as indices into it. They combine with AND: a unit is drawn when every active rule keeps it")

    @kante.django_field(description="The base colour as RGBA, 0-255. Null lets the viewer choose")
    def color(self, info: Info) -> scalars.RGBAColor | None:
        return self.color

    @kante.django_field(description="The table the raster's units are rows of: the one identifying its INDEX axis. Where every colour-by and filter-by starts. Null when no table identifies the units")
    def unit_table(self, info: Info) -> Optional[TableDataset]:
        return ephys_pickers.spike_root(self.sparse_dataset)

    @kante.django_field(field_name="spike_color_bys", description="The colourings this layer offers, in the order a picker should show them: columns of `unitTable` or of tables it references")
    def color_bys(self, info: Info) -> List[ColorBy]:
        return _color_bys(self.spike_color_bys)

    @kante.django_field(field_name="spike_filter_bys", description="The filters this layer offers: columns of `unitTable` or of tables it references, each keeping a range or a set of values")
    def filter_bys(self, info: Info) -> List[FilterBy]:
        return _filter_bys(self.spike_filter_bys)

    @classmethod
    def is_type_of(cls, obj, info) -> bool:  # noqa: ANN001 - strawberry's hook
        return getattr(obj, "kind", None) == enums.ExperimentLayerKind.SPIKES.value


@kante.django_type(
    models.ExperimentLayer,
    filters=filters.ExperimentLayerFilter,
    ordering=order.ExperimentLayerOrder,
    pagination=True,
    description=(
        "Events: a table dataset with a TIME coordinate column -- TTL edges, trials, stimulus onsets, Neo events and epochs -- drawn as a mark per row, or as an interval per row "
        "when `stopColumn` is set. The time column is the table's own declaration (`timeColumn`), never a per-layer copy; where the table sits on the timeline is the edge out of "
        "its space. Bulk and imported events; hand-drawn marks are an AnnotationLayer"
    ),
)
class EventsLayer(ExperimentLayer):
    """An events layer: an event table."""

    id: auto
    table_dataset: TableDataset = kante.django_field(description="The event table this layer draws")
    stop_column: str | None = kante.django_field(description="A column whose values end each row's interval, in the time column's unit. Null draws instants")
    label_column: str | None = kante.django_field(description="A column naming each row, drawn beside its mark")
    lane_column: str | None = kante.django_field(description="A categorical column giving each distinct value its own lane. Null draws one lane")
    colormap: enums.ColorMap | None = kante.django_field(description="The colormap the active colour-by is drawn through")
    active_color_by: int | None = kante.django_field(description="Which entry of `colorBys` is drawn, as an index into it. Null draws every row in `color`")
    active_filter_bys: List[int] = kante.django_field(description="Which entries of `filterBys` apply, as indices into it. They combine with AND")

    @kante.django_field(description="The base colour as RGBA, 0-255. Null lets the viewer choose")
    def color(self, info: Info) -> scalars.RGBAColor | None:
        return self.color

    @kante.django_field(description="The table's TIME coordinate column: where each row sits in the table's own space. Derived from the table's declaration, never stored per layer")
    def time_column(self, info: Info) -> str | None:
        column = self.table_dataset.columns.filter(role=enums.ColumnRoleChoices.COORDINATE.value, axis_type=enums.AxisTypeChoices.TIME.value).order_by("order").first()
        return column.name if column is not None else None

    @kante.django_field(field_name="table_color_bys", description="The colourings this layer offers: columns of the event table or of tables it references")
    def color_bys(self, info: Info) -> List[ColorBy]:
        return _color_bys(self.table_color_bys)

    @kante.django_field(field_name="table_filter_bys", description="The filters this layer offers: columns of the event table or of tables it references")
    def filter_bys(self, info: Info) -> List[FilterBy]:
        return _filter_bys(self.table_filter_bys)

    @classmethod
    def is_type_of(cls, obj, info) -> bool:  # noqa: ANN001 - strawberry's hook
        return getattr(obj, "kind", None) == enums.ExperimentLayerKind.EVENTS.value


@kante.django_type(
    models.ExperimentLayer,
    filters=filters.ExperimentLayerFilter,
    ordering=order.ExperimentLayerOrder,
    pagination=True,
    description="Hand-drawn marks: an annotation collection, drawn in the space it owns. One per collection per experiment -- per-shape styling lives on the annotations themselves",
)
class AnnotationLayer(ExperimentLayer):
    """An annotation layer: a collection's marks."""

    id: auto
    annotation_collection: AnnotationCollection = kante.django_field(description="The annotation collection whose marks this layer draws. Its own coordinate system is the layer's space")

    @classmethod
    def is_type_of(cls, obj, info) -> bool:  # noqa: ANN001 - strawberry's hook
        return getattr(obj, "kind", None) == enums.ExperimentLayerKind.ANNOTATION.value


@kante.django_type(
    models.ExperimentLayer,
    filters=filters.ExperimentLayerFilter,
    ordering=order.ExperimentLayerOrder,
    pagination=True,
    description=(
        "A heatmap: a lens over an array dataset drawn as an image, time across and one other axis down -- a spectrogram (t, f), a depth or current-source-density plot (t, c). "
        "mikro's intensity layer, over time: a continuous colormap between `climMin` and `climMax`, through `gamma`"
    ),
)
class HeatmapLayer(ExperimentLayer):
    """A heatmap layer: a lens drawn as an image."""

    id: auto
    lens: Lens = kante.django_field(description="The selection this layer draws. Every axis but TIME and `rowAxis` is fixed to one position")
    colormap: enums.ColorMap | None = kante.django_field(description="The continuous colormap the values are drawn through")
    clim_min: float | None = kante.django_field(description="The value at the bottom of the colormap, in the dataset's value unit")
    clim_max: float | None = kante.django_field(description="The value at the top of the colormap, in the dataset's value unit")
    gamma: float | None = kante.django_field(description="The gamma the colour range is drawn through; null is linear")

    row_axis: str | None = kante.django_field(
        description="The axis drawn down the image: the stated one, or the dataset's FREQUENCY axis, else CHANNEL, else INDEX -- resolved and checked when the layer was written"
    )

    @kante.django_field(description="How much time this layer shows: its lens' extent along the sample axis over the sampling law's rate. Null over a lookup")
    def duration(self, info: Info) -> quantities.Duration | None:
        return _lens_duration(self.lens)

    @kante.django_field(description="Per pyramid level, the path from that level's sample grid to this experiment's world: what a client zoomed out over an hour of data reads")
    def level_paths(self, info: Info) -> List[LevelPlacement]:
        return _level_paths(self, info)

    @classmethod
    def is_type_of(cls, obj, info) -> bool:  # noqa: ANN001 - strawberry's hook
        return getattr(obj, "kind", None) == enums.ExperimentLayerKind.HEATMAP.value


@kante.django_type(
    models.ExperimentLayer,
    filters=filters.ExperimentLayerFilter,
    ordering=order.ExperimentLayerOrder,
    pagination=True,
    description=(
        "A series: one numeric column of a table with a TIME column, drawn as a line over time -- running speed, pupil size, a temperature: a signal that arrives as rows "
        "rather than as an array. Placed by the table's own space, exactly as an events layer is"
    ),
)
class SeriesLayer(ExperimentLayer):
    """A series layer: a numeric table column over time."""

    id: auto
    table_dataset: TableDataset = kante.django_field(description="The table this layer draws")
    value_column: str | None = kante.django_field(description="The numeric column drawn as the value")
    interpolation: enums.SeriesInterpolation = kante.django_field(description="How consecutive rows are joined")
    lane_column: str | None = kante.django_field(description="A categorical column giving each distinct value its own line; null draws one")
    line_width: float | None = kante.django_field(description="The line width, in screen pixels")
    clim_min: float | None = kante.django_field(description="The bottom of the value range, in the column's unit")
    clim_max: float | None = kante.django_field(description="The top of the value range, in the column's unit")
    colormap: enums.ColorMap | None = kante.django_field(description="The colormap the active colour-by is drawn through")
    active_color_by: int | None = kante.django_field(description="Which entry of `colorBys` is drawn, as an index into it")
    active_filter_bys: List[int] = kante.django_field(description="Which entries of `filterBys` apply, as indices into it")

    @kante.django_field(description="The base colour as RGBA, 0-255. Null lets the viewer choose")
    def color(self, info: Info) -> scalars.RGBAColor | None:
        return self.color

    @kante.django_field(description="The table's TIME coordinate column: where each row sits in the table's own space. Derived from the table's declaration, never stored per layer")
    def time_column(self, info: Info) -> str | None:
        column = self.table_dataset.columns.filter(role=enums.ColumnRoleChoices.COORDINATE.value, axis_type=enums.AxisTypeChoices.TIME.value).order_by("order").first()
        return column.name if column is not None else None

    @kante.django_field(field_name="table_color_bys", description="The colourings this layer offers: columns of the table or of tables it references")
    def color_bys(self, info: Info) -> List[ColorBy]:
        return _color_bys(self.table_color_bys)

    @kante.django_field(field_name="table_filter_bys", description="The filters this layer offers: columns of the table or of tables it references")
    def filter_bys(self, info: Info) -> List[FilterBy]:
        return _filter_bys(self.table_filter_bys)

    @classmethod
    def is_type_of(cls, obj, info) -> bool:  # noqa: ANN001 - strawberry's hook
        return getattr(obj, "kind", None) == enums.ExperimentLayerKind.SERIES.value


@kante.django_type(
    models.ExperimentLayer,
    filters=filters.ExperimentLayerFilter,
    ordering=order.ExperimentLayerOrder,
    pagination=True,
    description=(
        "Waveforms: per-unit templates -- an array dataset (unit, [c,] w) derived from a spike raster -- drawn per unit in peri-spike time. `w` is timed by a sampling law "
        "onto a clock whose zero is the spike, so this layer lives in an experiment over that clock. Colour and order come from the raster's units table"
    ),
)
class WaveformLayer(ExperimentLayer):
    """A waveform layer: per-unit templates in peri-spike time."""

    id: auto
    lens: Lens = kante.django_field(description="The selection of templates this layer draws")
    channel_index: int | None = kante.django_field(description="The one channel drawn; null draws every channel")
    line_width: float | None = kante.django_field(description="The line width, in screen pixels")
    clim_min: float | None = kante.django_field(description="The bottom of the value range, in the templates' value unit")
    clim_max: float | None = kante.django_field(description="The top of the value range, in the templates' value unit")
    colormap: enums.ColorMap | None = kante.django_field(description="The colormap the active colour-by is drawn through")
    active_color_by: int | None = kante.django_field(description="Which entry of `colorBys` is drawn, as an index into it")
    active_filter_bys: List[int] = kante.django_field(description="Which entries of `filterBys` apply, as indices into it")

    @kante.django_field(description="The base colour as RGBA, 0-255. Null lets the viewer choose")
    def color(self, info: Info) -> scalars.RGBAColor | None:
        return self.color

    unit_axis: str | None = kante.django_field(description="The axis enumerating the units: the stated one, or the templates' one INDEX axis -- resolved when the layer was written")

    @kante.django_field(description="The units table the templates' raster names: where colour-bys and filter-bys start. Null when the templates were derived from no raster")
    def unit_table(self, info: Info) -> Optional[TableDataset]:
        return ephys_pickers.waveform_root(self.lens.dataset)

    @kante.django_field(description="How much peri-spike time a template spans: its extent along `w` over the sampling law's rate")
    def duration(self, info: Info) -> quantities.Duration | None:
        return _lens_duration(self.lens)

    @kante.django_field(field_name="spike_color_bys", description="The colourings this layer offers: columns of the units table or of tables it references")
    def color_bys(self, info: Info) -> List[ColorBy]:
        return _color_bys(self.spike_color_bys)

    @kante.django_field(field_name="spike_filter_bys", description="The filters this layer offers: columns of the units table or of tables it references")
    def filter_bys(self, info: Info) -> List[FilterBy]:
        return _filter_bys(self.spike_filter_bys)

    @classmethod
    def is_type_of(cls, obj, info) -> bool:  # noqa: ANN001 - strawberry's hook
        return getattr(obj, "kind", None) == enums.ExperimentLayerKind.WAVEFORM.value


def _coordinate_column_named(table: "models.TableDataset", axis_name: str) -> str | None:
    """The SPACE coordinate column a point layer reads as ``axis_name``. mikro's ``_coordinate_column_named``.

    By name first (case-insensitive), then by position among the SPACE columns -- the last is x,
    the one before y, the one before that z -- and only when there are at least two. Name the
    columns `x` and `y` and the fallback, which can transpose, is never reached.
    """
    spatial = [column for column in table.columns.filter(role=enums.ColumnRoleChoices.COORDINATE.value, axis_type=enums.AxisTypeChoices.SPACE.value).order_by("order")]
    for column in spatial:
        if column.name.lower() == axis_name:
            return column.name
    if len(spatial) < 2:
        return None
    position = {"x": -1, "y": -2, "z": -3}[axis_name]
    return spatial[position].name if len(spatial) >= -position else None


@kante.django_type(
    models.ExperimentLayer,
    filters=filters.ExperimentLayerFilter,
    ordering=order.ExperimentLayerOrder,
    pagination=True,
    description=(
        "Points: a table placed in space drawn as a point per row -- a probe's channel map, units at their positions. The table's SPACE coordinate columns place the rows "
        "(`xColumn`, `yColumn`, `zColumn`, derived from its declaration), so this layer lives in an experiment over a space. mikro's point layer"
    ),
)
class PointLayer(ExperimentLayer):
    """A point layer: a table placed in space."""

    id: auto
    table_dataset: TableDataset = kante.django_field(description="The table this layer draws")
    point_size: float | None = kante.django_field(description="A point's size, in screen pixels")
    size_column: str | None = kante.django_field(description="A numeric column scaling each point's size")
    label_column: str | None = kante.django_field(description="A column naming each point")
    colormap: enums.ColorMap | None = kante.django_field(description="The colormap the active colour-by is drawn through")
    active_color_by: int | None = kante.django_field(description="Which entry of `colorBys` is drawn, as an index into it")
    active_filter_bys: List[int] = kante.django_field(description="Which entries of `filterBys` apply, as indices into it")

    @kante.django_field(description="The base colour as RGBA, 0-255. Null lets the viewer choose")
    def color(self, info: Info) -> scalars.RGBAColor | None:
        return self.color

    @kante.django_field(description="The SPACE coordinate column read as x: the one named `x`, else the last SPACE column")
    def x_column(self, info: Info) -> str | None:
        return _coordinate_column_named(self.table_dataset, "x")

    @kante.django_field(description="The SPACE coordinate column read as y: the one named `y`, else the one before the last")
    def y_column(self, info: Info) -> str | None:
        return _coordinate_column_named(self.table_dataset, "y")

    @kante.django_field(description="The SPACE coordinate column read as z, if the table has three")
    def z_column(self, info: Info) -> str | None:
        return _coordinate_column_named(self.table_dataset, "z")

    @kante.django_field(field_name="table_color_bys", description="The colourings this layer offers: columns of the table or of tables it references")
    def color_bys(self, info: Info) -> List[ColorBy]:
        return _color_bys(self.table_color_bys)

    @kante.django_field(field_name="table_filter_bys", description="The filters this layer offers: columns of the table or of tables it references")
    def filter_bys(self, info: Info) -> List[FilterBy]:
        return _filter_bys(self.table_filter_bys)

    @classmethod
    def is_type_of(cls, obj, info) -> bool:  # noqa: ANN001 - strawberry's hook
        return getattr(obj, "kind", None) == enums.ExperimentLayerKind.POINT.value


#: The concrete layer types, for the schema's ``types=``. See the module docstring.
layer_types: list[type] = [TraceLayer, SpikesLayer, EventsLayer, AnnotationLayer, HeatmapLayer, SeriesLayer, WaveformLayer, PointLayer]
