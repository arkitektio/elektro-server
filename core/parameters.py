"""A simple parameter port for mechanisms.

This replaces the more complex ``ArgPort`` that used to live in
``rekuest_core``. A mechanism parameter only needs a handful of fields,
so we keep it deliberately simple here.
"""

from enum import Enum
from typing import Any, Optional

import strawberry
from strawberry.experimental import pydantic
from pydantic import BaseModel, model_validator
from typing_extensions import Self

from core import scalars
from core.units import dimensionality_of


@strawberry.enum(description="The kind of a mechanism parameter.")
class ParameterKind(str, Enum):
    INT = "INT"
    FLOAT = "FLOAT"
    STRING = "STRING"
    BOOL = "BOOL"


#: Kinds that may carry a physical unit. STRING/BOOL parameters are unitless.
_NUMERIC_KINDS = (ParameterKind.FLOAT, ParameterKind.INT)


class ParameterModel(BaseModel):
    key: str
    label: Optional[str] = None
    kind: ParameterKind = ParameterKind.FLOAT
    description: Optional[str] = None
    default: Optional[Any] = None
    nullable: bool = False
    # Permissive read model: no validation, so params persisted before units
    # existed still hydrate.
    reference_unit: Optional[str] = None
    proposed_units: Optional[list[str]] = None
    dimension: Optional[str] = None


class ParameterInputModel(BaseModel):
    key: str
    label: Optional[str] = None
    kind: ParameterKind = ParameterKind.FLOAT
    description: Optional[str] = None
    default: Optional[Any] = None
    nullable: bool = False
    reference_unit: Optional[str] = None
    proposed_units: Optional[list[str]] = None
    dimension: Optional[str] = None

    @model_validator(mode="after")
    def check_units(self) -> Self:
        if self.reference_unit is None:
            offending = [
                f
                for f in ("proposed_units", "dimension")
                if getattr(self, f) is not None
            ]
            if offending:
                raise ValueError(
                    f"Parameter '{self.key}' sets {', '.join(offending)} "
                    "without a reference_unit"
                )
            return self

        if self.kind not in _NUMERIC_KINDS:
            raise ValueError(
                f"Parameter '{self.key}' of kind {self.kind.value} cannot carry a "
                "unit; only FLOAT and INT parameters may set reference_unit"
            )

        derived = dimensionality_of(self.reference_unit)
        if self.dimension is not None and dimensionality_of(self.dimension) != derived:
            raise ValueError(
                f"Parameter '{self.key}': dimension '{self.dimension}' is "
                f"inconsistent with reference_unit '{self.reference_unit}' "
                f"(dimensionality '{derived}')"
            )
        self.dimension = derived  # derive or canonicalize the compatibility key
        for unit in self.proposed_units or []:
            unit_dim = dimensionality_of(unit)
            if unit_dim != derived:
                raise ValueError(
                    f"Parameter '{self.key}': proposed unit '{unit}' has "
                    f"dimensionality '{unit_dim}', expected '{derived}'"
                )
        return self


@pydantic.type(ParameterModel, description="A parameter port of a mechanism")
class Parameter:
    key: str
    label: Optional[str] = None
    kind: ParameterKind = ParameterKind.FLOAT
    description: Optional[str] = None
    default: Optional[scalars.Any] = None
    nullable: bool = False
    reference_unit: Optional[str] = strawberry.field(
        default=None,
        description=(
            "The canonical/reference unit of the parameter, e.g. 'mV' or 'S/cm2'. "
            "It is the default selection; other units of the same dimension are "
            "still allowed."
        ),
    )
    proposed_units: Optional[list[str]] = strawberry.field(
        default=None,
        description=(
            "Units offered as a dropdown in the UI, e.g. ['S/cm2', 'mS/cm2']. "
            "Proposals only — any unit of the same dimension remains valid."
        ),
    )
    dimension: Optional[str] = strawberry.field(
        default=None,
        description=(
            "The canonical pint dimensionality of the parameter's unit, e.g. "
            "'[length] ** 2 * [mass] / [current] / [time] ** 3'."
        ),
    )


@pydantic.input(ParameterInputModel, description="A parameter port of a mechanism")
class ParameterInput:
    key: str
    label: Optional[str] = None
    kind: ParameterKind = ParameterKind.FLOAT
    description: Optional[str] = None
    default: Optional[scalars.Any] = None
    nullable: bool = False
    reference_unit: Optional[str] = strawberry.field(
        default=None,
        description=(
            "The canonical/reference unit of the parameter, e.g. 'mV' or 'S/cm2'. "
            "It is the default selection; other units of the same dimension are "
            "still allowed. Only valid for FLOAT and INT parameters."
        ),
    )
    proposed_units: Optional[list[str]] = strawberry.field(
        default=None,
        description=(
            "Units offered as a dropdown in the UI. Proposals only — each must "
            "share the reference_unit's dimension."
        ),
    )
    dimension: Optional[str] = strawberry.field(
        default=None,
        description=(
            "The canonical pint dimensionality. Derived from reference_unit if "
            "omitted; cross-checked for consistency if provided."
        ),
    )
