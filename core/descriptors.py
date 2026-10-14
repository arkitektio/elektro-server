"""The descriptors of elektro's arrays — the server-side twin of the client's vocabulary.

They are declared once, as data, in ``elektro_server.contract`` (their keys are in
``elektro_server.vocabulary``), and read from there by everything that states them: a signal carries the object's descriptors so rekuest can match
it against triggers and against the ``requires`` of the ports it would be fed to, and the
GraphQL types answer them as ``descriptors``, so a client can ask which actions take the object
in hand. Those ports were declared with the elektro client's spec
vocabulary (``elektro.specs``), so keys and meaning must match ``elektro.specs.lens_descriptors``:
one count per axis type (zero included) plus the total extent along channel, time (samples) and
index axes -- and what the values are: ``@elektro/value_dimension`` read off the dataset-wide
value unit in the client's words, ``@elektro/value_kind`` off the primary derivation.

What is computed is **stored** on the row (``stored_descriptors``) whenever it is saved or
restored, so a ``requires`` filter reads it in SQL and a signal and the field read the same
value. What a save of the row cannot see is restored by whoever writes it (:func:`restore`):
``createArrayDataset`` restores its dataset once its arrays and anchors are written, a value
unit restores its dataset and lenses, and a derivation edge the datasets it leaves.
"""

from collections import Counter
from collections.abc import Sequence

from kanne_server.scalars import get_registry, is_arbitrary_unit, normalize_compact_units

from elektro_server.vocabulary import EXTENT_KEYS, KEY_BY_AXIS_TYPE, REFERENCE_UNITS, VALUE_DIMENSION, VALUE_KIND


def array_descriptors(axis_types: Sequence[str], shape: Sequence[int]) -> dict[str, int]:
    """The descriptors of an array with these per-axis types and this (level-0) shape."""
    if len(axis_types) != len(shape):
        raise ValueError(f"{len(axis_types)} axis types for a {len(shape)}-dimensional shape")
    counts = Counter(axis_types)
    descriptors = {key: counts.get(axis_type, 0) for axis_type, key in KEY_BY_AXIS_TYPE.items()}
    for key, wanted in EXTENT_KEYS.items():
        descriptors[key] = sum(extent for axis_type, extent in zip(axis_types, shape) if axis_type == wanted)
    return descriptors


def value_dimension(unit: str | None) -> str:
    """What a value unit measures, in the client's words (``elektro.specs.value_dimension``); empty for no unit."""
    if unit is None or not unit.strip():
        return ""
    if is_arbitrary_unit(unit):
        return "arbitrary"
    registry = get_registry()
    try:
        dimensionality = registry.Unit(normalize_compact_units(unit)).dimensionality
    except Exception:  # noqa: BLE001 -- pint raises several unrelated types for an unknown unit
        return "other"
    for dimension, reference in REFERENCE_UNITS.items():
        if registry.Unit(reference).dimensionality == dimensionality:
            return dimension
    return "other"


def value_descriptors(dataset) -> dict[str, str]:  # noqa: ANN001 - a core.models.ArrayDataset
    """What a dataset's values are: what its dataset-wide unit measures, and whether a derivation declared them labels."""
    from core.logic import graph as graph_logic  # it imports the models this module describes

    categorical = dataset.pk in graph_logic.categorized_dataset_ids([dataset.pk])
    return {VALUE_DIMENSION: value_dimension(dataset.value_unit), VALUE_KIND: "categorical" if categorical else "continuous"}


def dataset_descriptors(dataset) -> dict[str, int | str]:  # noqa: ANN001 - a core.models.ArrayDataset
    """An array dataset's descriptors, from the row and what was written with it."""
    try:
        counted = array_descriptors([axis.type for axis in dataset.axes], dataset.shape_list)
    except ValueError:  # axes and shape disagree (a half-written dataset): no descriptors, still an object
        return {}
    return {**counted, **value_descriptors(dataset)}


def lens_descriptors(lens) -> dict[str, int | str]:  # noqa: ANN001 - a core.models.Lens
    """A lens' descriptors: its dataset's axes over the shape its slices cut out.

    A lens keeps every axis of its dataset (a slice narrows an axis, it never drops one), so
    this is the client's ``lens_descriptors`` computed from the same two facts.
    """
    try:
        counted = array_descriptors([axis.type for axis in lens.dataset.axes], lens.shape_list)
    except ValueError:
        return {}
    return {**counted, **value_descriptors(lens.dataset)}


def restore(target: object) -> None:
    """Store the descriptors of a row, or of every row of a queryset, again: for what was written after it.

    Inside the transaction that created the row this announces nothing more -- its CREATED reads
    what is stored at the commit; on a row made before, a change is announced as UPDATED.
    """
    from elektro_server.service import service  # it binds the models this module describes

    service.restore(target)


def restore_datasets(dataset_ids: Sequence[int]) -> None:
    """Restore these datasets and their lenses: what their values are was stated or derived again."""
    from core import models  # it imports this module's callers

    if dataset_ids:
        restore(models.ArrayDataset.objects.filter(pk__in=dataset_ids).order_by("pk"))
        restore(models.Lens.objects.filter(dataset_id__in=dataset_ids).order_by("pk"))
