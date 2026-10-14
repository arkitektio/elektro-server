"""The descriptors of elektro's arrays, as data: the server-side twin of the client's vocabulary.

Declared once, on the structures in ``elektro_server.contract`` (``hosts``), and read from there
by everything that states them: a signal carries the object's descriptors so rekuest can match
it against triggers and against the ``requires`` of the ports it would be fed to, and the
GraphQL types answer them as ``descriptors``, so a client can ask which actions take the object
in hand. Those ports were declared with the elektro client's spec vocabulary
(``elektro.specs``), so keys and meaning must match ``elektro.specs.lens_descriptors``: one
count per axis type (zero included) plus the total extent along channel, time (samples) and
index axes.

Nothing here imports Django: the contract says these before the service has a config, and
``core.descriptors`` computes them from the same keys.
"""

from arkitekt_service.contract import Descriptor

KEY_BY_AXIS_TYPE = {
    "SPACE": "@elektro/n_space_axes",
    "TIME": "@elektro/n_time_axes",
    "CHANNEL": "@elektro/n_channel_axes",
    "FREQUENCY": "@elektro/n_frequency_axes",
    "INDEX": "@elektro/n_index_axes",
}
EXTENT_KEYS = {"@elektro/n_channels": "CHANNEL", "@elektro/n_samples": "TIME", "@elektro/n_indices": "INDEX"}
#: Every descriptor ``core.descriptors.array_descriptors`` produces — what elektro declares an
#: array dataset and a lens carry.
ARRAY_DESCRIPTORS = [
    *(Descriptor(key=key, type="INT", description=f"How many of its axes are {axis_type} axes") for axis_type, key in KEY_BY_AXIS_TYPE.items()),
    *(Descriptor(key=key, type="INT", description=f"Its total extent along its {axis_type} axes") for key, axis_type in EXTENT_KEYS.items()),
]
#: Descriptors an array carries that this server does not compute. Declared so that a port may
#: constrain on them at all -- rekuest refuses a key no service declares -- and absent from every
#: ``describe``, so no object is matched or refused on them here. What the values measure is read
#: by the client from the dataset's unit; what they mean is stated by whoever made the data.
VALUE_DIMENSION = "@elektro/value_dimension"
VALUE_KIND = "@elektro/value_kind"
#: What a value unit measures, by the unit each name is checked against: the client's
#: ``elektro.specs._REFERENCE_UNITS``, so a port's ``requires`` and the stored value agree.
REFERENCE_UNITS = {
    "voltage": "volt",
    "current": "ampere",
    "conductance": "siemens",
    "resistance": "ohm",
    "capacitance": "farad",
    "charge": "coulomb",
    "time": "second",
    "frequency": "hertz",
    "concentration": "mole / liter",
    "dimensionless": "dimensionless",
}
#: What its values are, beside its axes: read off its dataset-wide value unit and its primary derivation.
VALUE_DESCRIPTORS = [
    Descriptor(
        key=VALUE_DIMENSION,
        type="STRING",
        description="What its values measure, from its dataset-wide value unit: voltage, current, conductance, resistance, capacitance, charge, time, frequency, concentration, dimensionless, arbitrary (a.u.) or other; empty when no unit is stated",
    ),
    Descriptor(key=VALUE_KIND, type="STRING", description="What its values mean: categorical (labels, from a derivation declared CATEGORIZED) or continuous"),
]
