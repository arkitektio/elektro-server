from kante.types import Info
import strawberry
from core import types, models, scalars, enums
from strawberry import ID
import strawberry_django


@strawberry_django.input(models.ROI)
class RoiInput:
    trace: ID = strawberry.field(description="The image this ROI belongs to")
    vectors: list[scalars.TwoDVector] = strawberry.field(description="The vector coordinates defining the as XY")
    kind: enums.RoiKind = strawberry.field(description="The type/kind of ROI")
    label: str | None = strawberry.field(default=None, description="The label of the ROI")
    


@strawberry.input()
class DeleteRoiInput:
    id: strawberry.ID


@strawberry.input
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
    item = models.ROI.objects.get(id=input.id)
    item.delete()
    return input.id


def create_roi(
    info: Info,
    input: RoiInput,
) -> types.ROI:
    trace = models.Trace.objects.get(id=input.trace)

    max_t = max([i[0] for i in input.vectors])
    min_t = min([i[0] for i in input.vectors])



    roi = models.ROI.objects.create(
        trace=trace,
        vectors=input.vectors,
        max_t = max_t,
        min_t = min_t,
        kind=input.kind,
        creator=info.context.request.user,
        label=input.label,
    )



    
    return roi


@strawberry_django.input(models.ROI)
class UpdateRoiInput:
    roi: ID
    label: str | None = None
    vectors: list[scalars.TwoDVector] | None = None
    kind: enums.RoiKind | None = None



def update_roi(
    info: Info,
    input: UpdateRoiInput,
) -> types.ROI:
    item = models.ROI.objects.get(id=input.roi)
    item.vectors = input.vectors if input.vectors else item.vectors
    item.kind = input.kind if input.kind else item.kind
    item.label = input.label if input.label else item.label



    item.save()
    return item