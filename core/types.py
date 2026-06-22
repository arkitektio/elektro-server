from core.base_models.type.model import ModelConfigModel
from pydantic import BaseModel
import strawberry
import strawberry_django
from strawberry import auto
from typing import List, Optional, Annotated, Union, cast
import strawberry_django
from core import models, scalars, filters, enums
from kanne import scalars as quantities
from django.contrib.auth import get_user_model
from kante.types import Info
import datetime
from asgiref.sync import sync_to_async
from itertools import chain
from enum import Enum
from datalayer.datalayer import get_current_datalayer
from core.render.objects import models as rmodels
from strawberry.experimental import pydantic
from typing import Union
from core.base_models.type.graphql.cell import Cell
from core.base_models.type.graphql.topology import Topology
from core.base_models.type.graphql.model import ModelConfig
from authentikate.strawberry.types import Client, User
from koherent.strawberry.types import ProvenanceEntry
from .type_gen import create_stats_type
from datalayer import types as dt
import kante
from core.parameters import Parameter, ParameterModel


def build_prescoped_queryset(info, queryset, field="organization"):
    print(info)
    if info.variable_values.get("filters", {}).get("scope") is None:
        queryset = queryset.filter(**{field: info.context.request.organization})
        return queryset

    else:
        raise Exception("Custom scopes not implemented yet")


def build_prescoper(field="organization"):
    def prescoper(queryset, info):
        return build_prescoped_queryset(info, queryset, field=field)

    return prescoper


@strawberry_django.type(
    models.ViewCollection,
    filters=filters.ViewCollectionFilter,
    ordering=filters.ViewCollectionOrder,
    pagination=True,
)
class ViewCollection:
    """A colletion of views.

    View collections are use to provide overarching views on your data,
    that are not bound to a specific image. For example, you can create
    a view collection that includes all middle z views of all images with
    a certain tag.

    View collections are a pure metadata construct and will not map to
    oredering of binary data.


    """

    id: auto
    name: auto
    views: List["View"]
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()


@strawberry.enum
class ViewKind(str, Enum):
    """The kind of view.

    Views can be of different kinds. For example, a view can be a label view
    that will map a labeleling agent (e.g. an antibody) to a specific image channel.

    Depending on the kind of view, different fields will be available.

    """

    TIMEPOINT = "timepoint_views"


@strawberry_django.type(models.File, filters=filters.FileFilter, ordering=filters.FileOrder, pagination=True)
class File:
    id: auto
    name: auto
    origins: List["Trace"] = strawberry_django.field()
    store: dt.BigFileStore


@kante.django_type(models.ModEnvironment, filters=filters.ModEnvironmentFilter, pagination=True, ordering=filters.ModEnvironmentOrder)
class ModEnvironment:
    id: auto
    name: auto
    description: str | None
    store: dt.BigFileStore
    mechanisms: List["Mechanism"] = strawberry_django.field()


@strawberry_django.type(models.Mechanism, filters=filters.MechanismFilter, pagination=True, ordering=filters.MechanismOrder)
class Mechanism:
    id: auto
    name: auto
    description: str | None

    @kante.django_field(description="The parameter ports of the mechanism")
    def parameters(self, info: Info) -> list[Parameter]:
        return [ParameterModel(**param) for param in self.parameters]


@strawberry_django.type(models.ModelCollection, filters=filters.ModelCollectionFilter, ordering=filters.ModelCollectionOrder, pagination=True)
class ModelCollection:
    id: auto
    name: str
    models: List["NeuronModel"] = strawberry_django.field()
    description: str | None


@strawberry_django.type(models.ModelWorkspace, filters=filters.ModelWorkspaceFilter, ordering=filters.ModelWorkspaceOrder, pagination=True)
class ModelWorkspace:
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
class WorkspaceMapping:
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


def compare_models(dict_a: dict, dict_b: dict, path: Optional[List[str]] = None) -> List[Change]:
    if path is None:
        path = []

    changes: List[Change] = []

    keys_a = set(dict_a.keys())
    keys_b = set(dict_b.keys())

    for key in keys_a - keys_b:
        changes.append(Change(type=ChangeType.REMOVED, path=path + [key], value_a=dict_a[key], value_b=None))

    for key in keys_b - keys_a:
        changes.append(Change(type=ChangeType.ADDED, path=path + [key], value_a=None, value_b=dict_b[key]))

    for key in keys_a & keys_b:
        val_a = dict_a[key]
        val_b = dict_b[key]

        if isinstance(val_a, dict) and isinstance(val_b, dict):
            deeper_changes = compare_models(val_a, val_b, path + [key])
            if deeper_changes:
                changes.extend(deeper_changes)
            elif val_a != val_b:
                changes.append(Change(type=ChangeType.CHANGED, path=path + [key], value_a=val_a, value_b=val_b))
        elif isinstance(val_a, list) and isinstance(val_b, list):
            # Compare lists element by element
            min_len = min(len(val_a), len(val_b))
            for i in range(min_len):
                item_a = val_a[i]
                item_b = val_b[i]
                if isinstance(item_a, dict) and isinstance(item_b, dict):
                    deeper_changes = compare_models(item_a, item_b, path + [key, str(i)])
                    changes.extend(deeper_changes)
                elif item_a != item_b:
                    changes.append(Change(type=ChangeType.CHANGED, path=path + [key, str(i)], value_a=item_a, value_b=item_b))
            # Handle extra items
            for i in range(min_len, len(val_a)):
                changes.append(Change(type=ChangeType.REMOVED, path=path + [key, str(i)], value_a=val_a[i], value_b=None))
            for i in range(min_len, len(val_b)):
                changes.append(Change(type=ChangeType.ADDED, path=path + [key, str(i)], value_a=None, value_b=val_b[i]))
        elif val_a != val_b:
            changes.append(Change(type=ChangeType.CHANGED, path=path + [key], value_a=val_a, value_b=val_b))

    return changes


@strawberry.type
class Comparison:
    collection: ModelCollection
    changes: List[Change]


@strawberry_django.type(models.NeuronModel, filters=filters.NeuronModelFilter, pagination=True, ordering=filters.NeuronModelOrder)
class NeuronModel:
    id: auto
    name: auto
    description: str | None
    creator: User | None
    environment: ModEnvironment
    model_collections: list[ModelCollection] | None
    mappings: List["WorkspaceMapping"] = strawberry_django.field()
    simulations: List["Simulation"] = strawberry_django.field()
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()

    @strawberry_django.field()
    def config(self, info: Info) -> "ModelConfig":
        return ModelConfigModel(**self.json_model)

    @strawberry_django.field()
    def changes(self, info: Info, to: strawberry.ID | None = None) -> List[Change]:
        """Gets the changes"""
        if to is None:
            to_model = self.model_collections.first().models.first()
        else:
            to_model = models.NeuronModel.objects.get(id=to)

        changes = compare_models(self.json_model, to_model.json_model)
        return changes

    @strawberry_django.field()
    def comparisons(self, info: Info) -> List["Comparison"]:
        """Gets the changes"""
        comparisons = []
        for col in self.model_collections.all():
            changes = compare_models(self.json_model, col.models.first().json_model)
            comparisons.append(Comparison(collection=col, changes=changes))
        return comparisons


@strawberry_django.type(models.Experiment, filters=filters.ExperimentFilter, ordering=filters.ExperimentOrder, pagination=True)
class Experiment:
    id: auto
    name: str
    description: str | None
    time_trace: "Trace"
    created_at: datetime.datetime
    recording_views: List["ExperimentRecordingView"] = strawberry_django.field()
    stimulus_views: List["ExperimentStimulusView"] = strawberry_django.field()
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()


@strawberry_django.type(models.Simulation, filters=filters.SimulationFilter, ordering=filters.SimulationOrder, pagination=True)
class Simulation:
    id: auto
    name: str
    description: str | None
    kind: enums.StimulusKind
    creator: User | None
    model: NeuronModel
    duration: quantities.Duration
    dt: quantities.Duration
    time_trace: "Trace"
    stimuli: List["Stimulus"] = strawberry_django.field()
    recordings: List["Recording"] = strawberry_django.field()
    created_at: datetime.datetime
    recording_views: List["ExperimentRecordingView"] = strawberry_django.field()
    stimulus_views: List["ExperimentStimulusView"] = strawberry_django.field()


@strawberry_django.type(models.Recording, filters=filters.RecordingFilter, ordering=filters.RecordingOrder, pagination=True)
class Recording:
    id: auto
    simulation: Simulation
    kind: enums.RecordingKind
    trace: "Trace"
    location: str
    position: float
    cell: str

    @strawberry_django.field()
    def label(self, info: Info) -> str:
        return self.label or f"{self.cell}: {self.location}({self.position})"


@strawberry_django.type(models.Stimulus, filters=filters.StimulusFilter, ordering=filters.StimulusOrder, pagination=True)
class Stimulus:
    id: auto
    simulation: Simulation
    kind: enums.StimulusKind
    trace: "Trace"
    location: str
    position: float
    cell: str

    @strawberry_django.field()
    def label(self, info: Info) -> str:
        return self.label or f"{self.cell}: {self.location}({self.position})"


@strawberry_django.type(models.ExperimentRecordingView, filters=filters.ExperimentRecordingViewFilter, ordering=filters.ExperimentRecordingViewOrder, pagination=True)
class ExperimentRecordingView:
    id: auto
    recording: Recording
    label: str | None
    offset: quantities.Duration | None
    duration: quantities.Duration | None
    experiment: "Experiment"


@strawberry_django.type(models.ExperimentStimulusView, filters=filters.ExperimentStimulusViewFilter, ordering=filters.ExperimentStimulusViewOrder, pagination=True)
class ExperimentStimulusView:
    id: auto
    stimulus: Stimulus
    label: str | None
    offset: quantities.Duration | None
    duration: quantities.Duration | None
    experiment: "Experiment"


@strawberry_django.type(models.Block, filters=filters.BlockFilter, pagination=True, ordering=filters.BlockOrder)
class Block:
    id: auto
    name: str
    description: str | None
    trace: "Trace"
    acquired_at: datetime.datetime | None
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()
    creator: User | None = strawberry.field(description="Who created this recording session")
    groups: List["BlockGroup"] = strawberry_django.field(description="The groups in this recording session")
    segments: List["BlockSegment"] = strawberry_django.field(description="The segments in this recording session")


BlockStats, BlockStatsResolver = create_stats_type(
    model=models.Block,
    filters=filters.BlockFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
    prescope=build_prescoper(field="organization"),
)


@strawberry_django.type(models.BlockSegment, filters=filters.BlockSegmentFilter, ordering=filters.BlockSegmentOrder, pagination=True)
class BlockSegment:
    id: auto
    block: Block
    label: str
    description: str | None
    start_time: quantities.Duration | None
    end_time: quantities.Duration | None
    creator: User | None = strawberry.field(description="Who created this segment")
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()
    groups: List["BlockGroup"] = strawberry_django.field(description="The groups that this segment belongs to")
    analog_signals: List[Annotated["AnalogSignal", strawberry.lazy(__name__)]] = strawberry_django.field(description="The analog signals in this group")
    irregularly_sampled_signals: List[Annotated["IrregularlySampledSignal", strawberry.lazy(__name__)]] = strawberry_django.field(description="The irregularly sampled signals in this group")
    spike_trains: List[Annotated["SpikeTrain", strawberry.lazy(__name__)]] = strawberry_django.field(description="The spike trains in this group")


@strawberry_django.type(models.BlockGroup, filters=filters.BlockGroupFilter, ordering=filters.BlockGroupOrder, pagination=True)
class BlockGroup:
    id: auto
    name: str
    block: Block
    description: str | None
    analog_signals: List[Annotated["AnalogSignal", strawberry.lazy(__name__)]] = strawberry_django.field(description="The analog signals in this group")
    irregularly_sampled_signals: List[Annotated["IrregularlySampledSignal", strawberry.lazy(__name__)]] = strawberry_django.field(description="The irregularly sampled signals in this group")
    spike_trains: List[Annotated["SpikeTrain", strawberry.lazy(__name__)]] = strawberry_django.field(description="The spike trains in this group")


@strawberry.interface(description="A signal recorded during a recording session")
class Signal:
    name: str
    segment: BlockSegment


@strawberry_django.type(models.AnalogSignalChannel, filters=filters.AnalogSignalChannelFilter, ordering=filters.AnalogSignalChannelOrder, pagination=True)
class AnalogSignalChannel:
    id: auto
    name: str | None
    description: str | None
    label: str | None
    unit: str | None
    index: int
    trace: "Trace"
    signal: "AnalogSignal"


@strawberry_django.type(models.AnalogSignal, filters=filters.AnalogSignalFilter, ordering=filters.AnalogSignalOrder, pagination=True)
class AnalogSignal(Signal):
    id: auto
    sampling_rate: quantities.Frequency
    unit: str | None
    time_trace: "Trace"
    channels: List[AnalogSignalChannel] = strawberry_django.field()
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()


@strawberry_django.type(models.SpikeTrain, filters=filters.SpikeTrainFilter, ordering=filters.SpikeTrainOrder, pagination=True)
class SpikeTrain(Signal):
    id: auto
    trace: "Trace"
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()


@strawberry_django.type(models.IrregularlySampledSignal, filters=filters.IrregularlySampledSignalFilter, ordering=filters.IrregularlySampledSignalOrder, pagination=True)
class IrregularlySampledSignal(Signal):
    id: auto
    trace: "Trace"
    unit: str | None
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()


@strawberry_django.type(models.Trace, filters=filters.TraceFilter, ordering=filters.TraceOrder, pagination=True)
class Trace:
    """An image.


    Images are the central data type in mikro. They represent a single 5D bioimage, which
    binary data is stored in a ZarrStore. Images can be annotated with views, which are
    subsets of the image, ordered by its coordinates. Views can be of different kinds, for
    example, a label view will map a labeling agent (e.g. an antibody) to a specific image
    channel. Depending on the kind of view, different fields will be available.

    Images also represent the primary data container for other models of the mikro data model.
    For example rois, metrics, renders, and generated tables are all bound to a specific image,
    and will share the lifecycle of the image.

    """

    id: auto
    name: auto = strawberry_django.field(description="The name of the image")
    store: dt.ZarrStore = strawberry_django.field(description="The store where the image data is stored.")
    dataset: Optional["Dataset"] = strawberry_django.field(description="The dataset this image belongs to")
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()
    creator: User | None = strawberry_django.field(description="Who created this image")
    rois: List["ROI"] = strawberry_django.field(description="The rois of this image")

    @strawberry_django.field(description="Is this image pinned by the current user")
    def pinned(self, info: Info) -> bool:
        return cast(models.Image, self).pinned_by.filter(id=info.context.request.user.id).exists()

    @strawberry_django.field(description="The tags of this image")
    def tags(self, info: Info) -> list[str]:
        return cast(models.Image, self).tags.slugs()

    @strawberry_django.field()
    def events(
        self,
        info: Info,
        filters: filters.ROIFilter | None = strawberry.UNSET,
    ) -> List["ROI"]:
        qs = self.events.all()

        # apply filters if defined
        if filters is not strawberry.UNSET:
            qs = strawberry_django.filters.apply(filters, qs, info)

        return qs


@strawberry_django.type(models.Dataset, filters=filters.DatasetFilter, ordering=filters.DatasetOrder, pagination=True)
class Dataset:
    id: auto
    images: List["Trace"]
    files: List["File"]
    children: List["Dataset"]
    description: str | None
    name: str
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()
    is_default: bool
    created_at: datetime.datetime
    creator: User | None

    @strawberry_django.field()
    def pinned(self, info: Info) -> bool:
        return cast(models.Dataset, self).pinned_by.filter(id=info.context.request.user.id).exists()

    @strawberry_django.field()
    def tags(self, info: Info) -> list[str]:
        return cast(models.Image, self).tags.slugs()


class Slice:
    min: int
    max: int


def min_max_to_accessor(min, max):
    if min is None:
        min = ""
    if max is None:
        max = ""
    return f"{min}:{max}"


@strawberry_django.interface(models.View)
class View:
    """A view is a subset of an image."""

    image: "Trace"
    z_min: int | None = None
    z_max: int | None = None
    x_min: int | None = None
    x_max: int | None = None
    y_min: int | None = None
    y_max: int | None = None
    t_min: int | None = None
    t_max: int | None = None
    c_min: int | None = None
    c_max: int | None = None
    is_global: bool

    @strawberry_django.field(description="The accessor")
    def accessor(self) -> List[str]:
        z_accessor = min_max_to_accessor(self.z_min, self.z_max)
        t_accessor = min_max_to_accessor(self.t_min, self.t_max)
        c_accessor = min_max_to_accessor(self.c_min, self.c_max)
        x_accessor = min_max_to_accessor(self.x_min, self.x_max)
        y_accessor = min_max_to_accessor(self.y_min, self.y_max)

        return [c_accessor, t_accessor, z_accessor, x_accessor, y_accessor]


@strawberry_django.type(models.TimelineView)
class TimelineView(View):
    """A label view.

    Label views are used to give a label to a specific image channel. For example, you can
    create a label view that maps an antibody to a specific image channel. This will allow
    you to easily identify the labeling agent in the image. However, label views can be used
    for other purposes as well. For example, you can use a label to mark a specific channel
    to be of poor quality. (e.g. "bad channel").

    """

    id: auto
    trace: Trace

    @strawberry_django.field()
    def label(self, info: Info) -> str:
        return self.label or "No Label"


@strawberry_django.type(models.ROI, filters=filters.ROIFilter, ordering=filters.ROIOrder, pagination=True)
class ROI:
    """A region of interest."""

    id: auto
    trace: "Trace"
    kind: enums.RoiKind
    vectors: list[scalars.FiveDVector]
    created_at: datetime.datetime
    creator: User | None
    provenance_entries: List["ProvenanceEntry"] = strawberry_django.field()

    @strawberry_django.field()
    def pinned(self, info: Info) -> bool:
        return self.pinned_by.filter(id=info.context.request.user.id).exists()

    @strawberry_django.field()
    def name(self, info: Info) -> str:
        return self.kind

    @strawberry_django.field()
    def label(self, info: Info) -> str | None:
        return self.label
