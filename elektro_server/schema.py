from kante.types import Info
from typing import AsyncGenerator
import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension

from core.datalayer import DatalayerExtension
from core.channel import image_listen
from strawberry import ID as StrawberryID
from kante.directives import upper, replace, relation
from strawberry.permission import BasePermission
from typing import Any, Type
from core import types, models
from core import mutations
from core import queries
from core import subscriptions
from strawberry.field_extensions import InputMutationExtension
import strawberry_django
from koherent.strawberry.extension import KoherentExtension
from authentikate.strawberry.permissions import IsAuthenticated, NeedsScopes, HasScopes
from core.render.objects import types as render_types
from core.duck import DuckExtension
from typing import Annotated



ID = Annotated[StrawberryID, strawberry.argument(description="The unique identifier of an object")]

@strawberry.type
class Query:
    images: list[types.Image] = strawberry.django.field(extensions=[])
    rois: list[types.ROI] = strawberry_django.field()
    myimages: list[types.Image] = strawberry.django.field(extensions=[])
    datasets: list[types.Dataset] = strawberry_django.field()
    mydatasets: list[types.Dataset] = strawberry_django.field()
    timepoint_views: list[types.TimepointView] = strawberry_django.field()
    label_views: list[types.LabelView] = strawberry_django.field()
    channel_views: list[types.ChannelView] = strawberry_django.field()
    continous_scan_views: list[types.ContinousScanView] = strawberry_django.field()
    well_position_views: list[types.WellPositionView] = strawberry_django.field()
    acquisition_views: list[types.AcquisitionView] = strawberry_django.field()
    rgb_views: list[types.RGBView] = strawberry_django.field()
    affine_transformation_views: list[
        types.AffineTransformationView
    ] = strawberry_django.field()
    scale_views: list[types.ScaleView] = strawberry_django.field()
    eras: list[types.Era] = strawberry_django.field()
    myeras: list[types.Era] = strawberry_django.field()

    rendered_plots: list[types.RenderedPlot] = strawberry_django.field()

    stages: list[types.Stage] = strawberry_django.field()
    render_trees: list[types.RenderTree] = strawberry_django.field()

    experiments: list[types.Experiment] = strawberry_django.field()


    channels: list[types.Channel] = strawberry_django.field()
    rgbcontexts: list[types.RGBContext] = strawberry_django.field()
    mychannels: list[types.Channel] = strawberry_django.field()
    instruments: list[types.Instrument] = strawberry_django.field()
    instruments: list[types.Instrument] = strawberry_django.field()
    multi_well_plates: list[types.MultiWellPlate] = strawberry_django.field()
    objectives: list[types.Objective] = strawberry_django.field()
    myobjectives: list[types.Objective] = strawberry_django.field()
    specimen_views: list[types.StructureView] = strawberry_django.field()

    children = strawberry_django.field(resolver=queries.children)
    rows = strawberry_django.field(resolver=queries.rows)


    tables: list[types.Table] = strawberry_django.field()
    mytables: list[types.Table] = strawberry_django.field()

    snapshots: list[types.Snapshot] = strawberry_django.field()
    mysnapshots: list[types.Snapshot] = strawberry_django.field()

    files: list[types.File] = strawberry_django.field()
    myfiles: list[types.File] = strawberry_django.field()
    random_image: types.Image = strawberry_django.field(resolver=queries.random_image)




    ## Accessors for tables
    label_accessors: list[types.LabelAccessor] = strawberry_django.field()
    image_accessors: list[types.ImageAccessor] = strawberry_django.field()


    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def pixel_view(self, info: Info, id: ID) -> types.PixelView:
        print(id)
        return models.PixelView.objects.get(id=id)
    

    @strawberry.django.field(
        permission_classes=[IsAuthenticated],
        description="Returns a single image by ID"
    )
    def image(self, info: Info, id: ID) -> types.Image:
        print(id)
        return models.Image.objects.get(id=id)
    
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def roi(self, info: Info, id: ID) -> types.ROI:
        print(id)
        return models.ROI.objects.get(id=id)
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def render_tree(self, info: Info, id: ID) -> types.RenderTree:
        print(id)
        return models.RenderTree.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def rgbcontext(self, info: Info, id: ID) -> types.RGBContext:
        print(id)
        return models.RGBRenderContext.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def objective(self, info: Info, id: ID) -> types.Objective:
        print(id)
        return models.Objective.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def camera(self, info: Info, id: ID) -> types.Camera:
        print(id)
        return models.Camera.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def snapshot(self, info: Info, id: ID) -> types.Snapshot:
        print(id)
        return models.Snapshot.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def file(self, info: Info, id: ID) -> types.File:
        print(id)
        return models.File.objects.get(id=id)

    @strawberry_django.field(
        permission_classes=[]
    )
    def table(self, info: Info, id: ID) -> types.Table:
        print(id)
        return models.Table.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def instrument(self, info: Info, id: ID) -> types.Instrument:
        print(id)
        return models.Instrument.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def dataset(self, info: Info, id: ID) -> types.Dataset:
        return models.Dataset.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def multi_well_plate(self, info: Info, id: ID) -> types.MultiWellPlate:
        return models.MultiWellPlate.objects.get(id=id)

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def stage(self, info: Info, id: ID) -> types.Stage:
        return models.Stage.objects.get(id=id)
    
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def rendered_plot(self, info: Info, id: ID) -> types.RenderedPlot:
        return models.RenderedPlot.objects.get(id=id)
    
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def experiment(self, info: Info, id: ID) -> types.Experiment:
        return models.Experiment.objects.get(id=id)
    

@strawberry.type
class Mutation:
    # Relation
    relate_to_dataset: types.Image = strawberry_django.mutation(
        extensions=[InputMutationExtension()], 
        resolver=mutations.relate_to_dataset,
        description="Relate an image to a dataset"
    )

    # Image
    request_upload: types.Credentials = strawberry_django.mutation(
        resolver=mutations.request_upload,
        description="Request credentials to upload a new image"
    )
    request_access: types.AccessCredentials = strawberry_django.mutation(
        resolver=mutations.request_access,
        description="Request credentials to access an image",
    )
    from_array_like = strawberry_django.mutation(
        resolver=mutations.from_array_like,
        description="Create an image from array-like data"
    )
    pin_image = strawberry_django.mutation(
        resolver=mutations.pin_image,
        description="Pin an image for quick access"
    )
    update_image = strawberry_django.mutation(
        resolver=mutations.update_image,
        description="Update an existing image's metadata"
    )
    delete_image = strawberry_django.mutation(
        resolver=mutations.delete_image,
        description="Delete an existing image"
    )

    create_render_tree = strawberry_django.mutation(
        resolver=mutations.create_render_tree,
        description="Create a new render tree for image visualization"
    )

    request_media_upload: types.PresignedPostCredentials = strawberry_django.mutation(
        resolver=mutations.request_media_upload,
        description="Request credentials for media file upload"
    )

    request_table_upload: types.Credentials = strawberry_django.mutation(
        resolver=mutations.request_table_upload,
        description="Request credentials to upload a new table"
    )
    request_table_access: types.AccessCredentials = strawberry_django.mutation(
        resolver=mutations.request_table_access,
        description="Request credentials to access a table"
    )
    from_parquet_like = strawberry_django.mutation(
        resolver=mutations.from_parquet_like,
        description="Create a table from parquet-like data"
    )

    request_file_upload: types.Credentials = strawberry_django.mutation(
        resolver=mutations.request_file_upload,
        description="Request credentials to upload a new file"
    )
    request_file_upload_presigned: types.PresignedPostCredentials = strawberry_django.mutation(
        resolver=mutations.request_file_upload_presigned,
        description="Request presigned credentials for file upload"
    )
    request_file_access: types.AccessCredentials = strawberry_django.mutation(
        resolver=mutations.request_file_access,
        description="Request credentials to access a file"
    )
    from_file_like = strawberry_django.mutation(
        resolver=mutations.from_file_like,
        description="Create a file from file-like data"
    )
    delete_file = strawberry_django.mutation(
        resolver=mutations.delete_file,
        description="Delete an existing file"
    )

    # Rendered Plot
    create_rendered_plot = strawberry_django.mutation(
        resolver=mutations.create_rendered_plot,
        description="Create a new rendered plot" 
    )

    # Channel
    create_channel = strawberry_django.mutation(
        resolver=mutations.create_channel,
        description="Create a new channel"
    )
    pin_channel = strawberry_django.mutation(
        resolver=mutations.pin_channel,
        description="Pin a channel for quick access"
    )
    ensure_channel = strawberry_django.mutation(
        resolver=mutations.ensure_channel,
        description="Ensure a channel exists, creating if needed"
    )
    delete_channel = strawberry_django.mutation(
        resolver=mutations.delete_channel,
        description="Delete an existing channel"
    )


    # Stage
    create_stage = strawberry_django.mutation(
        resolver=mutations.create_stage,
        description="Create a new stage for organizing data"
    )
    pin_stage = strawberry_django.mutation(
        resolver=mutations.pin_stage,
        description="Pin a stage for quick access"
    )
    delete_stage = strawberry_django.mutation(
        resolver=mutations.delete_stage,
        description="Delete an existing stage"
    )


     # RGBContext
    create_rgb_context = strawberry_django.mutation(
        resolver=mutations.create_rgb_context,
        description="Create a new RGB context for image visualization"
    )
    delete_rgb_context = strawberry_django.mutation(
        resolver=mutations.delete_rgb_context,
        description="Delete an existing RGB context"
    )
    update_rgb_context = strawberry_django.mutation(
        resolver=mutations.update_rgb_context,
        description="Update settings of an existing RGB context" 
    )

    # Dataset
    create_dataset = strawberry_django.mutation(
        resolver=mutations.create_dataset,
        description="Create a new dataset to organize data"
    )
    update_dataset = strawberry_django.mutation(
        resolver=mutations.update_dataset,
        description="Update dataset metadata"
    )
    revert_dataset = strawberry_django.mutation(
        resolver=mutations.revert_dataset,
        description="Revert dataset to a previous version"
    )
    pin_dataset = strawberry_django.mutation(
        resolver=mutations.pin_dataset,
        description="Pin a dataset for quick access"
    )
    delete_dataset = strawberry_django.mutation(
        resolver=mutations.delete_dataset,
        description="Delete an existing dataset"
    )
    put_datasets_in_dataset = strawberry_django.mutation(
        resolver=mutations.put_datasets_in_dataset,
        description="Add datasets as children of another dataset"
    )
    release_datasets_from_dataset = strawberry_django.mutation(
        resolver=mutations.release_datasets_from_dataset,
        description="Remove datasets from being children of another dataset"
    )
    put_images_in_dataset = strawberry_django.mutation(
        resolver=mutations.put_images_in_dataset,
        description="Add images to a dataset"
    )
    release_images_from_dataset = strawberry_django.mutation(
        resolver=mutations.release_images_from_dataset,
        description="Remove images from a dataset"
    )
    put_files_in_dataset = strawberry_django.mutation(
        resolver=mutations.put_files_in_dataset,
        description="Add files to a dataset"
    )
    release_files_from_dataset = strawberry_django.mutation(
        resolver=mutations.release_files_from_dataset,
        description="Remove files from a dataset"
    )

  

    # MultiWellPlate

    create_multi_well_plate = strawberry_django.mutation(
        resolver=mutations.create_multi_well_plate,
        description="Create a new multi-well plate configuration"
    )
    ensure_multi_well_plate = strawberry_django.mutation(
        resolver=mutations.ensure_multi_well_plate,
        description="Ensure a multi-well plate exists, creating if needed"
    )
    pin_multi_well_plate = strawberry_django.mutation(
        resolver=mutations.pin_multi_well_plate,
        description="Pin a multi-well plate for quick access"
    )
    delete_multi_well_plate = strawberry_django.mutation(
        resolver=mutations.delete_multi_well_plate,
        description="Delete an existing multi-well plate configuration"
    )

    # View Collection
    create_view_collection = strawberry_django.mutation(
        resolver=mutations.create_view_collection,
        description="Create a new collection of views to organize related views"
    )
    pin_view_collection = strawberry_django.mutation(
        resolver=mutations.pin_view_collection,
        description="Pin a view collection for quick access"
    )
    delete_view_collection = strawberry_django.mutation(
        resolver=mutations.delete_view_collection,
        description="Delete an existing view collection"
    )

    # Era
    create_era = strawberry_django.mutation(
        resolver=mutations.create_era,
        description="Create a new era for temporal organization"
    )
    pin_era = strawberry_django.mutation(
        resolver=mutations.pin_era,
        description="Pin an era for quick access"
    )
    delete_era = strawberry_django.mutation(
        resolver=mutations.delete_era,
        description="Delete an existing era"
    )

    # Views
    create_label_view = strawberry_django.mutation(
        resolver=mutations.create_label_view,
        description="Create a new view for label data"
    )
    create_timepoint_view = strawberry_django.mutation(
        resolver=mutations.create_timepoint_view,
        description="Create a new view for temporal data"
    )
    create_file_view = strawberry_django.mutation(
        resolver=mutations.create_file_view,
        description="Create a new view for file data"
    )
    create_roi_view = strawberry_django.mutation(
        resolver=mutations.create_roi_view,
        description="Create a new view for region of interest data"
    )
    create_optics_view = strawberry_django.mutation(
        resolver=mutations.create_optics_view,
        description="Create a new view for optical settings"
    )
    create_rgb_view = strawberry_django.mutation(
        resolver=mutations.create_rgb_view,
        description="Create a new view for RGB image data"
    )
    create_channel_view = strawberry_django.mutation(
        resolver=mutations.create_channel_view,
        description="Create a new view for channel data"
    )
    create_structure_view = strawberry_django.mutation(
        resolver=mutations.create_structure_view,
        description="Create a new view for structural data"
    )
    create_well_position_view = strawberry_django.mutation(
        resolver=mutations.create_well_position_view,
        description="Create a new view for well position data"
    )
    create_continous_scan_view = strawberry_django.mutation(
        resolver=mutations.create_continous_scan_view,
        description="Create a new view for continuous scan data"
    )
    create_affine_transformation_view: types.AffineTransformationView = (
        strawberry_django.mutation(
            resolver=mutations.create_affine_transformation_view,
            description="Create a new view for affine transformation data"
        )
    )
    delete_affine_transformation_view = strawberry_django.mutation(
        resolver=mutations.delete_affine_transformation_view,
        description="Delete an existing affine transformation view"
    )
    delete_channel_view = strawberry_django.mutation(
        resolver=mutations.delete_channel_view,
        description="Delete an existing channel view"
    )
    delete_timepoint_view = strawberry_django.mutation(
        resolver=mutations.delete_timepoint_view,
        description="Delete an existing timepoint view"
    )
    delete_optics_view = strawberry_django.mutation(
        resolver=mutations.delete_optics_view,
        description="Delete an existing optics view"
    )
    delete_rgb_view = strawberry_django.mutation(
        resolver=mutations.delete_rgb_view,
        description="Delete an existing RGB view"
    )

    delete_view = strawberry_django.mutation(
        resolver=mutations.delete_view,
        description="Delete any type of view"
    )
    pin_view = strawberry_django.mutation(
        resolver=mutations.pin_view,
        description="Pin a view for quick access"
    )

    # Instrument
    create_instrument = strawberry_django.mutation(
        resolver=mutations.create_instrument,
        description="Create a new instrument configuration"
    )
    delete_instrument = strawberry_django.mutation(
        resolver=mutations.delete_instrument,
        description="Delete an existing instrument"
    )
    pin_instrument = strawberry_django.mutation(
        resolver=mutations.pin_instrument,
        description="Pin an instrument for quick access"
    )
    ensure_instrument = strawberry_django.mutation(
        resolver=mutations.ensure_instrument,
        description="Ensure an instrument exists, creating if needed"
    )

    # Objective
    create_objective = strawberry_django.mutation(
        resolver=mutations.create_objective,
        description="Create a new microscope objective configuration"
    )
    delete_objective = strawberry_django.mutation(
        resolver=mutations.delete_objective,
        description="Delete an existing objective"
    )
    pin_objective = strawberry_django.mutation(
        resolver=mutations.pin_objective,
        description="Pin an objective for quick access"
    )
    ensure_objective = strawberry_django.mutation(
        resolver=mutations.ensure_objective,
        description="Ensure an objective exists, creating if needed"
    )

    # Camera
    create_camera = strawberry_django.mutation(
        resolver=mutations.create_camera,
        description="Create a new camera configuration"
    )
    delete_camera = strawberry_django.mutation(
        resolver=mutations.delete_camera,
        description="Delete an existing camera"
    )
    pin_camera = strawberry_django.mutation(
        resolver=mutations.pin_camera,
        description="Pin a camera for quick access"
    )
    ensure_camera = strawberry_django.mutation(
        resolver=mutations.ensure_camera,
        description="Ensure a camera exists, creating if needed"
    )

    # Snapshot
    create_snapshot = strawberry_django.mutation(
        resolver=mutations.create_snapshot,
        description="Create a new state snapshot"
    )
    delete_snapshot = strawberry_django.mutation(
        resolver=mutations.delete_snapshot,
        description="Delete an existing snapshot"
    )
    pin_snapshot = strawberry_django.mutation(
        resolver=mutations.pin_snapshot,
        description="Pin a snapshot for quick access"
    )

    # ROI
    create_roi = strawberry_django.mutation(
        resolver=mutations.create_roi,
        description="Create a new region of interest"
    )
    update_roi = strawberry_django.mutation(
        resolver=mutations.update_roi,
        description="Update an existing region of interest"
    )
    pin_roi = strawberry_django.mutation(
        resolver=mutations.pin_roi,
        description="Pin a region of interest for quick access"
    )
    delete_roi = strawberry_django.mutation(
        resolver=mutations.delete_roi,
        description="Delete an existing region of interest"
    )


@strawberry.type
class ChatRoomMessage:
    room_name: str
    current_user: str
    message: str


@strawberry.type
class Subscription:
    @strawberry.subscription(description="Subscribe to real-time image history events")
    async def history_events(
        self,
        info: Info,
    ) -> AsyncGenerator[types.Image, None]:
        """Join and subscribe to message sent to the given rooms."""
        async for message in image_listen(info):
            yield await models.Image.objects.aget(id=message)


    rois = strawberry.subscription(
        resolver=subscriptions.rois,
        description="Subscribe to real-time ROI updates"
    )
    images = strawberry.subscription(
        resolver=subscriptions.images,
        description="Subscribe to real-time image updates"
    )
    files = strawberry.subscription(
        resolver=subscriptions.files,
        description="Subscribe to real-time file updates"
    )
    


schema = strawberry.Schema(
    query=Query,
    subscription=Subscription,
    mutation=Mutation,
    directives=[upper, replace, relation],
    extensions=[
        DjangoOptimizerExtension,
        KoherentExtension,
        DatalayerExtension,
        DuckExtension,
    ],
    types=[
        types.RenderNode,
        types.ContextNode,
        types.OverlayNode,
        types.GridNode,
        types.SplitNode,
    ]
)
