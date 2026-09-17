from kante.types import Info
from typing import List
import strawberry
from strawberry import ID as StrawberryID
from typing import Any, Type
from core import types, models, scoping
from core import scalars as core_scalars
from core import mutations
from core import queries
from core import subscriptions
import strawberry_django
from koherent.strawberry.extension import KoherentExtension
from core.duck import DuckExtension
from typing import Annotated
from core.base_models.type.graphql.model import SynapticConnection, Exp2Synapse
from core.base_models.type.graphql.model import ModelConfigModel
from core.base_models.type.graphql.topology import Section
from authentikate.strawberry.extension import AuthentikateExtension
from strawberry_django.optimizer import DjangoOptimizerExtension
from datalayer import mutations as datalayer_mutations
from datalayer import scalars as datalayer_scalars
from kanne_server import scalars as kanne_scalars
import kante
from strawberry.extensions.tracing import OpenTelemetryExtension
from strawberry.schema.config import StrawberryConfig
from core.input_unions import unionElementOf
from core.inputs.coords import derived_from_union_types, transform_union_types
from core.inputs.file_link import file_link_union_types
from core.types.coords import transformation_types

ID = Annotated[StrawberryID, strawberry.argument(description="The unique identifier of an object")]


@strawberry.type
class Query:
    # --- The coordinate graph ---------------------------------------------------------
    coordinate_systems: list[types.CoordinateSystem] = strawberry_django.field(description="List coordinate systems: the nodes of the coordinate graph -- a dataset's sample grid, a clock, an experiment's world")
    transformations: list[types.Transformation] = strawberry_django.field(
        description="List transformations: the directed edges of the coordinate graph -- a sampling law, a time lookup, an offset, a derivation. Compose them client-side; the server never stores a composed path, because the same dataset can sit in two experiments under two offsets"
    )
    lenses: list[types.Lens] = strawberry_django.field(description="List lenses: immutable selections over a dataset -- a sweep, an epoch window, a run of channels")

    @strawberry_django.field(description="Get a single coordinate system by ID")
    def coordinate_system(self, info: Info, id: ID) -> types.CoordinateSystem:
        """One coordinate system, scoped to the request's organization."""
        return scoping.get_for_org(models.CoordinateSystem, info, id=id)

    @strawberry_django.field(description="Get a single transformation by ID")
    def transformation(self, info: Info, id: ID) -> types.Transformation:
        """One transformation, scoped to the request's organization."""
        return scoping.get_for_org(models.Transformation, info, id=id)

    @strawberry_django.field(description="Get a single lens by ID")
    def lens(self, info: Info, id: ID) -> types.Lens:
        """One lens, scoped to the request's organization through its dataset."""
        return scoping.get_for_org(models.Lens, info, id=id)

    coordinate_graph = strawberry_django.field(
        resolver=queries.coordinate_graph,
        description="Walk the coordinate graph out from one system: every coordinate system it reaches and every top-level edge between them. Reachability is undirected (an edge pointing into the system relates to it as much as one pointing out), the edges keep their true direction, and nothing is composed -- what the list queries cannot answer is 'which edges relate to *this* one', because relatedness is transitive and a filter is not",
    )
    lineage_graph = strawberry_django.field(
        resolver=queries.lineage_graph,
        description="Walk the *derivation* edges out from one dataset and return its provenance component: everything this data was computed from, everything computed from it, transitively in both directions, and the edges between them. Distinct from `coordinateGraph`, which walks every edge touching a space -- a registration there drags in every other dataset on the same clock, which is a neighbourhood rather than a lineage. Nodes are datasets, not spaces: a dataset's sample grid and its lenses are one node in a provenance story. Kind-blind, so an UNMAPPABLE edge is included; filter on `kind` for the chain that actually places things. Root it at any dataset's coordinate system",
    )

    analog_signals: list[types.AnalogSignal] = strawberry_django.field()
    blocks: list[types.Block] = strawberry_django.field()
    array_datasets: list[types.ArrayDataset] = strawberry_django.field(description="List array datasets: N-dimensional arrays with named dimensions and anchored metadata -- a recording, a stimulus, a vector of sample times, a spike train")
    data_arrays: list[types.DataArray] = strawberry_django.field(description="List data arrays: the multiscale zarr arrays backing array datasets")
    coordinate_anchors: list[types.CoordinateAnchor] = strawberry_django.field(description="List coordinate anchors: the hubs pinning a value unit, a channel label or the rig state to coordinates of a dataset")
    file_links: list[types.FileLink] = strawberry_django.field(description="List file links: which file a container was read from, or written to")
    annotation_collections: list[types.AnnotationCollection] = strawberry_django.field(description="List annotation collections: named sets of marks, each owning the coordinate system they are drawn in")
    annotations: list[types.Annotation] = strawberry_django.field(description="List annotations: events, epochs and measurements, each in its collection's coordinate system")
    folders: list[types.Folder] = strawberry_django.field(description="List folders (collections of array datasets, recording sessions and files)")
    myfolders: list[types.Folder] = strawberry_django.field(description="List folders created by the current user")
    experiments: list[types.Experiment] = strawberry_django.field()
    neuron_models: list[types.NeuronModel] = strawberry_django.field()
    model_collections: list[types.ModelCollection] = strawberry_django.field()
    model_workspaces: list[types.ModelWorkspace] = strawberry_django.field()
    workspace_mappings: list[types.WorkspaceMapping] = strawberry_django.field()
    recordings: list[types.Recording] = strawberry_django.field()
    stimuli: list[types.Stimulus] = strawberry_django.field()

    files: list[types.File] = strawberry_django.field()
    simulations: list[types.Simulation] = strawberry_django.field()
    myfiles: list[types.File] = strawberry_django.field()
    children = strawberry_django.field(resolver=queries.children, description="List everything filed in a folder: its sub-folders, files, array datasets, annotation collections and recording sessions")

    block_stats: types.BlockStats = strawberry_django.field(resolver=types.BlockStatsResolver)

    mod_environments: list[types.ModEnvironment] = strawberry_django.field()
    mechanisms: list[types.Mechanism] = strawberry_django.field()
    mechanism: types.Mechanism = strawberry_django.field()
    mod_environment: types.ModEnvironment = strawberry_django.field()

    @strawberry_django.field(permission_classes=[], description="Get a single stimulus by ID")
    def stimulus(self, info: Info, id: ID) -> types.Stimulus:
        return scoping.get_for_org(models.Stimulus, info, id=id)

    @strawberry_django.field(permission_classes=[], description="Get a single analog signal by ID")
    def analog_signal(self, info: Info, id: ID) -> types.AnalogSignal:
        return scoping.get_for_org(models.AnalogSignal, info, id=id)

    @strawberry_django.field(permission_classes=[], description="Returns a list of cells in a model")
    def cells(
        self,
        info: Info,
        modelId: ID,
        ids: List[ID] | None = None,
        search: str | None = None,
    ) -> list[types.Cell]:
        model = scoping.get_for_org(models.NeuronModel, info, id=modelId)
        l = ModelConfigModel(**model.json_model)

        if search:
            return [cell for cell in l.cells if search in cell.id]
        if ids:
            return [cell for cell in l.cells if cell.id in ids]

        return l.cells

    @strawberry_django.field(permission_classes=[], description="The sections of one cell of a neuron model, read from the model's config")
    def sections(
        self,
        info: Info,
        modelId: ID,
        cellId: ID,
        ids: List[ID] | None = None,
        search: str | None = None,
    ) -> List["Section"]:
        """Get all cells"""
        model = scoping.get_for_org(models.NeuronModel, info, id=modelId)
        l = ModelConfigModel(**model.json_model)

        for cell in l.cells:
            if cell.id == cellId:
                if search:
                    return [section for section in cell.topology.sections if search in section.id]
                if ids:
                    return [section for section in cell.topology.sections if section.id in ids]

                return cell.topology.sections

        raise ValueError(f"Cell with ID {cellId} not found in model {modelId}")

    @strawberry_django.field(permission_classes=[], description="Get a single recording by ID")
    def recording(self, info: Info, id: ID) -> types.Recording:
        return scoping.get_for_org(models.Recording, info, id=id)

    @strawberry_django.field()
    def block(self, info: Info, id: ID) -> types.Block:
        """Get all blocks"""
        return scoping.get_for_org(models.Block, info, id=id)

    @strawberry_django.field()
    def experiment(self, info: Info, id: ID) -> types.Experiment:
        """Get all experiments"""
        return scoping.get_for_org(models.Experiment, info, id=id)

    @strawberry_django.field()
    def model_collection(self, info: Info, id: ID) -> types.ModelCollection:
        """Get all model collections"""
        return scoping.get_for_org(models.ModelCollection, info, id=id)

    @strawberry_django.field()
    def model_workspace(self, info: Info, id: ID) -> types.ModelWorkspace:
        """Get a single model workspace by id"""
        return scoping.get_for_org(models.ModelWorkspace, info, id=id)

    @strawberry_django.field()
    def workspace_mapping(self, info: Info, id: ID) -> types.WorkspaceMapping:
        """Get a single workspace mapping by id"""
        return scoping.get_for_org(models.WorkspaceMapping, info, id=id)

    @strawberry_django.field()
    def simulation(self, info: Info, id: ID) -> types.Simulation:
        """Get all simulations"""
        return scoping.get_for_org(models.Simulation, info, id=id)

    @strawberry_django.field(permission_classes=[], description="Get a single array dataset by ID")
    def array_dataset(self, info: Info, id: ID) -> types.ArrayDataset:
        return scoping.get_for_org(models.ArrayDataset, info, id=id)

    @strawberry_django.field(permission_classes=[], description="Get a single data array by ID")
    def data_array(self, info: Info, id: ID) -> types.DataArray:
        return scoping.get_for_org(models.DataArray, info, id=id)

    @strawberry_django.field(permission_classes=[], description="Get a single file link by ID")
    def file_link(self, info: Info, id: ID) -> types.FileLink:
        return scoping.get_for_org(models.FileLink, info, id=id)

    @strawberry_django.field(permission_classes=[], description="Returns a single neuron model by ID")
    def neuron_model(self, info: Info, id: ID) -> types.NeuronModel:
        return scoping.get_for_org(models.NeuronModel, info, id=id)

    @strawberry_django.field(description="Get a single annotation collection by ID")
    def annotation_collection(self, info: Info, id: ID) -> types.AnnotationCollection:
        """One annotation collection, scoped to the request's organization."""
        return scoping.get_for_org(models.AnnotationCollection, info, id=id)

    @strawberry_django.field(description="Get a single annotation by ID")
    def annotation(self, info: Info, id: ID) -> types.Annotation:
        """One annotation, scoped to the request's organization through its collection."""
        return scoping.get_for_org(models.Annotation, info, id=id)

    nearest_annotations = strawberry_django.field(
        resolver=queries.nearest_annotations,
        description="The k annotations of one collection nearest to a point -- the events nearest an instant -- by cube distance between the point and each annotation's bounding box (GiST-accelerated; 0 inside the box). Scoped to one collection because boxes only compare within one frame; the point is in the collection's own coordinate order",
    )

    @strawberry_django.field(permission_classes=[])
    def file(self, info: Info, id: ID) -> types.File:
        return scoping.get_for_org(models.File, info, id=id)

    @strawberry_django.field(permission_classes=[], description="Get a single folder by ID")
    def folder(self, info: Info, id: ID) -> types.Folder:
        return scoping.get_for_org(models.Folder, info, id=id)


@strawberry.type
class Mutation:
    create_block = strawberry_django.mutation(resolver=mutations.create_block, description="Create a recording session over array datasets that already exist: its clock, its segments, and the edge timing each signal's dataset. Creates no data")
    delete_block = strawberry_django.mutation(resolver=mutations.delete_block, description="Delete a recording session: its segments, its signals and its clocks. The array datasets its signals named stay")

    # --- Datalayer actions -------------------------------------------------
    # One block per store type. Each exposes: upload (request + finish),
    # single-object read access, and (where available) an organization-wide
    # "general" read access grant.

    # Media
    request_media_upload = kante.django_mutation(
        description="Upload media and return a URL for access",
        resolver=datalayer_mutations.request_media_upload,
    )
    finish_media_upload = kante.django_mutation(
        description="Finalize a media upload after the client has written the object",
        resolver=datalayer_mutations.finish_media_upload,
    )
    request_media_access = kante.django_mutation(
        description="Request temporary S3 read credentials for a media file",
        resolver=datalayer_mutations.request_media_access,
    )
    request_general_media_access = kante.django_mutation(
        description="Request temporary S3 read credentials for media files in the organization",
        resolver=datalayer_mutations.request_general_media_access,
    )

    # Big files
    request_bigfile_upload = kante.django_mutation(
        description="Request an upload grant for a big file store",
        resolver=datalayer_mutations.request_bigfile_upload,
    )
    finish_bigfile_upload = kante.django_mutation(
        description="Finalize a big file upload after the client has written the object",
        resolver=datalayer_mutations.finish_bigfile_upload,
    )
    request_bigfile_access = kante.django_mutation(
        description="Request temporary S3 read credentials for a big file",
        resolver=datalayer_mutations.request_bigfile_access,
    )

    # Zarr
    request_zarr_upload = kante.django_mutation(
        description="Request an upload grant for a Zarr store",
        resolver=datalayer_mutations.request_zarr_upload,
    )
    finish_zarr_upload = kante.django_mutation(
        description="Finalize a Zarr upload after the client has written the object",
        resolver=datalayer_mutations.finish_zarr_upload,
    )
    request_zarr_access = kante.django_mutation(
        description="Request temporary S3 read credentials for a Zarr store",
        resolver=datalayer_mutations.request_zarr_access,
    )
    request_general_zarr_access = kante.django_mutation(
        description="Request temporary S3 read credentials for Zarr stores in the organization",
        resolver=datalayer_mutations.request_general_zarr_access,
    )

    # Parquet
    request_parquet_upload = kante.django_mutation(
        description="Request an upload grant for a Parquet store",
        resolver=datalayer_mutations.request_parquet_upload,
    )
    finish_parquet_upload = kante.django_mutation(
        description="Finalize a Parquet upload after the client has written the object",
        resolver=datalayer_mutations.finish_parquet_upload,
    )
    request_parquet_access = kante.django_mutation(
        description="Request temporary S3 read credentials for a Parquet file",
        resolver=datalayer_mutations.request_parquet_access,
    )
    request_general_parquet_access = kante.django_mutation(
        description="Request temporary S3 read credentials for Parquet files in the organization",
        resolver=datalayer_mutations.request_general_parquet_access,
    )

    create_array_dataset = strawberry_django.mutation(
        resolver=mutations.create_array_dataset,
        description=(
            "Create a new dataset from array-like data, with its pyramid levels, optional coordinate anchors (a value unit, channel labels, the rig state) and derivation edges. "
            "This is the one way data enters: what it *means* -- a signal of a block, a recording of a simulation -- is said afterwards, by `createBlock` or `createSimulation` naming it by ID"
        ),
    )
    update_array_dataset = strawberry_django.mutation(
        resolver=mutations.update_array_dataset,
        description="Rename a dataset or redescribe it -- the whole of what is editable, and audited on `provenanceEntries`. Its arrays, axes and coordinate systems are fixed at creation; a recomputation is a new dataset",
    )
    delete_array_dataset = strawberry_django.mutation(
        resolver=mutations.delete_array_dataset,
        description="Delete an existing array dataset, with its levels, its lenses, every interpretation of it, and the coordinate systems nothing else lives in. Its stores are flagged, not deleted: `purge_orphaned_stores` collects them after a grace period",
    )
    delete_data_array = strawberry_django.mutation(resolver=mutations.delete_data_array, description="Delete one downsampled level of a dataset. Level 0 cannot be deleted: it is the dataset")

    create_mod_environment = strawberry_django.mutation(
        resolver=mutations.create_mod_environment,
        description="Create a mechanism from a mod file",
    )


    create_neuron_model = strawberry_django.mutation(resolver=mutations.create_neuron_model, description="Create a new neuron model")
    create_simulation = strawberry_django.mutation(resolver=mutations.create_simulation, description="Create a simulation over array datasets that already exist: its clock, a recording or stimulus per dataset, and the edge timing each one. Creates no data")

    # --- Guarded deletes ---------------------------------------------------
    # One delete per model. Each enforces the deletion guard (core.guards):
    # admins, the original task assigner, or the (non-bot) creator may delete;
    # sub-objects defer the check to their governing anchor.
    delete_model_collection = strawberry_django.mutation(resolver=mutations.delete_model_collection, description="Delete an existing model collection")
    delete_model_workspace = strawberry_django.mutation(resolver=mutations.delete_model_workspace, description="Delete an existing model workspace")
    delete_workspace_mapping = strawberry_django.mutation(resolver=mutations.delete_workspace_mapping, description="Delete an existing workspace mapping")
    delete_mod_environment = strawberry_django.mutation(resolver=mutations.delete_mod_environment, description="Delete an existing mod environment")
    delete_mechanism = strawberry_django.mutation(resolver=mutations.delete_mechanism, description="Delete an existing mechanism")
    delete_neuron_model = strawberry_django.mutation(resolver=mutations.delete_neuron_model, description="Delete an existing neuron model")
    delete_experiment = strawberry_django.mutation(resolver=mutations.delete_experiment, description="Delete an existing experiment")
    delete_experiment_recording_view = strawberry_django.mutation(resolver=mutations.delete_experiment_recording_view, description="Delete an existing experiment recording view")
    delete_experiment_stimulus_view = strawberry_django.mutation(resolver=mutations.delete_experiment_stimulus_view, description="Delete an existing experiment stimulus view")
    delete_block_group = strawberry_django.mutation(resolver=mutations.delete_block_group, description="Delete an existing block group")
    delete_block_segment = strawberry_django.mutation(resolver=mutations.delete_block_segment, description="Delete an existing block segment")
    delete_analog_signal = strawberry_django.mutation(resolver=mutations.delete_analog_signal, description="Delete an existing analog signal")
    delete_irregularly_sampled_signal = strawberry_django.mutation(resolver=mutations.delete_irregularly_sampled_signal, description="Delete an existing irregularly sampled signal")
    delete_spike_train = strawberry_django.mutation(resolver=mutations.delete_spike_train, description="Delete an existing spike train")
    delete_simulation = strawberry_django.mutation(resolver=mutations.delete_simulation, description="Delete a simulation: its recordings, its stimuli, their experiment views and its clock. The array datasets they named stay")
    delete_stimulus = strawberry_django.mutation(resolver=mutations.delete_stimulus, description="Delete an existing stimulus")
    delete_recording = strawberry_django.mutation(resolver=mutations.delete_recording, description="Delete an existing recording")

    from_file_like = strawberry_django.mutation(
        resolver=mutations.from_file_like,
        description="Create a file from file-like data",
    )
    delete_file = strawberry_django.mutation(resolver=mutations.delete_file, description="Delete an existing file")
    link_file = strawberry_django.mutation(
        resolver=mutations.link_file,
        description="Record a link between a file and the data it encodes, after both already exist",
    )
    unlink_file = strawberry_django.mutation(
        resolver=mutations.unlink_file,
        description="Delete a file link. Neither the file nor the container is touched",
    )

    create_model_collection = strawberry_django.mutation(
        resolver=mutations.create_model_collection,
        description="Create a new model collection",
    )

    # ModelWorkspace — a shared space for collaboratively developing neuron models.
    create_model_workspace = strawberry_django.mutation(
        resolver=mutations.create_model_workspace,
        description="Create a new model workspace",
    )
    update_model_workspace = strawberry_django.mutation(
        resolver=mutations.update_model_workspace,
        description="Update an existing model workspace",
    )
    pin_model_workspace = strawberry_django.mutation(
        resolver=mutations.pin_model_workspace,
        description="Pin or unpin a model workspace for the current user",
    )
    add_models_to_workspace = strawberry_django.mutation(
        resolver=mutations.add_models_to_workspace,
        description="Add neuron models to a workspace (optionally into a group)",
    )
    remove_models_from_workspace = strawberry_django.mutation(
        resolver=mutations.remove_models_from_workspace,
        description="Remove neuron models from a workspace",
    )
    update_workspace_mapping = strawberry_django.mutation(
        resolver=mutations.update_workspace_mapping,
        description="Update a workspace mapping (e.g. change its group)",
    )

    # Folder
    create_folder = strawberry_django.mutation(
        resolver=mutations.create_folder,
        description="Create a new folder to organize data",
    )
    ensure_folder = strawberry_django.mutation(
        resolver=mutations.ensure_folder,
        description="Create a new folder to organize data, or return the one the current user already has under this name and parent",
    )
    update_folder = strawberry_django.mutation(resolver=mutations.update_folder, description="Update folder metadata")
    revert_folder = strawberry_django.mutation(
        resolver=mutations.revert_folder,
        description="Revert folder to a previous version",
    )
    pin_folder = strawberry_django.mutation(resolver=mutations.pin_folder, description="Pin a folder for quick access")
    delete_folder = strawberry_django.mutation(resolver=mutations.delete_folder, description="Delete an existing folder. What was filed in it is unfiled, not deleted")
    put_folders_in_folder = strawberry_django.mutation(
        resolver=mutations.put_folders_in_folder,
        description="Add folders as children of another folder",
    )
    release_folders_from_folder = strawberry_django.mutation(
        resolver=mutations.release_folders_from_folder,
        description="Remove folders from being children of another folder",
    )
    put_files_in_folder = strawberry_django.mutation(resolver=mutations.put_files_in_folder, description="File files in a folder")
    release_files_from_folder = strawberry_django.mutation(resolver=mutations.release_files_from_folder, description="Take files out of a folder")
    put_array_datasets_in_folder = strawberry_django.mutation(
        resolver=mutations.put_array_datasets_in_folder,
        description="File array datasets in a folder. Only root data is filed explicitly: a derived dataset follows its primary parent, and moving the parent moves it",
    )
    release_array_datasets_from_folder = strawberry_django.mutation(
        resolver=mutations.release_array_datasets_from_folder,
        description="Take array datasets out of a folder",
    )
    put_annotation_collections_in_folder = strawberry_django.mutation(resolver=mutations.put_annotation_collections_in_folder, description="File annotation collections in a folder")
    release_annotation_collections_from_folder = strawberry_django.mutation(
        resolver=mutations.release_annotation_collections_from_folder,
        description="Take annotation collections out of a folder",
    )
    put_blocks_in_folder = strawberry_django.mutation(resolver=mutations.put_blocks_in_folder, description="File recording sessions in a folder")
    release_blocks_from_folder = strawberry_django.mutation(resolver=mutations.release_blocks_from_folder, description="Take recording sessions out of a folder")

    # Experiment
    create_experiment = strawberry_django.mutation(resolver=mutations.create_experiment, description="Create a new experiment")

    # --- Annotations ------------------------------------------------------------------
    create_annotation_collection = strawberry_django.mutation(
        resolver=mutations.create_annotation_collection,
        description="Create an annotation collection, in a coordinate system of its own, optionally related to what its shapes are drawn over: a dataset's sample grid, a segment's clock. The common path for a timeline -- drawing on an experiment -- goes through createAnnotation instead, which mints the experiment's collection on first use",
    )
    delete_annotation_collection = strawberry_django.mutation(resolver=mutations.delete_annotation_collection, description="Delete an annotation collection. Its annotations, its experiment views and the drawing space it owned go with it; what it was drawn over is untouched")
    create_annotation = strawberry_django.mutation(
        resolver=mutations.create_annotation,
        description="Draw an annotation into a collection, or onto an experiment (exactly one of the two). Drawing on an experiment finds its annotation collection or mints it on first use: a coordinate system copying the world's axes, an identity registration into the world, and one annotation view",
    )
    create_annotations = strawberry_django.mutation(resolver=mutations.create_annotations, description="Draw many annotations in one call -- a detector's whole output. One collection resolve, one chain resolve, one insert")
    update_annotation = strawberry_django.mutation(resolver=mutations.update_annotation, description="Edit an annotation. Only the supplied fields change; new vectors re-derive the bounding box")
    delete_annotation = strawberry_django.mutation(resolver=mutations.delete_annotation, description="Delete an annotation. Its collection, and the space it was drawn in, stay")
    delete_experiment_annotation_view = strawberry_django.mutation(resolver=mutations.delete_experiment_annotation_view, description="Stop showing an annotation collection in an experiment. The collection and its annotations are untouched")


    # --- The coordinate graph ---------------------------------------------------------
    create_coordinate_system = strawberry_django.mutation(
        resolver=mutations.create_coordinate_system,
        description="Create a SHARED coordinate system (a space nothing lives in: a clock, a world) and, in one call, author the edges registering any number of sources (datasets, lenses, coordinate systems) into it",
    )
    update_coordinate_system = strawberry_django.mutation(
        resolver=mutations.update_coordinate_system,
        description="Rename a shared coordinate system or anchor its clock. Shared spaces only -- a space data lives in is described by that data, and where data sits is an edge (updateTransformation), not a property of the space",
    )
    delete_coordinate_system = strawberry_django.mutation(
        resolver=mutations.delete_coordinate_system,
        description="Delete an unused shared coordinate system. Refused while data lives in it, while anything is laid out over it (an experiment, a block, a segment, a simulation), or while any transformation edge touches it. This is the only door a shared space leaves through -- deleting an experiment never deletes one",
    )
    clear_coordinate_system = strawberry_django.mutation(
        resolver=mutations.clear_coordinate_system,
        description="Delete every registration INTO a shared space in one call, returning the deleted edge ids. The space, whatever is laid out over it (its views drop to UNREGISTERED) and the space's own claims into wider spaces all survive",
    )
    delete_orphaned_coordinate_systems = strawberry_django.mutation(
        resolver=mutations.delete_orphaned_coordinate_systems,
        description="Delete every orphaned shared space in the organization -- nothing living in it, nothing laid out over it, no edge touching it -- and return the deleted ids. Org admins sweep every orphan; anyone else sweeps only their own",
    )
    create_transformation = strawberry_django.mutation(
        resolver=mutations.create_transformation,
        description="Create one edge of the coordinate graph, mapping an input coordinate system to an output one. This is where a sampling law is corrected, two clocks are synchronised, and a recording is registered into a world",
    )
    update_transformation = strawberry_django.mutation(
        resolver=mutations.update_transformation,
        description="Refine a transformation's parameters in place. Everything that looks through the edge moves with it, because nothing stores a composed path",
    )
    delete_transformation = strawberry_django.mutation(resolver=mutations.delete_transformation, description="Delete an existing transformation. A wrapper takes its children with it")
    delete_registration = strawberry_django.mutation(
        resolver=mutations.delete_registration,
        description="Un-register a source from a space by naming the source and the space rather than the edge. Deletes every edge from the source's spaces into that one -- rivals are allowed, so there is no single edge to mean -- and returns their ids. An UNMAPPABLE declaration is not a placement and is never matched",
    )
    create_lens = strawberry_django.mutation(resolver=mutations.create_lens, description="Create a lens: an immutable selection over a dataset. A sliced lens gets its own coordinate system and the derived edge recording the shift")
    delete_lens = strawberry_django.mutation(resolver=mutations.delete_lens, description="Delete a lens, and the coordinate system it owned if it was sliced")


@strawberry.type
class Subscription:
    """The root subscription type"""

    array_datasets = strawberry.subscription(
        resolver=subscriptions.array_datasets,
        description="Subscribe to the array datasets of this organization, or of one of its folders, as they are created, updated and deleted",
    )
    files = strawberry.subscription(resolver=subscriptions.files, description="Subscribe to real-time file updates")


schema = kante.Schema(
    query=Query,
    subscription=Subscription,
    mutation=Mutation,
    extensions=[
        OpenTelemetryExtension,
        AuthentikateExtension,
        KoherentExtension,
        # `only` optimization off, as in mikro: column pruning drops `Transformation.kind`, the
        # discriminator every concrete transformation type's `is_type_of` reads, so the read is
        # deferred and refreshed per row on the event-loop thread. The prefetch/select_related
        # half of the optimizer, which is where the query count is won, stays on.
        # A factory, not an instance: strawberry builds a fresh extension per request.
        lambda: DjangoOptimizerExtension(enable_only_optimization=False),
        DuckExtension,
    ],
    # Types reachable only through an interface, or referenced by no field at all, are not
    # discovered by strawberry: left out of this list they vanish from the SDL with no error.
    types=[
        SynapticConnection,
        Exp2Synapse,
        *transformation_types,
        *transform_union_types,
        *derived_from_union_types,
        *file_link_union_types,
    ],
    schema_directives=[unionElementOf],
    config=StrawberryConfig(scalar_map={**core_scalars.SCALAR_MAP, **datalayer_scalars.SCALAR_MAP, **kanne_scalars.SCALAR_MAP}),
)
