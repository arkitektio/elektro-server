from kante.types import Info
import strawberry
import kante
from typing import Any
from pydantic import BaseModel

from core import types, models, scalars
from core.guards import enforce_delete
from datalayer.datalayer import get_current_datalayer
import json
from django.conf import settings


class RequestFileUploadInputModel(BaseModel):
    key: str
    datalayer: str
    hash: str | None = None


@kante.pydantic_input(RequestFileUploadInputModel)
class RequestFileUploadInput:
    key: str
    datalayer: str
    hash: str | None = None


class DeleteFileInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteFileInputModel)
class DeleteFileInput:
    id: strawberry.ID


def delete_file(
    info: Info,
    input: DeleteFileInput,
) -> strawberry.ID:
    parsed = input.to_pydantic()
    view = models.File.objects.get(
        id=parsed.id,
    )
    enforce_delete(info, view)
    view.delete()
    return parsed.id


class PinFileInputModel(BaseModel):
    id: str
    pin: bool


@kante.pydantic_input(PinFileInputModel)
class PinFileInput:
    id: strawberry.ID
    pin: bool


def pin_file(
    info: Info,
    input: PinFileInput,
) -> types.File:
    raise NotImplementedError("TODO")


class FromFileLikeModel(BaseModel):
    name: str
    file: Any
    origins: list[str] | None = None
    dataset: str | None = None


@kante.pydantic_input(FromFileLikeModel)
class FromFileLike:
    name: str
    file: scalars.FileLike
    origins: list[strawberry.ID] | None = None
    dataset: strawberry.ID | None = None


def from_file_like(
    info: Info,
    input: FromFileLike,
) -> types.File:
    parsed = input.to_pydantic()
    store = models.BigFileStore.objects.get(id=parsed.file)
    store.fill_info()

    table = models.File.objects.create(
        dataset_id=parsed.dataset,
        creator=info.context.request.user,
        organization=info.context.request.organization,
        name=parsed.name,
        store=store,
    )

    return table


class DeleteEraInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteEraInputModel)
class DeleteEraInput:
    id: strawberry.ID


def delete_era(
    info: Info,
    input: DeleteEraInput,
) -> strawberry.ID:
    parsed = input.to_pydantic()
    item = models.File.objects.get(id=parsed.id)
    item.delete()
    return parsed.id
