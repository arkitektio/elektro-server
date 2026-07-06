import random
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.forms import FileField
from taggit.managers import TaggableManager
from core import enums
from koherent.fields import ProvenanceField, HistoricForeignKey
from django_choices_field import TextChoicesField
from core.fields import S3Field
from kanne_server.fields import QuantityField
from datalayer.datalayer import Datalayer

# Create your models here.
import boto3
import json
from django.conf import settings
from django.core.cache import cache
from authentikate.models import Organization, Membership
from polymorphic.models import PolymorphicModel
from datalayer.models import BigFileStore, ZarrStore


class DatasetManager(models.Manager):
    def get_current_default_for_user(self, user):
        potential = self.filter(creator=user, is_default=True).first()
        if not potential:
            return self.create(creator=user, name="Default", is_default=True)

        return potential


class Dataset(models.Model):
    """
    A dataset is a collection of data fssisles and metadata sfiles.
    It mimics the concept of a folder in sa files sysstsem and is the top level
    object in the data model.s

    """

    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="created_datasets",
        help_text="The user that created the dataset",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="The time the dataset was created")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    name = models.CharField(max_length=200, help_text="The name of the dataset")
    description = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="The description of the dataset",
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_datasets",
        blank=True,
        help_text="The users that have pinned the dataset",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Whether the dataset is the current default dataset for the user",
    )
    tags = TaggableManager(help_text="Tags for the dataset")
    provenance = ProvenanceField()
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="datasets",
        help_text="The organization that owns the dataset",
    )
    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        related_name="datasets",
        help_text="The organization that owns the dataset",
    )
    created_through = models.ForeignKey(
        "koherent.Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_%(class)ss",
        help_text="The task this object was created through, if any",
    )
    created_through_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_%(class)ss",
        help_text="The assigner of the creating task, denormalized for fast filtering",
    )

    objects = DatasetManager()

    def __str__(self) -> str:
        return super().__str__()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["creator", "is_default", "organization"],
                name="unique_default_per_creator",
                condition=models.Q(is_default=True),
            ),
            models.UniqueConstraint(
                fields=["parent", "name"],
                name="only_one_dataset_per_parent_and_name",
            ),
        ]


class Instrument(models.Model):
    name = models.CharField(max_length=1000)
    manufacturer = models.CharField(max_length=1000, null=True, blank=True)
    model = models.CharField(max_length=1000, null=True, blank=True)
    serial_number = models.CharField(max_length=1000, unique=True)

    provenance = ProvenanceField()


class File(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, null=True, blank=True, related_name="files")
    origins = models.ManyToManyField(
        "self",
        related_name="derived",
        symmetrical=False,
    )
    store = models.ForeignKey(
        BigFileStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the file",
    )
    name = models.CharField(max_length=1000, help_text="The name of the file", default="")
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, null=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="files",
        help_text="The organization that owns the file",
    )
    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="files",
        help_text="The membership of the user that created the file",
    )
    size = models.BigIntegerField(help_text="The size of the file in bytes", null=True, blank=True)
    content_type = models.CharField(
        max_length=1000,
        help_text="The content type of the file",
        null=True,
        blank=True,
    )
    created_through = models.ForeignKey(
        "koherent.Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_%(class)ss",
        help_text="The task this object was created through, if any",
    )
    created_through_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_%(class)ss",
        help_text="The assigner of the creating task, denormalized for fast filtering",
    )
    provenance = ProvenanceField()


class ModelCollection(models.Model):
    """A ModelCollection is a collection of models,

    that are comparable to each other.


    """

    comparison = models.ForeignKey(
        "NeuronModel",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="comparing_collections",
    )
    name = models.CharField(max_length=1000, help_text="The name of the model collection")
    description = models.CharField(max_length=1000, null=True, blank=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the model collection",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="model_collections",
        help_text="The organization that owns the model collection",
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_model_collections",
        help_text="The users that have pinned the model collection",
    )
    models = models.ManyToManyField(
        "NeuronModel",
        related_name="model_collections",
        help_text="The models that are in the collection",
    )


class ModEnvironment(models.Model):
    """A mod environment is a set of mod files
    that can be used to simulate a neuron model.

    They are stored as zip files in S3 and will be
    downloaded and extracted when a neuron model
    is simulated. They will be cached locally for
    faster access.

    """

    name = models.CharField(max_length=1000, help_text="The name of the mod environment")
    store = models.ForeignKey(
        BigFileStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The .mod file, stored in S3",
    )
    description = models.CharField(max_length=1000, null=True, blank=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="mod_environments",
        help_text="The organization that owns the mod environment",
    )

    created_at = models.DateTimeField(auto_now_add=True)


class Mechanism(models.Model):
    """A mod environment is a set of mod files
    that can be used to simulate a neuron model.

    They are stored as zip files in S3 and will be
    downloaded and extracted when a neuron model
    is simulated. They will be cached locally for
    faster access.

    """

    environment = models.ForeignKey(
        ModEnvironment,
        on_delete=models.CASCADE,
        related_name="mechanisms",
        help_text="The mod environment that the mechanism sbelongs to",
    )
    name = models.CharField(
        max_length=1000,
        help_text="The mechanism that can be simulated with the mod environment",
    )
    description = models.CharField(max_length=1000, null=True, blank=True)
    parameters = models.JSONField(
        help_text="The parameter ports of the mechanism, stored as a json object with the port name as key and the port type as value",
        default=list,
    )

    created_at = models.DateTimeField(auto_now_add=True)



class ModelWorkspace(models.Model):
    """A ModelWorkspace is a workspace for developing neuron models

    Within a workspace, a user can create and edit neuron models, as well as run simulations and analyze the results.
    Within a workspace models are expected to be comparable and to be iterated upon. A workspace can be shared with other users and AI agents who can then collaborate on the models within the workspace.
    
    
    
    """
    name = models.CharField(max_length=1000, help_text="The name of the workspace")
    description = models.CharField(max_length=1000, null=True, blank=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the workspace",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_workspaces",
        help_text="The users that have pinned the workspace",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="model_workspaces",
        help_text="The organization that owns the workspace",
    )




class WorkspaceMapping(models.Model):
    """A WorkspaceMapping is a mapping between a neuron model and a workspace.
    """
    workspace = models.ForeignKey(
        ModelWorkspace,
        on_delete=models.CASCADE,
        related_name="mappings",
        help_text="The workspace that the mapping belongs to",
    )
    model = models.ForeignKey(
        "NeuronModel",
        on_delete=models.CASCADE,
        related_name="mappings",
        help_text="The neuron model that the mapping belongs to",
    )
    workspace_group = models.CharField(
        max_length=1000,
        help_text="The group of the workspace that the mapping belongs to (if its subdivided into groups)",
    )
    created_at = models.DateTimeField(auto_now_add=True)



class NeuronModel(models.Model):
    """A NEURON model
    that can be used t simulate a neuron
    """
    environment = models.ForeignKey(
        ModEnvironment,
        on_delete=models.CASCADE,
        help_text="The mod environment that the neuron model belongs to",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="The parent model of the neuron (if it was derived from another model)",
    )
    hash = models.CharField(
        max_length=1000,
        help_text="The hash of the model",
        unique=True,
    )
    json_model = models.JSONField(
        help_text="The json model of the neuron",
        default=dict,
        blank=True,
    )
    name = models.CharField(max_length=1000, help_text="The name of the model")
    description = models.CharField(max_length=1000, null=True, blank=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the model",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_models",
        help_text="The users that have pinned the model",
    )
    provenance = ProvenanceField()


class Experiment(models.Model):
    name = models.CharField(max_length=1000, help_text="The name of the experiment")
    description = models.CharField(max_length=1000, null=True, blank=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the experimesnt",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_experiments",
        help_text="The users that have pinned the experiment",
    )
    time_trace = models.ForeignKey(
        "Trace",
        on_delete=models.CASCADE,
        related_name="experiments",
    )
    provenance = ProvenanceField()

    class Meta:
        ordering = ["-created_at"]


class ExperimentRecordingView(models.Model):
    """A SimulationView is a view of a simulation.

    It is used to group simulations together, for example to group all simulations
    that are used to represent a specific channel.

    """

    recording = models.ForeignKey(
        "Recording",
        on_delete=models.CASCADE,
        related_name="experiment_views",
        null=True,
        blank=True,
    )
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="recording_views",
        null=True,
        blank=True,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="experiment_recording_views",
        help_text="The organization that owns the recording view",
    )
    offset = QuantityField(base_unit="picosecond", help_text="The offset of the view, stored in picoseconds", null=True, blank=True)
    duration = QuantityField(base_unit="picosecond", help_text="The duration of the view, stored in picoseconds", null=True, blank=True)
    label = models.CharField(
        max_length=1000,
        help_text="The label of the view",
        null=True,
        blank=True,
    )


class ExperimentStimulusView(models.Model):
    """A SimulationView is a view of a simulation.

    It is used to group simulations together, for example to group all simulations
    that are used to represent a specific channel.

    """

    stimulus = models.ForeignKey(
        "Stimulus",
        on_delete=models.CASCADE,
        related_name="experiment_views",
        null=True,
        blank=True,
    )
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="stimulus_views",
        null=True,
        blank=True,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="experiment_stimulus_views",
        help_text="The organization that owns the stimulus view",
    )
    offset = QuantityField(base_unit="picosecond", help_text="The offset of the view, stored in picoseconds", null=True, blank=True)
    duration = QuantityField(base_unit="picosecond", help_text="The duration of the view, stored in picoseconds", null=True, blank=True)
    label = models.CharField(
        max_length=1000,
        help_text="The label of the view",
        null=True,
        blank=True,
    )


class Block(models.Model):
    """A RecordingSession is a session of recordings.

    It is used to group recordings together, for example to group all recordings
    that are part of the same experiment.

    """

    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="blocks",
    )
    origin = models.ForeignKey(
        "File",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="blocks",
    )
    name = models.CharField(max_length=1000, help_text="The name of the recording session")
    description = models.CharField(max_length=1000, null=True, blank=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the recording session",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_recording_sessions",
        help_text="The users that have pinned the recording session",
    )
    recording_time = models.DateTimeField(help_text="The time the recording session was acquired", null=True, blank=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="blocks")
    provenance = ProvenanceField()


class BlockGroup(models.Model):
    session = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name="groups",
    )
    label = models.CharField(max_length=1000, help_text="The label of the recording group")


class BlockSegment(models.Model):
    session = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="segments",
    )
    start_time = QuantityField(base_unit="picosecond", help_text="The start time of the segment, stored in picoseconds", null=True, blank=True)
    end_time = QuantityField(base_unit="picosecond", help_text="The end time of the segment, stored in picoseconds", null=True, blank=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="block_segments",
        help_text="The organization that owns the segment",
    )
    provenance = ProvenanceField()


class AnalogSignal(models.Model):
    recording_segment = models.ForeignKey(
        BlockSegment,
        on_delete=models.CASCADE,
        related_name="analog_signals",
    )
    time_trace = models.ForeignKey(
        "Trace",
        on_delete=models.CASCADE,
        related_name="analog_signal_time_traces",
    )
    name = models.CharField(max_length=1000, help_text="The name of the signal", default="")
    t_start = QuantityField(base_unit="picosecond", help_text="The start time of the signal, stored in picoseconds", default=0)
    description = models.CharField(max_length=1000, null=True, blank=True)
    sampling_rate = QuantityField(base_unit="nanohertz", help_text="The sampling frequency of the signal, stored in nanohertz", default=1_000_000_000_000)
    unit = models.CharField(max_length=100, help_text="The unit of the signal", default="mV", null=True, blank=True)
    color = models.CharField(max_length=7, help_text="The color of the signal in HEX", default="#000000")

    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_analog_signals",
        blank=True,
        help_text="The users that pinned this segment",
    )

    provenance = ProvenanceField()

    def __str__(self):
        return f"Segment {self.label} on {self.trace.name}"


class AnalogSignalChannel(models.Model):
    signal = models.ForeignKey(
        "AnalogSignal",
        on_delete=models.CASCADE,
        related_name="channels",
    )
    trace = models.ForeignKey(
        "Trace",
        on_delete=models.CASCADE,
        related_name="analog_signal_channels",
    )
    index = models.IntegerField(help_text="The index of the channel in the signal")
    name = models.CharField(max_length=1000, help_text="The name of the channel", default="")
    description = models.CharField(max_length=1000, null=True, blank=True)
    unit = models.CharField(max_length=100, help_text="The unit of the channel", default="mV", null=True, blank=True)
    color = models.CharField(max_length=7, help_text="The color of the signal in HEX", null=True, blank=True)


class IrregularlySampledSignal(models.Model):
    recording_segment = models.ForeignKey(
        BlockSegment,
        on_delete=models.CASCADE,
        related_name="irregularly_sampled_signals",
    )
    name = models.CharField(max_length=1000, help_text="The name of the signal", default="")
    trace = models.ForeignKey(
        "Trace",
        on_delete=models.CASCADE,
        related_name="irregularly_sampled_trace_signals",
    )
    time_trace = models.ForeignKey(
        "Trace",
        on_delete=models.CASCADE,
        related_name="irregularly_sampled_time_signals",
    )

    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_irregularly_sampled_signals",
        blank=True,
        help_text="The users that pinned this segment",
    )

    provenance = ProvenanceField()

    def __str__(self):
        return f"IrregularlySampledSignal {self.label} on {self.trace.name}"


class SpikeTrain(models.Model):
    recording_segment = models.ForeignKey(
        BlockSegment,
        on_delete=models.CASCADE,
        related_name="spike_trains",
    )
    name = models.CharField(max_length=1000, help_text="The name of the signal", default="")
    trace = models.ForeignKey(
        "Trace",
        on_delete=models.CASCADE,
        related_name="spike_trains",
    )
    unit = models.CharField(max_length=100, help_text="The unit of the signal", default="sec", null=True, blank=True)

    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_spike_trains",
        blank=True,
        help_text="The users that pinned this segment",
    )

    provenance = ProvenanceField()

    def __str__(self):
        return f"SpikeTrain {self.label} on {self.trace.name}"


class Trace(models.Model):
    """A Trace is n-dimensional representation of a time series.

    Mikro stores each image as sa 5-dimensional representation. The dimensions are:
    - t: time
    - c: channel
    - z: z-stack
    - x: x-dimension
    - y: y-dimension

    This ensures a unified api for all images, regardless of their original dimensions.
      Another main
    determining factor for a representation is its variety:
    A representation can be a raw image representating voxels (VOXEL)
    or a segmentation mask representing instances of a class. (MASK)
    It can also representate a human perception of the image (RGB)
    or a human perception of the mask (RGBMASK)


    #Origins and Derivations

    Images can be filtered, which means that a new representation
    is created from the other (soriginal) representations.
    This new representation is then linked to the original representations.
    This way, we can always trace back to the original representation.
    Both are encapsulaed in the origins and derived fields.

    Representations belong to *one* sample. Every transaction to our image data
    is still part of the original acuqistion, so also filtered
      images are refering back to the sample
    Each iamge has also a name, which is used to identify the image.
    The name is unique within a sample.
    File and Rois that are used to create images are saved in
      the file origins and roi origins repectively.


    """

    store = models.ForeignKey(
        ZarrStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the trace",
    )
    name = models.CharField(max_length=1000, help_text="The name of the image", default="")

    description = models.CharField(max_length=1000, null=True, blank=True)
    kind = TextChoicesField(
        choices_enum=enums.TraceKindChoices,
        default=enums.TraceKindChoices.UNKNOWN.value,
        help_text="The Representation can have vasrying kind, consult your API",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)

    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_traces",
        help_text="The users that have pinned the images",
    )
    provenance = ProvenanceField()
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="traces",
        help_text="The organization that owns the dataset",
    )
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="traces",
        help_text="The dataset that the trace belongs to",
    )

    tags = TaggableManager()

    class Meta:
        permissions = [("inspect_image", "Can view image")]

    def __str__(self) -> str:
        return f"Representation {self.id}"


class Simulation(models.Model):
    """A RUN is a run of a neuron model on a dataset.

    It is used to store the results of the run, such as the
    parameters used and the output of the run.
    """

    model = models.ForeignKey(NeuronModel, on_delete=models.CASCADE, related_name="simulations")
    duration = QuantityField(base_unit="picosecond", help_text="The duration of the run, stored in picoseconds")
    dt = QuantityField(base_unit="picosecond", help_text="The time step of the run, stored in picoseconds", default=1_000_000_000_000)
    time_trace = models.ForeignKey(
        Trace,
        on_delete=models.CASCADE,
        related_name="simulations",
    )
    name = models.CharField(max_length=1000, help_text="The name of the run")
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the run",
        null=True,
    )
    provenance = ProvenanceField()

    class Meta:
        ordering = ["-created_at"]


class Stimulus(models.Model):
    trace = models.ForeignKey(
        Trace,
        on_delete=models.CASCADE,
        related_name="stimuli",
    )
    simulation = models.ForeignKey(
        Simulation,
        on_delete=models.CASCADE,
        related_name="stimuli",
    )
    kind = TextChoicesField(
        choices_enum=enums.StimulusKindChoices,
        default=enums.StimulusKindChoices.CURRENT.value,
        help_text="The Representastion can have vasrying kind, consult your API",
    )
    cell = models.CharField(
        max_length=1000,
        help_text="The cell thsat was ssrecorded",
    )
    location = models.CharField(
        max_length=1000,
        help_text="The location of the recording",
    )
    position = models.CharField(
        max_length=1000,
        help_text="The position of the recording",
    )
    label = models.CharField(
        max_length=1000,
        help_text="The label of the recording",
    )


class Recording(models.Model):
    trace = models.ForeignKey(
        Trace,
        on_delete=models.CASCADE,
        related_name="recordings",
    )
    simulation = models.ForeignKey(
        Simulation,
        on_delete=models.CASCADE,
        related_name="recordings",
    )
    kind = TextChoicesField(
        choices_enum=enums.RecodingKindChoices,
        default=enums.RecodingKindChoices.VOLTAGE.value,
        help_text="The Representation can have vasrying kind, consult your API",
    )
    cell = models.CharField(
        max_length=1000,
        help_text="The cell of the recording",
    )
    location = models.CharField(
        max_length=1000,
        help_text="The location of the recording",
    )
    position = models.CharField(
        max_length=1000,
        help_text="The position of the recording",
    )
    label = models.CharField(
        max_length=1000,
        help_text="The label of the recording",
    )


class ViewCollection(models.Model):
    """A ViewCollection is a collection of views.

    It is used to group views together, for example to group all views
    that are used to represent a specific channel.

    """

    name = models.CharField(max_length=1000, help_text="The name of the view")
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="view_collections",
        help_text="The organization that owns the view collection",
    )
    provenance = ProvenanceField()


class View(models.Model):
    trace = HistoricForeignKey(Trace, on_delete=models.CASCADE)
    collection = models.ForeignKey(ViewCollection, on_delete=models.CASCADE, null=True, blank=True)
    a_min = models.IntegerField(help_text="The index of the channel", null=True, blank=True)
    a_max = models.IntegerField(help_text="The index of the channel", null=True, blank=True)
    t_min = models.IntegerField(help_text="The index of the channel", null=True, blank=True)
    t_max = models.IntegerField(help_text="The index of the channel", null=True, blank=True)
    c_min = models.IntegerField(help_text="The index of the channel", null=True, blank=True)
    c_max = models.IntegerField(help_text="The index of the channel", null=True, blank=True)
    is_global = models.BooleanField(help_text="Whether the view is global or not", default=False)

    class Meta:
        abstract = True


class TimelineView(View):
    start_time = models.DateTimeField(help_text="The start time of the view", null=True, blank=True)
    end_time = models.DateTimeField(help_text="The end time of the view", null=True, blank=True)


class FileView(View):
    """A FileView links a Trace to the source File it originated from.

    It records that this view of the trace was originally part of the file
    (optionally a specific series within it) and links back to the source file.
    """

    file = models.ForeignKey(File, on_delete=models.CASCADE, related_name="views")
    series_identifier = models.CharField(
        max_length=1000,
        help_text="The series identifier of the file",
        null=True,
        blank=True,
    )

    provenance = ProvenanceField()

    class Meta:
        default_related_name = "file_views"


class ROI(models.Model):
    """A Event is a event area within a trace

    This region is to be regarded as a view on the representation. Depending
    on the implementatoin (type) of the ROI, the view can be constructed
    differently. For example, a rectangular ROI can be constructed by cropping
    the representation according to its 2 vectors. while
      a polygonal ROI can be constructed by masking the
    representation with the polygon.

    The ROI can also store a name and a description. T
    his is used to display the ROI in the UI.

    """

    label = models.CharField(
        max_length=1000,
        help_text="The label of the ROI",
        null=True,
        blank=True,
    )
    trace = models.ForeignKey(
        Trace,
        on_delete=models.CASCADE,
        related_name="rois",
        help_text="The Representation this ROI was original used to create (drawn on)",
    )
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the ROI",
    )
    vectors = models.JSONField(
        max_length=3000,
        help_text="A list of the ROI Vectors (specific for each type)",
        default=list,
    )
    max_t = models.IntegerField(help_text="The maximum time of the ROI", default=0)
    min_t = models.IntegerField(help_text="The minimum time of the ROI", default=0)
    kind = TextChoicesField(
        choices_enum=enums.RoiKindChoices,
        default=enums.RoiKindChoices.SPIKE.value,
        help_text="The Roi can have vasrying kind, consult your API",
    )
    color = models.CharField(max_length=100, blank=True, null=True, help_text="The color of the ROI (for UI)")
    created_at = models.DateTimeField(auto_now=True, help_text="The time the ROI was created")
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_rois",
        blank=True,
        help_text="The users that pinned this ROI",
    )

    provenance = ProvenanceField()

    def __str__(self):
        return f"Event by {self.creator} on {self.trace.name}"


from core import signals
