from kante.types import Info
from typing import AsyncGenerator, List
import strawberry

from core.datalayer import DatalayerExtension
from strawberry import ID as StrawberryID
from typing import Any, Type
from core import types, models
from core import mutations
from core import queries
from core import subscriptions
import strawberry_django
from koherent.strawberry.extension import KoherentExtension
from core.render.objects import types as render_types
from core.duck import DuckExtension
from typing import Annotated
from core.base_models.type.graphql.model import SynapticConnection, Exp2Synapse
from core.base_models.type.graphql.model import ModelConfigModel
from core.base_models.type.graphql.topology import Section
from authentikate.strawberry.extension import AuthentikateExtension
from strawberry_django.optimizer import DjangoOptimizerExtension


ID = Annotated[StrawberryID, strawberry.argument(description="The unique identifier of an object")]


@strawberry.type
class Query:
    analog_signals: list[types.AnalogSignal] = strawberry_django.field()
    analog_signal_channels: list[types.AnalogSignalChannel] = strawberry_django.field()
    blocks: list[types.Block] = strawberry_django.field()
    traces: list[types.Trace] = strawberry_django.field(extensions=[])
    rois: list[types.ROI] = strawberry_django.field()
    datasets: list[types.Dataset] = strawberry_django.field()
    mydatasets: list[types.Dataset] = strawberry_django.field()
    experiments: list[types.Experiment] = strawberry_django.field()
    neuron_models: list[types.NeuronModel] = strawberry_django.field()
    model_collections: list[types.ModelCollection] = strawberry_django.field()
    recordings: list[types.Recording] = strawberry_django.field()
    stimuli: list[types.Stimulus] = strawberry_django.field()

    files: list[types.File] = strawberry_django.field()
    simulations: list[types.Simulation] = strawberry_django.field()
    myfiles: list[types.File] = strawberry_django.field()
    random_trace: types.Trace = strawberry_django.field(resolver=queries.random_trace)

    block_stats: types.BlockStats = strawberry_django.field(resolver=types.BlockStatsResolver)

    @strawberry_django.field(permission_classes=[], description="Returns a list of images")
    def stimulus(self, info: Info, id: ID) -> types.Stimulus:
        """Get all stimuli"""
        return models.Stimulus.objects.get(id=id)

    @strawberry_django.field(permission_classes=[], description="Returns a list of images")
    def analog_signal(self, info: Info, id: ID) -> types.AnalogSignal:
        """Get all stimuli"""
        return models.AnalogSignal.objects.get(id=id)

    @strawberry_django.field(permission_classes=[], description="Returns a list of images")
    def analog_signal_channel(self, info: Info, id: ID) -> types.AnalogSignalChannel:
        """Get all stimuli"""
        return models.AnalogSignalChannel.objects.get(id=id)

    @strawberry_django.field(permission_classes=[], description="Returns a list of cells in a model")
    def cells(self, info: Info, modelId: ID, ids: List[ID] | None = None, search: str | None = None) -> list[types.Cell]:
        model = models.NeuronModel.objects.get(id=modelId)
        l = ModelConfigModel(**model.json_model)

        if search:
            return [cell for cell in l.cells if search in cell.id]
        if ids:
            return [cell for cell in l.cells if cell.id in ids]

        return l.cells

    @strawberry_django.field(permission_classes=[], description="Returns a list of images")
    def sections(self, info: Info, modelId: ID, cellId: ID, ids: List[ID] | None = None, search: str | None = None) -> List["Section"]:
        """Get all cells"""
        model = models.NeuronModel.objects.get(id=modelId)
        l = ModelConfigModel(**model.json_model)

        for cell in l.cells:
            if cell.id == cellId:
                if search:
                    return [section for section in cell.topology.sections if search in section.id]
                if ids:
                    return [section for section in cell.topology.sections if section.id in ids]

                return cell.topology.sections

        raise ValueError(f"Cell with ID {cellID} not found in model {modelId}")

    @strawberry_django.field(permission_classes=[], description="Returns a list of images")
    def recording(self, info: Info, id: ID) -> types.Recording:
        """Get all stimuli"""
        return models.Recording.objects.get(id=id)

    @strawberry_django.field()
    def block(self, info: Info, id: ID) -> types.Block:
        """Get all blocks"""
        return models.Block.objects.get(id=id)

    @strawberry_django.field()
    def experiment(self, info: Info, id: ID) -> types.Experiment:
        """Get all experiments"""
        return models.Experiment.objects.get(id=id)

    @strawberry_django.field()
    def model_collection(self, info: Info, id: ID) -> types.ModelCollection:
        """Get all model collections"""
        return models.ModelCollection.objects.get(id=id)

    @strawberry_django.field()
    def simulation(self, info: Info, id: ID) -> types.Simulation:
        """Get all simulations"""
        return models.Simulation.objects.get(id=id)

    @strawberry_django.field()
    def neuron_model(self, info: Info, id: ID) -> types.NeuronModel:
        """Get all simulations"""
        return models.NeuronModel.objects.get(id=id)

    @strawberry_django.field(permission_classes=[], description="Returns a single image by ID")
    def trace(self, info: Info, id: ID) -> types.Trace:
        print(id)
        return models.Trace.objects.get(id=id)

    @strawberry_django.field(permission_classes=[], description="Returns a single image by ID")
    def neuron_model(self, info: Info, id: ID) -> types.NeuronModel:
        print(id)
        return models.NeuronModel.objects.get(id=id)

    @strawberry_django.field(permission_classes=[])
    def roi(self, info: Info, id: ID) -> types.ROI:
        print(id)
        return models.ROI.objects.get(id=id)

    @strawberry_django.field(permission_classes=[])
    def file(self, info: Info, id: ID) -> types.File:
        print(id)
        return models.File.objects.get(id=id)

    @strawberry_django.field(permission_classes=[])
    def dataset(self, info: Info, id: ID) -> types.Dataset:
        return models.Dataset.objects.get(id=id)


@strawberry.type
class Mutation:
    create_block = strawberry_django.mutation(resolver=mutations.create_block, description="Create a new block")
    delete_block = strawberry_django.mutation(resolver=mutations.delete_block, description="Delete an existing block")

    # Image
    request_upload: types.Credentials = strawberry_django.mutation(resolver=mutations.request_upload, description="Request credentials to upload a new image")
    request_access: types.AccessCredentials = strawberry_django.mutation(
        resolver=mutations.request_access,
        description="Request credentials to access an image",
    )
    from_trace_like = strawberry_django.mutation(resolver=mutations.from_trace_like, description="Create an image from array-like data")
    pin_image = strawberry_django.mutation(resolver=mutations.pin_trace, description="Pin an image for quick access")
    update_image = strawberry_django.mutation(resolver=mutations.update_trace, description="Update an existing image's metadata")
    delete_image = strawberry_django.mutation(resolver=mutations.delete_trace, description="Delete an existing image")

    create_neuron_model = strawberry_django.mutation(resolver=mutations.create_neuron_model, description="Create a new neuron model")
    create_simulation = strawberry_django.mutation(resolver=mutations.create_simulation, description="Create a new simulsation")

    request_media_upload: types.PresignedPostCredentials = strawberry_django.mutation(resolver=mutations.request_media_upload, description="Request credentials for media file upload")

    request_file_upload: types.Credentials = strawberry_django.mutation(resolver=mutations.request_file_upload, description="Request credentials to upload a new file")
    request_file_upload_presigned: types.PresignedPostCredentials = strawberry_django.mutation(resolver=mutations.request_file_upload_presigned, description="Request presigned credentials for file upload")
    request_file_access: types.AccessCredentials = strawberry_django.mutation(resolver=mutations.request_file_access, description="Request credentials to access a file")
    from_file_like = strawberry_django.mutation(resolver=mutations.from_file_like, description="Create a file from file-like data")
    delete_file = strawberry_django.mutation(resolver=mutations.delete_file, description="Delete an existing file")

    create_model_collection = strawberry_django.mutation(resolver=mutations.create_model_collection, description="Create a new model collection")

    # Dataset
    create_dataset = strawberry_django.mutation(resolver=mutations.create_dataset, description="Create a new dataset to organize data")
    update_dataset = strawberry_django.mutation(resolver=mutations.update_dataset, description="Update dataset metadata")
    revert_dataset = strawberry_django.mutation(resolver=mutations.revert_dataset, description="Revert dataset to a previous version")
    pin_dataset = strawberry_django.mutation(resolver=mutations.pin_dataset, description="Pin a dataset for quick access")
    delete_dataset = strawberry_django.mutation(resolver=mutations.delete_dataset, description="Delete an existing dataset")
    put_datasets_in_dataset = strawberry_django.mutation(resolver=mutations.put_datasets_in_dataset, description="Add datasets as children of another dataset")
    release_datasets_from_dataset = strawberry_django.mutation(resolver=mutations.release_datasets_from_dataset, description="Remove datasets from being children of another dataset")
    put_images_in_dataset = strawberry_django.mutation(resolver=mutations.put_images_in_dataset, description="Add images to a dataset")
    release_images_from_dataset = strawberry_django.mutation(resolver=mutations.release_images_from_dataset, description="Remove images from a dataset")
    put_files_in_dataset = strawberry_django.mutation(resolver=mutations.put_files_in_dataset, description="Add files to a dataset")
    release_files_from_dataset = strawberry_django.mutation(resolver=mutations.release_files_from_dataset, description="Remove files from a dataset")

    # Experiment
    create_experiment = strawberry_django.mutation(resolver=mutations.create_experiment, description="Create a new experiment")

    # ROI
    create_roi = strawberry_django.mutation(resolver=mutations.create_roi, description="Create a new region of interest")
    update_roi = strawberry_django.mutation(resolver=mutations.update_roi, description="Update an existing region of interest")
    pin_roi = strawberry_django.mutation(resolver=mutations.pin_roi, description="Pin a region of interest for quick access")
    delete_roi = strawberry_django.mutation(resolver=mutations.delete_roi, description="Delete an existing region of interest")


@strawberry.type
class Subscription:
    """The root subscription type"""

    rois = strawberry.subscription(resolver=subscriptions.rois, description="Subscribe to real-time ROI updates")
    traces = strawberry.subscription(resolver=subscriptions.traces, description="Subscribe to real-time image updates")
    files = strawberry.subscription(resolver=subscriptions.files, description="Subscribe to real-time file updates")


schema = strawberry.Schema(
    query=Query,
    subscription=Subscription,
    mutation=Mutation,
    extensions=[
        KoherentExtension,
        AuthentikateExtension,
        DjangoOptimizerExtension,
        DatalayerExtension,
        DuckExtension,
    ],
    types=[SynapticConnection, Exp2Synapse],
)
