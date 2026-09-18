"""What a spikes or events layer's colour and filter pickers store: column-backed entries.

The **stored shape is mikro's** (``mikro/core/render/{color_by,filter_by,joins}.py``), field for
field, so a client that reads a mikro picker reads these: ``table``, ``column``, ``joinPath``
(``[{table, column}]``), ``colormap``, ``min`` / ``max``, ``label`` -- and for a filter, ``values``
and ``exclude``. What is left out is the rest of mikro's union: a SPARSE entry (colour by one
slice of a matrix) and a GRAPH one (a network's per-node values). Neither has a source here yet,
so ``kind`` is stored for parity and admits COLUMN only.

A picker entry names its table by id, never its key: which column of a table holds row identity
is declared on the table (its single INDEX coordinate column), and a per-entry copy could
disagree with it. ``joinPath`` is how a column further than one table away is reached -- a
chain of ``Column.references`` hops, empty for the direct case. For an events layer the direct
case is the event table itself; for a spikes layer it is the table identifying the raster's
unit axis.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from core import enums


class JoinStepModel(BaseModel):
    """One reference hop: the column whose values identify rows of the next table.

    Carries the table it *stands in*, not the one it points at: the target is named by the next
    step, or for the last one by the entry's own ``table``.
    """

    table: str
    column: str


class ColorByModel(BaseModel):
    """Colour a layer's rows (events) or units (spikes) by a column of a table they reach.

    Which *sort* of colormap applies follows from the column's declared role rather than from a
    choice here: a measure takes a continuous colormap over its range, a categorical column (an
    id, a label) a qualitative one over its distinct values. ``min`` / ``max`` window a
    continuous colormap, in the column's own unit; a categorical column has no order to window.
    """

    kind: Literal["COLUMN"] = "COLUMN"
    table: str
    column: str
    join_path: list[JoinStepModel] = Field(default_factory=list)
    colormap: enums.ColorMap | None = None
    min: float | None = None
    max: float | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "ColorByModel":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"A colormap window runs from `min` to `max`, but {self.min} > {self.max}")
        return self


class FilterByModel(BaseModel):
    """Keep or drop a layer's rows (events) or units (spikes) by a column of a table they reach.

    A range (``min`` / ``max``, inclusive, in the column's unit) for a measure; a set of
    ``values`` for a categorical column. ``exclude`` inverts the rule: drop what it matches.
    """

    kind: Literal["COLUMN"] = "COLUMN"
    table: str
    column: str
    join_path: list[JoinStepModel] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    values: list[str] | None = None
    exclude: bool = False
    label: str | None = None

    @model_validator(mode="after")
    def _one_rule(self) -> "FilterByModel":
        ranged = self.min is not None or self.max is not None
        if ranged and self.values is not None:
            raise ValueError("A filter keeps a range (`min` / `max`) of a measure or a set of `values` of a category -- not both")
        if not ranged and self.values is None:
            raise ValueError("A filter needs a rule: a range (`min` / `max`) for a measure, or `values` for a category")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"A filter range runs from `min` to `max`, but {self.min} > {self.max}")
        return self
