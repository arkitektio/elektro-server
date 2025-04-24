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
from core.base_models.type.graphql.model import SynapticConnection, Exp2Synapse



ID = Annotated[StrawberryID, strawberry.argument(description="The unique identifier of an object")]

@strawberry.type
class Query:
    traces: list[types.Trace] = strawberry.django.field(extensions=[])
    rois: list[types.ROI] = strawberry_django.field()
    datasets: list[types.Dataset] = strawberry_django.field()
    mydatasets: list[types.Dataset] = strawberry_django.field()
    experiments: list[types.Experiment] = strawberry_django.field()
    neuron_models: list[types.NeuronModel] = strawberry_django.field()
    model_collections: list[types.ModelCollection] = strawberry_django.field()

    files: list[types.File] = strawberry_django.field()
    simulations: list[types.Simulation] = strawberry_django.field()
    myfiles: list[types.File] = strawberry_django.field()
    random_trace: types.Trace = strawberry_django.field(resolver=queries.random_trace)
    
    @strawberry.django.field()
    def experiment(self, info: Info, id: ID) -> types.Experiment:
        """Get all experiments"""
        return models.Experiment.objects.get(id=id)
    
    @strawberry.django.field()
    def model_collection(self, info: Info, id: ID) -> types.ModelCollection:
        """Get all model collections"""
        return models.ModelCollection.objects.get(id=id)

    @strawberry.django.field()
    def simulation(self, info: Info, id: ID) -> types.Simulation:
        """Get all simulations"""
        return models.Simulation.objects.get(id=id)

    @strawberry.django.field()
    def neuron_model(self, info: Info, id: ID) -> types.NeuronModel:
        """Get all simulations"""
        return models.NeuronModel.objects.get(id=id)


    @strawberry.django.field(
        permission_classes=[IsAuthenticated],
        description="Returns a single image by ID"
    )
    def trace(self, info: Info, id: ID) -> types.Trace:
        print(id)
        return models.Trace.objects.get(id=id)
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated],
        description="Returns a single image by ID"
    )
    def neuron_model(self, info: Info, id: ID) -> types.NeuronModel:
        print(id)
        return models.NeuronModel.objects.get(id=id)
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def roi(self, info: Info, id: ID) -> types.ROI:
        print(id)
        return models.ROI.objects.get(id=id)
    
   

    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def file(self, info: Info, id: ID) -> types.File:
        print(id)
        return models.File.objects.get(id=id)

    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def dataset(self, info: Info, id: ID) -> types.Dataset:
        return models.Dataset.objects.get(id=id)

    

@strawberry.type
class Mutation:

    # Image
    request_upload: types.Credentials = strawberry_django.mutation(
        resolver=mutations.request_upload,
        description="Request credentials to upload a new image"
    )
    request_access: types.AccessCredentials = strawberry_django.mutation(
        resolver=mutations.request_access,
        description="Request credentials to access an image",
    )
    from_trace_like = strawberry_django.mutation(
        resolver=mutations.from_trace_like,
        description="Create an image from array-like data"
    )
    pin_image = strawberry_django.mutation(
        resolver=mutations.pin_trace,
        description="Pin an image for quick access"
    )
    update_image = strawberry_django.mutation(
        resolver=mutations.update_trace,
        description="Update an existing image's metadata"
    )
    delete_image = strawberry_django.mutation(
        resolver=mutations.delete_trace,
        description="Delete an existing image"
    )
    
    create_neuron_model = strawberry_django.mutation(
        resolver=mutations.create_neuron_model,
        description="Create a new neuron model"
    )
    create_simulation = strawberry_django.mutation(
        resolver=mutations.create_simulation,
        description="Create a new simulsation"
    )


    request_media_upload: types.PresignedPostCredentials = strawberry_django.mutation(
        resolver=mutations.request_media_upload,
        description="Request credentials for media file upload"
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
    
    # Experiment
    create_experiment = strawberry_django.mutation(
        resolver=mutations.create_experiment,
        description="Create a new experiment"
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
class Subscription:
    @strawberry.subscription(description="Subscribe to real-time image history events")
    async def history_events(
        self,
        info: Info,
    ) -> AsyncGenerator[types.Trace, None]:
        """Join and subscribe to message sent to the given rooms."""
        async for message in image_listen(info):
            yield await models.Trace.objects.aget(id=message)


    rois = strawberry.subscription(
        resolver=subscriptions.rois,
        description="Subscribe to real-time ROI updates"
    )
    traces = strawberry.subscription(
        resolver=subscriptions.traces,
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
        SynapticConnection,
        Exp2Synapse
    ]
)
