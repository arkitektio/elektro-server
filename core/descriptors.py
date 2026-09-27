"""The descriptors elektro announces for a dataset — the server-side twin of the client's vocabulary.

Signals carry them so rekuest can match an object against triggers and against the ``requires``
of the ports it would be fed to. Those ports were declared with the elektro client's spec
vocabulary (``elektro.specs``), so keys and meaning must match ``elektro.specs.lens_descriptors``:
one count per axis type (zero included) plus the total extent along channel, time (samples) and
index axes. ``@elektro/value_dimension`` is left out: it needs the client's unit reading.
"""

from collections import Counter
from collections.abc import Sequence

KEY_BY_AXIS_TYPE = {
    "SPACE": "@elektro/n_space_axes",
    "TIME": "@elektro/n_time_axes",
    "CHANNEL": "@elektro/n_channel_axes",
    "FREQUENCY": "@elektro/n_frequency_axes",
    "INDEX": "@elektro/n_index_axes",
}
EXTENT_KEYS = {"@elektro/n_channels": "CHANNEL", "@elektro/n_samples": "TIME", "@elektro/n_indices": "INDEX"}
#: Every key :func:`array_descriptors` produces — what elektro declares its dataset signals carry.
ARRAY_DESCRIPTOR_KEYS = (*KEY_BY_AXIS_TYPE.values(), *EXTENT_KEYS)


def array_descriptors(axis_types: Sequence[str], shape: Sequence[int]) -> dict[str, int]:
    """The descriptors of an array with these per-axis types and this (level-0) shape."""
    if len(axis_types) != len(shape):
        raise ValueError(f"{len(axis_types)} axis types for a {len(shape)}-dimensional shape")
    counts = Counter(axis_types)
    descriptors = {key: counts.get(axis_type, 0) for axis_type, key in KEY_BY_AXIS_TYPE.items()}
    for key, wanted in EXTENT_KEYS.items():
        descriptors[key] = sum(extent for axis_type, extent in zip(axis_types, shape) if axis_type == wanted)
    return descriptors
