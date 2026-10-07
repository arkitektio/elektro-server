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
STATED_DESCRIPTORS = [
    Descriptor(key="@elektro/value_dimension", type="STRING", description="What its values measure (voltage, current, ...); read from its unit by the client"),
    Descriptor(key="@elektro/value_kind", type="STRING", description="What its values mean (e.g. categorical for labels); stated by its producer, never computed"),
]
