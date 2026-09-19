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
from datalayer.models import BigFileStore, ParquetStore, SparseStore, ZarrStore  # noqa: F401  (re-exported, as in mikro)


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
        # Required: `core.scoping` filters on this column, so a row without one is invisible to every scoped read.
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
        # Required: `core.scoping` filters on this column, so a row without one is invisible to every scoped read.
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
    """A composition of recordings and stimuli laid out on one timeline. mikro's Scene, over time.

    ``world`` is *which* space the experiment composes over -- by default a clock in seconds
    with no epoch, because trial-aligned time has no wall clock -- and it is always set. It is
    deliberately not ownership: an experiment adopts a space and never owns it, several
    experiments may share one, and deleting an experiment never deletes it.

    The experiment carries no time facts of its own. Where a recording sits in it is an edge
    from the recording's clock into ``world``; how much of it is shown is a lens.
    """

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
        blank=True,
        help_text="The users that have pinned the experiment",
    )
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="experiments", help_text="The organization that owns the experiment")
    world = models.ForeignKey(
        "core.CoordinateSystem",
        on_delete=models.RESTRICT,
        # Nullable only for the `historical*` twin. Every write path sets it.
        null=True,
        blank=True,
        related_name="experiments",
        help_text="The space this experiment composes over: its timeline. Adopted, never owned",
    )
    provenance = ProvenanceField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Experiment {self.pk}: {self.name}"


class ExperimentLayer(models.Model):
    """One thing drawn in an experiment, and how. mikro's ``Layer``, for time series.

    **Exactly one source**, and the kind says which: a ``lens`` (TRACE, HEATMAP, WAVEFORM -- an
    array dataset drawn as lines, as an image, or as per-unit templates), a ``sparse_dataset``
    (SPIKES -- a raster), a ``table_dataset`` (EVENTS, SERIES, POINT -- rows drawn as marks, as a
    line, or as points in space) or an ``annotation_collection`` (ANNOTATION). mikro checks that in its mutations only; here a CheckConstraint states it
    too, because a layer naming two sources would be placed by whichever the reader asked.

    **No time column**, as there was none on the views this replaced. Where the data sits is an
    edge from its clock into the experiment's world -- one per clock, so everything timed
    against that clock moves together -- and how much of an array is shown is the lens'
    slices. A spikes or events layer has no lens and shows its whole dataset; windowing it is
    the viewer's business, not a second selection vocabulary on the server.

    Everything past the compositing fields is **render state**, per kind, and like mikro's it
    is a flat set of nullable columns rather than a JSON blob: each is read by exactly one kind
    and ignored by the others.
    """

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name="layers", help_text="The experiment this layer is drawn in")
    kind = TextChoicesField(choices_enum=enums.ExperimentLayerKindChoices, help_text="How this layer draws its data, and so which source it has")
    name = models.CharField(max_length=1000, null=True, blank=True, help_text="A display name. Defaults to the source's name")
    blending = TextChoicesField(
        choices_enum=enums.BlendingChoices,
        # NORMAL, not mikro's ADDITIVE: a trace is a line in its own lane, drawn over whatever
        # is beneath it. Summing two voltages' pixels means nothing.
        default=enums.BlendingChoices.NORMAL.value,
        help_text="How this layer composites over the layers below it",
    )
    opacity = models.FloatField(default=1.0, help_text="The layer's opacity, 0 to 1")
    visible = models.BooleanField(default=True, help_text="Whether the layer is shown")
    order = models.IntegerField(default=0, help_text="The position of the layer within its experiment, top to bottom")

    # -- the source: exactly one, matching `kind` ---------------------------------------------
    lens = models.ForeignKey("core.Lens", on_delete=models.CASCADE, null=True, blank=True, related_name="experiment_layers", help_text="(trace) The selection of an array dataset this layer draws")
    sparse_dataset = models.ForeignKey("core.SparseDataset", on_delete=models.CASCADE, null=True, blank=True, related_name="experiment_layers", help_text="(spikes) The spike raster this layer draws")
    table_dataset = models.ForeignKey("core.TableDataset", on_delete=models.CASCADE, null=True, blank=True, related_name="experiment_layers", help_text="(events) The event table this layer draws")
    annotation_collection = models.ForeignKey(
        "core.AnnotationCollection", on_delete=models.CASCADE, null=True, blank=True, related_name="experiment_layers", help_text="(annotation) The annotation collection whose marks this layer draws"
    )

    # -- trace ----------------------------------------------------------------------------------
    channel_index = models.IntegerField(null=True, blank=True, help_text="(trace) The one channel of the lens' CHANNEL axis to draw; null draws every channel, stacked")
    clim_min = models.FloatField(null=True, blank=True, help_text="(trace) The bottom of the value range, in the dataset's value unit; (spikes, amplitude) the bottom of the colormap. Null reads it from the value histogram")
    clim_max = models.FloatField(null=True, blank=True, help_text="(trace) The top of the value range, in the dataset's value unit; (spikes, amplitude) the top of the colormap. Null reads it from the value histogram")
    line_width = models.FloatField(null=True, blank=True, help_text="(trace) The line width, in screen pixels")

    # -- shared by the drawing kinds -----------------------------------------------------------
    color = models.JSONField(null=True, blank=True, help_text="(trace, spikes, events) The base colour as RGBA, 0-255. Null lets the viewer choose")
    colormap = TextChoicesField(choices_enum=enums.ColorMapChoices, null=True, blank=True, help_text="(spikes, events) The colormap an active colour-by or an amplitude is drawn through")

    # -- spikes ---------------------------------------------------------------------------------
    tick_height = models.FloatField(null=True, blank=True, help_text="(spikes) A spike tick's height as a fraction of its unit's row, 0 to 1")
    row_order_column = models.CharField(max_length=255, null=True, blank=True, help_text="(spikes) A column of the table identifying the unit axis to order the rows by (depth, channel); null keeps unit index order")
    value_mode = TextChoicesField(choices_enum=enums.SpikeValueModeChoices, default=enums.SpikeValueModeChoices.PRESENCE.value, help_text="(spikes) What a nonzero value means: one spike, or its amplitude")
    rate_bin = QuantityField(base_unit="picosecond", null=True, blank=True, help_text="(spikes) Draw a firing-rate histogram at this bin width instead of a raster. Null draws the raster")
    spike_color_bys = models.JSONField(default=list, blank=True, help_text="(spikes) The colour pickers over the unit table, each a column-backed colouring; which one is active is `active_color_by`")
    spike_filter_bys = models.JSONField(default=list, blank=True, help_text="(spikes) The filter pickers over the unit table; which apply is `active_filter_bys`")

    # -- heatmap --------------------------------------------------------------------------------
    row_axis = models.CharField(max_length=100, null=True, blank=True, help_text="(heatmap) The lens axis drawn down the image; null resolves to its FREQUENCY axis, else CHANNEL, else INDEX")
    gamma = models.FloatField(null=True, blank=True, help_text="(heatmap) The gamma the colour range is drawn through; null is linear")

    # -- series ---------------------------------------------------------------------------------
    value_column = models.CharField(max_length=255, null=True, blank=True, help_text="(series) The numeric column drawn as the line's value")
    interpolation = TextChoicesField(
        choices_enum=enums.SeriesInterpolationChoices, default=enums.SeriesInterpolationChoices.LINEAR.value, help_text="(series) How consecutive rows are joined"
    )

    # -- waveform -------------------------------------------------------------------------------
    unit_axis = models.CharField(max_length=100, null=True, blank=True, help_text="(waveform) The lens axis enumerating the units; null resolves to its INDEX axis")

    # -- point ----------------------------------------------------------------------------------
    point_size = models.FloatField(null=True, blank=True, help_text="(point) A point's size, in screen pixels")
    size_column = models.CharField(max_length=255, null=True, blank=True, help_text="(point) A numeric column scaling each point's size")

    # -- events, series and point: a table's rows ----------------------------------------------
    stop_column = models.CharField(max_length=255, null=True, blank=True, help_text="(events) A column whose values end each row's interval, in the TIME column's unit; null draws instants")
    label_column = models.CharField(max_length=255, null=True, blank=True, help_text="(events) A column naming each row, drawn beside its mark")
    lane_column = models.CharField(max_length=255, null=True, blank=True, help_text="(events) A categorical column giving each distinct value its own lane; null draws one lane")
    table_color_bys = models.JSONField(default=list, blank=True, help_text="(events, series, point) The colour pickers over the table and what it references; which one is active is `active_color_by`")
    table_filter_bys = models.JSONField(default=list, blank=True, help_text="(events, series, point) The filter pickers over the table and what it references; which apply is `active_filter_bys`")

    # -- picker state (mikro's rule: one active index per layer, whatever its kind) -------------
    active_color_by = models.PositiveSmallIntegerField(null=True, blank=True, help_text="The index of the colour picker in use; null colours by `color`")
    active_filter_bys = models.JSONField(default=list, blank=True, help_text="The indices of the filter pickers in use")

    provenance = ProvenanceField()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            # elektro: mikro enforces "exactly one source" in its mutations only.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind__in=[enums.ExperimentLayerKindChoices.TRACE.value, enums.ExperimentLayerKindChoices.HEATMAP.value, enums.ExperimentLayerKindChoices.WAVEFORM.value],
                        lens__isnull=False, sparse_dataset__isnull=True, table_dataset__isnull=True, annotation_collection__isnull=True,
                    )
                    | models.Q(kind=enums.ExperimentLayerKindChoices.SPIKES.value, lens__isnull=True, sparse_dataset__isnull=False, table_dataset__isnull=True, annotation_collection__isnull=True)
                    | models.Q(
                        kind__in=[enums.ExperimentLayerKindChoices.EVENTS.value, enums.ExperimentLayerKindChoices.SERIES.value, enums.ExperimentLayerKindChoices.POINT.value],
                        lens__isnull=True, sparse_dataset__isnull=True, table_dataset__isnull=False, annotation_collection__isnull=True,
                    )
                    | models.Q(kind=enums.ExperimentLayerKindChoices.ANNOTATION.value, lens__isnull=True, sparse_dataset__isnull=True, table_dataset__isnull=True, annotation_collection__isnull=False)
                ),
                name="experiment_layer_has_the_source_its_kind_names",
            ),
            # One layer per annotation collection per experiment, as there was one view: per-shape
            # styling lives on the annotations themselves.
            models.UniqueConstraint(fields=["experiment", "annotation_collection"], condition=models.Q(annotation_collection__isnull=False), name="one_layer_per_collection_per_experiment"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} layer {self.pk} in experiment {self.experiment_id}"


from core.models.coords import CoordinateSystem, Axis, Transformation  # noqa: E402,F401  (re-exported via core.models)
from core.models.folder import Folder, FolderManager, File, FileLink  # noqa: E402,F401
from core.models.array_dataset import (  # noqa: E402,F401
    ArrayDataset,
    DataArray,
    CoordinateAnchor,
    RigState,
    AcquisitionMetadata,
    ValueHistogram,
    ChannelLabel,
    ValueUnit,
    RecordingSite,
    StimulusSite,
    SimulationState,
    Lens,
)
from core.models.annotation import AnnotationCollection, Annotation  # noqa: E402,F401
from core.models.table_dataset import TableDataset, Column  # noqa: E402,F401
from core.models.sparse_dataset import SparseDataset, SparseArray, SparseAxisReference  # noqa: E402,F401

from core import signals
