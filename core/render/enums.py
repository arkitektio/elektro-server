import strawberry
from enum import Enum


@strawberry.enum
class RenderNodeKind(str, Enum):
    CONTEXT = "context"
    OVERLAY = "overlay"
    GRID = "grid"
    SPIT = "split"


