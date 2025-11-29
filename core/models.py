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
from core.datalayer import Datalayer

# Create your models here.
import boto3
import json
from django.conf import settings
from django.core.cache import cache
from authentikate.models import Organization, Membership
from polymorphic.models import PolymorphicModel


class DatasetManager(models.Manager):
    def get_current_default_for_user(self, user):
        potential = self.filter(creator=user, is_default=True).first()
        if not potential:
            return self.create(creator=user, name="Default", is_default=True)

        return potential


class Dataset(models.Model):
    """
    A dataset is a collection of data files and metadata files.
    It mimics the concept of a folder in a file system and is the top level
    object in the data model.

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

    objects = DatasetManager()

    def __str__(self) -> str:
        return super().__str__()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["creator", "is_default"],
                name="unique_default_per_creator",
                condition=models.Q(is_default=True),
            ),
        ]


class Instrument(models.Model):
    name = models.CharField(max_length=1000)
    manufacturer = models.CharField(max_length=1000, null=True, blank=True)
    model = models.CharField(max_length=1000, null=True, blank=True)
    serial_number = models.CharField(max_length=1000, unique=True)

    provenance = ProvenanceField()


class S3Store(models.Model):
    path = S3Field(null=True, blank=True, help_text="The store of the image", unique=True)
    key = models.CharField(max_length=1000)
    bucket = models.CharField(max_length=1000)
    populated = models.BooleanField(default=False)


class ZarrStore(S3Store):
    shape = models.JSONField(null=True, blank=True)
    chunks = models.JSONField(null=True, blank=True)
    dtype = models.CharField(max_length=1000, null=True, blank=True)

    def fill_info(self, datalayer: Datalayer) -> None:
        # Create a boto3 S3 client
        s3 = datalayer.s3v4

        # Extract the bucket and key from the S3 path
        bucket_name, prefix = self.path.replace("s3://", "").split("/", 1)

        # List all files under the given prefix
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)

        # Check if the '.zarray' file exists and retrieve its content
        for obj in response.get("Contents", []):
            if obj["Key"].endswith(".zarray"):
                array_name = obj["Key"].split("/")[-2]
                assert array_name == "data", "If using zarr v2, the array name must be 'data'"

                # Get the content of the '.zarray' file
                zarray_file = s3.get_object(Bucket=bucket_name, Key=obj["Key"])
                zarray_content = zarray_file["Body"].read().decode("utf-8")
                zarray_json = json.loads(zarray_content)

                # Retrieve the 'shape' and 'chunks' attributes

                self.shape = zarray_json.get("shape")
                self.chunks = zarray_json.get("chunks")
                self.dtype = zarray_json.get("dtype")
                self.version = "2"
                break

            if obj["Key"].endswith("zarr.json"):
                array_name = obj["Key"].split("/")[-2]

                # Get the content of the '.zarray' file
                zarray_file = s3.get_object(Bucket=bucket_name, Key=obj["Key"])
                zarray_content = zarray_file["Body"].read().decode("utf-8")
                zarray_json = json.loads(zarray_content)
                if zarray_json["node_type"] == "array":
                    self.shape = zarray_json["shape"]
                    self.chunks = zarray_json.get("chunk_grid", {}).get("configuration", {}).get("chunk_shape", [])
                    self.dtype = zarray_json["data_type"]
                    self.version = "3"
                    break

        assert self.shape is not None, "Could not find shape in zarr store"
        self.populated = True
        self.save()

    @property
    def c_size(self):
        return self.shape[0]

    @property
    def t_size(self):
        return self.shape[1]

    @property
    def z_size(self):
        return self.shape[2]

    @property
    def y_size(self):
        return self.shape[3]

    @property
    def x_size(self):
        return self.shape[4]


class ParquetStore(S3Store):
    pass

    def fill_info(self) -> None:
        pass

    @property
    def duckdb_string(self):
        return f"read_parquet('s3://{self.bucket}/{self.key}')"


class BigFileStore(S3Store):
    pass

    def fill_info(self) -> None:
        pass

    def get_presigned_url(
        self,
        info,
        datalayer: Datalayer,
        host: str | None = None,
    ) -> str:
        s3 = datalayer.s3
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self.key,
            },
            ExpiresIn=3600,
        )
        return url.replace(settings.AWS_S3_ENDPOINT_URL, host or "")


class MediaStore(S3Store):
    def get_presigned_url(self, info, datalayer: Datalayer, host: str | None = None) -> str:
        cache_key = f"presigned_url:{self.bucket}:{self.key}:{host}"
        # Check if the URL is in the cache
        url = cache.get(cache_key)

        if not url:
            # Generate a new presigned URL if not cached
            s3 = datalayer.s3
            url = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": self.key,
                },
                ExpiresIn=3600,
            )
            # Replace the endpoint URL
            url = url.replace(settings.AWS_S3_ENDPOINT_URL, host or "")
            # Cache the URL with a timeout of 3600 seconds (same as ExpiresIn)
            cache.set(cache_key, url, timeout=3600)

        return url

    def put_file(self, datalayer: Datalayer, file: FileField):
        s3 = datalayer.s3
        s3.upload_fileobj(file, self.bucket, self.key)
        self.save()


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


class HocEnvironment(models.Model):
    """A hoc environment is a set of hoc.mode
    file  that can be used to simulate a neuron model.

    They are stored as zip files in S3 and will be
    downloaded and extracted when a neuron model
    is simulated. They will be cached locally for
    faster access.

    """

    hash = models.CharField(
        max_length=1000,
        help_text="The hash of the hoc file",
        unique=True,
    )
    name = models.CharField(max_length=1000, help_text="The name of the hoc environment")
    store = models.ForeignKey(
        BigFileStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the file",
    )


class NeuronModel(models.Model):
    """A NEURON model
    that can be used t simulate a neuron
    """

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="The parent model of the neuron",
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


class Experiment(models.Model):
    name = models.CharField(max_length=1000, help_text="The name of the experiment")
    description = models.CharField(max_length=1000, null=True, blank=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the experiment",
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
    offset = models.FloatField(help_text="The offset of the view in seconds", null=True, blank=True)
    duration = models.FloatField(help_text="The duration of the view in seconds", null=True, blank=True)
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
    offset = models.FloatField(help_text="The offset of the view in seconds", null=True, blank=True)
    duration = models.FloatField(help_text="The duration of the view in seconds", null=True, blank=True)
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
    t_start = models.FloatField(help_text="The start time of the signal in seconds", default=0.0)
    description = models.CharField(max_length=1000, null=True, blank=True)
    sampling_rate = models.FloatField(help_text="The sampling frequency of the signal in Hz", default=1000.0)
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
    duration = models.FloatField(help_text="The duration of the run in seconds")
    dt = models.FloatField(help_text="The time step of the run in seconds", default=1.0)
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
