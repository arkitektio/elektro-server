from core.base_models.type.model import ModelConfigModel
from pydantic import BaseModel
import strawberry
import strawberry.django
from strawberry import auto
from typing import List, Optional, Annotated, Union, cast
import strawberry_django
from core import models, scalars, filters, enums
from django.contrib.auth import get_user_model
from koherent.models import AppHistoryModel
from authentikate.models import App as AppModel
from kante.types import Info
import datetime
from asgiref.sync import sync_to_async
from itertools import chain
from enum import Enum
from core.datalayer import get_current_datalayer
from core.render.objects import models as rmodels
from strawberry.experimental import pydantic
from typing import Union
from strawberry import LazyType
from core.duck import get_current_duck
from core.base_models.type.graphql.cell import Cell
from core.base_models.type.graphql.model import ModelConfig



@strawberry_django.type(AppModel, description="An app.")
class App:
    id: auto
    name: str
    client_id: str

@strawberry_django.type(get_user_model(), description="A user.")
class User:
    id: auto
    sub: str
    username: str
    email: str
    password: str


@strawberry.type(description="Temporary Credentials for a file upload that can be used by a Client (e.g. in a python datalayer)")
class Credentials:
    """Temporary Credentials for a a file upload."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    datalayer: str
    bucket: str
    key: str
    store: str

@strawberry.type(description="Temporary Credentials for a file upload that can be used by a Client (e.g. in a python datalayer)")
class PresignedPostCredentials:
    """Temporary Credentials for a a file upload."""
    key: str
    x_amz_algorithm: str
    x_amz_credential: str
    x_amz_date: str
    x_amz_signature: str
    policy: str
    datalayer: str
    bucket: str
    store: str



@strawberry.type(description="Temporary Credentials for a file download that can be used by a Client (e.g. in a python datalayer)")
class AccessCredentials:
    """Temporary Credentials for a a file upload."""

    access_key: str
    secret_key: str
    session_token: str
    bucket: str
    key: str
    path: str


@strawberry_django.type(
    models.ViewCollection,
    filters=filters.TraceFilter,
    order=filters.TraceOrder,
    pagination=True,
)
class ViewCollection:
    """ A colletion of views.
    
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
    history: List["History"]


@strawberry.enum
class ViewKind(str, Enum):
    """The kind of view.
    
    Views can be of different kinds. For example, a view can be a label view
    that will map a labeleling agent (e.g. an antibody) to a specific image channel.
    
    Depending on the kind of view, different fields will be available.
    
    """

    TIMEPOINT = "timepoint_views"



@strawberry_django.type(models.ZarrStore)
class ZarrStore:
    """Zarr Store.
    
    A ZarrStore is a store that contains a Zarr dataset on a connected
    S3 compatible storage backend. The store will contain the path to the
    dataset in the corresponding bucket.

    Importantly to retrieve the data, you will need to ask this API for 
    temporary credentials to access the data. This is an additional step
    and is required to ensure that the data is only accessible to authorized
    users.
    
    """


    id: auto
    path: str | None = strawberry.field(description="The path to the data. Relative to the bucket.")
    shape: List[int] | None = strawberry.field(description="The shape of the data.")
    dtype: str | None = strawberry.field(description="The dtype of the data.")
    bucket: str = strawberry.field(description="The bucket where the data is stored.")
    key: str = strawberry.field(description="The key where the data is stored.")
    chunks: List[int] | None = strawberry.field(description="The chunks of the data.")
    populated: bool = strawberry.field(description="Whether the zarr store was populated (e.g. was a dataset created).")


@strawberry_django.type(models.ParquetStore)
class ParquetStore:
    id: auto
    path: str
    bucket: str
    key: str



@strawberry.django.type(models.BigFileStore)
class BigFileStore:
    id: auto
    path: str
    bucket: str
    key: str

    @strawberry.field()
    def presigned_url(self, info: Info) -> str:
        datalayer = get_current_datalayer()
        return cast(models.BigFileStore, self).get_presigned_url(info, datalayer=datalayer)


@strawberry_django.type(models.MediaStore)
class MediaStore:
    id: auto
    path: str
    bucket: str
    key: str

    @strawberry_django.field()
    def presigned_url(self, info: Info, host: str | None = None) -> str:
        datalayer = get_current_datalayer()
        return cast(models.MediaStore, self).get_presigned_url(info, datalayer=datalayer, host=host)


@strawberry_django.type(models.File, filters=filters.FileFilter, pagination=True)
class File:
    id: auto
    name: auto
    origins: List["Trace"] = strawberry.django.field()
    store: BigFileStore
   
   
@strawberry_django.type(models.ModelCollection, filters=filters.ModelCollectionFilter, pagination=True)
class ModelCollection:
    id: auto
    name: str
    models: List["NeuronModel"] = strawberry.django.field()
    description: str | None
   
 
    
@strawberry_django.type(models.NeuronModel,  filters=filters.NeuronModelFilter, pagination=True)
class NeuronModel:
    id: auto
    name: auto
    description: str | None
    creator: User | None
    collection: ModelCollection | None
    
    @strawberry.django.field()
    def config(self, info: Info) -> "ModelConfig":
        return ModelConfigModel(**self.json_model)
    

    
    
@strawberry_django.type(models.Experiment, filters=filters.ExperimentFilter, pagination=True)
class Experiment:
    id: auto
    name: str
    description: str | None
    views: List["ExperimentView"]
    
@strawberry_django.type(models.Simulation, filters=filters.SimulationFilter, pagination=True)
class Simulation:
    id: auto
    name: str
    description: str | None
    kind: enums.StimulusKind
    creator: User | None
    model: NeuronModel
    duration: int = 400
    time_trace: "Trace"
    stimuli: List["Stimulus"] = strawberry.django.field()
    recordings: List["Recording"] = strawberry.django.field()


@strawberry_django.type(models.Recording)
class Recording:
    id: auto
    simulation: Simulation
    kind: enums.RecordingKind
    trace: "Trace"
    location: str
    position: str 
    cell: str
    
    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return self.label or f"{self.cell}: {self.location}({self.position})"


      
    
@strawberry_django.type(models.Stimulus)
class Stimulus:
    id: auto
    simulation: Simulation
    kind: enums.StimulusKind
    trace: "Trace"
    location: str
    position: str 
    cell: str
    
    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return self.label or f"{self.cell}: {self.location}({self.position})"


@strawberry_django.type(models.ExperimentView, filters=filters.ExperimentFilter, pagination=True)
class ExperimentView:
    id: auto
    stimulus: Stimulus | None
    recording: Recording | None
    label: str | None
    offset: float | None
    duration: float | None
    
    

    
    

@strawberry_django.type(
    models.Trace, filters=filters.TraceFilter, order=filters.TraceOrder, pagination=True
)
class Trace:
    """ An image.
    
    
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
    store: ZarrStore = strawberry_django.field(description="The store where the image data is stored.")
    dataset: Optional["Dataset"] = strawberry_django.field(description="The dataset this image belongs to")
    history: List["History"] = strawberry_django.field(description="History of changes to this image")
    creator: User | None = strawberry_django.field(description="Who created this image")




    @strawberry.django.field(description="Is this image pinned by the current user")
    def pinned(self, info: Info) -> bool:
        return (
            cast(models.Image, self)
            .pinned_by.filter(id=info.context.request.user.id)
            .exists()
        )

    @strawberry.django.field(description="The tags of this image")
    def tags(self, info: Info) -> list[str]:
        return cast(models.Image, self).tags.slugs()


    @strawberry.django.field()
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


@strawberry_django.type(models.Dataset, filters=filters.DatasetFilter, pagination=True)
class Dataset:
    id: auto
    images: List["Trace"]
    files: List["File"]
    children: List["Dataset"]
    description: str | None
    name: str
    history: List["History"]
    is_default: bool
    created_at: datetime.datetime
    creator: User | None

    @strawberry.django.field()
    def pinned(self, info: Info) -> bool:
        return (
            cast(models.Dataset, self)
            .pinned_by.filter(id=info.context.request.user.id)
            .exists()
        )

    @strawberry.django.field()
    def tags(self, info: Info) -> list[str]:
        return cast(models.Image, self).tags.slugs()



@strawberry.enum
class HistoryKind(str, Enum):
    CREATE = "+"
    UPDATE = "~"
    DELETE = "-"


@strawberry.type()
class ModelChange:
    field: str
    old_value: str | None
    new_value: str | None


@strawberry_django.type(AppHistoryModel, pagination=True)
class History:
    app: App | None

    @strawberry.django.field()
    def user(self, info: Info) -> User | None:
        return self.history_user

    @strawberry.django.field()
    def kind(self, info: Info) -> HistoryKind:
        return self.history_type

    @strawberry.django.field()
    def date(self, info: Info) -> datetime.datetime:
        return self.history_date

    @strawberry.django.field()
    def during(self, info: Info) -> str | None:
        return self.assignation_id

    @strawberry.django.field()
    def id(self, info: Info) -> strawberry.ID:
        return self.history_id

    @strawberry.django.field()
    def effective_changes(self, info: Info) -> list[ModelChange]:
        new_record, old_record = self, self.prev_record

        changes = []
        if old_record is None:
            return changes

        delta = new_record.diff_against(old_record)
        for change in delta.changes:
            changes.append(
                ModelChange(
                    field=change.field, old_value=change.old, new_value=change.new
                )
            )

        return changes


OtherItem = Annotated[Union[Dataset, Trace], strawberry.union("OtherItem")]



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

    image: "Image"
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

    @strawberry.django.field(description="The accessor")
    def accessor(self) -> List[str]:
        z_accessor = min_max_to_accessor(self.z_min, self.z_max)
        t_accessor = min_max_to_accessor(self.t_min, self.t_max)
        c_accessor = min_max_to_accessor(self.c_min, self.c_max)
        x_accessor = min_max_to_accessor(self.x_min, self.x_max)
        y_accessor = min_max_to_accessor(self.y_min, self.y_max)

        return [c_accessor, t_accessor, z_accessor, x_accessor, y_accessor]
    



@strawberry_django.type(models.TimelineView)
class TimelineView(View):
    """ A label view.
    
    Label views are used to give a label to a specific image channel. For example, you can
    create a label view that maps an antibody to a specific image channel. This will allow
    you to easily identify the labeling agent in the image. However, label views can be used
    for other purposes as well. For example, you can use a label to mark a specific channel
    to be of poor quality. (e.g. "bad channel").
    
    """
    id: auto
    trace: Trace

    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return self.label or "No Label"





@strawberry_django.type(models.ROI, filters=filters.ROIFilter, pagination=True)
class ROI:
    """ A region of interest."""
    id: auto
    trace: "Trace"
    kind: enums.RoiKind
    vectors: list[scalars.FiveDVector]
    created_at: datetime.datetime
    creator: User | None
    history: List["History"]

    @strawberry.django.field()
    def pinned(self, info: Info) -> bool:
        return (
            self
            .pinned_by.filter(id=info.context.request.user.id)
            .exists()
        )
    
    
    @strawberry.django.field()
    def name(self, info: Info) -> str:
        return self.kind
    



