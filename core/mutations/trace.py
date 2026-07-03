from kante.types import Info
import strawberry
import kante
from typing import Any
from pydantic import BaseModel, Field

from core import types, models, scalars
from core.guards import enforce_delete
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


class PinImageInputModel(BaseModel):
    id: str
    pin: bool


@kante.pydantic_input(PinImageInputModel)
class PinImageInput:
    id: strawberry.ID
    pin: bool


def pin_trace(
    info: Info,
    input: PinImageInput,
) -> types.Trace:
    raise NotImplementedError("TODO")


class UpdateTraceInputModel(BaseModel):
    id: str
    tags: list[str] | None = None
    name: str | None = None


@kante.pydantic_input(UpdateTraceInputModel)
class UpdateTraceInput:
    id: strawberry.ID
    tags: list[str] | None = None
    name: str | None = None


def update_trace(
    info: Info,
    input: UpdateTraceInput,
) -> types.Trace:
    parsed = input.to_pydantic()
    image = models.Trace.objects.get(id=parsed.id)

    if parsed.tags:
        image.tags.add(*parsed.tags)

    if parsed.name:
        image.name = parsed.name

    image.save()

    return image


class DeleteTraceInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteTraceInputModel)
class DeleteTraceInput:
    id: strawberry.ID


def delete_trace(
    info: Info,
    input: DeleteTraceInput,
) -> strawberry.ID:
    parsed = input.to_pydantic()
    item = models.Trace.objects.get(id=parsed.id)
    enforce_delete(info, item)
    item.delete()
    return parsed.id


class FromTraceLikeInputModel(BaseModel):
    array: Any = Field(description="The array-like object to create the image from")
    name: str = Field(description="The name of the image")
    dataset: str | None = Field(default=None, description="Optional dataset ID to associate the image with")
    tags: list[str] | None = Field(default=None, description="Optional list of tags to associate with the image")


@kante.pydantic_input(FromTraceLikeInputModel, description="Input type for creating an image from an array-like object")
class FromTraceLikeInput:
    array: ArrayLike = strawberry.field(description="The array-like object to create the image from")
    name: str = strawberry.field(description="The name of the image")
    dataset: strawberry.ID | None = strawberry.field(default=None, description="Optional dataset ID to associate the image with")
    tags: list[str] | None = strawberry.field(default=None, description="Optional list of tags to associate with the image")


def from_trace_like(
    info: Info,
    input: FromTraceLikeInput,
) -> types.Trace:
    parsed = input.to_pydantic()
    datalayer = get_current_datalayer()

    store = models.ZarrStore.objects.get(id=parsed.array)
    store.fill_info(datalayer)

    dataset = parsed.dataset or get_trace_dataset(info).id

    image = models.Trace.objects.create(
        dataset_id=dataset,
        creator=info.context.request.user,
        organization=info.context.request.organization,
        name=parsed.name,
        store=store,
    )

    if parsed.tags:
        image.tags.add(*parsed.tags)

    return image


def get_trace_dataset(info: Info) -> models.Dataset:
    return models.Dataset.objects.get_or_create(organization=info.context.request.organization, creator=info.context.request.user, membership=info.context.request.membership, name="Default Dataset")[0]
