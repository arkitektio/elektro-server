import strawberry
from typing import Optional
from pydantic import BaseModel
from strawberry.experimental import pydantic
from typing import Literal, Union
import datetime
from typing import Any


class RenderNodeModel(BaseModel):
    kind: str

class SplitNodeModel(RenderNodeModel):
    kind: Literal["split"]
    children: list["RenderNodeUnion"]
    label: str | None = None


class ContextNodeModel(RenderNodeModel):
    kind: Literal["context"]
    context: str
    label: str | None = None


class OverlayNodeModel(RenderNodeModel):
    kind: Literal["overlay"]
    children: list["RenderNodeUnion"]
    label: str | None = None


class GridNodeModel(RenderNodeModel):
    kind: Literal["grid"]
    children: list["RenderNodeUnion"]
    gap: int | None = None
    label: str | None = None



RenderNodeUnion = Union[ContextNodeModel, OverlayNodeModel, GridNodeModel]


class TreeModel(BaseModel):
    children: list[RenderNodeUnion]


GridNodeModel.update_forward_refs()
OverlayNodeModel.update_forward_refs()
ContextNodeModel.update_forward_refs()
TreeModel.update_forward_refs()
