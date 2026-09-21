"""Creating, renaming and deleting an array dataset.

**Vendored from mikro** (``mikro/core/mutations/array_dataset.py``): ``createArrayDataset``
takes mikro's input and writes what mikro writes -- the dataset, its grid, a data array per
level, the level edges, the derivation edges, the file links, the anchors. What differs is
the anchor's spokes (a rig state, a value unit and acquisition metadata where mikro has a
microscope state, a light path and phasors -- and, for a simulated trace, its sites and its
simulation state), that anchors are checked against the axes, and that deleting sweeps the
spaces left empty. How a dataset is *drawn* is not said here at all: that is the
interpretation layer (``experiment.py``), which names datasets by id exactly as mikro's
scenes and layers do.
"""

from kante.types import Info
import strawberry

from core import enums, types, models, scalars
from datalayer.datalayer import get_current_datalayer
import json

import kante
from django.db import transaction
from pydantic import BaseModel, Field
from kanne_server import scalars as kanne_scalars
from rigkit.inputs import RigStateInput
from rigkit.models import RigStateModel
from core.creation import CreationContext
from core.inputs.coords import AxisInput, AxisInputModel, DerivedFromInput, DerivedFromSpec
from core.inputs.file_link import SourceFileInput, SourceFileInputModel
from core.logic import coordinate_system as coordinate_system_logic
from core.logic import file_link as file_link_logic
from core.logic import folder as folder_logic
from core.logic import coords as coords_logic
from core.logic import graph as graph_logic
from core.guards import enforce_delete
from core.logic import spaces as spaces_logic
from core.logic import sites as sites_logic
from core.mutations.delete import delete_flagging_stores
from core.scoping import get_for_org
import logging

logger = logging.getLogger(__name__)


class AxisAnchorInputModel(BaseModel):
    axis: str
    value: int


@kante.pydantic_input(AxisAnchorInputModel, description="Input type for an axis anchor, which pins one axis to one discrete position")
class AxisAnchorInput:
    axis: str = strawberry.field(description="The axis to anchor to, e.g. 'c', 'sweep' or 't'")
    value: int = strawberry.field(description="The position to anchor the axis to, e.g. 0 for the first position along that axis")


class AcquisitionMetadataInputModel(BaseModel):
    metadata_string: str = Field(..., description="The acquisition metadata as a JSON string")


@kante.pydantic_input(AcquisitionMetadataInputModel, description="Input type for acquisition metadata: whatever the source format said (an ABF header, an NWB attribute set), kept as a JSON object. mikro's OME metadata slot")
class AcquisitionMetadataInput:
    metadata_string: str = strawberry.field(description="The acquisition metadata as a JSON string. Must be a JSON object")


class ValueUnitInputModel(BaseModel):
    unit: str


@kante.pydantic_input(ValueUnitInputModel, description="Input type for a value unit: what the array's VALUES measure at the anchored coordinates. Not an axis unit -- an axis says where a sample is, this says what was measured there")
class ValueUnitInput:
    unit: kanne_scalars.Unit = strawberry.field(description="The unit of the values, e.g. 'mV', 'pA', or 'second' for a dataset whose values are sample times. 'a.u.' for arbitrary units")


class ValueHistogramInputModel(BaseModel):
    histogram: list[float] = Field(..., description="The histogram of the values (y values)")
    bins: list[float] = Field(..., description="The bin indices of the histogram (x values)")
    min: float | None = Field(None, description="The minimum value of the histogram")
    max: float | None = Field(None, description="The maximum value of the histogram")
    p1: float | None = Field(None, description="The 1st percentile value of the histogram")
    p99: float | None = Field(None, description="The 99th percentile value of the histogram")


@kante.pydantic_input(ValueHistogramInputModel, description="Input type for a value histogram, which specifies the histogram of the values along certain dimensions, so a client can pick a display range without reading the array")
class ValueHistogramInput:
    histogram: list[float] = strawberry.field(description="The histogram of the values (y values)")
    bins: list[float] = strawberry.field(description="The bin indices of the histogram (x values)")
    min: float | None = strawberry.field(default=None, description="The minimum value of the histogram")
    max: float | None = strawberry.field(default=None, description="The maximum value of the histogram")
    p1: float | None = strawberry.field(default=None, description="The 1st percentile value of the histogram")
    p99: float | None = strawberry.field(default=None, description="The 99th percentile value of the histogram")


class LabelInputModel(BaseModel):
    label: str


@kante.pydantic_input(LabelInputModel, description="Input type for a label, which specifies a label to associate with a coordinate anchor")
class LabelInput:
    label: str = strawberry.field(description="The label to associate with the coordinate anchor: the name of the channel, sweep or unit it pins")


class SiteInputModel(BaseModel):
    model: str
    cell: str | None = None
    location: str | None = None
    position: float | None = Field(default=None, ge=0.0, le=1.0)
    label: str | None = None


class RecordingSiteInputModel(SiteInputModel):
    kind: enums.RecordingKind = enums.RecordingKind.VOLTAGE


class StimulusSiteInputModel(SiteInputModel):
    kind: enums.StimulusKind = enums.StimulusKind.CURRENT


@kante.pydantic_input(RecordingSiteInputModel, description="A place on a neuron model where the anchored values were RECORDED: the model it is part of, NEURON's cell, section and position along it in that model, and what was recorded. elektro's own spoke; it replaces the `Recording` row of a simulation")
class RecordingSiteInput:
    kind: enums.RecordingKind = strawberry.field(default=enums.RecordingKind.VOLTAGE, description="What was recorded: a voltage, a current, or one named ionic current")
    model: strawberry.ID = strawberry.field(description="The neuron model this site is part of. `cell` and `location` are checked against its config")
    cell: str | None = strawberry.field(default=None, description="The id of the cell: one of the cells the model declares")
    location: str | None = strawberry.field(default=None, description="The id of the section: one of the sections of that cell. Without `cell`, the model's only cell")
    position: float | None = strawberry.field(default=None, description="The normalized position along the section, 0 to 1 (NEURON's section(x))")
    label: str | None = strawberry.field(default=None, description="A display label. Defaults to 'cell: location(position)'")


@kante.pydantic_input(StimulusSiteInputModel, description="A place on a neuron model where the anchored values were INJECTED: the model it is part of, NEURON's cell, section and position along it in that model, and what was clamped. elektro's own spoke; it replaces the `Stimulus` row of a simulation")
class StimulusSiteInput:
    kind: enums.StimulusKind = strawberry.field(default=enums.StimulusKind.CURRENT, description="What was clamped: current or voltage")
    model: strawberry.ID = strawberry.field(description="The neuron model this site is part of. `cell` and `location` are checked against its config")
    cell: str | None = strawberry.field(default=None, description="The id of the cell: one of the cells the model declares")
    location: str | None = strawberry.field(default=None, description="The id of the section: one of the sections of that cell. Without `cell`, the model's only cell")
    position: float | None = strawberry.field(default=None, description="The normalized position along the section, 0 to 1 (NEURON's section(x))")
    label: str | None = strawberry.field(default=None, description="A display label. Defaults to 'cell: location(position)'")


class SimulationStateInputModel(BaseModel):
    model: str
    duration: int
    dt: int | None = None


@kante.pydantic_input(
    SimulationStateInputModel,
    description=(
        "The anchored values were COMPUTED, by integrating a neuron model: the model that was run and NEURON's dt and tstop. elektro's own spoke -- the synthetic rig, "
        "a simulated output's counterpart of `rig`. A run is its clock: the outputs timed onto one clock are one run, and must agree on it. An input (a stimulus waveform) carries none"
    ),
)
class SimulationStateInput:
    model: strawberry.ID = strawberry.field(description="The neuron model that was integrated. Every recording or stimulus site of the same dataset is part of this model")
    duration: kanne_scalars.Duration = strawberry.field(description="How long the model was run for (NEURON's tstop)")
    dt: kanne_scalars.Duration | None = strawberry.field(default=None, description="The integration time step (NEURON's dt). An integrator parameter, not the sampling period: a run can record more coarsely than it integrates")


class CoordinateAnchorInputModel(BaseModel):
    axis_anchors: list[AxisAnchorInputModel]
    rig: RigStateModel | None = None
    acquisition_metadata: AcquisitionMetadataInputModel | None = None
    value_histogram: ValueHistogramInputModel | None = None
    label: LabelInputModel | None = None
    value_unit: ValueUnitInputModel | None = None
    recording_site: RecordingSiteInputModel | None = None
    stimulus_site: StimulusSiteInputModel | None = None
    simulation: SimulationStateInputModel | None = None


@kante.pydantic_input(CoordinateAnchorInputModel, description="Input type for a coordinate anchor, which specifies a list of dimension anchors to anchor to")
class CoordinateAnchorInput:
    axis_anchors: list[AxisAnchorInput] = strawberry.field(description="A list of dimension anchors to anchor to, e.g. [{'axis': 'c', 'value': 0}, {'axis': 'sweep', 'value': 5}] to anchor to the first channel of the sixth sweep. An empty list anchors to the whole dataset")
    rig: RigStateInput | None = strawberry.field(default=None, description="Optional recorded rig state to associate with the coordinate anchor: the hardware truth -- clamp mode, holding level, series resistance, per-device settings -- at this coordinate, as composable typed input (quantities like '-70 mV' or '12 Mohm' where the setting carries a unit). An acquisition fact, recorded at ingest like the other spokes")
    acquisition_metadata: AcquisitionMetadataInput | None = strawberry.field(default=None, description="Optional acquisition metadata to associate with the coordinate anchor: whatever the source format said, kept as it said it")
    value_histogram: ValueHistogramInput | None = strawberry.field(default=None, description="Optional value histogram to associate with the coordinate anchor, which can provide additional context about the distribution of values along the anchored dimensions")
    label: LabelInput | None = strawberry.field(default=None, description="Optional label to associate with the coordinate anchor -- the name of the channel at `{c: 3}`, of the sweep at `{sweep: 12}`")
    value_unit: ValueUnitInput | None = strawberry.field(default=None, description="Optional unit of the array's values at this coordinate. Anchor it to no axis at all to state it for the whole dataset (what `ArrayDataset.valueUnit` reads); anchor it per channel when the channels measure different things")
    recording_site: RecordingSiteInput | None = strawberry.field(default=None, description="(simulation) Where on the model the values at this coordinate were recorded. The whole dataset at `{}`, one channel at `{c: i}`. Not together with `stimulusSite`")
    stimulus_site: StimulusSiteInput | None = strawberry.field(default=None, description="(simulation) Where on the model the values at this coordinate were injected. The whole dataset at `{}`, one channel at `{c: i}`. Not together with `recordingSite`")
    simulation: SimulationStateInput | None = strawberry.field(default=None, description="(simulation) The model and integrator parameters that computed the values at this coordinate. Usually once, at `{}`, for the whole dataset")


class ScaleInputModel(BaseModel):
    level: int
    array: str = Field(..., description="The array-like object to create the dataset from")
    scale_method: enums.ScaleMethod | None = None


@kante.pydantic_input(ScaleInputModel, description="Input type for one pyramid level: the array backing it, and how it was downsampled. Its scale factor is derived from its actual shape, never supplied")
class ScaleInput:
    """Input for one pyramid level."""

    level: int = strawberry.field(description="The level of the scale, where 0 is the highest resolution scale and higher levels are lower resolution scales")
    array: scalars.ArrayLike = strawberry.field(description="The array-like object to create the dataset from")
    scale_method: enums.ScaleMethod | None = strawberry.field(
        default=None,
        description="How this level's voxels were computed from the level above it. Stated, never derived -- nothing about two arrays says whether one was averaged or picked out of the other. **Required, and restricted to NEAREST or MODE, when this dataset's primary derivation is declared CATEGORIZED, or when any of its axes is an INDEX axis** -- an axis that enumerates objects: over an array of object ids every other method returns numbers that were not in the input, and an invented id is an object that does not exist",
    )


class CreateDatasetInputModel(BaseModel):
    data: str
    scales: list[ScaleInputModel]
    name: str
    axes: list[AxisInputModel]
    folder: str | None = None
    anchors: list[CoordinateAnchorInputModel] | None = None
    derived_from: list[DerivedFromSpec] | None = None
    source_files: list[SourceFileInputModel] | None = None


@kante.pydantic_input(CreateDatasetInputModel, description="Input type for creating an array dataset. Its axes are structural (name and kind); physical units, if known, arrive afterwards through createCoordinateSystem with a registrations entry naming the dataset")
class CreateArrayDatasetInput:
    """Input for creating an array dataset."""

    data: scalars.ArrayLike = strawberry.field(description="The array-like object to create the dataset from")
    scales: list[ScaleInput] = strawberry.field(description="The lower-resolution pyramid levels. Each level's absolute scale is derived from its actual shape against level 0's -- a pyramid whose axes do not halve cleanly is described correctly, and no caller can supply a wrong factor")
    name: str = strawberry.field(description="The name of the dataset")
    axes: list[AxisInput] = strawberry.field(
        description="The dataset's structural axes, in array order (slowest-varying first) -- they must describe the store's dimensions, and are checked against its shape. No ordering by type is required beyond that: (t, c) and (c, t) are both accepted as given. TIME for the sample axis (even when sampling is irregular), CHANNEL for channels, INDEX for sweeps, trials or spike numbers. They carry no units: the intrinsic space is the sample grid, and units belong to the clock a sampling law maps it onto"
    )
    folder: strawberry.ID | None = strawberry.field(
        default=None,
        description="The folder to file this dataset in. Organisational only -- it says nothing about where the data sits in space. Defaults to the user's default folder",
    )
    anchors: list[CoordinateAnchorInput] | None = strawberry.field(
        default=None, description="Optional list of coordinate anchors to associate with the dataset, each pinning metadata spokes (a value unit, a channel label, the rig state, a histogram, acquisition metadata) to specific positions along certain axes"
    )
    derived_from: list[DerivedFromInput] | None = strawberry.field(
        default=None,
        description="Optional statement of where this dataset's samples came from: one entry per source lens -- a filter or a decimation has one, a difference of two channels has several -- each carrying the map back into that lens' space. Stored as edges of the coordinate graph, not as labels: the derived dataset then inherits its sources' placements, so refining a source's registration moves it too, and a layer over it resolves `pathToWorld` through a source. The order is the priority: the first entry is the primary parent (it drives `derivedFrom` order and the lineage root); later entries are additional sources whose edges are just as walkable. An UNMAPPABLE entry records history only and may not precede a mappable one",
    )
    source_files: list[SourceFileInput] | None = strawberry.field(
        default=None,
        description=(
            "Optional statement of which files this dataset's arrays were converted from -- the ABF or NWB file a converter read to write this Zarr, named per series. **Not a "
            "`derivedFrom` entry, deliberately**: a derivation is an edge of the coordinate graph and every one of them relates two spaces, while a file has no space at all. "
            "This records lineage between bytes and data, claims no geometry, and leaves the graph untouched"
        ),
    )


def _parse_json_object(value: str | None, field: str) -> dict:
    """Parse a JSON-object string a client sent, and say so when it is not what it claims to be.

    The spoke columns are JSONFields, so the string must be a JSON *object*. It is an easy
    field to get wrong -- acquisition metadata is often XML, and an empty upload is a string of
    whitespace -- and a bare `json.loads` reports every one of those the same way:
    "Expecting value: line 1 column 1 (char 0)", with no hint that it was talking about this
    field rather than, say, the zarr metadata read a few lines earlier.
    """
    if value is None or value.strip() == "":
        return {}

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        head = value.strip()[:80]
        hint = " It looks like XML; it must be converted to JSON before it is sent." if head.startswith("<") else ""
        raise ValueError(f"{field} is not valid JSON ({exc}).{hint} It starts: {head!r}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be a JSON object, not a {type(parsed).__name__}.")

    return parsed


def assert_pyramid_is_label_compliant(name: str, scales: list[ScaleInputModel], axes: list[AxisInputModel], derived_from: list | None) -> None:
    """A pyramid over object ids may only have been built by picking, never by averaging.

    The guard exists because the damage is silent and permanent. Downsample a mask with an
    area average and level 1 holds 41.5 where objects 41 and 42 meet -- an id belonging to
    no object, along every boundary in the image. Nothing later notices: the array is
    well-formed, it renders, and the phantom ids only show up as objects that cannot be
    looked up in the table the mask keys into. By then level 0 is the only trustworthy
    level and no server-side fix exists, because the original assignment is gone.

    So it is checked at the one moment it can be: when the levels are written, and on two
    signals rather than one.

    The first is the primary derivation's ``value_relation`` -- the same statement
    ``_infer_kind`` reads to bootstrap a label layer -- taken off the *input*, since the
    edges themselves are not written until after the levels exist.

    The second is an **INDEX axis**: a dimension that enumerates objects rather than
    measuring anything. It says the array is not intensities as loudly as CATEGORIZED does,
    and it says it through a door the first signal cannot see -- a mask ingested with no
    derivation at all states nothing about its values, and until this it was checked by
    nothing. It refuses more than it strictly must: an INDEX axis can never shrink between
    levels (``core.logic.coords._DOWNSAMPLABLE_TYPES``), so what a ``(object, y, x)`` pyramid
    downsamples is y and x, and a stack of per-object *intensity* crops is honestly built
    with AREA. That case is refused too, deliberately: the cost of a wrong refusal is a
    caller restating a method, and the cost of a wrong acceptance is a pyramid of ids that
    belong to nothing.

    Neither signal catches a mask that is declared later, by a ``keyedBy`` edge authored when
    its object table is created: by then the pyramid is already written, and refusing that
    edge would fail a *table*'s creation over a *mask*'s history without repairing anything.
    That case is reported instead, on ``ArrayDataset.pyramidIsLabelCompliant``.
    """
    primary = next(iter(derived_from or []), None)
    categorized = primary is not None and primary.value_relation == enums.ValueRelation.CATEGORIZED
    indexed = [axis.name for axis in axes if axis.type == enums.AxisType.INDEX]
    if not categorized and not indexed:
        return

    if categorized:
        claim = "is declared CATEGORIZED -- its values are object ids"
        short = "is declared CATEGORIZED"
    else:
        named = ", ".join(f"'{axis}'" for axis in indexed)
        noun = "axes" if len(indexed) > 1 else "axis"
        claim = f"carries the INDEX {noun} {named} -- {'they enumerate' if len(indexed) > 1 else 'it enumerates'} objects rather than measuring them"
        short = f"carries the INDEX {noun} {named}"

    allowed = ", ".join(sorted(enums.LABEL_COMPLIANT_SCALE_METHODS))
    for scale in scales:
        if scale.scale_method is None:
            raise ValueError(
                f"'{name}' {claim} -- so pyramid level {scale.level} must say how it was downsampled, and say one of {allowed}. "
                "A label pyramid built by averaging holds ids belonging to no object along every boundary, and nothing downstream can tell those apart from real ones."
            )
        if scale.scale_method.value not in enums.LABEL_COMPLIANT_SCALE_METHODS:
            raise ValueError(
                f"'{name}' {short}, so pyramid level {scale.level} may not have been downsampled with {scale.scale_method.value}: it returns values that were not in the input, and an invented id is an object that does not exist. Use one of {allowed}."
            )


def parse_value_unit(unit: str) -> str:
    """Validate a value unit and return its canonical spelling. kanne keeps ``a.u.`` as it is."""
    return kanne_scalars.parse_unit(unit)


def assert_anchors_name_axes(anchors: list, axis_names: list[str], *, what: str = "dataset") -> None:
    """Refuse an anchor pinned along an axis the container does not have, or pinned twice.

    Elektro's addition. An anchor's ``coordinates`` are keyed by axis name and read back by
    name (`Lens.activeAnchors`, `inView`), so ``{"ch": 3}`` on a ``(t, c)`` dataset is not an
    error anywhere downstream -- it is a channel label that silently labels nothing. Two
    anchors with the same coordinates are refused for the same reason a spoke is one-to-one:
    the second would be a rival answer to the first.

    ``axis_names`` are the array's axes or the table's coordinate columns; ``what`` names
    the container in the refusal.
    """
    known = list(axis_names)
    seen: list[dict] = []
    for anchor in anchors:
        coordinates = {entry.axis: entry.value for entry in anchor.axis_anchors}
        if len(coordinates) != len(anchor.axis_anchors):
            raise ValueError(f"An anchor names an axis once, but {[entry.axis for entry in anchor.axis_anchors]} repeats one. One position per axis; a second position is a second anchor.")
        unknown = sorted(set(coordinates) - set(known))
        if unknown:
            if not known:
                raise ValueError(f"This {what} has no coordinate columns, so its anchors can only be global ({{}}), but an anchor pins {unknown}.")
            raise ValueError(f"An anchor pins the axes its {what} has, but {unknown} {'is' if len(unknown) == 1 else 'are'} not among {known}.")
        if coordinates in seen:
            raise ValueError(f"Two anchors are pinned to the same coordinates {coordinates or '{} (the whole ' + what + ')'}. One anchor per coordinate: put every spoke for it on the one anchor.")
        seen.append(coordinates)
        if getattr(anchor, "recording_site", None) is not None and getattr(anchor, "stimulus_site", None) is not None:
            raise ValueError(
                f"The anchor at {coordinates or '{} (the whole dataset)'} carries both a recording site and a stimulus site. One value was either recorded or injected: "
                "a clamp's command and its measured response are two channels, each with a site of its own."
            )
    assert_one_model_per_dataset(anchors)


def assert_one_model_per_dataset(anchors: list) -> None:
    """Refuse a dataset whose sites and simulation state name different models, or whose simulation states disagree.

    A dataset was computed by one run of one model: its sites are places *in* that model, and
    its integrator facts are that run's. Two answers on two anchors of one dataset would be
    rivals, not detail.
    """
    runs = {(spoke.model, spoke.dt, spoke.duration) for anchor in anchors if (spoke := getattr(anchor, "simulation", None)) is not None}
    if len(runs) > 1:
        raise ValueError(f"The anchors of one dataset state {len(runs)} different simulation states. A dataset was computed by one run: one model, one dt, one duration.")
    named = {spoke.model for anchor in anchors for spoke in (getattr(anchor, "recording_site", None), getattr(anchor, "stimulus_site", None), getattr(anchor, "simulation", None)) if spoke is not None}
    if len(named) > 1:
        raise ValueError(f"The sites and simulation state of one dataset name different neuron models ({sorted(named)}). A dataset was computed by one model, and its sites are places in that model.")


def assert_axes_describe_the_store(axes: list, store: "models.ZarrStore") -> None:
    """Check the declared axes against what the zarr itself says, before anything is written.

    Two checks, and the second is the one that has never existed. ``ZarrStore.fill_info``
    reads ``dimension_names`` off the array and stores it (`datalayer/models.py:296`); it is
    published in the SDL (`datalayer/types.py:503`); and nothing has ever compared it to the
    caller's ``axes``. So a ``(z, y, x)`` store declared ``(x, y, z)`` was accepted, and the
    failure is not an error: the render axes are derived from the *position* of the spatial
    axes, so it renders transposed.

    That the names are redundant with the bytes is exactly why they are worth checking rather
    than dropping. The *type* is not redundant -- nothing in a zarr says an axis is TIME
    rather than SPACE -- so ``axes`` stays required; mapping ``{x, y, z} -> SPACE`` here
    would be convention-guessing, which is the thing this codebase argues against everywhere
    else. Declare the type, and the name is checked for free.

    Entry-wise, skipping nulls: zarr v3 permits a null per dimension, which
    :class:`~datalayer.base_models.ZarrMetadata` types as ``list[str | None] | None``. A null
    is the store declining to name that dimension, not a disagreement. A store with no
    ``dimension_names`` at all -- zarr v2, or written before the field existed -- is skipped
    entirely rather than refused: the check is on what the bytes say, and those bytes say
    nothing.
    """
    declared = [axis.name for axis in axes]

    if len(store.shape) != len(declared):
        raise ValueError(
            f"The data has {len(store.shape)} dimensions but {len(declared)} "
            f"{'axis was' if len(declared) == 1 else 'axes were'} declared "
            f"({', '.join(declared) or 'none'}). Every dimension of the array needs an axis: "
            "an axis is what gives a dimension a type, and the type is what decides how it is "
            "rendered, coarsened and composed."
        )

    named = store.dimension_names
    if not named:
        return

    disagree = [
        (index, stored, declared[index])
        for index, stored in enumerate(named)
        if stored is not None and stored != declared[index]
    ]
    if disagree:
        detail = "; ".join(
            f"dimension {index} is {stored!r} in the store and was declared {given!r}"
            for index, stored, given in disagree
        )
        raise ValueError(
            f"The declared axes do not describe this array: {detail}. The store names its "
            f"dimensions {list(named)} and the declaration reads {declared}. This is refused "
            "rather than reconciled because the failure would not be an error -- the render "
            "axes are derived from the *position* of the spatial axes, so a transposed "
            "declaration renders the wrong picture instead of raising. Reorder the axes to "
            "match the array, or transpose the array before uploading it."
        )


def create_array_dataset(
    info: Info,
    input: CreateArrayDatasetInput,
) -> types.ArrayDataset:
    """Create an array dataset, its coordinate systems and the edges placing every level in its intrinsic space.

    One transaction, which mikro's is not: a refusal raised after the row exists -- a
    derivation the rank rule forbids, a level whose axes disagree, a value unit that is not a
    unit -- takes the dataset, its grid and its edges with it instead of leaving a dataset
    behind that nothing finished describing.
    """
    with transaction.atomic():
        return _create_array_dataset(info, input)


def _create_array_dataset(info: Info, input: CreateArrayDatasetInput) -> "models.ArrayDataset":
    """The body of :func:`create_array_dataset`, which mikro's is verbatim."""
    model = input.to_pydantic()

    # Before anything is written: a pyramid the values forbid must not leave a dataset behind.
    assert_pyramid_is_label_compliant(model.name, model.scales, model.axes, model.derived_from)
    assert_anchors_name_axes(model.anchors or [], [axis.name for axis in model.axes])

    datalayer = get_current_datalayer()

    data_store = get_for_org(models.ZarrStore, info, id=model.data)
    data_store.fill_info(datalayer)

    base_shape = data_store.shape
    # An `assert`, until 2026-08-20: it vanished under `-O` and surfaced as an
    # AssertionError rather than as prose a caller could act on.
    assert_axes_describe_the_store(model.axes, data_store)

    axis_specs = [coords_logic.AxisSpec(name=axis.name, type=axis.type.value) for axis in model.axes]

    # The declared order is taken as given. It is the store's dimension order -- that is
    # what `assert_axes_describe_the_store` above has just checked it against -- and no
    # further ordering is required of it: (z, c, y, x) and (c, z, y, x) are ordinary ways
    # to write an acquisition, and `resolve_render_axes` reads neither the position of the
    # channel axis nor that of the time axis.

    ctx = CreationContext.from_info(info)
    # The space first, then the data that lives in it. Under residence nothing points from a
    # space back at its data, so there is no cycle to break and no second write: one INSERT
    # each, in the order the dependency actually runs.
    intrinsic = models.CoordinateSystem.objects.create(
        name=f"{model.name}/intrinsic",
        creator=ctx.user,
        organization=ctx.organization,
    )
    dataset = models.ArrayDataset.objects.create(
        name=model.name,
        coordinate_system=intrinsic,
        folder=folder_logic.folder_for_new_container(info, ctx, model.folder, model.derived_from),
        creator=ctx.user,
        organization=ctx.organization,
        **ctx.provenance_kwargs(),
    )
    graph_logic.create_pixel_axes(intrinsic, model.axes)

    levels = [(0, data_store)] + [(scale.level, get_for_org(models.ZarrStore, info, id=scale.array)) for scale in model.scales]
    scale_methods = {scale.level: scale.scale_method.value for scale in model.scales if scale.scale_method is not None}

    for level, store in levels:
        if level != 0:
            store.fill_info(datalayer)
            # The same check level 0 gets, and for the same reason: a level is the *same*
            # array at a coarser grid, so it has the same axes in the same order. A level
            # whose zarr names its dimensions differently is the transposition bug one zoom
            # down -- the dataset renders correctly until the viewer crosses into that level.
            # This was a second bare `assert`, on rank only, until 2026-08-20.
            try:
                assert_axes_describe_the_store(model.axes, store)
            except ValueError as error:
                raise ValueError(f"Pyramid level {level}: {error}") from None

        # Level 0 lives in the dataset's own grid -- it *is* that grid -- so it points at
        # the same space rather than getting a duplicate node joined by an all-ones SCALE.
        # Only a level whose space really differs gets one of its own.
        array_system = intrinsic
        if level != 0:
            array_system = models.CoordinateSystem.objects.create(
                name=f"{model.name}/{level}",
                creator=ctx.user,
                organization=ctx.organization,
            )

        data_array = models.DataArray.objects.create(
            level=level,
            store=store,
            dataset=dataset,
            coordinate_system=array_system,
            shape=store.shape,
            chunk_shape=store.chunks,
            # Null for level 0: it was not downsampled from anything.
            scale_method=scale_methods.get(level),
        )

        if level == 0:
            continue

        graph_logic.create_pixel_axes(array_system, model.axes)

        graph_logic.create_level_edge(
            array_system=array_system,
            intrinsic=intrinsic,
            shape_0=base_shape,
            shape_level=store.shape,
            axis_specs=axis_specs,
            ctx=ctx,
        )

    if model.derived_from:
        coordinate_system_logic.write_derivation_edges(info, name=dataset.name, own_system=intrinsic, derived_from=model.derived_from, ctx=ctx)

    file_link_logic.write_file_links(info, container=dataset, source_files=model.source_files or [], ctx=ctx)

    for anchor in model.anchors or []:
        coordinate_anchor = _get_or_create_anchor(dataset, anchor.axis_anchors)
        _write_anchor_spokes(info, coordinate_anchor, anchor)

    return dataset


#: The spokes that describe an *array* and nothing else. A table's value units are its
#: columns' (`Column.unit`), and `ArrayDataset.valueUnit` reads this spoke, so allowing it on
#: a table anchor would be a second copy of one truth.
_ARRAY_ONLY_SPOKES: tuple[str, ...] = ("value_unit",)


#: Which anchor column each container kind is keyed on.
_CONTAINER_FIELDS: dict[type, str] = {models.ArrayDataset: "dataset", models.TableDataset: "table", models.SparseDataset: "sparse"}


def _get_or_create_anchor(container: "models.ArrayDataset | models.TableDataset | models.SparseDataset", axis_anchors: list[AxisAnchorInputModel] | None) -> "models.CoordinateAnchor":
    """Get-or-create rather than create: two spokes at one coordinate are two spokes of *one* anchor.

    Keyed on the container -- an array, table or sparse dataset -- and the coordinates; the
    namespaces cannot collide because an anchor has exactly one container.
    """
    coordinates = {axis_anchor.axis: axis_anchor.value for axis_anchor in axis_anchors or []}
    try:
        field = next(field for kind, field in _CONTAINER_FIELDS.items() if isinstance(container, kind))
    except StopIteration:
        raise TypeError(f"A coordinate anchor pins into an array, table or sparse dataset, not a {type(container).__name__}.") from None
    anchor, _ = models.CoordinateAnchor.objects.get_or_create(coordinates=coordinates, **{field: container})
    return anchor


def _write_anchor_spokes(info: Info, anchor: "models.CoordinateAnchor", input: CoordinateAnchorInputModel) -> None:
    """Write every spoke the input states onto ``anchor``, replacing one already there.

    The one write path for anchor metadata, whether stated at ingest (``createArrayDataset``,
    ``createTableDataset``) or attached afterwards (``createCoordinateAnchor``). Each spoke is
    ``update_or_create``: a later statement replaces the earlier one, which is what "attach
    after the fact" needs to be idempotent.

    A table-anchored simulation state is stored but not clock-checked: ``clocks.assert_one_run``
    walks ``anchor__dataset``, and a table has no sampling law to reconcile against.
    """
    if anchor.dataset_id is None:
        offending = [name for name in _ARRAY_ONLY_SPOKES if getattr(input, name) is not None]
        if offending:
            raise ValueError(f"{', '.join(repr(name) for name in offending)} {'is an array-only spoke' if len(offending) == 1 else 'are array-only spokes'} and cannot be attached to a table or sparse anchor. A table's units are its columns'.")

    if input.rig:
        # The typed model's dump IS the stored JSON, so the column never grows a shape
        # the types cannot express.
        models.RigState.objects.update_or_create(anchor=anchor, defaults={"state": input.rig.model_dump(mode="json")})

    if input.acquisition_metadata:
        logger.debug("Creating acquisition metadata for coordinate anchor with coordinates %s", anchor.coordinates)
        models.AcquisitionMetadata.objects.update_or_create(
            anchor=anchor,
            defaults={"metadata": _parse_json_object(input.acquisition_metadata.metadata_string, "anchor.acquisitionMetadata.metadataString")},
        )

    if input.value_histogram:
        models.ValueHistogram.objects.update_or_create(
            anchor=anchor,
            defaults={
                "histogram": input.value_histogram.histogram,
                "bins": input.value_histogram.bins,
                "min": input.value_histogram.min,
                "max": input.value_histogram.max,
                "p1": input.value_histogram.p1,
                "p99": input.value_histogram.p99,
            },
        )

    if input.label:
        models.ChannelLabel.objects.update_or_create(anchor=anchor, defaults={"label": input.label.label})

    if input.value_unit:
        models.ValueUnit.objects.update_or_create(anchor=anchor, defaults={"unit": parse_value_unit(input.value_unit.unit)})

    if input.recording_site:
        models.RecordingSite.objects.update_or_create(anchor=anchor, defaults=_site_fields(info, input.recording_site))

    if input.stimulus_site:
        models.StimulusSite.objects.update_or_create(anchor=anchor, defaults=_site_fields(info, input.stimulus_site))

    if input.simulation:
        models.SimulationState.objects.update_or_create(
            anchor=anchor,
            defaults={
                "model": get_for_org(models.NeuronModel, info, id=input.simulation.model),
                "duration": input.simulation.duration,
                "dt": input.simulation.dt,
            },
        )


def _site_fields(info: Info, site: SiteInputModel) -> dict:
    """A site's row: its neuron model resolved in the caller's organization, and its cell and section checked against that model."""
    fields = site.model_dump(mode="json")
    model = get_for_org(models.NeuronModel, info, id=fields.pop("model"))
    sites_logic.assert_site_on_model(model, cell=site.cell, location=site.location)
    return {**fields, "model": model}


class UpdateArrayDatasetInputModel(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None


@kante.pydantic_input(
    UpdateArrayDatasetInputModel,
    description="Input for renaming or redescribing a dataset. These two fields are the whole of what is editable: the arrays, the axes and the coordinate systems built from them are fixed at creation, and a recomputation is a new dataset",
)
class UpdateArrayDatasetInput:
    """Input for updating a dataset."""

    id: strawberry.ID = strawberry.field(description="The ID of the dataset to update")
    name: str | None = strawberry.field(default=None, description="A new name")
    description: str | None = strawberry.field(default=None, description="A new description")


def update_array_dataset(info: Info, input: UpdateArrayDatasetInput) -> types.ArrayDataset:
    """Rename a dataset, or redescribe it. Those two fields are the whole of what is editable.

    Deliberately not here: the arrays, the axes, and the coordinate systems derived from them.
    The dataset's geometry is not a set of columns to be corrected -- its dimensions live on
    its INTRINSIC system's axes, and ``Axis.order`` is written by enumeration with the rest of
    the graph measured against it, so an axis edit is a *different space*, not a repair of this
    one. ``updateCoordinateSystem`` refuses a dataset's own system for that reason; it serves
    anchors alone. A recomputation is a new dataset.

    Both fields are audited: ``ArrayDataset.provenance`` records a history row per save, attributed
    to the client, user and task the change happened under, and ``ArrayDataset.provenanceEntries``
    reads them back. That is the whole point of routing a rename through a mutation rather than
    leaving the column writable by whatever happens to hold the row.
    """
    model = input.to_pydantic()
    dataset = get_for_org(models.ArrayDataset, info, id=model.id)
    if model.name is not None:
        dataset.name = model.name
    if model.description is not None:
        dataset.description = model.description
    dataset.save()
    return dataset


class DeleteArrayDatasetInputModel(BaseModel):
    id: str = Field(description="The ID of the array dataset to delete")


@kante.pydantic_input(DeleteArrayDatasetInputModel, description="Input for deleting an array dataset by ID")
class DeleteArrayDatasetInput:
    """Input for deleting an array dataset by ID"""

    id: strawberry.ID = strawberry.field(description="The ID of the array dataset to delete")


class DeleteDataArrayInputModel(BaseModel):
    id: str = Field(description="The ID of the data array to delete")


@kante.pydantic_input(DeleteDataArrayInputModel, description="Input for deleting a data array by ID")
class DeleteDataArrayInput:
    """Input for deleting a data array by ID"""

    id: strawberry.ID = strawberry.field(description="The ID of the data array to delete")


def delete_array_dataset(info: Info, input: DeleteArrayDatasetInput) -> strawberry.ID:
    """Delete a dataset, its levels and lenses, and the spaces nothing else lives in.

    mikro's delete plus one step. The dataset goes first -- its FK to its grid is PROTECT --
    taking its levels, lenses, anchors and every interpretation of it (a signal, a recording,
    a view) with it, and flagging the stores that leaves unreferenced. Then the spaces it
    lived in are swept: a grid is deleted only if this was its last resident, and every edge
    touching it goes with it -- the sampling law, a registration, a derivation.
    """
    parsed = input.to_pydantic()
    dataset = get_for_org(models.ArrayDataset, info, id=parsed.id)
    enforce_delete(info, dataset)

    systems = {
        dataset.coordinate_system_id,
        *dataset.lenses.values_list("coordinate_system_id", flat=True),
        *dataset.data_arrays.values_list("coordinate_system_id", flat=True),
    } - {None}
    delete_flagging_stores(dataset)
    spaces_logic.sweep_empty_systems(systems)
    return parsed.id


def _refuse_level_zero(array: "models.DataArray") -> None:
    """Level 0 is the dataset: its shape, its lenses and its grid are all read off it."""
    if array.level == 0:
        raise ValueError(f"Data array {array.pk} is level 0 of dataset '{array.dataset.name}': it *is* the dataset's data, and its shape is what every lens and level is measured against. Delete the dataset instead.")


def delete_data_array(info: Info, input: DeleteDataArrayInput) -> strawberry.ID:
    """Delete one downsampled level, and the space only it lived in."""
    parsed = input.to_pydantic()
    array = get_for_org(models.DataArray, info, id=parsed.id)
    enforce_delete(info, array)
    _refuse_level_zero(array)
    systems = {array.coordinate_system_id} - {None}
    delete_flagging_stores(array)
    spaces_logic.sweep_empty_systems(systems)
    return parsed.id
