from core.base_models.type.model import ModelConfigModel
from core.analysis import compute_dominance
from core.analysis.dominance import DEFAULT_WEIGHTS
from pydantic import BaseModel
import strawberry
import strawberry_django
from strawberry import auto
from typing import Any, List, Optional, Annotated, Union, cast
import strawberry_django
from core import models, scalars, filters, enums, scoping
from kanne_server import scalars as quantities
from django.contrib.auth import get_user_model
from kante.types import Info
import datetime
from asgiref.sync import sync_to_async
from itertools import chain
from enum import Enum
from datalayer.datalayer import get_current_datalayer
from strawberry.experimental import pydantic
from typing import Union
from core.base_models.type.graphql.cell import Cell
from core.base_models.type.graphql.topology import Topology
from core.base_models.type.graphql.model import ModelConfig
from authentikate.strawberry.types import Client, User
from koherent.strawberry.types import ProvenanceEntry
from core.type_gen import create_stats_type
from datalayer import types as dt
import kante
from core.parameters import Parameter, ParameterModel


from core.types._shared import OrgScoped, build_prescoped_queryset, build_prescoper  # noqa: E402,F401  (re-exported: mutations and tests import them from here)


@kante.django_type(models.ModEnvironment, filters=filters.ModEnvironmentFilter, pagination=True, ordering=filters.ModEnvironmentOrder)
class ModEnvironment(OrgScoped):
    id: auto
    name: auto
    description: str | None
    store: dt.BigFileStore
    mechanisms: List["Mechanism"] = strawberry_django.field()


@strawberry_django.type(models.Mechanism, filters=filters.MechanismFilter, pagination=True, ordering=filters.MechanismOrder)
class Mechanism(OrgScoped):
    id: auto
    name: auto
    description: str | None

    @kante.django_field(only=["parameters"], description="The parameter ports of the mechanism")
    def parameters(self, info: Info) -> list[Parameter]:
        return [ParameterModel(**param) for param in self.parameters]


@strawberry_django.type(models.ModelCollection, filters=filters.ModelCollectionFilter, ordering=filters.ModelCollectionOrder, pagination=True)
class ModelCollection(OrgScoped):
    id: auto
    name: str
    models: List["NeuronModel"] = strawberry_django.field()
    description: str | None


@strawberry_django.type(models.ModelWorkspace, filters=filters.ModelWorkspaceFilter, ordering=filters.ModelWorkspaceOrder, pagination=True)
class ModelWorkspace(OrgScoped):
    """A shared space for collaboratively developing neuron models.

    A workspace is a collaboration/sharing boundary: users and AI agents share it
    to create, edit, simulate and iterate on neuron models together. Models join
    a workspace through a ``WorkspaceMapping`` (which may also assign them to a
    named group within the workspace). This is orthogonal to ``ModelCollection`` —
    a collection groups *comparable* models, a workspace groups *collaborators*
    around a set of models. A model can belong to both independently.
    """

    id: auto
    name: str
    description: str | None
    creator: User | None
    created_at: datetime.datetime
    mappings: List["WorkspaceMapping"] = strawberry_django.field()

    @strawberry_django.field(description="Whether the current user has pinned this workspace")
    def pinned(self, info: Info) -> bool:
        return cast(models.ModelWorkspace, self).pinned_by.filter(id=info.context.request.user.id).exists()


@strawberry_django.type(models.WorkspaceMapping, filters=filters.WorkspaceMappingFilter, ordering=filters.WorkspaceMappingOrder, pagination=True)
class WorkspaceMapping(OrgScoped):
    """The link between a neuron model and a workspace.

    Optionally assigns the model to a named ``workspace_group`` so a workspace can
    subdivide its models into groups.
    """

    id: auto
    workspace: ModelWorkspace
    model: "NeuronModel"
    workspace_group: str
    created_at: datetime.datetime


@strawberry.enum
class ChangeType(str, Enum):
    REMOVED = "removed"
    ADDED = "added"
    CHANGED = "changed"


@strawberry.type
class Change:
    type: ChangeType
    path: List[str]
    value_a: Optional[scalars.Any]
    value_b: Optional[scalars.Any]


def quantity_display(value: Any) -> Optional[str]:
    """If ``value`` is a serialized quantity struct, render it as a single compact,
    human-readable string; otherwise return None.

    Quantities are stored in ``json_model`` as dicts, so a naive recursive diff would
    descend into them and report several rows of internal fields (the raw ``canonical``
    integer plus the ``given`` string). Collapsing them here yields one readable value:

    - kanne dimension-locked quantity ``{canonical, given, unit}`` -> its ``given`` string
      (e.g. ``"-67 mV"``);
    - GenericQuantity ``{magnitude, unit, dimension}`` -> ``"<magnitude> <unit>"``
      (e.g. ``"0.12 siemens / centimeter ** 2"``, ``"0.7 a.u."``).
    """
    if not isinstance(value, dict):
        return None
    if "canonical" in value and "given" in value:
        return value.get("given")
    if "magnitude" in value and "unit" in value:
        return f"{value['magnitude']} {value['unit']}"
    return None


def _leaf(value: Any) -> Any:
    """Condense a quantity struct to its human string for a change value; else pass through."""
    display = quantity_display(value)
    return display if display is not None else value


def _compare_values(val_a: Any, val_b: Any, path: List[str]) -> List[Change]:
    """Diff two values at ``path``, treating quantity structs as single human-readable leaves."""
    changes: List[Change] = []

    disp_a = quantity_display(val_a)
    disp_b = quantity_display(val_b)
    if disp_a is not None or disp_b is not None:
        # At least one side is a quantity — compare as one leaf so a quantity change is a
        # single readable row (e.g. "-67 mV" -> "-70 mV"), not separate canonical/given rows.
        left = disp_a if disp_a is not None else val_a
        right = disp_b if disp_b is not None else val_b
        if left != right:
            changes.append(Change(type=ChangeType.CHANGED, path=path, value_a=left, value_b=right))
        return changes

    if isinstance(val_a, dict) and isinstance(val_b, dict):
        deeper_changes = compare_models(val_a, val_b, path)
        if deeper_changes:
            changes.extend(deeper_changes)
        elif val_a != val_b:
            changes.append(Change(type=ChangeType.CHANGED, path=path, value_a=val_a, value_b=val_b))
    elif isinstance(val_a, list) and isinstance(val_b, list):
        min_len = min(len(val_a), len(val_b))
        for i in range(min_len):
            changes.extend(_compare_values(val_a[i], val_b[i], path + [str(i)]))
        for i in range(min_len, len(val_a)):
            changes.append(Change(type=ChangeType.REMOVED, path=path + [str(i)], value_a=_leaf(val_a[i]), value_b=None))
        for i in range(min_len, len(val_b)):
            changes.append(Change(type=ChangeType.ADDED, path=path + [str(i)], value_a=None, value_b=_leaf(val_b[i])))
    elif val_a != val_b:
        changes.append(Change(type=ChangeType.CHANGED, path=path, value_a=val_a, value_b=val_b))

    return changes


def compare_models(dict_a: dict, dict_b: dict, path: Optional[List[str]] = None) -> List[Change]:
    if path is None:
        path = []

    changes: List[Change] = []

    keys_a = set(dict_a.keys())
    keys_b = set(dict_b.keys())

    for key in keys_a - keys_b:
        changes.append(Change(type=ChangeType.REMOVED, path=path + [key], value_a=_leaf(dict_a[key]), value_b=None))

    for key in keys_b - keys_a:
        changes.append(Change(type=ChangeType.ADDED, path=path + [key], value_a=None, value_b=_leaf(dict_b[key])))

    for key in keys_a & keys_b:
        changes.extend(_compare_values(dict_a[key], dict_b[key], path + [key]))

    return changes


@strawberry.type
class Comparison:
    collection: ModelCollection
    changes: List[Change]


@strawberry.type
class SectionDominance:
    """How much a section shapes the whole simulation, estimated analytically from the
    stored geometry + biophysics (classical cable theory; no NEURON run).

    ``global_score`` and ``reference_score`` are normalized fractions of the model total
    (each sums to 1 across a model). ``global_score`` is reference-independent (the
    section's overall weight in the cell); ``reference_score`` attenuates that by
    electrotonic distance to the reference site (default: the soma / tree root). The
    remaining fields are the underlying physical factors, exposed for explainability.
    """

    cell_id: str
    section_id: str
    category: str | None
    global_score: float
    reference_score: float
    raw_global: float
    raw_reference: float
    area: float  # cm²
    capacitance: float  # farad
    axial_conductance: float  # siemens
    conductance_load: float  # siemens
    electrotonic_distance: float  # length constants to the reference
    transfer_weight: float  # exp(-electrotonic_distance)
    is_reference: bool


@strawberry_django.type(models.NeuronModel, filters=filters.NeuronModelFilter, pagination=True, ordering=filters.NeuronModelOrder)
class NeuronModel(OrgScoped):
    id: auto
    name: auto
    description: str | None
    creator: User | None
    environment: ModEnvironment
    model_collections: list[ModelCollection] | None
    mappings: List["WorkspaceMapping"] = strawberry_django.field()
    simulations: List["Simulation"] = strawberry_django.field()
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()

    @strawberry_django.field(only=["json_model"])
    def config(self, info: Info) -> "ModelConfig":
        return ModelConfigModel(**self.json_model)

    @strawberry_django.field(only=["json_model"])
    def changes(self, info: Info, to: strawberry.ID | None = None) -> List[Change]:
        """Gets the changes"""
        if to is None:
            to_model = self.model_collections.first().models.first()
        else:
            to_model = models.NeuronModel.objects.get(id=to)

        changes = compare_models(self.json_model, to_model.json_model)
        return changes

    @strawberry_django.field(only=["json_model"])
    def comparisons(self, info: Info) -> List["Comparison"]:
        """Gets the changes"""
        comparisons = []
        for col in self.model_collections.all():
            changes = compare_models(self.json_model, col.models.first().json_model)
            comparisons.append(Comparison(collection=col, changes=changes))
        return comparisons

    @strawberry_django.field(only=["json_model"])
    def section_dominance(
        self,
        info: Info,
        reference_cell: strawberry.ID | None = None,
        reference_section: strawberry.ID | None = None,
        weight_conductance: Annotated[
            Optional[float],
            strawberry.argument(
                description=(
                    "Weight of the conductance load factor (Σ gbar · area — driven by channel "
                    "densities like g_pas / gnabar_hh). Defaults to the built-in blend when unset."
                ),
            ),
        ] = None,
        weight_capacitance: Annotated[
            Optional[float],
            strawberry.argument(
                description=(
                    "Weight of the membrane capacitance factor (cm · area — driven by specific "
                    "capacitance). Defaults to the built-in blend when unset."
                ),
            ),
        ] = None,
        weight_axial: Annotated[
            Optional[float],
            strawberry.argument(
                description=(
                    "Weight of the axial coupling factor (∝ diam² / (Ra · length) — driven by "
                    "section diameter, axial resistivity and length). Defaults to the built-in "
                    "blend when unset."
                ),
            ),
        ] = None,
    ) -> List["SectionDominance"]:
        """Per-section dominance scores — how much each section shapes the simulation.

        Computed analytically from the stored geometry + biophysics (no NEURON run).
        ``reference_section`` (optionally scoped by ``reference_cell``) pins the site the
        reference score attenuates toward; unset, each cell uses its own soma / root.

        The global score is a weighted blend of three normalized factors — conductance
        load, capacitance and axial coupling. The ``weight_*`` arguments tune how much each
        factor drives the score; any left unset keep the default blend.
        """
        reference = None
        if reference_section is not None:
            reference = {"cell_id": reference_cell, "section_id": reference_section}
        default_conductance, default_capacitance, default_axial = DEFAULT_WEIGHTS
        weights = (
            weight_conductance if weight_conductance is not None else default_conductance,
            weight_capacitance if weight_capacitance is not None else default_capacitance,
            weight_axial if weight_axial is not None else default_axial,
        )
        config = ModelConfigModel(**self.json_model)
        return [
            SectionDominance(
                cell_id=d.cell_id,
                section_id=d.section_id,
                category=d.category,
                global_score=d.global_score,
                reference_score=d.reference_score,
                raw_global=d.raw_global,
                raw_reference=d.raw_reference,
                area=d.area,
                capacitance=d.capacitance,
                axial_conductance=d.axial_conductance,
                conductance_load=d.conductance_load,
                electrotonic_distance=d.electrotonic_distance,
                transfer_weight=d.transfer_weight,
                is_reference=d.is_reference,
            )
            for d in compute_dominance(config, reference=reference, weights=weights)
        ]


@strawberry_django.type(models.Simulation, filters=filters.SimulationFilter, ordering=filters.SimulationOrder, pagination=True)
class Simulation(OrgScoped):
    """One run of a neuron model: what was injected, what was recorded, and the clock it ran on."""

    id: auto
    name: str
    description: str | None
    creator: User | None
    model: NeuronModel
    duration: quantities.Duration = strawberry_django.field(description="How long the model was run for (NEURON's tstop)")
    dt: quantities.Duration | None = strawberry_django.field(description="The integration time step (NEURON's dt). An integrator parameter, not the sampling period: a run can record more coarsely than it integrates. Null when unstated")
    stimuli: List["Stimulus"] = strawberry_django.field()
    recordings: List["Recording"] = strawberry_django.field()
    created_at: datetime.datetime
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()
    clock: Optional[Annotated["CoordinateSystem", strawberry.lazy("core.types.coords")]] = strawberry_django.field(
        description="The clock the run's recordings and stimuli are timed against: a coordinate system with one TIME axis, in milliseconds by default. Laying a run into an experiment is one edge from this clock into the experiment's world"
    )

    @strawberry_django.field(
        select_related=["clock"],
        description=(
            "The dataset whose values are the instants the run's samples were recorded at. Derived: it is the field of the time lookups from the run's datasets onto its clock. "
            "Null for a run recorded at a fixed interval, which has a sampling law instead -- see `samplingRate`"
        ),
    )
    def time_dataset(self, info: Info) -> Optional[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]]:
        """The times dataset, read off a lookup edge."""
        from core.logic import clocks

        simulation = cast(models.Simulation, self)
        for grid in _site_grids(simulation):
            times = clocks.times_dataset_of(grid, simulation.clock)
            if times is not None:
                return times
        return None

    @strawberry_django.field(
        select_related=["clock"],
        description=(
            "The rate the run's samples were recorded at, when every recording and stimulus agrees on one. Derived from their sampling laws -- each dataset has its own edge onto the run's "
            "clock, and this is their common value. Null for a run timed by `timeDataset`, and null when the edges have been corrected apart: ask each recording for its own `samplingRate` then"
        ),
    )
    def sampling_rate(self, info: Info) -> quantities.Frequency | None:
        """The rate every sampling law of the run states, if they state one."""
        from core.logic import clocks

        simulation = cast(models.Simulation, self)
        rates = {clocks.sampling_of(grid, simulation.clock)[0] for grid in _site_grids(simulation)}
        return rates.pop() if len(rates) == 1 else None


def _site_grids(simulation: "models.Simulation") -> list:
    """The sample grids of a run's recordings and stimuli, recordings first."""
    sites = [*simulation.recordings.select_related("dataset__coordinate_system"), *simulation.stimuli.select_related("dataset__coordinate_system")]
    return [site.dataset.coordinate_system for site in sites if site.dataset.coordinate_system_id is not None]


_SITE_TIMING_RELATIONS = ["dataset__coordinate_system", "simulation__clock"]


def _site_sampling(site) -> tuple:  # noqa: ANN001 - a recording or a stimulus row
    """``(sampling_rate, t_start)`` of one site's dataset on its run's clock."""
    from core.logic import clocks

    return clocks.sampling_of(site.dataset.coordinate_system, site.simulation.clock)


@strawberry_django.type(models.Recording, filters=filters.RecordingFilter, ordering=filters.RecordingOrder, pagination=True)
class Recording(OrgScoped):
    """What was recorded from the model at one site."""

    id: auto
    simulation: Simulation
    kind: enums.RecordingKind
    dataset: Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")] = strawberry_django.field(description="The recorded samples: an array dataset with a TIME axis. Its `valueUnit` says what was recorded")
    cell: str | None = strawberry_django.field(description="The id of the cell, as the model config names it")
    location: str | None = strawberry_django.field(description="The id of the section, as the model config names it")
    position: float | None = strawberry_django.field(description="The normalized position along the section, 0 to 1")

    @strawberry_django.field(description="The stated label, or the site spelled out as 'cell: location(position)'")
    def label(self, info: Info) -> str:
        return cast(models.Recording, self).display_label

    @strawberry_django.field(select_related=_SITE_TIMING_RELATIONS, description="The rate this dataset's samples were recorded at. Derived from its sampling law, the edge from its sample grid onto the run's clock. Null when the run is timed by `timeDataset`")
    def sampling_rate(self, info: Info) -> quantities.Frequency | None:
        """The rate the sampling law states."""
        return _site_sampling(cast(models.Recording, self))[0]

    @strawberry_django.field(select_related=_SITE_TIMING_RELATIONS, description="When sample 0 was recorded, on the run's clock. Derived from the same sampling-law edge as `samplingRate`")
    def t_start(self, info: Info) -> quantities.Duration | None:
        """The start time the sampling law states."""
        return _site_sampling(cast(models.Recording, self))[1]


@strawberry_django.type(models.Stimulus, filters=filters.StimulusFilter, ordering=filters.StimulusOrder, pagination=True)
class Stimulus(OrgScoped):
    """What was injected into the model at one site."""

    id: auto
    simulation: Simulation
    kind: enums.StimulusKind
    dataset: Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")] = strawberry_django.field(description="The injected samples: an array dataset with a TIME axis. Its `valueUnit` says what was injected")
    cell: str | None = strawberry_django.field(description="The id of the cell, as the model config names it")
    location: str | None = strawberry_django.field(description="The id of the section, as the model config names it")
    position: float | None = strawberry_django.field(description="The normalized position along the section, 0 to 1")

    @strawberry_django.field(description="The stated label, or the site spelled out as 'cell: location(position)'")
    def label(self, info: Info) -> str:
        return cast(models.Stimulus, self).display_label

    @strawberry_django.field(select_related=_SITE_TIMING_RELATIONS, description="The rate this dataset's samples were recorded at. Derived from its sampling law, the edge from its sample grid onto the run's clock. Null when the run is timed by `timeDataset`")
    def sampling_rate(self, info: Info) -> quantities.Frequency | None:
        """The rate the sampling law states."""
        return _site_sampling(cast(models.Stimulus, self))[0]

    @strawberry_django.field(select_related=_SITE_TIMING_RELATIONS, description="When sample 0 was recorded, on the run's clock. Derived from the same sampling-law edge as `samplingRate`")
    def t_start(self, info: Info) -> quantities.Duration | None:
        """The start time the sampling law states."""
        return _site_sampling(cast(models.Stimulus, self))[1]


@strawberry_django.type(models.Block, filters=filters.BlockFilter, ordering=filters.BlockOrder, pagination=True)
class Block(OrgScoped):
    """A recording session: the top-level container of Neo's data model."""

    id: auto
    name: str
    description: str | None
    created_at: datetime.datetime
    folder: Optional[Annotated["Folder", strawberry.lazy("core.types.folder")]] = strawberry_django.field(description="The folder this block is filed in. Organisational only")
    origin: Optional[Annotated["File", strawberry.lazy("core.types.folder")]] = strawberry_django.field(description="The file this block was read from, if any")
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()
    creator: User | None = strawberry_django.field(description="Who created this recording session")
    groups: List["BlockGroup"] = strawberry_django.field(description="The groups in this recording session")
    segments: List["BlockSegment"] = strawberry_django.field(description="The segments of this recording session, in order")
    clock: Optional[Annotated["CoordinateSystem", strawberry.lazy("core.types.coords")]] = strawberry_django.field(
        description="The session clock: a coordinate system with one TIME axis. Its `epoch` is when the recording started; every segment's clock is this one or is related to it by an offset edge"
    )

    @strawberry_django.field(select_related=["clock"], description="The wall-clock instant the recording started. Derived: it is the `epoch` of the session `clock`, so everything timed against that clock agrees about it")
    def recording_time(self, info: Info) -> datetime.datetime | None:
        """The session clock's epoch."""
        return cast(models.Block, self).recording_time

    @strawberry_django.field(description="Is this block pinned by the current user")
    def pinned(self, info: Info) -> bool:
        return cast(models.Block, self).pinned_by.filter(id=info.context.request.user.id).exists()


BlockStats, BlockStatsResolver = create_stats_type(
    model=models.Block,
    filters=filters.BlockFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
    prescope=build_prescoper(),
)


@strawberry_django.type(models.BlockSegment, filters=filters.BlockSegmentFilter, ordering=filters.BlockSegmentOrder, pagination=True)
class BlockSegment(OrgScoped):
    """One contiguous stretch of a session -- a trial, a sweep, a protocol step. Neo's Segment."""

    id: auto
    block: Block
    index: int
    name: str | None
    description: str | None
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()
    analog_signals: List[Annotated["AnalogSignal", strawberry.lazy(__name__)]] = strawberry_django.field(description="The regularly sampled signals of this segment")
    irregularly_sampled_signals: List[Annotated["IrregularlySampledSignal", strawberry.lazy(__name__)]] = strawberry_django.field(description="The irregularly sampled signals of this segment")
    spike_trains: List[Annotated["SpikeTrain", strawberry.lazy(__name__)]] = strawberry_django.field(description="The spike trains of this segment")
    clock: Optional[Annotated["CoordinateSystem", strawberry.lazy("core.types.coords")]] = strawberry_django.field(
        description="The clock this segment's signals are timed against. The session's own when the signals' start times are session-relative; otherwise the segment's own, related to the session's by one offset edge when its start is known"
    )

    @strawberry_django.field(
        select_related=["clock", "block__clock"],
        description="Where this segment starts on the session clock. Derived from the offset edge between the two clocks: zero when the segment shares the session's clock, null when its own clock was never related to it",
    )
    def start_time(self, info: Info) -> quantities.Duration | None:
        """The segment clock's offset on the session clock."""
        from core.logic import clocks

        segment = cast(models.BlockSegment, self)
        if segment.clock_id is None:
            return None
        if segment.clock_id == segment.block.clock_id:
            return 0
        return clocks.offset_of(segment.clock, segment.block.clock)


@strawberry_django.type(models.BlockGroup, filters=filters.BlockGroupFilter, ordering=filters.BlockGroupOrder, pagination=True)
class BlockGroup(OrgScoped):
    """A named grouping across a block's segments -- a tetrode, a brain area, a sorted unit. Neo's Group."""

    id: auto
    name: str
    block: Block
    description: str | None
    parent: Optional[Annotated["BlockGroup", strawberry.lazy(__name__)]]
    children: List[Annotated["BlockGroup", strawberry.lazy(__name__)]] = strawberry_django.field(description="The groups nested in this one")
    analog_signals: List[Annotated["AnalogSignal", strawberry.lazy(__name__)]] = strawberry_django.field(description="The analog signals in this group")
    irregularly_sampled_signals: List[Annotated["IrregularlySampledSignal", strawberry.lazy(__name__)]] = strawberry_django.field(description="The irregularly sampled signals in this group")
    spike_trains: List[Annotated["SpikeTrain", strawberry.lazy(__name__)]] = strawberry_django.field(description="The spike trains in this group")


@strawberry.interface(description="A signal recorded in a segment: a named dataset, timed against the segment's clock by an edge of the coordinate graph")
class Signal:
    """What every signal kind shares."""

    id: strawberry.ID
    name: str
    description: str | None
    segment: BlockSegment
    dataset: Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]


def _signal_timing(signal) -> tuple:  # noqa: ANN001 - any signal row
    """The sample grid of a signal's dataset, and the clock of its segment: the two ends of its timing edge."""
    return signal.dataset.coordinate_system, signal.segment.clock


_TIMING_RELATIONS = ["dataset__coordinate_system", "segment__clock"]


@strawberry_django.type(models.AnalogSignal, filters=filters.AnalogSignalFilter, ordering=filters.AnalogSignalOrder, pagination=True)
class AnalogSignal(Signal, OrgScoped):
    """A regularly sampled signal: Neo's AnalogSignal, one (t, c) dataset for all its channels."""

    id: auto
    name: str
    description: str | None
    color: str
    segment: BlockSegment
    dataset: Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")] = strawberry_django.field(description="The samples: one dataset, with a CHANNEL axis when the signal has more than one channel. Its `valueUnit` is the signal's unit")
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()

    @strawberry_django.field(
        select_related=_TIMING_RELATIONS,
        description=(
            "The sampling rate. Derived: it is read off the sampling law, the one edge from the dataset's sample grid onto the segment's clock -- so correcting that edge "
            "(updateTransformation) corrects this. Exact up to about 100 kHz; read the edge's `affine` when the last digit matters. Null if the edge was deleted"
        ),
    )
    def sampling_rate(self, info: Info) -> quantities.Frequency | None:
        """The rate the sampling law states."""
        from core.logic import clocks

        return clocks.sampling_of(*_signal_timing(cast(models.AnalogSignal, self)))[0]

    @strawberry_django.field(select_related=_TIMING_RELATIONS, description="When sample 0 was taken, on the segment's clock. Derived from the same sampling-law edge as `samplingRate`")
    def t_start(self, info: Info) -> quantities.Duration | None:
        """The start time the sampling law states."""
        from core.logic import clocks

        return clocks.sampling_of(*_signal_timing(cast(models.AnalogSignal, self)))[1]

    @strawberry_django.field(select_related=_TIMING_RELATIONS, description="The sampling law itself: the edge from the dataset's sample grid onto the segment's clock, with its validity and provenance")
    def sampling_law(self, info: Info) -> Optional[Annotated["Transformation", strawberry.lazy("core.types.coords")]]:
        """The edge `samplingRate` and `tStart` are read from."""
        grid, clock = _signal_timing(cast(models.AnalogSignal, self))
        if grid is None or clock is None:
            return None
        return models.Transformation.objects.filter(input=grid, output=clock, parent__isnull=True).order_by("pk").first()


@strawberry_django.type(models.SpikeTrain, filters=filters.SpikeTrainFilter, ordering=filters.SpikeTrainOrder, pagination=True)
class SpikeTrain(Signal, OrgScoped):
    """The spike times of one unit: Neo's SpikeTrain. The dataset's values are the times."""

    id: auto
    name: str
    description: str | None
    segment: BlockSegment
    dataset: Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")] = strawberry_django.field(description="The spike times: one value per spike along an INDEX axis, in the unit of the segment's clock")
    waveforms: Optional[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]] = strawberry_django.field(description="The spike waveforms, as a (spike, c, t) dataset")
    t_start: quantities.Duration = strawberry_django.field(description="The start of the window the unit was observed over, on the segment's clock. Stored, not derived: a train with no spikes over 10 s is a different measurement from one with no spikes over 100 s")
    t_stop: quantities.Duration = strawberry_django.field(description="The end of the window the unit was observed over, on the segment's clock")
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()


@strawberry_django.type(models.IrregularlySampledSignal, filters=filters.IrregularlySampledSignalFilter, ordering=filters.IrregularlySampledSignalOrder, pagination=True)
class IrregularlySampledSignal(Signal, OrgScoped):
    """A signal sampled at arbitrary instants: Neo's IrregularlySampledSignal."""

    id: auto
    name: str
    description: str | None
    segment: BlockSegment
    dataset: Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")] = strawberry_django.field(description="The samples. Its `valueUnit` is the signal's unit")
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()

    @strawberry_django.field(
        select_related=_TIMING_RELATIONS,
        description="The dataset whose values are the instants the samples were taken at. Derived: it is the field of the time lookup, the FIELD edge from the signal's sample grid onto the segment's clock",
    )
    def time_dataset(self, info: Info) -> Optional[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]]:
        """The times dataset, read off the lookup edge."""
        from core.logic import clocks

        return clocks.times_dataset_of(*_signal_timing(cast(models.IrregularlySampledSignal, self)))


# The coordinate graph lives in its own module, at the path mikro keeps it. Imported last:
# its lazy annotations point back at the types above.
from core.types.coords import (  # noqa: E402,F401
    Axis,
    CoordinateSystem,
    Transformation,
    Selector,
    PlacementStep,
    AffinePlacement,
    AxisExtent,
    SourcePlacement,
    CoordinateGraph,
    LineageGraph,
    transformation_types,
)

# The data layer, at the paths mikro keeps it: what lives in a space, and where it is filed.
from core.types.array_dataset import (  # noqa: E402,F401
    ArrayDataset,
    DataArray,
    CoordinateAnchor,
    RigState,
    ValueHistogram,
    ChannelLabel,
    ValueUnit,
    AcquisitionMetadata,
    Lens,
    Slice,
)
from core.types.folder import File, Folder  # noqa: E402,F401
from core.types.file_link import FileLink, FileLinkContainer  # noqa: E402,F401

# Annotations are drawn in a space of the graph, and experiments compose over it and show them: in that order.
from core.types.annotation import Annotation, AnnotationCollection, BoundingBox, Coordinate  # noqa: E402,F401
from core.types.experiment import (  # noqa: E402,F401
    Experiment,
    ExperimentView,
    ExperimentLensView,
    ExperimentRecordingView,
    ExperimentStimulusView,
    ExperimentAnnotationView,
)
