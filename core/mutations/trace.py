from kante.types import Info
import strawberry

from core import types, models, scalars
from datalayer.datalayer import get_current_datalayer
import json
from django.conf import settings
from django.contrib.auth import get_user_model
from core.managers import auto_create_views

from datalayer.scalars import ArrayLike


def relate_to_dataset(
    info: Info,
    id: strawberry.ID,
    other: strawberry.ID,
) -> types.Trace:
    image = models.Trace.objects.get(id=id)
    other = models.Dataset.objects.get(id=other)

    return image


@strawberry.input
class PinImageInput:
    id: strawberry.ID
    pin: bool


def pin_trace(
    info: Info,
    input: PinImageInput,
) -> types.Trace:
    raise NotImplementedError("TODO")


@strawberry.input
class UpdateTraceInput:
    id: strawberry.ID
    tags: list[str] | None = None
    name: str | None = None


def update_trace(
    info: Info,
    input: UpdateTraceInput,
) -> types.Trace:
    image = models.Trace.objects.get(id=input.id)

    if input.tags:
        image.tags.add(*input.tags)

    if input.name:
        image.name = input.name

    image.save()

    return image


@strawberry.input()
class DeleteTraceInput:
    id: strawberry.ID


def delete_trace(
    info: Info,
    input: DeleteTraceInput,
) -> strawberry.ID:
    item = models.Trace.objects.get(id=input.id)
    item.delete()
    return input.id


@strawberry.input(description="Input type for creating an image from an array-like object")
class FromTraceLikeInput:
    array: ArrayLike = strawberry.field(description="The array-like object to create the image from")
    name: str = strawberry.field(description="The name of the image")
    dataset: strawberry.ID | None = strawberry.field(default=None, description="Optional dataset ID to associate the image with")
    tags: list[str] | None = strawberry.field(default=None, description="Optional list of tags to associate with the image")


def from_trace_like(
    info: Info,
    input: FromTraceLikeInput,
) -> types.Trace:
    datalayer = get_current_datalayer()

    store = models.ZarrStore.objects.get(id=input.array)
    store.fill_info(datalayer)

    dataset = input.dataset or get_trace_dataset(info)

    image = models.Trace.objects.create(
        dataset_id=dataset,
        creator=info.context.request.user,
        organization=info.context.request.organization,
        name=input.name,
        store=store,
    )

    if input.tags:
        image.tags.add(*input.tags)

    print(input)

    return image


def get_trace_dataset(info: Info) -> models.Dataset:
    return models.Dataset.objects.get_or_create(organization=info.context.request.organization, creator=info.context.request.user, name="Default Dataset")[0]
