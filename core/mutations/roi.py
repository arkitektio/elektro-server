from kante.types import Info
import strawberry
from core import types, models, scalars, enums
from strawberry import ID
import strawberry_django


@strawberry_django.input(models.ROI)
class RoiInput:
    image: ID = strawberry.field(description="The image this ROI belongs to")
    vectors: list[scalars.FiveDVector] = strawberry.field(description="The vector coordinates defining the ROI")
    kind: enums.RoiKind = strawberry.field(description="The type/kind of ROI")


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
    image = models.Image.objects.get(id=input.image)


    roi = models.ROI.objects.create(
        image=image,
        vectors=input.vectors,
        kind=input.kind,
        creator=info.context.request.user
    )



    
    return roi


@strawberry_django.input(models.ROI)
class UpdateRoiInput:
    roi: ID
    vectors: list[scalars.FiveDVector] | None = None
    kind: enums.RoiKind | None = None
    entity: ID | None = None
    entity_kind: ID | None = None
    entity_group: ID | None = None
    entity_parent: ID | None = None




def update_roi(
    info: Info,
    input: UpdateRoiInput,
) -> types.ROI:
    item = models.ROI.objects.get(id=input.roi)
    item.vectors = input.vectors if input.vectors else item.vectors
    item.kind = input.kind if input.kind else item.kind
    item.entity = input.entity if input.entity else item.entity



    item.save()
    return item