"""The stored pickers, and what they name.

The counterpart of mikro's ``core/logic/pickers.py``, with mikro's function names so the
vendored delete mutations read the same (``deleteTableDataset`` guards with
:func:`assert_table_not_in_a_picker`, ``deleteSparseDataset`` with
:func:`assert_sparse_dataset_not_in_a_picker`). What differs is *where* the pickers sit: mikro
keeps them on its ``Layer`` (mesh, point, network and label pickers); here they are the
``spike_*`` and ``event_*`` columns of :class:`core.models.ExperimentLayer`.

**Why a table cannot simply be deleted out from under a picker.** A picker entry names its table
by id, in JSON, so there is no foreign key and nothing cascades. Delete the table and the entry
survives as a join nothing can execute: the layer still claims to colour its units by a column
of a table that is not there, and the failure surfaces at render time, to whoever opens the
experiment next. Refusing the delete puts the discovery back where the decision is being made.

mikro's third guard, ``assert_edge_not_stranding_a_picker``, has no counterpart: a spikes
layer reaches its units table through a :class:`~core.models.SparseAxisReference` and an events
layer *is* its table, so no picker here crosses a FIELD edge a delete could strand.
"""

from typing import TYPE_CHECKING

from django.db.models import Q

from core import models

if TYPE_CHECKING:
    from django.db.models import QuerySet


#: The JSON columns the picker-bearing layer kinds keep their pickers in. Listed rather than
#: derived because they *are* the storage shape: a new picker on a new layer kind must be added
#: here, and ``tests/test_architecture.py::test_every_picker_column_is_guarded`` says so.
_PICKER_COLUMNS = (
    "spike_color_bys",
    "spike_filter_bys",
    "event_color_bys",
    "event_filter_bys",
)


def _names_table(table_id: str) -> Q:
    """Every way a stored picker entry can name one table.

    Two ways per picker: an entry names its terminal table in ``table``, *and* every table its
    ``join_path`` hops through. Deleting a table a path merely passes through breaks the join
    exactly as thoroughly as deleting the one the value is read from. JSONB containment
    (``@>``), which matches when some element of the list contains the pattern.
    """
    query = Q()
    for pattern in ([{"table": table_id}], [{"join_path": [{"table": table_id}]}]):
        for column in _PICKER_COLUMNS:
            query |= Q(**{f"{column}__contains": pattern})
    return query


def layers_naming_table(table) -> "QuerySet[models.ExperimentLayer]":  # noqa: ANN001 - a TableDataset
    """The layers whose colour or filter picker names this table, by any route.

    Not organization-scoped, deliberately: a guard that only looked at the caller's own
    organization would let a delete break something it could not see, and looking too widely
    only refuses a delete, which is recoverable.
    """
    return models.ExperimentLayer.objects.filter(_names_table(str(table.pk))).select_related("experiment").order_by("pk")


def _refuse(what: str, layers: list, total: int, verb: str) -> None:
    described = ", ".join(f"layer {layer.pk} in experiment '{layer.experiment.name}'" for layer in layers)
    more = f" (and {total - len(layers)} more)" if total > len(layers) else ""
    raise ValueError(
        f"{what} cannot be deleted: {total} layer(s) {verb} -- {described}{more}. "
        "A picker naming deleted data is a join nothing can execute, and it would look valid until a renderer tried it. "
        "Clear those entries first (pass the picker without them, or `[]` to remove it), or delete the layers."
    )


def assert_table_not_in_a_picker(table) -> None:  # noqa: ANN001 - a TableDataset
    """Refuse to delete a table some layer still colours or filters by."""
    layers = list(layers_naming_table(table)[:5])
    if layers:
        _refuse(f"Table dataset '{table.name}' ({table.pk})", layers, layers_naming_table(table).count(), "colour or filter by a column of it")


def _names_sparse_dataset(dataset_id: str) -> Q:
    """Every way a stored picker entry can name one sparse dataset: its ``dataset`` key."""
    query = Q()
    for column in _PICKER_COLUMNS:
        query |= Q(**{f"{column}__contains": [{"dataset": dataset_id}]})
    return query


def layers_naming_sparse_dataset(dataset) -> "QuerySet[models.ExperimentLayer]":  # noqa: ANN001 - a SparseDataset
    """Every layer whose pickers name this sparse dataset."""
    return models.ExperimentLayer.objects.filter(_names_sparse_dataset(str(dataset.pk))).select_related("experiment").order_by("pk")


def assert_sparse_dataset_not_in_a_picker(dataset) -> None:  # noqa: ANN001 - a SparseDataset
    """Refuse to delete a sparse dataset some layer's picker still names.

    A spikes layer *drawing* the raster is not a picker: it has a real foreign key and
    cascades with it, as a trace layer cascades with its lens. This guards only the JSON.
    """
    layers = list(layers_naming_sparse_dataset(dataset)[:5])
    if layers:
        _refuse(f"Sparse dataset '{dataset.name}' ({dataset.pk})", layers, layers_naming_sparse_dataset(dataset).count(), "colour by a slice of it")
