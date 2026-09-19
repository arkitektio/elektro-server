"""GraphQL types for the data layer: array datasets, their levels, their anchors, and lenses.

**Vendored from mikro** (``mikro/core/types/array_dataset.py``), at the same path, which is
where ``core.types.coords`` expects to find what lives in a space. mikro keeps its scenes and
layers in this module too; the interpretation layer here (experiments and their
layers) lives in ``core/types/__init__.py``, ``core/types/experiment.py`` and
``core/types/layers.py`` instead. What a dataset
gains over mikro's is ``valueUnit`` / ``valueDimension`` and the reverse accessors to what
interprets it; what it loses is ``scenes``, ``defaultScene`` and ``latestSnapshot``. The
spokes are this service's (:mod:`rigkit` where mikro has ``optikit``). Every type mixes in
``OrgScoped``.
"""

import datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

import strawberry
from strawberry import auto

import kante
from kante.types import Info
from kanne_server import scalars as kanne_scalars
from rigkit.models import RigStateModel
from rigkit.types import RigStateGraph

from core import enums, filters, models, order, scalars, scoping
from core.base_models import slices as base_models
from core.logic import file_link as file_link_logic
from core.logic import graph as graph_logic
from core.types._shared import OrgScoped, apply_link_filters
from core.types.auth import ProvenanceEntry, Task, User
from core.types.coords import CoordinateSystem, Resident, Transformation
from datalayer.types import ZarrStore

if TYPE_CHECKING:
    # Only for the lazy annotations below: each of these modules imports this one back.
    from core.types import NeuronModel
    from core.types.layers import ExperimentLayer
    from core.types.annotation import AnnotationCollection
    from core.types.file_link import FileLink
    from core.types.folder import Folder


@kante.django_type(
    models.ArrayDataset,
    filters=filters.ArrayDatasetFilter,
    ordering=order.ArrayDatasetOrder,
    pagination=True,
    description="A multi-dimensional array dataset: a recording, a stimulus, a vector of sample times, a unit's waveform templates. Its dimensions and their types live on the axes of its INTRINSIC (sample grid) coordinate system; physical units live on the clocks it has edges into; its pyramid levels are DataArrays, each mapping into its grid. What it *means* -- a trace in an experiment -- is said by whatever names it, never here; where it was recorded is a `recordingSite` on its anchors",
)
class ArrayDataset(OrgScoped):
    """A multi-dimensional array dataset with named dimensions, described by its intrinsic pixel-grid coordinate system."""

    folder: Optional[Annotated["Folder", strawberry.lazy("core.types.folder")]] = kante.django_field(
        description="The folder this dataset is filed in. Organisational only: it says where a user keeps this dataset, never where the data sits in space -- that is `intrinsicSystem` and the edges out of it"
    )

    @kante.django_field(
        description=(
            "The files this dataset was converted from -- the ABF or NWB file a converter read to write these arrays, named per series. **Read this alongside `derivedFrom`, not instead of "
            "it**: `derivedFrom` says which *data* this was computed from and relates two coordinate systems, while this says which *bytes* it was read out of and relates to no "
            "space at all, because a file has none. Both can be non-empty and complete"
        ),
        prefetch_related=["file_links__file"],
    )
    def source_files(self, info: Info, filters: filters.FileLinkFilter | None = strawberry.UNSET) -> List[Annotated["FileLink", strawberry.lazy("core.types.file_link")]]:
        """The links naming a file this dataset was produced from."""
        return apply_link_filters(file_link_logic.links_for(self, enums.FileLinkDirectionChoices.SOURCE), filters, info)

    @kante.django_field(
        description="The files written out of this dataset: an NWB export, a CSV of samples. The mirror of `sourceFiles`",
        prefetch_related=["file_links__file"],
    )
    def exports(self, info: Info, filters: filters.FileLinkFilter | None = strawberry.UNSET) -> List[Annotated["FileLink", strawberry.lazy("core.types.file_link")]]:
        """The links naming a file written out of this dataset."""
        return apply_link_filters(file_link_logic.links_for(self, enums.FileLinkDirectionChoices.RENDITION), filters, info)

    id: auto
    name: auto
    description: str | None
    # `name` and `description` are the only two fields `updateArrayDataset` can reach, which is
    # exactly why the audit trail is worth reading: a rename is the one thing about a dataset
    # that can change, so who changed it is the one history there is to keep.
    provenance_entries: List["ProvenanceEntry"] = kante.django_field(
        description="Every change made to this dataset: who created it, and every subsequent rename or redescription, attributed to the client, user and task it happened under. Only `name` and `description` can change -- the arrays, the axes and the coordinate systems built from them are fixed at creation"
    )
    creator: User | None = kante.django_field(description="Who created this dataset")
    created_at: datetime.datetime
    created_through: Task | None = kante.django_field(description="The task this dataset was created through, if any")
    created_through_by: User | None = kante.django_field(description="The assigner of the creating task, if any")
    data_arrays: List["DataArray"] = kante.django_field(description="The multiscale data arrays belonging to this dataset")
    lenses: List["Lens"] = kante.django_field(description="The lenses over this dataset: its sweeps, epoch windows and channel selections")
    anchors: List["CoordinateAnchor"] = kante.django_field(description="The coordinate anchors of this dataset, each pinning metadata spokes -- a value unit, a channel label, the rig state -- to some of its coordinates")

    @kante.django_field(description="The dataset's INTRINSIC coordinate system: its level-0 sample grid, the space every pyramid level and lens maps into, and the one a sampling law or a time lookup leaves from. Structural and unit-independent")
    def intrinsic_system(self, info: Info) -> CoordinateSystem | None:
        """The dataset's INTRINSIC coordinate system."""
        return self.intrinsic_coordinate_system

    @kante.django_field(
        description="The edges from this dataset's pixel grid back into the lenses it was computed from, when it is a derived dataset: one for a deconvolution or a resample, several for a fusion of channels or tiles. Empty for a dataset that was acquired rather than derived. The order is the priority its creator declared: the first edge is the primary parent, the one that places the dataset. They are edges, not labels: each carries the map itself, so a client can compose it -- and they are why a derived dataset inherits its sources' placements instead of needing its own registration"
    )
    def derived_from(self, info: Info) -> List[Transformation]:
        """The stored derivation edges, primary parent first, if this dataset was computed from others."""
        return graph_logic.derivation_edges(self)

    @kante.django_field(
        description="The datasets computed from this one -- the other end of `derivedFrom`, and the way to ask what a source produced: the deconvolutions, segmentations and projections that named a space of this dataset as their parent. Derived from the same edges, never a stored back-reference that could disagree with them. Every child, not just those this dataset places: a fusion that named this source second is listed here, and so is a child whose derivation is UNMAPPABLE -- it came from here even though its geometry did not survive. The maps themselves are on each child's own `derivedFrom`"
    )
    def derived_datasets(self, info: Info) -> List["ArrayDataset"]:
        """The datasets whose derivation edges land in one of this dataset's spaces."""
        return graph_logic.derived_datasets(self)

    @kante.django_field(
        description=(
            "Everything computed from this dataset, whatever kind of container it is: the derived datasets `derivedDatasets` lists, and also the annotation "
            "collections that named this dataset as their source. A separate field rather than a widening of that one, which stays honestly about "
            "*datasets*. Same edges, same kind-blindness: an UNMAPPABLE child came from here even though its geometry did not survive"
        )
    )
    def derived_residents(self, info: Info) -> List[Resident]:
        """Every container whose derivation edges land in one of this dataset's spaces."""
        return graph_logic.derived_containers(self)

    @kante.django_field(description="Whether this dataset carries a resolution pyramid. Derived: true when it has more than one level")
    def multiscale(self, info: Info) -> bool:
        """Whether the dataset has more than one pyramid level."""
        return self.multiscale

    @kante.django_field(description="The dataset's axis names, in array order. Derived from the axes of its intrinsic coordinate system")
    def axis_names(self, info: Info) -> List[str]:
        """The dataset's axis names."""
        return self.axis_names

    @kante.django_field(
        prefetch_related=["data_arrays"],
        description=(
            "Whether every downsampled level of this pyramid was built by a method that only ever returns a value already present in the input -- NEAREST or MODE. Only meaningful "
            "when the values are object ids, and only *reportable* rather than enforceable: `createArrayDataset` refuses a non-compliant pyramid on a dataset already declared "
            "CATEGORIZED or carrying an INDEX axis, but a mask can be declared a mask afterwards, by the `keyedBy` FIELD edge authored when its object table is created -- and by then the levels exist. "
            "False means the levels above 0 hold ids that were interpolated into existence and belong to no object; treat level 0 as the only trustworthy one. Null when no level "
            "says how it was made, which is not the same as compliant. True for an unpyramided dataset: there is nothing that could be wrong"
        ),
    )
    def pyramid_is_label_compliant(self, info: Info) -> bool | None:
        """Whether every downsampled level was built by picking rather than averaging."""
        methods = [array.scale_method for array in self.data_arrays.all() if array.level != 0]
        if not methods:
            return True
        if all(method is None for method in methods):
            return None
        return all(method in enums.LABEL_COMPLIANT_SCALE_METHODS for method in methods)

    @kante.django_field(
        description="What this dataset structurally is, materialized from the axes of its intrinsic coordinate system at creation: the one spatial spec its SPACE axis count denotes, then a modifier per acquisition axis present. A (t, c) recording is [SCALAR, TIMESERIES, MULTICHANNEL]. Presence, not size: a one-channel CHANNEL axis still counts. Empty while the intrinsic system does not exist yet"
    )
    def spec(self, info: Info) -> List[enums.ArrayDatasetSpec]:
        """Every spec the dataset's axes satisfy."""
        return self.spec

    @kante.django_field(description="The dataset's shape: that of its level-0 array")
    def shape(self, info: Info) -> List[int]:
        """The dataset's shape."""
        return self.shape_list

    @kante.django_field(
        description=(
            "The unit of this dataset's VALUES -- what was measured at each sample ('mV', 'pA', 'second' for a times dataset). Read from the dataset-wide `ValueUnit` anchor, the one "
            "pinned to no coordinate; a per-channel unit is on that channel's anchor and is not an answer here. Not an axis unit: an axis says where a sample is. Null when unstated"
        )
    )
    def value_unit(self, info: Info) -> kanne_scalars.Unit | None:
        """The dataset-wide value unit."""
        return self.value_unit

    @kante.django_field(description="The physical dimension of this dataset's values, derived from `valueUnit` ('[time]' for a times dataset, a voltage or a current for a recording). Null when the unit is unstated or arbitrary")
    def value_dimension(self, info: Info) -> kanne_scalars.Dimension | None:
        """The dimensionality of the value unit."""
        unit = self.value_unit
        if not unit or kanne_scalars.is_arbitrary_unit(unit):
            return None
        return kanne_scalars.parse_dimension(unit)

    @kante.django_field(
        description=(
            "The annotation collections drawn over this dataset, or over a lens of it: the marks made on this dataset in particular. Derived from the graph -- a collection keeps no "
            "dataset column, the edge from its drawing space into this dataset's sample grid is the only place that fact lives. Marks made on the *clock* this dataset is sampled onto "
            "apply to it too, and are asked of the clock: `intrinsicSystem { annotations }`"
        )
    )
    def annotation_collections(self, info: Info) -> List[Annotated["AnnotationCollection", strawberry.lazy("core.types.annotation")]]:
        """The collections whose derivation edge lands in this dataset's spaces."""
        return list(scoping.for_org(models.AnnotationCollection, info).filter(coordinate_system__in=filters._systems_drawn_over_dataset(self.pk)))

    # What interprets this dataset. Elektro's counterpart of mikro's `ArrayDataset.scenes`: a
    # dataset says nothing about what it means, so this is the way to ask who does.
    @kante.django_field(description="The experiment layers drawing this dataset, through any of its lenses")
    def experiment_layers(self, info: Info) -> List[Annotated["ExperimentLayer", strawberry.lazy("core.types.layers")]]:
        """The layers whose lens selects over this dataset."""
        return list(scoping.for_org(models.ExperimentLayer, info).filter(lens__dataset_id=self.pk).order_by("experiment_id", "order", "pk"))

    @kante.django_field(
        description="What computed this dataset, if it was simulated: the `simulation` spoke of its whole-dataset anchor -- the model that was integrated, its dt and duration. Null for a recording, and for a run's input"
    )
    def simulation(self, info: Info) -> Optional["SimulationState"]:
        """The simulation state anchored at ``{}``."""
        return models.SimulationState.objects.filter(anchor__dataset_id=self.pk, anchor__coordinates={}).select_related("model").first()


@kante.django_type(
    models.DataArray,
    filters=filters.DataArrayFilter,
    ordering=order.DataArrayOrder,
    pagination=True,
    description="One level of a dataset's resolution pyramid: a zarr-backed array, with its own sample-index coordinate system and a stored edge into the dataset's intrinsic space. Level 0 is the recording; higher levels are decimations a client reads when zoomed out over hours of data",
)
class DataArray(OrgScoped):
    """One level of a dataset's resolution pyramid, with the edge that places it in the dataset's intrinsic space."""

    id: auto
    store: ZarrStore
    shape: list[int]
    chunk_shape: list[int]
    level: int
    dataset: ArrayDataset
    scale_method: enums.ScaleMethod | None = strawberry.field(
        description="How this level's voxels were computed from the level above it. Null for level 0, which was downsampled from nothing, and null for a level whose writer did not say. Over a dataset whose values are object ids only NEAREST and MODE are honest -- see `ArrayDataset.pyramidIsLabelCompliant`"
    )

    @kante.django_field(
        select_related=["coordinate_system", "dataset__coordinate_system"],
        description="The coordinate system this level's voxels live in. Level 0 owns none: the dataset's INTRINSIC system IS the level-0 pixel grid, so this resolves to it. Higher levels own an ARRAY (voxel index) system",
    )
    def coordinate_system(self, info: Info) -> CoordinateSystem | None:
        """The system this level's voxels live in: its own ARRAY system, or intrinsic for level 0."""
        return self.space

    @kante.django_field(
        description="The edge from this level's voxel space into the dataset's intrinsic space. Its scale is absolute -- derived from the actual shapes, not from a nominal 2**level -- so a pyramid whose axes do not halve cleanly is described correctly. Null for level 0: its space IS the intrinsic space, and there is nothing to map",
    )
    def to_parent(self, info: Info) -> Transformation | None:
        """The stored level-to-intrinsic edge."""
        return self.to_parent


@kante.django_type(
    models.RigState,
    filters=filters.RigStateFilter,
    pagination=True,
    description="The hardware truth: the recorded rig state pinned to a coordinate anchor",
)
class RigState(OrgScoped):
    """The hardware truth: the recorded rig state pinned to a coordinate anchor"""

    id: auto

    @kante.django_field(description="The recorded rig state, reconstructed into its typed form: clamp mode, holding level, access and membrane measurements as quantities, everything else as per-device named settings")
    def state(self, info: Info) -> RigStateGraph:
        """The recorded rig state."""
        return RigStateModel(**self.state)


@kante.django_type(
    models.ValueHistogram,
    filters=filters.ValueHistogramFilter,
    pagination=True,
    description="The distribution of values pinned to a coordinate anchor, including histogram bins, min/max and percentile limits",
)
class ValueHistogram(OrgScoped):
    """The distribution of values pinned to a coordinate anchor, including histogram bins, min/max and percentile limits"""

    id: auto
    p1: float | None
    p99: float | None
    histogram: list[float]
    bins: list[float]
    min: float | None
    max: float | None


@kante.django_type(
    models.ChannelLabel,
    filters=filters.ChannelLabelFilter,
    pagination=True,
    description="The channel truth: a human-readable label for a channel, pinned to a coordinate anchor",
)
class ChannelLabel(OrgScoped):
    """The channel truth: a human-readable label for a channel, pinned to a coordinate anchor"""

    id: auto
    label: str


@kante.django_type(
    models.ValueUnit,
    filters=filters.ValueUnitFilter,
    pagination=True,
    description="The value truth: the unit of the array's values at the anchored coordinates. Anchored to no coordinate it speaks for the whole dataset; anchored to a channel, for that channel",
)
class ValueUnit(OrgScoped):
    """The value truth: what the array's values measure, pinned to a coordinate anchor"""

    id: auto
    unit: kanne_scalars.Unit = kante.django_field(description="The unit of the values, e.g. 'millivolt'. 'a.u.' for arbitrary units")

    @kante.django_field(description="The physical dimension of the unit. Null for arbitrary units")
    def dimension(self, info: Info) -> kanne_scalars.Dimension | None:
        """The dimensionality of the unit."""
        if kanne_scalars.is_arbitrary_unit(self.unit):
            return None
        return kanne_scalars.parse_dimension(self.unit)


@kante.django_type(
    models.AcquisitionMetadata,
    filters=filters.AcquisitionMetadataFilter,
    pagination=True,
    description="The file truth: whatever the acquisition format said, pinned to a coordinate anchor and kept as it said it",
)
class AcquisitionMetadata(OrgScoped):
    """The file truth: acquisition metadata pinned to a coordinate anchor"""

    id: auto

    @kante.django_field(description="The acquisition metadata, as a JSON object")
    def metadata(self, info: Info) -> scalars.Any:
        """The acquisition metadata."""
        return self.metadata


@kante.django_type(
    models.RecordingSite,
    pagination=True,
    description="The site truth, recorded: a place on a neuron model -- the model it is part of, NEURON's cell, section and position along it in that model -- where the anchored values were recorded, and what was recorded. elektro's own spoke; it was the `Recording` row of a simulation",
)
class RecordingSite(OrgScoped):
    """A place on a neuron model where the anchored values were recorded."""

    id: auto
    kind: enums.RecordingKind
    model: Annotated["NeuronModel", strawberry.lazy("core.types")] = kante.django_field(description="The neuron model this site is part of")
    cell: str | None = kante.django_field(description="The id of the cell, one of the cells the model declares")
    location: str | None = kante.django_field(description="The id of the section, one of the sections of that cell of the model")
    position: float | None = kante.django_field(description="The normalized position along the section, 0 to 1")

    @kante.django_field(description="The stated label, or the site spelled out as 'cell: location(position)'")
    def label(self, info: Info) -> str:
        return self.display_label


@kante.django_type(
    models.StimulusSite,
    pagination=True,
    description="The site truth, injected: a place on a neuron model -- the model it is part of, NEURON's cell, section and position along it in that model -- where the anchored values were injected, and what was clamped. elektro's own spoke; it was the `Stimulus` row of a simulation",
)
class StimulusSite(OrgScoped):
    """A place on a neuron model where the anchored values were injected."""

    id: auto
    kind: enums.StimulusKind
    model: Annotated["NeuronModel", strawberry.lazy("core.types")] = kante.django_field(description="The neuron model this site is part of")
    cell: str | None = kante.django_field(description="The id of the cell, one of the cells the model declares")
    location: str | None = kante.django_field(description="The id of the section, one of the sections of that cell of the model")
    position: float | None = kante.django_field(description="The normalized position along the section, 0 to 1")

    @kante.django_field(description="The stated label, or the site spelled out as 'cell: location(position)'")
    def label(self, info: Info) -> str:
        return self.display_label


@kante.django_type(
    models.SimulationState,
    pagination=True,
    description=(
        "The integrator truth: the anchored values were computed by integrating a neuron model -- the model, NEURON's dt and tstop. elektro's own spoke, the synthetic rig. "
        "A run is its clock: the outputs timed onto one clock are one run, and agree on it"
    ),
)
class SimulationState(OrgScoped):
    """What computed the anchored values."""

    id: auto
    model: Annotated["NeuronModel", strawberry.lazy("core.types")] = kante.django_field(description="The neuron model that was integrated")
    duration: kanne_scalars.Duration = kante.django_field(description="How long the model was run for (NEURON's tstop)")
    dt: kanne_scalars.Duration | None = kante.django_field(description="The integration time step (NEURON's dt). Not the sampling period: a run can record more coarsely than it integrates. Null when unstated")


@kante.django_type(
    models.CoordinateAnchor,
    filters=filters.CoordinateAnchorFilter,
    pagination=True,
    description="The axis-agnostic hub that pins metadata spokes (a value unit, a channel label, the rig state, a value histogram, acquisition metadata) to specific coordinates of a dataset",
)
class CoordinateAnchor(OrgScoped):
    """The axis-agnostic hub that pins metadata spokes to specific coordinates of a dataset"""

    id: auto
    dataset: ArrayDataset
    # The reverse accessor from RigState.anchor is `rig`, not `rig_state`.
    rig: RigState | None = kante.django_field(description="The rig state recorded at this coordinate")
    value_histogram: ValueHistogram | None
    channel_label: ChannelLabel | None
    value_unit: ValueUnit | None
    acquisition_metadata: AcquisitionMetadata | None
    recording_site: Optional["RecordingSite"] = kante.django_field(description="(simulation) Where on the model the values at this coordinate were recorded")
    stimulus_site: Optional["StimulusSite"] = kante.django_field(description="(simulation) Where on the model the values at this coordinate were injected")
    simulation: Optional[SimulationState] = kante.django_field(description="(simulation) The model and integrator parameters that computed the values at this coordinate")

    @kante.django_field(
        description="The coordinates this anchor is pinned to, e.g. {'c': 0, 'sweep': 5}. Level-0 sample indices, i.e. coordinates of the dataset's INTRINSIC system. An anchor that omits an axis is global along it; an empty object is the whole dataset"
    )
    def coordinates(self, info: Info) -> scalars.Any:
        """The coordinates this anchor is pinned to."""
        return self.coordinates


@kante.pydantic_type(base_models.SliceModel, description="A slice along a named axis, with optional start, stop and step")
class Slice:
    """A slice along a named axis, with optional start, stop and step."""

    axis: str
    start: int | None
    stop: int | None
    step: int | None


@kante.django_type(
    models.Lens,
    filters=filters.LensFilter,
    ordering=order.LensOrder,
    pagination=True,
    description="A lens is a way of looking at a dataset: a selection (slices) along its axes -- a sweep, an epoch window, a run of channels. Immutable: there is no updateLens",
)
class Lens(OrgScoped):
    """A selection over a dataset. Its shape and axes are derived from the dataset and the slices."""

    id: auto
    dataset: ArrayDataset

    @kante.django_field(
        select_related=["coordinate_system", "dataset__coordinate_system"],
        description="The coordinate system the lens' selection is expressed in. A sliced lens owns one (the space its slices cut out, with the derived edge recording the shift); an unsliced lens selects everything, so this resolves to the dataset's INTRINSIC system",
    )
    def coordinate_system(self, info: Info) -> CoordinateSystem | None:
        """The system the lens' selection is expressed in: its own, or intrinsic when unsliced."""
        return self.space

    @kante.django_field(description="The lens' axis names, in array order. A selection never drops or reorders an axis")
    def axis_names(self, info: Info) -> List[str]:
        """The lens' axis names."""
        return self.axis_names

    @kante.django_field(description="The shape this lens' slices cut out of its dataset")
    def shape(self, info: Info) -> List[int]:
        """The lens' shape."""
        return self.shape_list

    @kante.django_field(
        description="The edge from this lens' space back into its dataset's sample grid. A window is a translation of the slice starts; a strided lens also rescales. Without this edge sample 0 of a window would read as sample 0 of the recording. Null for an unsliced lens: its space IS the intrinsic space, and there is no shift to record",
    )
    def to_parent(self, info: Info) -> Transformation | None:
        """The stored lens-to-parent edge."""
        return self.to_parent

    @kante.django_field(
        description="The datasets computed from this lens' selection: the direct other end of `derivedFrom`, which names a *lens* as a parent rather than a dataset. An unsliced lens reports what was derived from the whole intrinsic grid -- its space is that grid, so it can say nothing narrower. Like the forward field this reports every child, whether or not this lens is its primary parent and whether or not its geometry survived"
    )
    def derived_datasets(self, info: Info) -> List[ArrayDataset]:
        """The datasets whose derivation edges land in this lens' space."""
        return graph_logic.lens_derived_datasets(self)

    @kante.django_field(description="The slices this lens makes, one per axis it restricts. Empty for a lens that selects everything")
    def slices(self, info: Info) -> List[Slice]:
        """The lens' slices."""
        return self.slices_list

    @kante.django_field(description="The dataset's coordinate anchors that fall inside this lens: an anchor pinned along an axis is in when its position is within the slice, and an anchor global along it always is. How a view of channels 2 to 5 learns what those four channels are called")
    def active_anchors(self, info: Info) -> List[CoordinateAnchor]:
        """The anchors the lens' slices do not exclude."""
        return self.active_anchors
