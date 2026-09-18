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

    @strawberry_django.field(description="The recording sites that are part of this model: every place on it some dataset's values were recorded from, in the viewer's organization")
    def recording_sites(self, info: Info) -> List[Annotated["RecordingSite", strawberry.lazy("core.types.array_dataset")]]:
        return list(scoping.for_org(models.RecordingSite, info).filter(model=self))

    @strawberry_django.field(description="The stimulus sites that are part of this model: every place on it some dataset's values were injected at, in the viewer's organization")
    def stimulus_sites(self, info: Info) -> List[Annotated["StimulusSite", strawberry.lazy("core.types.array_dataset")]]:
        return list(scoping.for_org(models.StimulusSite, info).filter(model=self))

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
    """One run of a neuron model: the model, the integrator's parameters, and the clock it ran on."""

    id: auto
    name: str
    description: str | None
    creator: User | None
    model: NeuronModel
    duration: quantities.Duration = strawberry_django.field(description="How long the model was run for (NEURON's tstop)")
    dt: quantities.Duration | None = strawberry_django.field(description="The integration time step (NEURON's dt). An integrator parameter, not the sampling period: a run can record more coarsely than it integrates. Null when unstated")
    created_at: datetime.datetime
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()
    clock: Optional[Annotated["CoordinateSystem", strawberry.lazy("core.types.coords")]] = strawberry_django.field(
        description="The clock the run's datasets are timed against: a coordinate system with one TIME axis, in milliseconds by default. Laying a run into an experiment is one edge from this clock into the experiment's world"
    )

    @strawberry_django.field(
        select_related=["clock"],
        description="The array datasets timed on this run's clock -- recordings and stimuli alike, each by its own sampling law or time lookup. Read off the graph, never stored: timing a dataset on the clock is what makes it part of the run",
    )
    def datasets(self, info: Info) -> List[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]]:
        """The datasets whose grid has a timing edge onto the clock."""
        from core.logic import clocks

        return clocks.datasets_timed_on(cast(models.Simulation, self).clock)

    @strawberry_django.field(select_related=["clock"], description="The datasets of this run carrying a `recordingSite` on some anchor: what was recorded, and where")
    def recordings(self, info: Info) -> List[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]]:
        """The run's datasets with a recording site."""
        return _with_site(cast(models.Simulation, self), "recording_site")

    @strawberry_django.field(select_related=["clock"], description="The datasets of this run carrying a `stimulusSite` on some anchor: what was injected, and where")
    def stimuli(self, info: Info) -> List[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]]:
        """The run's datasets with a stimulus site."""
        return _with_site(cast(models.Simulation, self), "stimulus_site")

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
        for grid in clocks.grids_timed_on(simulation.clock):
            times = clocks.times_dataset_of(grid, simulation.clock)
            if times is not None:
                return times
        return None

    @strawberry_django.field(
        select_related=["clock"],
        description=(
            "The rate the run's samples were recorded at, when every dataset timed on its clock agrees on one. Derived from their sampling laws -- each has its own edge onto the "
            "clock, and this is their common value. Null for a run timed by `timeDataset`, and null when the edges have been corrected apart"
        ),
    )
    def sampling_rate(self, info: Info) -> quantities.Frequency | None:
        """The rate every sampling law of the run states, if they state one."""
        from core.logic import clocks

        simulation = cast(models.Simulation, self)
        rates = {clocks.sampling_of(grid, simulation.clock)[0] for grid in clocks.grids_timed_on(simulation.clock)}
        return rates.pop() if len(rates) == 1 else None


def _with_site(simulation: "models.Simulation", spoke: str) -> list:
    """The run's datasets with an anchor carrying ``spoke``, in timing order."""
    from core.logic import clocks

    datasets = clocks.datasets_timed_on(simulation.clock)
    sited = set(models.CoordinateAnchor.objects.filter(dataset__in=datasets, **{f"{spoke}__isnull": False}).values_list("dataset_id", flat=True))
    return [dataset for dataset in datasets if dataset.pk in sited]


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
    RecordingSite,
    StimulusSite,
    AcquisitionMetadata,
    Lens,
    Slice,
)
from core.types.table_dataset import TableDataset, Column  # noqa: E402,F401
from core.types.sparse_dataset import SparseDataset, SparseArray, SparseAxisReference  # noqa: E402,F401
from core.types.folder import File, Folder  # noqa: E402,F401
from core.types.file_link import FileLink, FileLinkContainer  # noqa: E402,F401

# Annotations are drawn in a space of the graph, and experiments compose over it and show them: in that order.
from core.types.annotation import Annotation, AnnotationCollection, BoundingBox, Coordinate  # noqa: E402,F401
from core.types.experiment import Experiment  # noqa: E402,F401
from core.types.layers import (  # noqa: E402,F401
    ExperimentLayer,
    TraceLayer,
    SpikesLayer,
    EventsLayer,
    AnnotationLayer,
    HeatmapLayer,
    SeriesLayer,
    WaveformLayer,
    PointLayer,
    ColorBy,
    FilterBy,
    JoinStep,
    LevelPlacement,
    layer_types,
)
