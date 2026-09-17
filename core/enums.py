from django.db.models import TextChoices
import strawberry
from enum import Enum, EnumMeta


def _describe(enum_cls: EnumMeta, **descriptions: str) -> None:
    """Attach SDL descriptions to the members of an already-decorated strawberry enum.

    ``strawberry.enum_value`` cannot be used on ``(str, Enum)`` classes: the str
    mixin bakes the definition object's repr into the member value before
    strawberry can unwrap it, silently corrupting every runtime comparison and
    Django write. Members therefore keep their plain string values and the
    descriptions are patched onto the strawberry definition afterwards.
    """
    values = {v.name: v for v in enum_cls.__strawberry_definition__.values}
    for name, description in descriptions.items():
        values[name].description = description


class PlacementValidityChoices(TextChoices):
    """How much a transformation edge's map is actually known: guessed, inferred from metadata, authored by someone, or validated against the data. A layer's validity is derived from it -- the weakest edge on its path to world."""

    MANUAL = "MANUAL", "Manual"
    INFERRED = "INFERRED", "Inferred from Metadata"
    VALIDATED = "VALIDATED", "Validated by User"
    UNKNOWN = "UNKNOWN", "Unknown"


class ValueRelationChoices(TextChoices):
    """What a derivation did to the *values*: the axis the spatial kind deliberately says nothing about. A threshold is spatially IDENTITY with categorized values; a crop is value-identical."""

    IDENTICAL = "IDENTICAL", "Identical (the source's numbers)"
    TRANSFORMED = "TRANSFORMED", "Transformed (same quantity, new numbers)"
    CATEGORIZED = "CATEGORIZED", "Categorized (values became labels)"


class ScaleMethodChoices(TextChoices):
    """How a pyramid level's voxels were computed from the level above it.

    Stated, never derived: two arrays are all that survives a downsample, and nothing about
    the numbers in them says whether they were averaged or picked. It matters because the
    answer is not always allowed. Over an intensity image every one of these is a defensible
    choice; over an array whose values are *object ids* only the ones that return a value
    that was already there are -- the mean of ids 41 and 42 is 41.5, which is no object, and
    an image pyramid built that way paints a border of phantom objects along every boundary.
    """

    NEAREST = "NEAREST", "Nearest neighbour (one source voxel, unchanged)"
    MODE = "MODE", "Mode (the most frequent source voxel)"
    LINEAR = "LINEAR", "Linear interpolation"
    CUBIC = "CUBIC", "Cubic interpolation"
    AREA = "AREA", "Area average (the mean over the source window)"
    GAUSSIAN = "GAUSSIAN", "Gaussian-weighted average"
    MAX = "MAX", "Maximum of the source window"
    MIN = "MIN", "Minimum of the source window"


#: The methods a label pyramid may be built with: the ones whose output value was already a
#: value of the input. Everything else invents numbers, and an invented id is an object that
#: does not exist. MAX and MIN return a real id but not the *right* one -- they bias every
#: boundary toward whichever object happens to sort higher -- so they are excluded too: a
#: label downsample has to answer "which object is here", and only NEAREST and MODE do.
LABEL_COMPLIANT_SCALE_METHODS = frozenset({ScaleMethodChoices.NEAREST.value, ScaleMethodChoices.MODE.value})


class FileLinkDirectionChoices(TextChoices):
    """Which side of a file link was made from the other. Not derivable: nothing else records which existed first."""

    SOURCE = "SOURCE", "Source (the container was made from the file)"
    RENDITION = "RENDITION", "Rendition (the file was written from the container)"


class TransformKindChoices(TextChoices):
    """The RFC-5 transformation kinds. One table, discriminated by this column.

    Replaces the former ``TransformationKind`` (``AFFINE`` / ``NON_AFFINE``), which
    was never referenced by a model, a migration or a resolver.

    ``UNMAPPABLE`` is ours, not RFC-5's, and it is the only kind that asserts a
    *non*-correspondence: every other kind says how a point maps, and there was no
    way to say that none does. Without it, data whose geometry a task destroyed --
    a phasor array whose arrival-time axis collapsed, a per-object measurement --
    could only be recorded by lying with an IDENTITY or by recording nothing at
    all, and recording nothing loses the lineage with it.
    """

    IDENTITY = "IDENTITY", "Identity"
    SCALE = "SCALE", "Scale"
    TRANSLATION = "TRANSLATION", "Translation"
    MAP_AXIS = "MAP_AXIS", "Map Axis"
    AFFINE = "AFFINE", "Affine"
    ROTATION = "ROTATION", "Rotation"
    SEQUENCE = "SEQUENCE", "Sequence"
    BY_DIMENSION = "BY_DIMENSION", "By Dimension"
    FIELD = "FIELD", "Field (a map given by the values of an array)"
    UNMAPPABLE = "UNMAPPABLE", "Unmappable (a declared non-correspondence)"


class AxisTypeChoices(TextChoices):
    """The semantic axis types, inspired by RFC-5's.

    ``FREQUENCY`` and ``VALUE`` are ours, not RFC-5's; the spec explicitly permits types beyond its
    own enum. It replaces mikro's ``MICROTIME`` and ``SPECTRUM``, which name optical
    acquisitions this service never sees. There is deliberately no ``ARRAY`` type:
    whether an axis holds sample indices or physical instants is a property of its
    *system* (unit nullability). That is why the sample axis of a regularly sampled
    trace is ``TIME`` with no unit and never ``INDEX``: an ``INDEX`` has no metric,
    so the sampling law (a scale and an offset) could not be stated over it.

    ``VALUE`` is the y axis of a plotted trace, and exists for *drawing spaces*: an annotation
    collection's system. A trace's own sample grid never has one -- what was measured at a
    sample is the trace's ``value_unit``, not a coordinate of the sample -- but a line from
    baseline to peak is drawn in ``(t, v)``, and without this type there was no way to say so.
    An edge between a drawing space and a sample grid names ``t`` and says nothing about ``v``.
    """

    SPACE = "SPACE", "Space"
    TIME = "TIME", "Time"
    CHANNEL = "CHANNEL", "Channel"
    COORDINATE = "COORDINATE", "Coordinate"
    DISPLACEMENT = "DISPLACEMENT", "Displacement"
    FREQUENCY = "FREQUENCY", "Frequency (a spectral bin: a spectrogram row, a PSD sample)"
    VALUE = "VALUE", "Value (what was measured: the y axis of a plotted trace)"
    INDEX = "INDEX", "Index (an enumeration with no metric: an object id, a row number)"


class RecordingKindChoices(TextChoices):
    """What a recording measured."""

    TIME = "TIME", "Time"
    VOLTAGE = "VOLTAGE", "Voltage"
    CURRENT = "CURRENT", "Current"
    INA = "INA", "Sodium current (ina)"
    
    
class StimulusKindChoices(TextChoices):
    """Variety expresses the Type of Representation we are dealing with"""
    CURRENT = "CURRENT", "Current (Value represent Intensity)"
    VOLTAGE = "VOLTAGE", "Voltage (Value represent Intensity)"
    

class ProvenanceAction(TextChoices):
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    DELETE = "DELETE", "Delete"
    RELATE = "RELATE", "Relate"


class AnnotationKindChoices(TextChoices):
    """The shapes an annotation on a trace can be drawn as.

    The vocabulary is Neo's where Neo has one -- an *event* is an instant, an *epoch* is a
    stretch of time -- and mikro's rule governs the rest: **a kind names geometry only.**
    Which axes a shape spans is a property of the coordinate system it is drawn in, never of
    the shape. So there is no "channel epoch" and no "amplitude window": an epoch drawn in a
    ``(t)`` space is an interval, the same epoch drawn in a ``(t, c)`` space also bounds a run
    of channels, and in a ``(t, v)`` space a range of values -- and it is one kind, stored the
    same way, as two opposite corners.

    What a shape *means* -- a spike, an artifact, a burst, a stimulus onset -- is not a kind
    either. That is what the annotation's ``name`` and its collection are for; the old
    ``RoiKind`` mixed the two (``SPIKE`` beside ``LINE``) and so could not say "an epoch that
    is an artifact".
    """

    # Instants.
    EVENT = "event", "Event (one instant)"
    EVENTS = "events", "Events (several instants of one kind)"

    # A stretch, stored as two opposite corners. One axis makes it an interval, more make it a box.
    EPOCH = "epoch", "Epoch (a stretch of time, as two opposite corners)"

    # Runs of points. These need a second axis to mean anything: a value axis, typically.
    LINE = "line", "Line (a measurement between two points)"
    PATH = "path", "Path (a run of points)"
    POLYGON = "polygon", "Polygon (a closed region)"


@strawberry.enum
class DuckDBDataType(Enum):
    BOOLEAN = strawberry.enum_value("BOOLEAN", description="Represents a True/False value")
    TINYINT = strawberry.enum_value("TINYINT", description="Very small integer (-128 to 127)")
    SMALLINT = strawberry.enum_value("SMALLINT", description="Small integer (-32,768 to 32,767)")
    INTEGER = strawberry.enum_value("INTEGER", description="Standard integer (-2,147,483,648 to 2,147,483,647)")
    BIGINT = strawberry.enum_value("BIGINT", description="Large integer for large numeric values")
    HUGEINT = strawberry.enum_value("HUGEINT", description="Extremely large integer for very large numeric ranges")
    FLOAT = strawberry.enum_value("FLOAT", description="Single-precision floating point number")
    DOUBLE = strawberry.enum_value("DOUBLE", description="Double-precision floating point number")
    VARCHAR = strawberry.enum_value("VARCHAR", description="Variable-length string (text)")
    BLOB = strawberry.enum_value("BLOB", description="Binary large object for storing binary data")
    TIMESTAMP = strawberry.enum_value("TIMESTAMP", description="Date and time with precision")
    DATE = strawberry.enum_value("DATE", description="Specific date (year, month, day)")
    TIME = strawberry.enum_value("TIME", description="Specific time of the day (hours, minutes, seconds)")
    INTERVAL = strawberry.enum_value("INTERVAL", description="Span of time between two dates or times")
    DECIMAL = strawberry.enum_value("DECIMAL", description="Exact decimal number with defined precision and scale")
    UUID = strawberry.enum_value("UUID", description="Universally Unique Identifier used to uniquely identify objects")
    LIST = strawberry.enum_value("LIST", description="A list of values of the same data type")
    MAP = strawberry.enum_value("MAP", description="A collection of key-value pairs where each key is unique")
    ENUM = strawberry.enum_value("ENUM", description="Enumeration of predefined values")
    STRUCT = strawberry.enum_value("STRUCT", description="Composite type grouping several fields with different data types")
    JSON = strawberry.enum_value("JSON", description="JSON object, a structured text format used for representing data")


@strawberry.enum
class SynapseKind(str, Enum):
    """Variety expresses the Type of Representation we are dealing with"""
    EXP2SYN = "exp2syn"
    GABAA = "gabaA"
    

@strawberry.enum
class ConnectionKind(str, Enum):
    """Variety expresses the Type of Representation we are dealing with"""
    SYNAPSE = "synapse"


@strawberry.enum
class DistributionKind(str, Enum):
    """How a section parameter is distributed along a section (NEURON range variable)."""
    UNIFORM = "uniform"
    LINEAR = "linear"
    EXPRESSION = "expression"


@strawberry.enum
class IonStyle(str, Enum):
    """How an ion's reversal potential and concentrations are treated (NEURON ion_style)."""
    FIXED_REVERSAL = "fixed_reversal"   # e<ion> is a fixed parameter (set reversal_potential)
    NERNST = "nernst"                   # e<ion> computed from fixed concentrations via Nernst
    ACCUMULATED = "accumulated"         # concentrations are states (accumulation mechanism); e follows via Nernst
      


@strawberry.enum
class RecordingKind(str, Enum):
    VOLTAGE = "VOLTAGE"
    CURRENT = "CURRENT"
    TIME = "TIME"
    INA = "INA"
    UNKNOWN = "UNKNOWN"
    
@strawberry.enum
class StimulusKind(str, Enum):
    VOLTAGE = "VOLTAGE"
    CURRENT = "CURRENT"
    UNKNOWN = "UNKNOWN"

@strawberry.enum(description="The shape an annotation on a trace is drawn as. The members name geometry only: which axes a shape spans is a property of the coordinate system it is drawn in, and what it *means* -- a spike, an artifact -- is its name, not its kind")
class AnnotationKind(str, Enum):
    """The shape an annotation is drawn as."""

    EVENT = "event"
    EVENTS = "events"
    EPOCH = "epoch"
    LINE = "line"
    PATH = "path"
    POLYGON = "polygon"


_describe(
    AnnotationKind,
    EVENT="One instant: a stimulus onset, a threshold crossing, a marker. One vertex. Neo's Event.",
    EVENTS="Several instants of one kind, as one annotation: the spikes a detector found, the pulses of a train. One vertex each.",
    EPOCH="A stretch, as two opposite corners: `[[t0], [t1]]` in a space with only a time axis, where it is an interval -- Neo's Epoch. Drawn in a space with more axes the same two corners bound those too: a run of channels, a range of values. Inverted corners are normalised.",
    LINE="A measurement between two points: an amplitude from baseline to peak, a slope, a latency. Two vertices. Meaningful in a space with a second axis, typically a VALUE axis.",
    PATH="An open run of points: a fitted curve, a drawn baseline. At least two vertices.",
    POLYGON="A closed region: a lasso around part of a trace, a cluster boundary in a phase plot. At least three vertices.",
)


# --- The coordinate graph (vendored from mikro; see core/models/coords.py) ---


@strawberry.enum(description="The semantic kind of an axis. Axes are declared in the order the data has them -- a trace's store dimension order -- and no ordering by type is required of them: the time and channel axes are found by type rather than by position.")
class AxisType(str, Enum):
    """The semantic kind of an axis, inspired by RFC-5."""

    SPACE = "SPACE"
    TIME = "TIME"
    CHANNEL = "CHANNEL"
    COORDINATE = "COORDINATE"
    DISPLACEMENT = "DISPLACEMENT"
    FREQUENCY = "FREQUENCY"
    VALUE = "VALUE"
    INDEX = "INDEX"


_describe(
    AxisType,
    INDEX="An enumerating axis with no metric: a sweep, a trial, a spike number. It has no unit because there is nothing to measure — the distance between spike 3 and spike 4 means nothing, which is why a spike train reaches time through a FIELD and never through a SCALE.",
    SPACE="A spatial axis. Unitless indices in a sample-grid system; carries a physical length unit in a unit-carrying system. No model of this service lives in a spatial system yet, but one can be authored and registered into.",
    TIME="A time axis. Sample indices in a trace's sample grid (no unit); carries a physical duration unit on a clock.",
    CHANNEL="A categorical channel axis: its coordinates index electrodes or acquisitions, not positions. Never downsampled.",
    COORDINATE="The value axis of a coordinate-valued array: its positions enumerate the components of an absolute output position. This is what makes the array readable as the `field` of a FIELD edge. A scalar-valued field (a label mask, whose one value is an object id) carries no value axis at all -- absent means scalar, and scalar means COORDINATE.",
    DISPLACEMENT="The value axis of a displacement-valued array: its positions enumerate the components of a per-point OFFSET, where COORDINATE enumerates absolute positions. Stating it here rather than on the edge is deliberate: it is a property of the array, and an array that says it twice can disagree with itself.",
    VALUE="What was measured: the y axis of a plotted trace. Only a drawing space has one -- an annotation collection's system, where a line from baseline to peak needs somewhere to be drawn. A trace's sample grid never does: the value at a sample is not a coordinate of it. Carries any unit (mV, pA), or none.",
    FREQUENCY="A spectral bin: a row of a spectrogram, a sample of a power spectral density. Continuous -- unlike a CHANNEL axis -- so it carries a frequency unit in a unit-carrying system and may be rescaled.",
)


@strawberry.enum(description="The kind of a coordinate transformation, discriminating how its parameters are interpreted. Direction is always forward: input -> output.")
class TransformKind(str, Enum):
    """The kind of a coordinate transformation, discriminating how its parameters are interpreted."""

    IDENTITY = "IDENTITY"
    SCALE = "SCALE"
    TRANSLATION = "TRANSLATION"
    MAP_AXIS = "MAP_AXIS"
    AFFINE = "AFFINE"
    ROTATION = "ROTATION"
    SEQUENCE = "SEQUENCE"
    BY_DIMENSION = "BY_DIMENSION"
    FIELD = "FIELD"
    UNMAPPABLE = "UNMAPPABLE"


_describe(
    TransformKind,
    IDENTITY="The identity map. Input and output coordinates are the same.",
    SCALE="A per-axis multiplication. Its `scale` has one entry per input axis.",
    TRANSLATION="A per-axis offset. Its `translation` has one entry per input axis.",
    MAP_AXIS="A permutation of axes, mapping each input axis to an output axis by name.",
    AFFINE="A general affine map, given as an M x (N+1) matrix with rows outermost.",
    ROTATION="A rotation, given as an orthonormal matrix.",
    SEQUENCE="An ordered composition of child transformations, applied first to last.",
    BY_DIMENSION="A composition of child transformations, each acting on a named subset of the axes.",
    FIELD="A non-affine map given by the values of an array rather than by a formula. The array is a `field`: a coordinate system, and so a node of this graph, not a payload on this edge. Whether its values are absolute POSITIONS or per-point OFFSETS is read from the value axis of that node -- COORDINATE or DISPLACEMENT -- never restated here. A label mask is the case where the field IS the input: its own pixels are the map. Not invertible in closed form, so a placement path never walks it backwards -- which is also the right semantics for a dereference, an object being a set of pixels.",
    UNMAPPABLE="A declared NON-correspondence: the two systems are related — one was derived from the other — and no point of either maps to a point of the other. It carries no parameters, is constrained by no rank, has no matrix, and is never walked by a placement search, in either direction. Recording an IDENTITY instead would be a lie; recording nothing would lose the lineage.",
)


@strawberry.enum(description="The kind of a transformation a client can author directly: the discriminator of `TransformInput`. SEQUENCE is absent on purpose -- it is a wrapper the ingest builds together with its children (pyramid levels, stepped lenses), never authored empty.")
class CreatableTransformKind(str, Enum):
    """The directly-creatable subset of :class:`TransformKind`, used only by inputs."""

    IDENTITY = "IDENTITY"
    SCALE = "SCALE"
    TRANSLATION = "TRANSLATION"
    MAP_AXIS = "MAP_AXIS"
    AFFINE = "AFFINE"
    ROTATION = "ROTATION"
    BY_DIMENSION = "BY_DIMENSION"
    FIELD = "FIELD"
    UNMAPPABLE = "UNMAPPABLE"


_describe(
    CreatableTransformKind,
    IDENTITY="The identity map. Input and output coordinates are the same, so it takes no parameters.",
    SCALE="A per-axis multiplication. Takes `scale`, one entry per input axis.",
    TRANSLATION="A per-axis offset. Takes `translation`, one entry per input axis.",
    MAP_AXIS="A permutation of axes, mapping each input axis to an output axis by name. Takes `inputAxes` and `outputAxes`; the matrix is synthesized from them.",
    AFFINE="A general affine map. Takes `affine`, an M x (N+1) matrix with rows outermost.",
    ROTATION="A rotation. Takes `affine`: the orthonormal matrix, in the same layout an AFFINE uses.",
    BY_DIMENSION="A map acting on a named subset of the axes and saying nothing about the rest. Takes `inputAxes` and `outputAxes`, and optionally `scale`, `translation` or `affine` acting on the named axes.",
    FIELD="A non-affine map given by the values of an array rather than by a formula. Takes `field` (the array's coordinate system), `inputAxes` and `outputAxes`.",
    UNMAPPABLE="A declared NON-correspondence: no point of either space maps to a point of the other. Takes only an optional `reason`.",
)


@strawberry.enum(
    description=(
        "Which kind of thing a derivation names as the source its data was computed from: the discriminator of `DerivedFromInput`. The edge itself is the same whichever is chosen -- "
        "child space in, source space out -- so a dataset named as DATASET and the same dataset named by its COORDINATE_SYSTEM write the identical row; the read side reports what "
        "lives at the far end through `CoordinateSystem.residents`, not which member was used to say it"
    )
)
class DerivationSourceKind(str, Enum):
    """Which kind of thing a derivation names as the source its data was computed from."""

    LENS = "LENS"
    DATASET = "DATASET"
    ANNOTATION_COLLECTION = "ANNOTATION_COLLECTION"
    COORDINATE_SYSTEM = "COORDINATE_SYSTEM"


_describe(
    DerivationSourceKind,
    LENS="A selection over an array dataset, and the preferred way to name one: a lens' own edge back to its dataset already carries the crop, so pointing at it gets the rest of the chain for free.",
    DATASET="An array dataset as a whole, through its intrinsic sample grid. Use it when the source is the entire recording and there is no lens worth minting.",
    ANNOTATION_COLLECTION="An annotation collection, through the space its shapes are drawn in.",
    COORDINATE_SYSTEM="A coordinate system directly, when the source is a space rather than a dataset -- a clock, or a world.",
)


@strawberry.enum(
    description=(
        "Which geometric properties survive a coordinate transformation. A nested hierarchy -- each class preserves strictly less than the one above it -- so the class of a "
        "composed path is the weakest of its steps. Derived from a transformation's `kind`, never stored: a column could contradict the parameters, and the parameters would be right."
    )
)
class TransformInvariance(str, Enum):
    """Which geometric properties survive a transformation. Derived from `kind`, never stored.

    Declared strongest to weakest, so the SDL reads as the nesting it describes.

    ``AFFINE`` here and ``TransformKind.AFFINE`` share the string ``"AFFINE"``. They are
    distinct GraphQL types and a comparison mixing them would silently succeed, so a
    classifier must dispatch on the kind first and never round-trip through this enum.
    """

    ISOMETRY = "ISOMETRY"
    SIMILARITY = "SIMILARITY"
    AFFINE = "AFFINE"
    DIFFEOMORPHIC = "DIFFEOMORPHIC"
    NONE = "NONE"


_describe(
    TransformInvariance,
    ISOMETRY="Distances, angles and areas all transfer unchanged: a length measured on one side IS that length on the other. An identity, a translation, a rotation, an axis permutation.",
    SIMILARITY="Angles and length *ratios* transfer; every absolute length scales by one common factor. A circle is still a circle, just a different size -- so anything dimensionless carries across untouched, and anything measured needs the one factor.",
    AFFINE="Parallelism and area *ratios* transfer; angles and distances do not. A square may arrive a parallelogram, so an angle or a length read on one side means nothing on the other. Stated for every AFFINE edge, including one whose matrix happens to be rigid: telling those apart needs an SVD, which is numerics inside a metadata answer -- the same line the graph draws when it declines to catch a singular affine.",
    DIFFEOMORPHIC="Topology at best, and only locally: the Jacobian varies with position, so no distance, angle, area or ratio survives anywhere. A ceiling, not a guarantee -- a FIELD is many-to-one on purpose (an object is a set of pixels), and such a map is not a diffeomorphism at all.",
    NONE="Nothing corresponds. On an edge, an UNMAPPABLE: a declared non-correspondence. On a layer, no path to the world at all -- `placement` says which of the two reasons applies.",
)


@strawberry.enum(description="How much a transformation edge's map is actually known: guessed, inferred from metadata, authored by someone, or validated against the data. A layer's validity is derived from it, never stored: the weakest edge on its path to world.")
class PlacementValidity(str, Enum):
    """How much a transformation edge's map is actually known."""

    MANUAL = "MANUAL"
    INFERRED = "INFERRED"
    VALIDATED = "VALIDATED"
    UNKNOWN = "UNKNOWN"


_describe(
    PlacementValidity,
    MANUAL="Someone authored this map -- a registration pipeline, a human with a matrix. It exists on purpose, but nothing has checked it against the data.",
    INFERRED="The numbers were read from acquisition metadata (a pixel size, a stage pose). As right as the metadata is.",
    VALIDATED="Exact or checked: either the server derived the map from shapes and slices, so it cannot be wrong, or someone validated an authored registration against the data.",
    UNKNOWN="This map was assumed, never measured -- badge it. The server writes it nowhere: nothing fabricates a placement any more, so an edge wears UNKNOWN only because a client said so on `createTransformation`, or because it is a historical auto-registered edge.",
)


@strawberry.enum(description="What a derivation did to the values -- the axis the spatial kind says nothing about. A threshold is spatially IDENTITY with categorized values; a crop is value-identical. Stated on the derivation edge (one event, one row, two orthogonal statements); the algorithm and its parameters belong to task provenance, not here.")
class ValueRelation(str, Enum):
    """What a derivation did to the values, orthogonal to its spatial kind."""

    IDENTICAL = "IDENTICAL"
    TRANSFORMED = "TRANSFORMED"
    CATEGORIZED = "CATEGORIZED"


@strawberry.enum(
    description=(
        "Which side of a file link was made from the other. A file is a store, not a container -- it has no coordinate system -- so this relates bytes to data rather than "
        "two spaces, and it is deliberately not a `DerivedFromInput` kind. Direction has to be stated because nothing else records which side existed first"
    )
)
class FileLinkDirection(str, Enum):
    """Which side of a file link was made from the other."""

    SOURCE = "SOURCE"
    RENDITION = "RENDITION"


_describe(
    FileLinkDirection,
    SOURCE="The container was produced from the file: a CZI a converter read to write a Zarr dataset, a CSV a table was loaded from. This is the ingest direction, and the file existed first.",
    RENDITION="The file was produced from the container: a dataset written out as OME-TIFF, a mesh exported to STL. This is the export direction, and the container existed first.",
)


@strawberry.enum(description="Whether a layer has a place in its scene's world, and if not, why not. Derived, never stored.")
class PlacementState(str, Enum):
    """Whether a layer has a place in its scene's world, and if not, why not."""

    PLACED = "PLACED"
    CONDITIONAL = "CONDITIONAL"
    UNREGISTERED = "UNREGISTERED"
    UNMAPPABLE = "UNMAPPABLE"


_describe(
    PlacementState,
    PLACED="The layer's data reaches the scene's world: `pathToWorld` is the route.",
    CONDITIONAL="The layer's data is registered, but only at particular coordinates — a per-channel or per-timepoint correction, written as one selector-scoped edge per index. Where it sits genuinely depends on where you are standing, so `pathToWorld` and `asAffine` are null until you pass `at`, and answer for that coordinate when you do. This is a placement, not a gap: there is nothing to author.",
    UNREGISTERED="Nothing yet relates this layer's data to the scene's world. `pathToWorld` is null because the registration is *missing* — this is a gap in the data, and authoring the edge closes it.",
    UNMAPPABLE="This layer's data can never be placed: it reaches the world only across an UNMAPPABLE edge, which declares that no point correspondence exists, and it reaches nowhere else. `pathToWorld` is null because there is nothing to find — badge it, and do not go looking for the missing registration.",
)


@strawberry.enum(description="Whether the server can state where a source sits in a space, and if not, why not. Derived, never stored.")
class ExtentState(str, Enum):
    """Whether a source's extent in a space is computable, and if not, why not.

    A bare null extent conflates a Parquet the server never reads with a warp field on the
    path, and a client cannot tell them apart -- the same reason `PlacementState` exists
    beside a null `pathToWorld`.
    """

    KNOWN = "KNOWN"
    CONDITIONAL = "CONDITIONAL"
    UNREADABLE = "UNREADABLE"
    NON_AFFINE = "NON_AFFINE"
    INVERTED = "INVERTED"


_describe(
    ExtentState,
    KNOWN="The extent is stated, over the axes it names and only those.",
    CONDITIONAL="The source reaches this space only across a selector-scoped edge — a per-channel or per-timepoint correction — so where it sits depends on a coordinate this query did not fix. The source is returned, because it genuinely is in the space; `extent` is empty because there is no single box, not because none could be computed. Ask again with `at` to get one.",
    UNREADABLE="The source's geometry is not something the server holds: a mesh collection's vertices and a table dataset's rows live in Parquet it never opens. `extent` is null because there is no box to push, not because the path failed -- and the source is returned anyway, because refusing to bound something is not the same as knowing it is out of view.",
    NON_AFFINE="A FIELD edge on the path gives the map as the values of an array rather than as a formula, so there is no closed form to push a box through. The path is real and is returned; `invariance` reads DIFFEOMORPHIC.",
    INVERTED="The path walks an edge against its stored direction, and the extent walk composes forward only -- it pushes a box, and re-bounding one through an inverted step is a different calculation. The step *is* invertible: a placement search offers a backwards step only for a map that has an inverse, which is why `Layer.asAffine` composes such a path without difficulty. So compose `path` yourself, inverting the flagged step, or read the layer's `asAffine`.",
)


@strawberry.enum(description="What a dataset structurally is, materialized from the axes of its intrinsic coordinate system at creation. Specs stack: a 3D timelapse is VOLUME, TIMESERIES and MULTICHANNEL at once. Exactly one spatial member (SCALAR/PROFILE/IMAGE/VOLUME/HYPERVOLUME) ever holds.")
class ArrayDatasetSpec(str, Enum):
    """What a dataset structurally is, materialized from its axes at creation.

    A strawberry enum only, no Django TextChoices twin: it is never chosen or
    validated at a boundary. The values are stored raw on `ArrayDataset.stored_spec`,
    materialized from the intrinsic axes when they are written (see
    `core.logic.graph.create_pixel_axes`) and read back through `ArrayDataset.spec`.
    Storing it is safe -- unlike `CoordinateSystem.kind`, which is still derived
    from ownership on every read -- precisely because the axes are immutable: a
    value computed from immutable inputs cannot disagree with its source. The
    single source of truth for the derivation stays `core.logic.coords.specs_for_axes`.

    Presence, never size: a dataset with a z axis is a VOLUME whether or not z has
    depth, and TIMESERIES means it has a time axis, not that it has more than one
    sample.

    Vendored from mikro with the spatial members intact -- a probe's depth profile or an
    imaging-derived array is still data this service may hold -- minus FLIM, and with
    SPECTRAL keyed on this service's FREQUENCY axis type.
    """

    SCALAR = "SCALAR"
    PROFILE = "PROFILE"
    IMAGE = "IMAGE"
    VOLUME = "VOLUME"
    HYPERVOLUME = "HYPERVOLUME"
    TIMESERIES = "TIMESERIES"
    MULTICHANNEL = "MULTICHANNEL"
    SPECTRAL = "SPECTRAL"


_describe(
    ArrayDatasetSpec,
    SCALAR="No spatial extent: the array carries no SPACE axis at all. What nearly every electrophysiology array is -- a (t, c) recording is SCALAR, TIMESERIES and MULTICHANNEL.",
    PROFILE="One spatial axis -- a line profile, a depth trace.",
    IMAGE="Two spatial axes: a plane. The ordinary micrograph.",
    VOLUME="Three spatial axes: a stack. Holds whenever a z axis is present, even if it carries a single plane.",
    HYPERVOLUME="Four or more spatial axes.",
    TIMESERIES="Carries a TIME axis -- a signal. Presence only: a single-sample time axis still counts.",
    MULTICHANNEL="Carries a CHANNEL axis. Presence only: a one-channel axis still counts.",
    SPECTRAL="Carries a FREQUENCY axis: a spectrum or a spectrogram, not a signal over time.",
)


@strawberry.enum(description="How a pyramid level's voxels were computed from the level above it. Stated, never derived -- nothing about two arrays says whether one was averaged or picked out of the other -- and it matters because over an array of object ids only NEAREST and MODE are allowed: every other method returns numbers that were not in the input, and an invented id is an object that does not exist.")
class ScaleMethod(str, Enum):
    """How a pyramid level's voxels were computed from the level above it."""

    NEAREST = "NEAREST"
    MODE = "MODE"
    LINEAR = "LINEAR"
    CUBIC = "CUBIC"
    AREA = "AREA"
    GAUSSIAN = "GAUSSIAN"
    MAX = "MAX"
    MIN = "MIN"


_describe(
    ScaleMethod,
    NEAREST="One source voxel, carried through unchanged. Label-safe: the value was already there.",
    MODE="The most frequent value in the source window. Label-safe, and the better of the two for a mask -- it keeps the object that actually dominates the window rather than whichever one the sampling grid happens to land on.",
    LINEAR="Linear interpolation over the source window. Invents intermediate values, so never over ids.",
    CUBIC="Cubic interpolation. Invents intermediate values, and overshoots past the input range at edges.",
    AREA="The mean over the source window -- the usual image-pyramid default, and the usual way a mask pyramid gets silently ruined.",
    GAUSSIAN="A Gaussian-weighted average over the source window.",
    MAX="The maximum of the source window. Returns a real value, but over ids it biases every boundary toward whichever object sorts higher, so it is not label-safe either.",
    MIN="The minimum of the source window. Not label-safe, for the mirror of MAX's reason.",
)


@strawberry.enum(
    description=(
        "Which sort of container a file link names: the discriminator of `ExportOfInput`. Only the two containers that hold data a file can be written from or read into -- "
        "a lens is a selection over a dataset rather than a thing with its own bytes, and a coordinate system is a space, which no file encodes"
    )
)
class FileLinkContainerKind(str, Enum):
    """Which sort of container a file link names."""

    DATASET = "DATASET"
    ANNOTATION_COLLECTION = "ANNOTATION_COLLECTION"


_describe(
    FileLinkContainerKind,
    DATASET="An array dataset -- the container an ABF or NWB file is converted into, and the one an export is written from.",
    ANNOTATION_COLLECTION="An annotation collection, the container an event or epoch file is loaded into.",
)


@strawberry.enum(
    description=(
        "A coarse bucket for what sort of thing a file holds, for a picker that wants \"just the recordings\". **Derived at query time from the file's extension, never stored** -- "
        "so it cannot drift from the file it describes, and it is a filter only. Classified by extension rather than by `contentType` on purpose: an ABF or a vendor recording is uploaded "
        "as `application/octet-stream`, so a content-type rule would file every one of them under OTHER, which is precisely the case worth finding. `contentType` is the "
        "fallback when the extension is unknown. It is a curated list, not an authority: filter on `name` or `contentType` directly when you need an exact answer"
    )
)
class FileMimeGroup(str, Enum):
    """A coarse bucket for what sort of thing a file holds. Derived from the extension, never stored."""

    RECORDING = "RECORDING"
    MODEL = "MODEL"
    TABLE = "TABLE"
    DOCUMENT = "DOCUMENT"
    ARCHIVE = "ARCHIVE"
    OTHER = "OTHER"


_describe(
    FileMimeGroup,
    RECORDING="Electrophysiology acquisition formats: abf, nwb, smr, wcp, dat, plx, nev/nsX, rhd, edf, and the generic containers recordings ship in (h5, mat).",
    MODEL="Model and morphology sources: hoc, mod, swc, asc, nml.",
    TABLE="Tabular data: csv, tsv, parquet, feather, xlsx.",
    DOCUMENT="Human-readable notes and reports: pdf, txt, md, docx.",
    ARCHIVE="Containers of other files: zip, tar, gz, 7z. A zipped acquisition is an ARCHIVE, not a RECORDING -- the extension is all this reads.",
    OTHER="Nothing the curated list recognizes, and no usable `contentType`. Includes every file with no extension at all.",
)
