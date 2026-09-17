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


class ExperimentViewBase(models.Model):
    """What a view of an experiment is: a lens, shown in an experiment. mikro's Layer.

    **No time column.** A view used to carry its own ``offset`` and ``duration``, which let a
    stimulus view and a recording view of *one* simulation state two different offsets and
    silently misalign stimulus and response. Where the data sits is an edge from its clock
    into the experiment's world -- one per clock, so everything timed against that clock moves
    together -- and how much of it is shown is the lens' slices. ``offset`` and ``duration``
    are still readable, derived from those.
    """

    label = models.CharField(max_length=1000, help_text="The label of the view", null=True, blank=True)
    order = models.PositiveIntegerField(default=0, help_text="The position of the view within its experiment, top to bottom")
    visible = models.BooleanField(default=True, help_text="Whether the view is shown")

    class Meta:
        abstract = True
        ordering = ["order", "id"]


class ExperimentRecordingView(ExperimentViewBase):
    """A recording, shown in an experiment."""

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name="recording_views")
    recording = models.ForeignKey("Recording", on_delete=models.CASCADE, related_name="experiment_views")
    lens = models.ForeignKey("core.Lens", on_delete=models.CASCADE, related_name="experiment_recording_views", help_text="The selection of the recording's dataset this view shows")

    def __str__(self) -> str:
        return f"View of recording {self.recording_id} in experiment {self.experiment_id}"


class ExperimentStimulusView(ExperimentViewBase):
    """A stimulus, shown in an experiment."""

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name="stimulus_views")
    stimulus = models.ForeignKey("Stimulus", on_delete=models.CASCADE, related_name="experiment_views")
    lens = models.ForeignKey("core.Lens", on_delete=models.CASCADE, related_name="experiment_stimulus_views", help_text="The selection of the stimulus' dataset this view shows")

    def __str__(self) -> str:
        return f"View of stimulus {self.stimulus_id} in experiment {self.experiment_id}"


class ExperimentAnnotationView(ExperimentViewBase):
    """An annotation collection, shown in an experiment. mikro's annotation layer.

    One view per collection: per-shape styling lives on the annotations themselves. Its
    data lives in the collection's own drawing space, and where that sits on the timeline is
    an edge like any other -- the identity a drawn-on-the-experiment collection is minted
    with, or whatever relates a collection drawn over a dataset to the dataset.
    """

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name="annotation_views")
    collection = models.ForeignKey("core.AnnotationCollection", on_delete=models.CASCADE, related_name="experiment_views", help_text="The annotation collection whose shapes this view shows")

    class Meta(ExperimentViewBase.Meta):
        constraints = [models.UniqueConstraint(fields=["experiment", "collection"], name="one_view_per_collection_per_experiment")]

    def __str__(self) -> str:
        return f"View of annotation collection {self.collection_id} in experiment {self.experiment_id}"


class Block(models.Model):
    """A recording session: the top-level container of Neo's data model.

    A block groups the segments of one session and owns the session's **clock** -- a space
    with one TIME axis whose ``epoch`` is the wall-clock instant the recording started. That
    is where ``recording_time`` went: it is a property of the clock, so that everything laid
    out on it agrees about when it started (see :mod:`core.logic.clocks`).
    """

    # Filing, not containment: deleting the folder unfiles the session, it does not delete it.
    folder = models.ForeignKey(
        "Folder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blocks",
        help_text="The folder this session is filed in. Organisational only",
    )
    origin = models.ForeignKey(
        "File",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blocks",
        help_text="The file this block was read from, if any",
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
        related_name="pinned_blocks",
        blank=True,
        help_text="The users that have pinned the recording session",
    )
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="blocks")
    clock = models.ForeignKey(
        "core.CoordinateSystem",
        # A block is laid out on its clock without living in it: the clock outlives nothing
        # it times, and cannot be deleted from under it.
        on_delete=models.RESTRICT,
        # Nullable only for the `historical*` twin. Every write path sets it.
        null=True,
        blank=True,
        related_name="blocks",
        help_text="The session clock: one TIME axis, whose epoch is the wall-clock instant the recording started",
    )
    provenance = ProvenanceField()

    @property
    def recording_time(self):
        """The wall-clock instant the session started: its clock's epoch."""
        return self.clock.epoch if self.clock_id else None

    def __str__(self) -> str:
        return f"Block {self.pk}: {self.name}"


class BlockSegment(models.Model):
    """One contiguous stretch of a session -- a trial, a sweep, a protocol step. Neo's Segment.

    Every signal of a segment is timed against the segment's ``clock``. That clock is either
    the session's own (the signals' start times are already session-relative, so there is
    nothing to relate) or the segment's own -- related to the session's by one offset edge
    when the segment's start is known, and honestly unrelated when it is not.
    """

    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="segments")
    index = models.PositiveIntegerField(default=0, help_text="The position of the segment within its block")
    name = models.CharField(max_length=1000, null=True, blank=True, help_text="The name of the segment")
    description = models.CharField(max_length=1000, null=True, blank=True)
    clock = models.ForeignKey(
        "core.CoordinateSystem",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="block_segments",
        help_text="The clock this segment's signals are timed against: the session's, or one of its own",
    )
    provenance = ProvenanceField()

    class Meta:
        ordering = ["index", "id"]

    def __str__(self) -> str:
        return f"Segment {self.index} of block {self.block_id}"


class SignalBase(models.Model):
    """What every signal is: a named dataset recorded in a segment.

    A signal is a *spoke on a dataset*, not data in its own right: the samples are the dataset's,
    the dataset lives in its sample grid, and how those samples are timed is an edge from that
    grid onto the segment's clock. Nothing here says when anything happened.
    """

    name = models.CharField(max_length=1000, help_text="The name of the signal", default="")
    description = models.CharField(max_length=1000, null=True, blank=True)

    # `provenance` is declared on each concrete signal, not here: history on an abstract
    # model is not inherited, so the three signals would silently keep no audit trail.

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{type(self).__name__} {self.pk}: {self.name}"


class AnalogSignal(SignalBase):
    """A regularly sampled signal: Neo's AnalogSignal, one ``(t, c)`` dataset for all its channels.

    Its sampling rate and start time are not columns. They are the sampling law: one edge
    from the dataset's sample grid onto the segment's clock, read back as ``samplingRate`` and
    ``tStart``. The unit of its values is the dataset's ``value_unit``.
    """

    segment = models.ForeignKey(BlockSegment, on_delete=models.CASCADE, related_name="analog_signals")
    dataset = models.ForeignKey("ArrayDataset", on_delete=models.CASCADE, related_name="analog_signals", help_text="The samples: one array dataset, with a CHANNEL axis when the signal has more than one channel")
    color = models.CharField(max_length=7, help_text="The color of the signal in HEX", default="#000000")
    pinned_by = models.ManyToManyField(get_user_model(), related_name="pinned_analog_signals", blank=True, help_text="The users that pinned this signal")
    provenance = ProvenanceField()


class IrregularlySampledSignal(SignalBase):
    """A signal sampled at arbitrary instants: Neo's IrregularlySampledSignal.

    It has no sampling law. Its samples are timed by a *lookup* -- a FIELD edge from its sample
    grid onto the segment's clock, whose field is the system of a separate times dataset. That
    times dataset is not a column here: it is read back off the edge (``timeDataset``).
    """

    segment = models.ForeignKey(BlockSegment, on_delete=models.CASCADE, related_name="irregularly_sampled_signals")
    dataset = models.ForeignKey("ArrayDataset", on_delete=models.CASCADE, related_name="irregularly_sampled_signals", help_text="The samples")
    pinned_by = models.ManyToManyField(get_user_model(), related_name="pinned_irregularly_sampled_signals", blank=True, help_text="The users that pinned this signal")
    provenance = ProvenanceField()


class SpikeTrain(SignalBase):
    """The spike times of one unit: Neo's SpikeTrain.

    The dataset's *values are the times* -- one per spike, along an INDEX axis, because spike
    number has no metric. It is timed by a lookup whose field is the dataset's own grid.

    ``t_start`` and ``t_stop`` stay columns, and are the one exception to "derive everything":
    they are the **observation window**, which the spike times cannot reproduce. A train with
    no spikes over ten seconds is a different measurement from one with no spikes over a hundred.
    """

    segment = models.ForeignKey(BlockSegment, on_delete=models.CASCADE, related_name="spike_trains")
    dataset = models.ForeignKey("ArrayDataset", on_delete=models.CASCADE, related_name="spike_trains", help_text="The spike times: one value per spike")
    waveforms = models.ForeignKey(
        "ArrayDataset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="spike_train_waveforms",
        help_text="The spike waveforms, as a (spike, c, t) array dataset",
    )
    t_start = QuantityField(base_unit="picosecond", help_text="The start of the window the unit was observed over, on the segment's clock, stored in picoseconds")
    t_stop = QuantityField(base_unit="picosecond", help_text="The end of the window the unit was observed over, on the segment's clock, stored in picoseconds")
    pinned_by = models.ManyToManyField(get_user_model(), related_name="pinned_spike_trains", blank=True, help_text="The users that pinned this spike train")
    provenance = ProvenanceField()


class BlockGroup(models.Model):
    """A named grouping across a block's segments -- a tetrode, a brain area, a sorted unit. Neo's Group.

    Also where a *non-contiguous* channel selection lives: a lens slices ``start:stop:step``
    and cannot pick channels 0, 3 and 7, but a group can name them.
    """

    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="groups")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    name = models.CharField(max_length=1000, help_text="The name of the group")
    description = models.CharField(max_length=1000, null=True, blank=True)
    analog_signals = models.ManyToManyField(AnalogSignal, related_name="groups", blank=True)
    irregularly_sampled_signals = models.ManyToManyField(IrregularlySampledSignal, related_name="groups", blank=True)
    spike_trains = models.ManyToManyField(SpikeTrain, related_name="groups", blank=True)

    def __str__(self) -> str:
        return f"Group {self.pk}: {self.name}"


class Simulation(models.Model):
    """One run of a neuron model: what was injected, what was recorded, and the clock it ran on.

    Every recording and stimulus of a run is an array dataset of its own, living in its own
    sample grid, and each is timed against the simulation's one ``clock`` by an edge of its
    own: a sampling law when the run recorded at a fixed interval, a time lookup through a
    times dataset when it did not (NEURON's variable time step). That they line up is a fact
    about those edges -- all onto one clock -- not about sharing a grid.

    ``dt`` and ``duration`` stay columns, and are not that edge: they are the *integrator's*
    parameters (NEURON's ``h.dt`` and ``h.tstop``). A run can record at a coarser interval
    than it integrates, so ``dt`` is not the sampling period.
    """

    model = models.ForeignKey(NeuronModel, on_delete=models.CASCADE, related_name="simulations")
    duration = QuantityField(base_unit="picosecond", help_text="How long the model was run for (NEURON's tstop), stored in picoseconds")
    # Nullable, with no default: the old default was one *second*, which no integrator ever
    # used. An unstated time step is unknown, and says so.
    dt = QuantityField(base_unit="picosecond", null=True, blank=True, help_text="The integration time step (NEURON's dt), stored in picoseconds. Not the sampling period")
    clock = models.ForeignKey(
        "core.CoordinateSystem",
        on_delete=models.RESTRICT,
        # Nullable only for the `historical*` twin. Every write path sets it.
        null=True,
        blank=True,
        related_name="simulations",
        help_text="The clock the run's recordings and stimuli are timed against",
    )
    name = models.CharField(max_length=1000, help_text="The name of the run")
    description = models.CharField(max_length=1000, null=True, blank=True)
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

    def __str__(self) -> str:
        return f"Simulation {self.pk}: {self.name}"


class SiteBase(models.Model):
    """Where on the model a stimulus was injected or a recording was taken, and the dataset it produced.

    The site is NEURON's addressing: a cell, a section of it (``location``) and a normalized
    position along that section, 0 to 1. It is not a position in any coordinate system yet --
    no spatial model lives in the graph -- so these stay descriptive fields.
    """

    cell = models.CharField(max_length=1000, null=True, blank=True, help_text="The id of the cell, as the model config names it")
    location = models.CharField(max_length=1000, null=True, blank=True, help_text="The id of the section, as the model config names it")
    position = models.FloatField(null=True, blank=True, help_text="The normalized position along the section, 0 to 1 (NEURON's section(x))")
    label = models.CharField(max_length=1000, null=True, blank=True, help_text="A display label. Defaults to 'cell: location(position)'")

    class Meta:
        abstract = True

    @property
    def display_label(self) -> str:
        """The stated label, or the site spelled out."""
        return self.label or f"{self.cell}: {self.location}({self.position})"


class Stimulus(SiteBase):
    """What was injected into the model at one site, as a dataset over the run's samples."""

    dataset = models.ForeignKey("ArrayDataset", on_delete=models.CASCADE, related_name="stimuli")
    simulation = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name="stimuli")
    kind = TextChoicesField(
        choices_enum=enums.StimulusKindChoices,
        default=enums.StimulusKindChoices.CURRENT.value,
        help_text="What was clamped: current or voltage",
    )

    def __str__(self) -> str:
        return f"Stimulus {self.pk}: {self.display_label}"


class Recording(SiteBase):
    """What was recorded from the model at one site, as a dataset over the run's samples."""

    dataset = models.ForeignKey("ArrayDataset", on_delete=models.CASCADE, related_name="recordings")
    simulation = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name="recordings")
    kind = TextChoicesField(
        choices_enum=enums.RecordingKindChoices,
        default=enums.RecordingKindChoices.VOLTAGE.value,
        help_text="What was recorded: a voltage, a current, or one named ionic current",
    )

    def __str__(self) -> str:
        return f"Recording {self.pk}: {self.display_label}"


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
    Lens,
)
from core.models.annotation import AnnotationCollection, Annotation  # noqa: E402,F401

from core import signals
