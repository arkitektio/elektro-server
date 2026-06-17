from kante.types import Info
import strawberry
import kante
from typing import Any
from pydantic import BaseModel, Field
from core import types, models, scalars, enums
from core.guards import enforce_delete
from strawberry import ID


class RoiInputModel(BaseModel):
    trace: str = Field(description="The image this ROI belongs to")
    vectors: list[Any] = Field(description="The vector coordinates defining the as XY")
    kind: enums.RoiKind = Field(description="The type/kind of ROI")
    label: str | None = Field(default=None, description="The label of the ROI")


@kante.pydantic_input(RoiInputModel)
class RoiInput:
    trace: ID = strawberry.field(description="The image this ROI belongs to")
    vectors: list[scalars.TwoDVector] = strawberry.field(description="The vector coordinates defining the as XY")
    kind: enums.RoiKind = strawberry.field(description="The type/kind of ROI")
    label: str | None = strawberry.field(default=None, description="The label of the ROI")


class DeleteRoiInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteRoiInputModel)
class DeleteRoiInput:
    id: strawberry.ID


class PinROIInputModel(BaseModel):
    id: str
    pin: bool


@kante.pydantic_input(PinROIInputModel)
class PinROIInput:
    id: strawberry.ID
    pin: bool


def pin_roi(
    info: Info,
    input: PinROIInput,
) -> types.ROI:
    raise NotImplementedError("TODO")


def delete_roi(
    info: Info,
    input: DeleteRoiInput,
) -> strawberry.ID:
    parsed = input.to_pydantic()
    item = models.ROI.objects.get(id=parsed.id)
    enforce_delete(info, item)
    item.delete()
    return parsed.id


def create_roi(
    info: Info,
    input: RoiInput,
) -> types.ROI:
    parsed = input.to_pydantic()
    trace = models.Trace.objects.get(id=parsed.trace)

    max_t = max([i[0] for i in parsed.vectors])
    min_t = min([i[0] for i in parsed.vectors])

    roi = models.ROI.objects.create(
        trace=trace,
        vectors=parsed.vectors,
        max_t=max_t,
        min_t=min_t,
        kind=parsed.kind,
        creator=info.context.request.user,
        label=parsed.label,
    )

    return roi


class UpdateRoiInputModel(BaseModel):
    roi: str
    label: str | None = None
    vectors: list[Any] | None = None
    kind: enums.RoiKind | None = None


@kante.pydantic_input(UpdateRoiInputModel)
class UpdateRoiInput:
    roi: ID
    label: str | None = None
    vectors: list[scalars.TwoDVector] | None = None
    kind: enums.RoiKind | None = None


def update_roi(
    info: Info,
    input: UpdateRoiInput,
) -> types.ROI:
    parsed = input.to_pydantic()
    item = models.ROI.objects.get(id=parsed.roi)
    item.vectors = parsed.vectors if parsed.vectors else item.vectors
    item.kind = parsed.kind if parsed.kind else item.kind
    item.label = parsed.label if parsed.label else item.label

    item.save()
    return item
