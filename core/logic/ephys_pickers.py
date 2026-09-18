"""Checking a spikes or events layer's pickers against the tables they name.

elektro's own, and small, where mikro's picker validation (``core/mutations/layer.py``,
``core/logic/column_options.py``) walks FIELD edges from a mask into the tables it keys. Here
nothing has to be walked through space: an events layer's rows *are* the rows of its table, and
a spikes layer's units are the rows of the table identifying its unit axis. So the reachable
tables are that one **root** and whatever its columns' ``references`` lead to, and the checks
are mikro's, in the same words:

* the ``table`` is reachable, and ``joinPath`` is the way it is reached -- every hop a column
  that references the next table;
* the ``column`` is declared on that table;
* a categorical column takes a qualitative colormap and no window, a measure a continuous one;
* a filter's range goes with a measure and its ``values`` with a category;
* the active indices point at entries that exist.

Entries are stored as their pydantic dumps (:mod:`core.render.pickers`), so what is read back
is what was checked.
"""

from collections.abc import Sequence

from core import enums, models
from core.render import pickers as picker_models

#: The roles whose values are categories rather than measures. A qualitative colormap and a
#: ``values`` filter go with these; a continuous colormap, a window and a range with the rest.
CATEGORICAL_ROLES = frozenset(
    {
        enums.ColumnRoleChoices.ID.value,
        enums.ColumnRoleChoices.TRACK_ID.value,
        enums.ColumnRoleChoices.GROUP_ID.value,
        enums.ColumnRoleChoices.LABEL.value,
    }
)


def spike_root(dataset: "models.SparseDataset") -> "models.TableDataset | None":
    """The table a spike raster's units are rows of: the one identifying its INDEX axis.

    A raster has one INDEX axis (its units) and one TIME axis. When the unit axis is identified
    by a table, that table is where a unit's depth, channel and quality live, and so where every
    spikes picker starts. None for a raster whose units nothing names -- it has nothing to colour by.
    """
    reference = dataset.axis_references.select_related("references").order_by("pk").first()
    return reference.references if reference is not None else None


def raster_parent(dataset: "models.ArrayDataset") -> "models.SparseDataset | None":
    """The spike raster an array dataset was derived from, when its primary parent is one.

    Waveform templates ``(unit, c, w)`` are computed from a sorting, and say so with a
    ``derivedFrom`` naming the raster's space -- UNMAPPABLE, since a template sample is no
    position of the raster. That edge is what ties a template's ``unit`` to the raster's units,
    and so to the units table the pickers colour by.
    """
    from core.logic import graph as graph_logic

    edges = graph_logic.derivation_edges(dataset)
    if not edges or edges[0].output_id is None:
        return None
    return models.SparseDataset.objects.filter(coordinate_system_id=edges[0].output_id).first()


def waveform_root(dataset: "models.ArrayDataset") -> "models.TableDataset | None":
    """The units table a waveform layer's pickers start at: its raster's, or None when it was derived from no raster."""
    raster = raster_parent(dataset)
    return spike_root(raster) if raster is not None else None


def reachable_tables(root: "models.TableDataset | None") -> dict[str, list[tuple[str, str]]]:
    """Every table reachable from ``root`` along ``Column.references``, with the path to it.

    ``{table id: [(table id, column), ...]}`` -- the join path each is reached by, shortest
    first (breadth-first), the root itself at the empty path.
    """
    if root is None:
        return {}
    paths: dict[str, list[tuple[str, str]]] = {str(root.pk): []}
    frontier = [root.pk]
    while frontier:
        columns = models.Column.objects.filter(table_id__in=frontier, references__isnull=False).order_by("table_id", "order")
        frontier = []
        for column in columns:
            target = str(column.references_id)
            if target in paths:
                continue
            paths[target] = [*paths[str(column.table_id)], (str(column.table_id), column.name)]
            frontier.append(column.references_id)
    return paths


def _column(table_id: str, name: str) -> "models.Column | None":
    return models.Column.objects.filter(table_id=table_id, name=name).first()


def _check_route(entry, root: "models.TableDataset | None", what: str) -> "models.Column":  # noqa: ANN001 - a picker model
    """The column an entry names, refused unless its ``joinPath`` leads from ``root`` to its table.

    Walked forward: every step stands in the table the previous one reached and names a column
    that references the next; the last lands on the entry's own ``table``. An empty path is
    the direct case -- the column is on the root itself.
    """
    if root is None:
        raise ValueError(f"This layer has no table to {what} by: its data names none (a spike raster whose unit axis no table identifies has nothing to look a unit up in).")
    here = str(root.pk)
    for step in entry.join_path:
        if step.table != here:
            raise ValueError(f"Join step ({step.table}, '{step.column}') does not stand in table {here}, which is where the path has reached. Each step names a column of the table the previous one led to.")
        column = _column(step.table, step.column)
        if column is None or column.references_id is None:
            raise ValueError(f"Column '{step.column}' of table {step.table} references no table, so the path cannot continue through it. Only a column declared with a TABLE identification is a hop.")
        here = str(column.references_id)
    if here != entry.table:
        path = reachable_tables(root).get(entry.table)
        hint = f" It is reached by {[{'table': t, 'column': c} for t, c in path]}." if path is not None else " It is not reachable from this layer's table at all."
        raise ValueError(f"The join path ends at table {here}, not at table {entry.table}, which the entry reads.{hint}")
    column = _column(entry.table, entry.column)
    if column is None:
        raise ValueError(f"Table {entry.table} declares no column '{entry.column}'.")
    return column


def validate_color_bys(entries: Sequence, root: "models.TableDataset | None") -> list[dict]:
    """Check each colour picker entry, and return the dumps to store."""
    dumps: list[dict] = []
    for raw in entries:
        entry = raw if isinstance(raw, picker_models.ColorByModel) else picker_models.ColorByModel(**raw)
        column = _check_route(entry, root, "colour")
        categorical = column.role in CATEGORICAL_ROLES
        if entry.colormap is not None and (entry.colormap in enums.QUALITATIVE_COLORMAPS) != categorical:
            want = "a qualitative colormap (hues, distinct, pastel, vivid)" if categorical else "a continuous colormap"
            raise ValueError(f"Column '{column.name}' is {'a category' if categorical else 'a measure'}, so it takes {want}, not '{entry.colormap.value}'.")
        if categorical and (entry.min is not None or entry.max is not None):
            raise ValueError(f"Column '{column.name}' is a category, which has no order to window: drop `min` / `max`.")
        dump = entry.model_dump(mode="json")
        if dump in dumps:
            raise ValueError(f"The colour picker names ({entry.table}, '{entry.column}') twice with the same settings. Two rows that render identically are one row.")
        dumps.append(dump)
    return dumps


def validate_filter_bys(entries: Sequence, root: "models.TableDataset | None") -> list[dict]:
    """Check each filter picker entry, and return the dumps to store."""
    dumps: list[dict] = []
    for raw in entries:
        entry = raw if isinstance(raw, picker_models.FilterByModel) else picker_models.FilterByModel(**raw)
        column = _check_route(entry, root, "filter")
        categorical = column.role in CATEGORICAL_ROLES
        if categorical and entry.values is None:
            raise ValueError(f"Column '{column.name}' is a category, so a filter over it keeps a set of `values`, not a range.")
        if not categorical and entry.values is not None and column.role != enums.ColumnRoleChoices.COLOR.value:
            raise ValueError(f"Column '{column.name}' is a measure, so a filter over it keeps a range (`min` / `max`), not a set of values.")
        dumps.append(entry.model_dump(mode="json"))
    return dumps


def assert_active_color_by(active: int | None, color_bys: list) -> None:
    """The active colouring is an index into the picker, or none."""
    if active is not None and not 0 <= active < len(color_bys):
        raise ValueError(f"`activeColorBy` is {active}, but the picker has {len(color_bys)} entr{'y' if len(color_bys) == 1 else 'ies'}.")


def assert_active_filter_bys(active: Sequence[int], filter_bys: list) -> None:
    """Every active filter is an index into the picker, named once."""
    wrong = sorted({index for index in active if not 0 <= index < len(filter_bys)})
    if wrong:
        raise ValueError(f"`activeFilterBys` names {wrong}, but the picker has {len(filter_bys)} entries.")
    if len(set(active)) != len(active):
        raise ValueError("`activeFilterBys` names a filter more than once. A rule applied twice is the rule applied once.")
