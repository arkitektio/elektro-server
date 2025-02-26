from typing import List
from kante.types import Info
import strawberry
from core import types, models, scalars, enums
from strawberry import ID
import strawberry_django
from datetime import datetime
from django.contrib.auth import get_user_model

@strawberry_django.input(models.Accessor)
class AccessorInput:
    keys: list[str] 
    min_index: int | None = None
    max_index: int | None = None


@strawberry_django.input(models.LabelAccessor)
class PartialLabelAccessorInput(AccessorInput):
    pixel_view: ID
    pass


@strawberry_django.input(models.ImageAccessor)
class PartialImageAccessorInput(AccessorInput):
    image: ID
    pass



@strawberry_django.input(models.AffineTransformationView)
class LabelAccessorInput(PartialLabelAccessorInput):
    table: ID


@strawberry_django.input(models.LabelView)
class ImageAccessorInput(PartialImageAccessorInput):
    table: ID



def accessor_kwargs_from_input(input: LabelAccessorInput) -> dict:
    is_global = all(
        x is None
        for x in [
            input.min_index,
            input.max_index,
        ]
    )

    is_global = is_global and len(input.keys) == 0

    return dict(
        keys=input.keys,
        min_index=input.min_index,
        max_index=input.max_index,
        is_global=is_global,
    )


@strawberry.input()
class DeleteAccesorInput:
    id: strawberry.ID


def delete_accessor(
    info: Info,
    input: DeleteAccesorInput,
) -> strawberry.ID:
    item = models.Accessor.objects.get(id=input.id)
    item.delete()
    return input.id


@strawberry.input
class PinAccesorInput:
    id: strawberry.ID
    pin: bool


def pin_view(
    info: Info,
    input: PinAccesorInput,
) -> types.View:
    raise NotImplementedError("TODO")



def create_label_accessor(
    info: Info,
    input: LabelAccessorInput,
) -> types.ChannelView:
    table = models.Table.objects.get(id=input.table)

    view = models.LabelAccessor.objects.create(
        table=table,
        pixel_view=models.PixelView.objects.get(id=input.pixel_view),
        **accessor_kwargs_from_input(input),
    )
    return view


def create_image_accessor(
    info: Info,
    input: ImageAccessorInput,
) -> types.ChannelView:
    table = models.Table.objects.get(id=input.table)

    view = models.ImageAccessor.objects.create(
        table=table,
        image=models.Image.objects.get(id=input.image),
        **accessor_kwargs_from_input(input),
    )
    return view


