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


def sessions_of(info: Info, datasets: "models.QuerySet") -> List["NeuronModelSession"]:
    """The viewer's datasets among ``datasets``, grouped by the clock they are timed onto (`sites.sessions_of`)."""
    from core.logic import sites

    scoped = list(scoping.for_org(models.ArrayDataset, info).filter(pk__in=datasets.values("pk")).order_by("pk"))
    return [NeuronModelSession(clock=clock, datasets=grouped) for clock, grouped in sites.sessions_of(scoped)]


@strawberry.type(description="One session of a neuron model: a clock, and the model's datasets timed onto it -- one run, since a run is its clock")
class NeuronModelSession:
    clock: Optional[Annotated["CoordinateSystem", strawberry.lazy("core.types.coords")]] = strawberry.field(
        description="The clock the datasets are timed onto: the run. Null for the model's simulated datasets timed onto no clock yet"
    )
    datasets: List[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]] = strawberry.field(description="The datasets timed onto this clock, in creation order")


@strawberry_django.type(models.NeuronModel, filters=filters.NeuronModelFilter, pagination=True, ordering=filters.NeuronModelOrder)
class NeuronModel(OrgScoped):
    id: auto
    name: auto
    description: str | None
    creator: User | None
    environment: ModEnvironment
    coordinate_system: Annotated["CoordinateSystem", strawberry.lazy("core.types.coords")] | None = strawberry_django.field(
        description="The coordinate system this model owns. It carries one INDEX axis and nothing placeable; its derivation edges are the model's lineage"
    )
    model_collections: list[ModelCollection] | None
    mappings: List["WorkspaceMapping"] = strawberry_django.field()
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()

    @strawberry_django.field(
        description="The array datasets computed by integrating this model: those carrying a `simulation` anchor on it, in the viewer's organization. A run is its clock: the outputs of one run are those timed onto one clock"
    )
    def simulated_datasets(self, info: Info) -> List[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]]:
        return list(scoping.for_org(models.ArrayDataset, info).filter(anchors__simulation__model=self).distinct().order_by("pk"))

    @strawberry_django.field(
        description=(
            "The model's simulated datasets grouped by the clock they are timed onto: one session per run, since a run is its clock. Read off the graph, never stored. "
            "A dataset timed onto two clocks is in both; the datasets timed onto none come last, under a null clock"
        )
    )
    def sessions(self, info: Info) -> List[NeuronModelSession]:
        """Group :meth:`simulated_datasets` by the clock they are timed onto, in clock order."""
        return sessions_of(info, models.ArrayDataset.objects.filter(anchors__simulation__model=self))

    @strawberry_django.field(
        description=(
            "Every edge from this model's space back into what it was computed from, in declared order -- the first is the primary parent, the model it was edited out of. Always "
            "UNMAPPABLE: a model's space carries one INDEX axis and nothing placeable, so the edge records the lineage and claims no geometry. Empty for a model written from "
            "scratch. This replaces the old `parent` field, which recorded no validity, no value relation and no provenance, and which `lineageGraph` could not see"
        )
    )
    def derived_from(self, info: Info) -> List[Annotated["Transformation", strawberry.lazy("core.types.coords")]]:
        """The edges relating this model's space to whatever it came from."""
        system = getattr(self, "coordinate_system", None)
        from core.logic import graph as graph_logic

        return graph_logic.collection_derivation_edges(system) if system else []

    @strawberry_django.field(
        description=(
            "Everything computed from this model, whatever kind of container it is: the models edited out of it, and the datasets whose `derivedFrom` names it -- a simulated "
            "trace that stated where it came from. Derived from the same edges as `derivedFrom`, never a stored back-reference that could disagree with them. **Not the same "
            "question as `simulatedDatasets`**, which reads the `simulation` spoke and answers for every run of this model whether or not anyone authored a derivation"
        )
    )
    def derived_into(self, info: Info) -> List[Annotated["Resident", strawberry.lazy("core.types.coords")]]:
        """The containers computed from this model."""
        system = getattr(self, "coordinate_system", None)
        from core.logic import graph as graph_logic

        return graph_logic.containers_derived_into(system) if system else []

    @strawberry_django.field(description="The recording sites that are part of this model: every place on it some dataset's values were recorded from, in the viewer's organization")
    def recording_sites(self, info: Info) -> List[Annotated["RecordingSite", strawberry.lazy("core.types.array_dataset")]]:
        return list(scoping.for_org(models.RecordingSite, info).filter(model=self))

    @strawberry_django.field(description="The stimulus sites that are part of this model: every place on it some dataset's values were injected at, in the viewer's organization")
    def stimulus_sites(self, info: Info) -> List[Annotated["StimulusSite", strawberry.lazy("core.types.array_dataset")]]:
        return list(scoping.for_org(models.StimulusSite, info).filter(model=self))

    @strawberry_django.field(only=["id", "json_model"])
    def config(self, info: Info) -> "ModelConfig":
        from core.logic import sites

        return sites.config_of(cast(models.NeuronModel, self))

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
    SimulationState,
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
