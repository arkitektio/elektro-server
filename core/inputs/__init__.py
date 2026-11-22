import kante
import strawberry
from pydantic import BaseModel


class AssociateInputModel(BaseModel):
    selfs: list[str]
    other: str


@kante.pydantic_input(AssociateInputModel)
class AssociateInput:
    selfs: list[strawberry.ID]
    other: strawberry.ID


class DesociateInputModel(BaseModel):
    selfs: list[str]
    other: str


@kante.pydantic_input(DesociateInputModel)
class DesociateInput:
    selfs: list[strawberry.ID]
    other: strawberry.ID


@strawberry.input(
    description="A value window along one axis of a container's anchor coordinates: a time window in samples, one channel (`min == max`)"
)
class AnchorWindowInput:
    """A range along one named axis, either side open."""

    axis: str = strawberry.field(
        description="The name of the axis the window constrains, e.g. 't' for a recording's time axis"
    )
    min: float | None = strawberry.field(
        default=None,
        description="The smallest position kept, inclusive, or None for no lower bound",
    )
    max: float | None = strawberry.field(
        default=None,
        description="The largest position kept, inclusive, or None for no upper bound",
    )
