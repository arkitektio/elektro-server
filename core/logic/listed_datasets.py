"""What a list of array datasets reads per row, loaded for the whole list at once.

A dataset's ``multiscale``, ``shape``, ``axisNames``, ``valueUnit`` and ``simulation`` are
each derived from a related row (its levels, its system's axes, its whole-dataset anchor).
Read row by row that is four or five queries per dataset in a list. The prefetches here
load them for every dataset of a queryset in one query each; the readers use what was
prefetched and fall back to asking, so a dataset fetched some other way still answers.
"""

from django.db.models import Prefetch, QuerySet

from core import models

UNIT_ANCHORS = "listed_unit_anchors"
"""The whole-dataset anchor carrying a value unit, prefetched (a list of at most one)."""

SIMULATION_ANCHORS = "listed_simulation_anchors"
"""The whole-dataset anchor carrying a simulation state with its model (at most one)."""


def unit_anchors() -> Prefetch:
    """The dataset-wide anchor with a :class:`ValueUnit`, as :data:`UNIT_ANCHORS`."""
    return Prefetch(
        "anchors",
        queryset=models.CoordinateAnchor.objects.filter(
            coordinates={}, value_unit__isnull=False
        ).select_related("value_unit"),
        to_attr=UNIT_ANCHORS,
    )


def simulation_anchors() -> Prefetch:
    """The dataset-wide anchor with a :class:`SimulationState`, as :data:`SIMULATION_ANCHORS`."""
    return Prefetch(
        "anchors",
        queryset=models.CoordinateAnchor.objects.filter(
            coordinates={}, simulation__isnull=False
        ).select_related("simulation__model"),
        to_attr=SIMULATION_ANCHORS,
    )


def with_list_facts(
    datasets: QuerySet[models.ArrayDataset],
) -> QuerySet[models.ArrayDataset]:
    """``datasets`` with everything a list row reads loaded alongside."""
    return datasets.select_related("coordinate_system").prefetch_related(
        "data_arrays", "coordinate_system__axes", unit_anchors(), simulation_anchors()
    )


def levels(dataset: models.ArrayDataset) -> list[models.DataArray]:
    """The dataset's pyramid levels, finest first (prefetched or asked)."""
    return sorted(dataset.data_arrays.all(), key=lambda array: array.level)


def multiscale(dataset: models.ArrayDataset) -> bool:
    """Whether the dataset has more than one pyramid level."""
    return len(dataset.data_arrays.all()) > 1


def shape(dataset: models.ArrayDataset) -> list[int]:
    """The shape of the dataset's finest level."""
    found = levels(dataset)
    return list(found[0].shape) if found and isinstance(found[0].shape, list) else []


def value_unit(dataset: models.ArrayDataset) -> str | None:
    """The dataset-wide value unit."""
    anchors: list[models.CoordinateAnchor] | None = getattr(dataset, UNIT_ANCHORS, None)
    if anchors is None:
        return dataset.value_unit
    return anchors[0].value_unit.unit if anchors else None


def simulation(dataset: models.ArrayDataset) -> models.SimulationState | None:
    """The simulation state anchored at ``{}``, with its model."""
    anchors: list[models.CoordinateAnchor] | None = getattr(
        dataset, SIMULATION_ANCHORS, None
    )
    if anchors is None:
        return (
            models.SimulationState.objects.filter(
                anchor__dataset_id=dataset.pk, anchor__coordinates={}
            )
            .select_related("model")
            .first()
        )
    return anchors[0].simulation if anchors else None
