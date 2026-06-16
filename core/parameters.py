"""A simple parameter port for mechanisms.

This replaces the more complex ``ArgPort`` that used to live in
``rekuest_core``. A mechanism parameter only needs a handful of fields,
so we keep it deliberately simple here.
"""

from enum import Enum
from typing import Any, Optional

import strawberry
from strawberry.experimental import pydantic
from pydantic import BaseModel

from core import scalars


@strawberry.enum(description="The kind of a mechanism parameter.")
class ParameterKind(str, Enum):
    INT = "INT"
    FLOAT = "FLOAT"
    STRING = "STRING"
    BOOL = "BOOL"


class ParameterModel(BaseModel):
    key: str
    label: Optional[str] = None
    kind: ParameterKind = ParameterKind.FLOAT
    description: Optional[str] = None
    default: Optional[Any] = None
    nullable: bool = False


class ParameterInputModel(BaseModel):
    key: str
    label: Optional[str] = None
    kind: ParameterKind = ParameterKind.FLOAT
    description: Optional[str] = None
    default: Optional[Any] = None
    nullable: bool = False


@pydantic.type(ParameterModel, description="A parameter port of a mechanism")
class Parameter:
    key: str
    label: Optional[str] = None
    kind: ParameterKind = ParameterKind.FLOAT
    description: Optional[str] = None
    default: Optional[scalars.Any] = None
    nullable: bool = False


@pydantic.input(ParameterInputModel, description="A parameter port of a mechanism")
class ParameterInput:
    key: str
    label: Optional[str] = None
    kind: ParameterKind = ParameterKind.FLOAT
    description: Optional[str] = None
    default: Optional[scalars.Any] = None
    nullable: bool = False
