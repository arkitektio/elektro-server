"""The descriptors of elektro's arrays — the server-side twin of the client's vocabulary.

They are declared once, as data, in ``elektro_server.contract`` (their keys are in
``elektro_server.vocabulary``), and read from there by everything that states them: a signal carries the object's descriptors so rekuest can match
it against triggers and against the ``requires`` of the ports it would be fed to, and the
GraphQL types answer them as ``descriptors``, so a client can ask which actions take the object
in hand. Those ports were declared with the elektro client's spec
vocabulary (``elektro.specs``), so keys and meaning must match ``elektro.specs.lens_descriptors``:
one count per axis type (zero included) plus the total extent along channel, time (samples) and
index axes. ``@elektro/value_dimension`` is left out: it needs the client's unit reading.
"""

from collections import Counter
from collections.abc import Sequence

from elektro_server.vocabulary import EXTENT_KEYS, KEY_BY_AXIS_TYPE


def array_descriptors(axis_types: Sequence[str], shape: Sequence[int]) -> dict[str, int]:
    """The descriptors of an array with these per-axis types and this (level-0) shape."""
    if len(axis_types) != len(shape):
        raise ValueError(f"{len(axis_types)} axis types for a {len(shape)}-dimensional shape")
    counts = Counter(axis_types)
    descriptors = {key: counts.get(axis_type, 0) for axis_type, key in KEY_BY_AXIS_TYPE.items()}
    for key, wanted in EXTENT_KEYS.items():
        descriptors[key] = sum(extent for axis_type, extent in zip(axis_types, shape) if axis_type == wanted)
    return descriptors


def dataset_descriptors(dataset) -> dict[str, int]:  # noqa: ANN001 - a core.models.ArrayDataset
    """An array dataset's descriptors, from the row (in a signal: read at commit, the axes are written after it)."""
    try:
        return array_descriptors([axis.type for axis in dataset.axes], dataset.shape_list)
    except ValueError:  # axes and shape disagree (a half-written dataset): no descriptors, still an object
        return {}


def lens_descriptors(lens) -> dict[str, int]:  # noqa: ANN001 - a core.models.Lens
    """A lens' descriptors: its dataset's axes over the shape its slices cut out.

    A lens keeps every axis of its dataset (a slice narrows an axis, it never drops one), so
    this is the client's ``lens_descriptors`` computed from the same two facts.
    """
    try:
        return array_descriptors([axis.type for axis in lens.dataset.axes], lens.shape_list)
    except ValueError:
        return {}
