"""The data layer: array datasets, their pyramid levels, their anchors, and lenses over them.

**Vendored from mikro** (``mikro/core/models/array_dataset.py``), identifiers and all: this
service holds the same kind of data mikro does -- n-dimensional zarr arrays that live in a
coordinate system -- and differs only in how it *interprets* them. mikro reads an array as a
layer in a scene; elektro reads it as a signal in a block, a recording of a simulation, a
view in an experiment (``core/models/__init__.py``). Nothing in this module knows which.

What was cut: ``default_scene`` (there are no scenes), the light path and the phasor spokes.
What was renamed: mikro's ``OptikitState`` spoke is :class:`RigState` (``rigkit`` is to an
electrophysiology rig what ``optikit`` is to a microscope) and its ``OmeMetadata`` slot is
:class:`AcquisitionMetadata`. What was added: :class:`ValueUnit`, because an ephys array's
values carry a unit (mV, pA) and a pixel's do not.
"""

from django.db import models
from django.contrib.auth import get_user_model
from core import enums
from koherent.fields import ProvenanceField
from embeddings.models import EmbeddedDescriptionMixin, embedding_indexes
from django_choices_field import TextChoicesField
from kanne_server.fields import QuantityField
from authentikate.models import Organization
from django.db.models import Q
from datalayer.models import ZarrStore
from django.contrib.postgres.indexes import GinIndex
from core.base_models import slices as base_models
from core.logic import coords as coords_logic
from core.models.coords import CoordinateSystem, Transformation  # noqa: F401  (re-exported via core.models)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models.sparse_dataset import SparseDataset
    from core.models.table_dataset import TableDataset


class ArrayDataset(EmbeddedDescriptionMixin, models.Model):
    """A multi-dimensional array of data, with one or more pyramid levels attached as DataArrays.

    The dataset's dimensions and their types live on the axes of its INTRINSIC
    :class:`~core.models.CoordinateSystem` -- its level-0 pixel grid -- and its
    shape is the shape of its level-0 array. Physical units live on its
    physical spaces (unit-carrying systems), never here. Almost none of it is duplicated on
    columns: the properties below derive it, so there is no second copy that can
    disagree. That includes ``multiscale``, which is simply "more than one level".

    The one materialized exception is ``stored_spec`` (read back through the ``spec``
    property): the list of :class:`~core.enums.ArrayDatasetSpec` the axes satisfy, written
    once at creation. It is safe to store precisely because the axes are immutable (see
    below) -- a value computed from immutable inputs at write time cannot disagree with
    its source, the same reason ``DataArray`` stores its absolute scale on the edge at
    write time rather than re-deriving it. The single source of truth stays
    :func:`core.logic.coords.specs_for_axes`; the column is materialized *from* it by the
    axis writer, never re-derived on read.

    **Only ``name`` and ``description`` are editable**, through ``updateArrayDataset``. Everything
    that says where the data *is* -- the arrays, the axes, the systems built from them -- is
    written at creation and never after: ``Axis.order`` is written by enumeration and the rest
    of the graph is measured against it, so an axis edit is a different space rather than a
    correction, and ``updateCoordinateSystem`` refuses a dataset's own system for that reason
    (it serves shared spaces alone). A recomputation is a new dataset.

    Both editable fields are audited. ``provenance`` records a history row per save, attributed
    to the client, user and task the change happened under, and reads back as
    ``provenanceEntries``. A rename is the only thing about a dataset that can change, which is
    exactly why it is worth knowing who changed it.
    """

    name = models.CharField(max_length=1000, help_text="The name of the data source")
    description = models.CharField(max_length=1000, help_text="The description of the data source", null=True)

    # Residence, not ownership (RFC-9). The dataset lives in a space; the space does not
    # belong to the dataset. A plain FK rather than a one-to-one because several datasets
    # genuinely may share one frame -- a hundred tiles acquired on one stage -- while two
    # unrelated acquisitions get their own because the writer creates one each.
    coordinate_system = models.ForeignKey(
        CoordinateSystem,
        on_delete=models.PROTECT,
        # Nullable in the database only because the `historical*` twin carries rows written
        # before this column existed, and a history row must be allowed to say "not
        # recorded". Every write path sets it, so a live row never has none.
        null=True,
        blank=True,
        related_name="datasets",
        help_text="The coordinate system this dataset's pixels are expressed in: its level-0 grid. PROTECT, because a space cannot be deleted while data lives in it",
    )

    # Filing, not placement. A folder says where a user keeps this dataset; it says nothing
    # about what space the data is in -- that is the coordinate graph's job, and the two must
    # never be read as one. Nullable because a dataset can exist unfiled, and because every
    # row predating this column has no answer; the create mutation files new ones in the
    # user's default folder, exactly as `create_image_from_array` has always done for images.
    folder = models.ForeignKey(
        "Folder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="array_datasets",
        help_text="The folder this dataset is filed in. Organisational only -- it says nothing about where the data sits in space",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="The time the data source was created")
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, null=True, blank=True, help_text="The user that created the data source")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, help_text="The organization the data source belongs to")
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
    # The embedding columns are storage, not an edit: keep them out of the history rows.
    provenance = ProvenanceField(excluded_fields=["embedding", "embedding_model"])

    stored_spec = models.JSONField(
        default=list,
        help_text=(
            "What this dataset structurally is: the raw ArrayDatasetSpec values (one spatial member plus a "
            "modifier per acquisition axis) that its intrinsic axes satisfy, materialized at creation by "
            "the axis writer from core.logic.coords.specs_for_axes. Immutable because the axes are, so it "
            "cannot disagree with them. Read it back as enum members through the `spec` property. Empty "
            "while the intrinsic system does not exist yet."
        ),
    )

    class Meta:
        indexes = [
            GinIndex(fields=["stored_spec"], name="array_dataset_spec_gin"),
            # The embedding healer's "any row not by the current model?" probe.
            *embedding_indexes("array_dataset"),
        ]

    @property
    def intrinsic_coordinate_system(self):
        """The space this dataset's pixels live in. An alias for `coordinate_system`.

        Kept because a great deal of the graph layer says "intrinsic" to mean "the grid the
        geometry is measured against", and that is still what this is -- it is simply no
        longer a *kind* of system, just the one this dataset lives in.
        """
        return self.coordinate_system

    @property
    def multiscale(self) -> bool:
        """Whether this dataset carries a resolution pyramid. Derived: more than one level."""
        return self.data_arrays.count() > 1

    @property
    def axes(self) -> list:
        """The dataset's axes, in array order."""
        system = self.intrinsic_coordinate_system
        return list(system.axes.all()) if system else []

    @property
    def axis_specs(self) -> list[coords_logic.AxisSpec]:
        """The dataset's axes, coerced for :mod:`core.logic.coords`."""
        return [coords_logic.AxisSpec(name=axis.name, type=axis.type) for axis in self.axes]

    @property
    def axis_names(self) -> list:
        """The dataset's axis names, in array order. Derived from the intrinsic axes."""
        return [axis.name for axis in self.axes]

    @property
    def spec(self) -> list:
        """Every spec this dataset's axes satisfy: what it structurally is.

        Read from ``stored_spec``, materialized at creation from the intrinsic
        axes -- not re-derived on read. The axes are immutable, so the column
        cannot disagree with them; this is the same write-time materialization as
        ``DataArray``'s absolute scale.

        Empty -- not SCALAR -- when the intrinsic system did not exist at creation:
        a dataset whose axes are unknown has no spatial extent to report, and
        claiming SCALAR would say it has none. A genuine no-SPACE-axis dataset
        stores ``['SCALAR', ...]``, so the two stay distinguishable.
        """
        return [enums.ArrayDatasetSpec(value) for value in self.stored_spec]

    @property
    def shape_list(self) -> list:
        """The dataset's shape: that of its level-0 array."""
        base = self.data_arrays.order_by("level").first()
        return base.shape if base and isinstance(base.shape, list) else []

    @property
    def value_unit(self) -> str | None:
        """The unit of this dataset's VALUES (mV, pA, s for a times dataset), or None.

        Read from the dataset-wide :class:`ValueUnit` anchor -- the one pinned to no
        coordinate. A per-channel unit (``{"c": 3}``) is a different fact and is not an
        answer here: a dataset whose channels disagree has no single value unit.
        """
        spoke = ValueUnit.objects.filter(anchor__dataset=self, anchor__coordinates={}).first()
        return spoke.unit if spoke else None


class DataArray(models.Model):
    """One level of a dataset's resolution pyramid: a zarr-backed array.

    A downsampled level's voxel-index space is an ARRAY
    :class:`~core.models.CoordinateSystem`, and the map from that space into the
    dataset's intrinsic space is a stored :class:`~core.models.Transformation`.
    Every level maps into the *same* intrinsic system -- a star, not a chain -- so
    no level's placement depends on another's. Level 0 owns no system and no edge:
    the INTRINSIC system *is* the level-0 pixel grid, by definition, and a second
    node for the same space joined by an all-ones SCALE edge would record nothing
    (see :attr:`space`).

    The old ``scale_factors`` column is gone. It stored *nominal* factors
    (1, 2, 4, 8, ...), which a real pyramid does not obey: a 36-voxel axis floors
    to 36, 18, 9, 4, 2, 1, whose true factors are 1, 2, 4, 9, 18, 36. The
    absolute scale is now derived from the actual shapes at write time, by
    :func:`core.logic.coords.pyramid_transform`, and stored on the edge.
    """

    store = models.ForeignKey(
        ZarrStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the data array",
    )
    shape = models.JSONField(help_text="The shape of the data array")
    chunk_shape = models.JSONField(help_text="The chunk shape of the data array")

    dataset = models.ForeignKey(ArrayDataset, on_delete=models.CASCADE, related_name="data_arrays")
    level = models.IntegerField(help_text="The level of the data array in the resolution pyramid, 0 being the highest resolution")

    # A fact of the level, not of the dataset -- the same reason `shape` lives here: a
    # pyramid may well have been built one level at a time by different code. Null on level
    # 0, which was not downsampled from anything, and null on a level whose writer did not
    # say. Stated rather than derived: two arrays are all that survives a downsample, and
    # nothing in the numbers says whether they were averaged or picked.
    scale_method = TextChoicesField(
        choices_enum=enums.ScaleMethodChoices,
        null=True,
        blank=True,
        help_text="How this level's voxels were computed from the level above it. Null for level 0, and for a level whose writer did not say. Over a dataset whose values are object ids only NEAREST and MODE are accepted -- everything else returns numbers that were not in the input, and an invented id is an object that does not exist",
    )

    # Always set, including for level 0 -- which is where this shape pays off. Level 0 used
    # to own *no* system, with a null and a "means the dataset's own grid" convention to
    # explain it; under residence it simply lives in that grid, pointing at the same node the
    # dataset does. The special case is gone rather than ported.
    coordinate_system = models.ForeignKey(
        CoordinateSystem,
        on_delete=models.PROTECT,
        # Nullable in the database only because the `historical*` twin carries rows written
        # before this column existed, and a history row must be allowed to say "not
        # recorded". Every write path sets it, so a live row never has none.
        null=True,
        blank=True,
        related_name="data_arrays",
        help_text="The coordinate system this level's voxels are expressed in. Level 0 shares its dataset's; every downsampled level has its own, with a stored edge relating the two",
    )

    class Meta:
        """Meta options for the data array."""

        # Everything -- the dataset's shape, the lens edges, the pyramid
        # derivation -- keys off "the level-0 array". Two arrays claiming the
        # same level would make all of it silently ambiguous.
        constraints = [
            models.UniqueConstraint(fields=["dataset", "level"], name="one_data_array_per_level"),
        ]

    @property
    def space(self):
        """The coordinate system this level's voxels live in.

        Level 0 owns no system: the dataset's INTRINSIC system *is* the level-0 pixel
        grid, by definition, so this resolves to it. Higher levels own an ARRAY system
        and a stored edge into intrinsic.
        """
        return getattr(self, "coordinate_system", None) or (self.dataset.intrinsic_coordinate_system if self.level == 0 else None)

    @property
    def to_parent(self):
        """The stored edge from this level's voxel space into the dataset's intrinsic space.

        None for level 0: its space IS the intrinsic space, and an identity edge between one
        space and itself would be a stored fact carrying no information.

        **Both endpoints, and top-level only.** Filtering on ``input`` alone used to be enough,
        back when a level-0 array owned no system: the only edge out of a level's own space was
        its own. Under residence (level 0 shares the dataset's grid) every physical-space edge
        and every registration also leaves that space, so an input-only filter returned whichever
        of them sorted first under ``Meta.ordering`` -- a registration into a world, presented as
        the pyramid edge, exactly where this docstring promises ``None``. Naming the output pins
        it to the one edge `core.logic.graph.create_level_edge` wrote, and ``parent__isnull``
        keeps a SEQUENCE's child from standing in for its wrapper.
        """
        system = getattr(self, "coordinate_system", None)
        intrinsic = self.dataset.intrinsic_coordinate_system
        if system is None or intrinsic is None or system.pk == intrinsic.pk:
            return None
        return Transformation.objects.filter(input=system, output=intrinsic, parent__isnull=True).first()


# ==========================================
# 2. THE HUB & SPOKES (Metadata)
# ==========================================


class CoordinateAnchor(models.Model):
    """The Axis-Agnostic Hub: the one place metadata spokes are pinned to coordinates.

    An anchor belongs to exactly one container: an :class:`ArrayDataset`, whose coordinates
    are level-0 sample indices keyed by axis name; a :class:`TableDataset`, whose
    coordinates are values of its coordinate columns keyed by column name; or a
    :class:`SparseDataset`, whose coordinates are positions along its enumerated axes. Either
    way an omitted axis means "global along it", and the spokes hanging off the anchor are the
    same models -- a per-unit table carries the rig state and the acquisition metadata of
    the recording it was computed from.

    ``organization`` is denormalised on purpose. Tenant scoping (:mod:`core.scoping`) walks
    only non-nullable foreign keys to find the organization, and with two nullable
    containers there is no required path to walk. The same shape as :class:`FileLink`.
    """

    id = models.BigAutoField(primary_key=True)
    dataset = models.ForeignKey(
        ArrayDataset,
        related_name="anchors",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The array dataset this anchor pins into. Null otherwise",
    )
    table = models.ForeignKey(
        "TableDataset",
        related_name="anchors",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The table dataset this anchor pins into. Null otherwise",
    )
    sparse = models.ForeignKey(
        "SparseDataset",
        related_name="anchors",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The sparse dataset this anchor pins into. Null otherwise",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="coordinate_anchors",
        help_text="The organization of the anchor's container, denormalised so tenant scoping has a required path to walk",
    )
    coordinates = models.JSONField(
        default=dict,
        help_text=(
            "The coordinates this anchor is pinned to, keyed by axis name, e.g. {'c': 0, 't': 5}. For an array dataset these are level-0 sample indices (its INTRINSIC space); "
            "for a table dataset they are values of its coordinate columns, keyed by column name; for a sparse dataset they are positions along its enumerated axes. An omitted axis "
            "means global along it"
        ),
    )

    class Meta:
        indexes = [GinIndex(fields=["coordinates"], name="anchor_coords_gin")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(dataset__isnull=False, table__isnull=True, sparse__isnull=True)
                    | Q(dataset__isnull=True, table__isnull=False, sparse__isnull=True)
                    | Q(dataset__isnull=True, table__isnull=True, sparse__isnull=False)
                ),
                name="coordinate_anchor_has_exactly_one_container",
            )
        ]

    @property
    def container(self) -> "ArrayDataset | TableDataset | SparseDataset":
        """The dataset, table or sparse dataset this anchor belongs to: the owner for scoping and deletion."""
        if self.dataset_id is not None:
            return self.dataset
        if self.table_id is not None:
            return self.table
        return self.sparse

    def save(self, *args, **kwargs) -> None:
        """Fill ``organization`` from the container so every write path stays a one-liner."""
        if self.organization_id is None and self.container is not None:
            self.organization_id = self.container.organization_id
        super().save(*args, **kwargs)


class RigState(models.Model):
    """1:1 Spoke (Hardware Truth): the state of the rig -- see :mod:`rigkit`."""

    anchor = models.OneToOneField(CoordinateAnchor, related_name="rig", on_delete=models.CASCADE)
    state = models.JSONField(default=dict)


class AcquisitionMetadata(models.Model):
    """N:1 Spoke (File Truth): whatever the acquisition format said, kept as it said it."""

    anchor = models.OneToOneField(CoordinateAnchor, related_name="acquisition_metadata", on_delete=models.CASCADE)
    metadata = models.JSONField(default=dict)


class ValueHistogram(models.Model):
    """N:1 Spoke (Pixel Value Distribution)"""

    anchor = models.OneToOneField(CoordinateAnchor, related_name="value_histogram", on_delete=models.CASCADE)
    histogram = models.JSONField(default=list, help_text="The histogram of the pixel values (y values)")
    bins = models.JSONField(default=list, help_text="The bin indices of the histogram (x values)")
    min = models.FloatField(help_text="The minimum pixel value of the histogram", null=True, blank=True)
    max = models.FloatField(help_text="The maximum pixel value of the histogram", null=True, blank=True)
    p1 = models.FloatField(help_text="The first percentile of the pixel values", null=True, blank=True)
    p99 = models.FloatField(help_text="The 99th percentile of the pixel values", null=True, blank=True)


class ChannelLabel(models.Model):
    """N:1 Spoke (Channel Truth)"""

    anchor = models.OneToOneField(CoordinateAnchor, related_name="channel_label", on_delete=models.CASCADE)
    label = models.CharField(max_length=1000, help_text="The label of the channel", null=True, blank=True)


class ValueUnit(models.Model):
    """N:1 Spoke (Value Truth): what the array's values measure.

    Not an axis and not a column. An axis says *where* a sample is; this says what was
    measured there, and it may differ along an axis -- a (t, c) recording whose channels are
    a membrane potential and a command current has two. Anchored at ``{}`` it speaks for the
    whole dataset (``ArrayDataset.value_unit``); anchored at ``{"c": 3}`` for one channel.
    """

    anchor = models.OneToOneField(CoordinateAnchor, related_name="value_unit", on_delete=models.CASCADE)
    unit = models.CharField(max_length=64, help_text="The unit of the values, as a pint unit validated on write; 'a.u.' for arbitrary units")


class SiteBase(models.Model):
    """A place on a :class:`NeuronModel` where a stimulus was injected or a recording was taken. elektro's own spoke.

    A site is part of a neuron model: it names the model (``model``, required) and addresses a
    place *in* it the way NEURON does -- a cell of the model's config, a section of that cell
    (``location``) and a normalized position along that section, 0 to 1. ``cell`` and
    ``location`` are ids the model's ``json_model`` declares, checked on write
    (`core.logic.sites`). It is not a position in any coordinate system -- no morphology lives
    in the graph -- so these stay descriptive fields.

    It used to be the ``Recording`` and ``Stimulus`` *rows* of a simulation, each naming a
    dataset. A site is a fact of the measurement -- where the electrode was -- not of the run,
    so it lives with the data, beside the rig state, and a dataset carries it whichever run (or
    none) it is timed against. Which run that is, is a fact of the graph: the dataset's grid is
    timed onto the run's clock. Anchored at ``{}`` it speaks for the whole dataset, at
    ``{"c": 1}`` for one channel of a multi-site recording.
    """

    cell = models.CharField(max_length=1000, null=True, blank=True, help_text="The id of the cell, one of the cells the site's neuron model declares")
    location = models.CharField(max_length=1000, null=True, blank=True, help_text="The id of the section, one of the sections of that cell of the site's neuron model")
    position = models.FloatField(null=True, blank=True, help_text="The normalized position along the section, 0 to 1 (NEURON's section(x))")
    label = models.CharField(max_length=1000, null=True, blank=True, help_text="A display label. Defaults to 'cell: location(position)'")

    class Meta:
        abstract = True

    @property
    def display_label(self) -> str:
        """The stated label, or the site spelled out."""
        return self.label or f"{self.cell}: {self.location}({self.position})"


class RecordingSite(SiteBase):
    """1:1 Spoke (Site Truth): the values here were *recorded* from this site of a neuron model."""

    anchor = models.OneToOneField(CoordinateAnchor, related_name="recording_site", on_delete=models.CASCADE)
    # After ``anchor``: the org path follows the first required FK, and a site's organization
    # is its dataset's, not its model's.
    model = models.ForeignKey(
        "core.NeuronModel",
        on_delete=models.CASCADE,
        related_name="recording_sites",
        help_text="The neuron model this site is part of: the model whose cell, section and position it names",
    )
    kind = TextChoicesField(
        choices_enum=enums.RecordingKindChoices,
        default=enums.RecordingKindChoices.VOLTAGE.value,
        help_text="What was recorded: a voltage, a current, or one named ionic current",
    )


class StimulusSite(SiteBase):
    """1:1 Spoke (Site Truth): the values here were *injected* at this site of a neuron model."""

    anchor = models.OneToOneField(CoordinateAnchor, related_name="stimulus_site", on_delete=models.CASCADE)
    # After ``anchor``: the org path follows the first required FK, and a site's organization
    # is its dataset's, not its model's.
    model = models.ForeignKey(
        "core.NeuronModel",
        on_delete=models.CASCADE,
        related_name="stimulus_sites",
        help_text="The neuron model this site is part of: the model whose cell, section and position it names",
    )
    kind = TextChoicesField(
        choices_enum=enums.StimulusKindChoices,
        default=enums.StimulusKindChoices.CURRENT.value,
        help_text="What was clamped: current or voltage",
    )



class SimulationState(models.Model):
    """1:1 Spoke (Integrator Truth): these values were *computed*, by integrating a neuron model.

    The synthetic rig. Where a wet recording carries its :class:`RigState` -- clamp mode,
    temperature, the amplifier's settings -- a simulated output carries the integrator's: the
    model that was run (``model``), NEURON's ``dt`` and ``tstop`` (``duration``). A fact of the
    data, like every spoke, so it lives with the data.

    **A run is its clock.** There is no run row: the clock minted for a run is a node with an
    identity of its own, which run a trace belongs to is its timing edge onto that clock, and
    what the run was is this spoke on each output, checked to agree on every clock
    (``clocks.assert_one_run``). An input -- a stimulus waveform -- carries no spoke and may be
    timed onto many runs' clocks. The sites of the same dataset name the same model
    (`core/mutations/array_dataset.py`).

    ``dt`` is not the sampling period: a run can record more coarsely than it integrates, and
    how its samples are timed is the dataset's sampling law or time lookup onto the clock.
    """

    anchor = models.OneToOneField(CoordinateAnchor, related_name="simulation", on_delete=models.CASCADE)
    # After ``anchor``: the org path follows the first required FK, and the spoke's
    # organization is its dataset's, not its model's.
    model = models.ForeignKey(
        "core.NeuronModel",
        on_delete=models.CASCADE,
        related_name="simulation_states",
        help_text="The neuron model that was integrated to compute these values",
    )
    duration = QuantityField(base_unit="picosecond", help_text="How long the model was run for (NEURON's tstop), stored in picoseconds")
    # Nullable, with no default: an unstated time step is unknown, and says so.
    dt = QuantityField(base_unit="picosecond", null=True, blank=True, help_text="The integration time step (NEURON's dt), stored in picoseconds. Not the sampling period")


class Lens(models.Model):
    """A selection over a dataset. Nothing else.

    Its shape and dimensions are derived from the dataset and the slices -- they
    were columns, and two people computing them from the same slices are
    guaranteed to agree, so there was no reason for a second copy that could
    drift.

    A *sliced* lens has its own coordinate system, and the edge back to the dataset
    is a stored :class:`~core.models.Transformation`. Before that, slicing shifted
    voxel coordinates and nothing recorded the shift: an ROI drawn on a cropped
    lens had no defined path back to its dataset. An **unsliced** lens selects
    everything, so its space is the dataset's intrinsic space by definition -- it
    owns no system and no edge (see :attr:`space`), because a second node for the
    same space joined by an identity edge would record nothing. Lenses are
    immutable, so the decision is made once, at creation.

    The lens-to-parent edge is **derived from the slices, never authored** --
    recreating a lens from its slices reproduces its geometry exactly. In
    particular, per-channel corrections (chromatic drift) are not lens
    properties: they are acquisition facts, and a correction stored on a view
    would be a second copy free to disagree with the next view of the same
    channel. The supported interim pattern is one lens per channel plus a
    scene-level registration edge authored from the lens' system
    (``createTransformation`` accepts any input system, and the search in
    :mod:`core.logic.graph` takes the direct edge because it is both the
    best-known route and the shortest -- not because directness is itself
    preferred; there is no such rule). If channel-wise correction becomes a
    first-class need, it will be a dataset-owned ``aligned`` system with one
    channel-wise edge from intrinsic -- the physical-space pattern again, never
    per-view state.
    """

    dataset = models.ForeignKey(ArrayDataset, on_delete=models.CASCADE, related_name="lenses")
    slices = models.JSONField(help_text="The selection this lens makes over its dataset, as a list of per-dimension slices", default=list)

    # Always set. An unsliced lens used to own no system, with a null standing for "the
    # dataset's grid"; under residence it lives in that grid and points at the same node.
    coordinate_system = models.ForeignKey(
        CoordinateSystem,
        on_delete=models.PROTECT,
        # Nullable in the database only because the `historical*` twin carries rows written
        # before this column existed, and a history row must be allowed to say "not
        # recorded". Every write path sets it, so a live row never has none.
        null=True,
        blank=True,
        related_name="lenses",
        help_text="The coordinate system this lens' voxels are expressed in. An unsliced lens shares its dataset's; a sliced one has its own, with a stored edge carrying the shift",
    )

    provenance = ProvenanceField()

    @property
    def slices_list(self) -> list[base_models.SliceModel]:
        """Return the slices of the lens as a list."""
        return [base_models.SliceModel(**slice_dict) for slice_dict in self.slices] if isinstance(self.slices, list) else []

    @property
    def axis_names(self) -> list:
        """The lens' axis names. A selection never drops or reorders an axis."""
        return self.dataset.axis_names

    @property
    def axis_specs(self) -> list[coords_logic.AxisSpec]:
        """The lens' axes, coerced for :mod:`core.logic.coords`."""
        return self.dataset.axis_specs

    @property
    def shape_list(self) -> list:
        """The shape this lens' slices cut out of its dataset."""
        return coords_logic.lens_shape(self.dataset.shape_list, self.dataset.axis_names, self.slices_list)

    @property
    def space(self):
        """The coordinate system this lens' selection is expressed in.

        A lens with no slices selects everything, so its space is the dataset's
        intrinsic space *by definition* and it owns no system -- the same rule as a
        level-0 array. A sliced lens shifts voxel coordinates, which is a real fact,
        so it owns a system and the derived edge that records the shift.
        """
        return getattr(self, "coordinate_system", None) or self.dataset.intrinsic_coordinate_system

    @property
    def to_parent(self):
        """The stored edge from this lens' space back into its dataset's intrinsic space.

        None for an unsliced lens: its space IS the intrinsic space, and there is no shift to
        record.

        Both endpoints named, and top-level only, for the same reason as
        :attr:`DataArray.to_parent` -- an input-only filter returns any edge leaving the space,
        which for an unsliced lens (sharing the dataset's grid) is every registration the dataset
        has.
        """
        system = getattr(self, "coordinate_system", None)
        intrinsic = self.dataset.intrinsic_coordinate_system
        if system is None or intrinsic is None or system.pk == intrinsic.pk:
            return None
        return Transformation.objects.filter(input=system, output=intrinsic, parent__isnull=True).first()

    def get_size_of_axis(self, axis_name: str) -> int:
        """Get the size of an axis by its name."""
        axis_names, shape = self.axis_names, self.shape_list
        try:
            return shape[axis_names.index(axis_name)]
        except ValueError as error:
            raise ValueError(f"Axis {axis_name} not found in lens axes {axis_names}.") from error

    @property
    def active_anchors(self):
        """
        THE WORKSPACE QUERY:
        Finds all anchors that fall within the boundaries of this Lens.
        Respects the "Axis-Agnostic" rule: If an anchor is global ({})
        or partial ({"c": 0}), it is included as long as it doesn't contradict the Lens.
        """
        qs = CoordinateAnchor.objects.filter(dataset=self.dataset)

        # Loop through the axis constraints of the Lens
        for slc in self.slices_list:
            axis = slc.axis

            # Condition A: The anchor is global for this axis (key doesn't exist)
            axis_is_global = ~Q(coordinates__has_key=axis)

            if slc.start is not None and slc.stop is not None:
                axis_in_range = Q(**{f"coordinates__{axis}__gte": slc.start, f"coordinates__{axis}__lt": slc.stop})
            else:
                continue  # Failsafe for unhandled slice types

            # The anchor must either be global for this axis, OR fall inside the slice limits
            qs = qs.filter(axis_is_global | axis_in_range)

        # OPTIMIZATION: prefetch/select the spokes to prevent N+1 database death
        return qs.select_related("rig").prefetch_related("acquisition_metadata", "value_histogram")

