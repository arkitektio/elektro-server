import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models.expressions import Expression
from django.db.models.sql.compiler import SQLCompiler

if TYPE_CHECKING:
    # django-stubs' name for what `as_sql` returns; it exists only in the stubs.
    from django.db.models.sql.compiler import _AsSqlType

#: A cube corner: one coordinate per dimension.
Corner = Sequence[float]


def validate_s3(value: str) -> None:
    s3_pattern = r"^s3://.+/.+/.+"
    if not re.match(s3_pattern, value):
        raise ValidationError(
            "Invalid S3 path format. Should be s3://datalayer/bucket_name/object_key",
            code="invalid",
        )


class S3Field(models.CharField):
    description = "CharField to store S3 path for Zarr dataset with validation"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["max_length"] = kwargs.get("max_length", 500)

        super().__init__(*args, **kwargs)


# --- PostgreSQL ``cube`` (vendored from mikro's core/fields.py) ---------------------------------
#
# Stores an axis-aligned N-dimensional box and is GiST-indexable: overlap (``&&``), containment
# (``@>``) and nearest-by-distance (``<->``) all use the index. An annotation's bounding box is
# kept in one, which is what makes "every event between 12.0 s and 12.5 s" an index scan.
# Everything is exchanged as cube *text literals* with an explicit ``::cube`` cast: psycopg3's
# binding mode must never be relied on to cast an untyped text parameter implicitly.


def cube_literal(low: Corner, high: Corner | None = None) -> str:
    """The cube text literal for a point or a (low, high) box, e.g. ``(0.0, 1.0),(2.0, 3.0)``."""

    def corner(values: Corner) -> str:
        return "(" + ", ".join(repr(float(value)) for value in values) + ")"

    return corner(low) if high is None else f"{corner(low)},{corner(high)}"


class CubeField(models.Field):
    """A PostgreSQL ``cube`` column: an axis-aligned box, GiST-indexable for spatial search.

    Write-only as far as the API is concerned: values are denormalized from a JSON
    source of truth at write time and only ever *queried* (never resolved back), so
    reads return the raw text representation and no parsing is implemented.
    """

    description = "An axis-aligned N-dimensional box (PostgreSQL cube)"

    def db_type(self, connection: BaseDatabaseWrapper) -> str:
        """The column type: the extension's ``cube``."""
        return "cube"

    def get_placeholder(
        self, value: object, compiler: SQLCompiler, connection: BaseDatabaseWrapper
    ) -> str:
        """The write placeholder, with an explicit cast.

        A bare text parameter is `text`, not `unknown`, under client- and
        server-side binding alike, and `text -> cube` has no implicit cast.
        """
        return "%s::cube"

    def get_prep_value(self, value: object) -> str | None:
        """Serialize a bbox dict, (low, high) pair, or bare point to a cube text literal."""
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, dict):
            # The intrinsic_bbox dict itself: {'min': [...], 'max': [...]}.
            return cube_literal(value["min"], value["max"])
        if (
            isinstance(value, (list, tuple))
            and value
            and isinstance(value[0], (list, tuple))
        ):
            return cube_literal(value[0], value[1])
        return cube_literal(value)

    def from_db_value(
        self,
        value: str | None,
        expression: Expression,
        connection: BaseDatabaseWrapper,
    ) -> str | None:
        """The raw cube text representation -- never parsed, the column is query-only."""
        return value


class CubeOverlaps(models.Lookup):
    """``&&`` -- whether two boxes share any point. GiST-accelerated."""

    lookup_name = "overlaps"

    def as_sql(
        self, compiler: SQLCompiler, connection: BaseDatabaseWrapper
    ) -> "_AsSqlType":
        """``lhs && rhs::cube``."""
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} && {rhs}::cube", (*lhs_params, *rhs_params)


class CubeContainsPoint(models.Lookup):
    """``@>`` -- whether the box contains the probe (a zero-volume point cube). GiST-accelerated."""

    lookup_name = "contains_point"

    def as_sql(
        self, compiler: SQLCompiler, connection: BaseDatabaseWrapper
    ) -> "_AsSqlType":
        """``lhs @> rhs::cube``."""
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} @> {rhs}::cube", (*lhs_params, *rhs_params)


CubeField.register_lookup(CubeOverlaps)
CubeField.register_lookup(CubeContainsPoint)
