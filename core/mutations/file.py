from kante.types import Info
import strawberry

from core import types, models, scalars
from datalayer.datalayer import get_current_datalayer
import json
from django.conf import settings


@strawberry.input()
class RequestFileUploadInput:
    key: str
    datalayer: str
    hash: str | None = None


@strawberry.input
class DeleteFileInput:
    id: strawberry.ID


def delete_file(
    info: Info,
    input: DeleteFileInput,
) -> strawberry.ID:
    view = models.File.objects.get(
        id=input.id,
    )
    view.delete()
    return input.id


@strawberry.input
class PinFileInput:
    id: strawberry.ID
    pin: bool


def pin_file(
    info: Info,
    input: PinFileInput,
) -> types.File:
    raise NotImplementedError("TODO")


@strawberry.input
class FromFileLike:
    name: str
    file: scalars.FileLike
    origins: list[strawberry.ID] | None = None
    dataset: strawberry.ID | None = None


def from_file_like(
    info: Info,
    input: FromFileLike,
) -> types.File:
    store = models.BigFileStore.objects.get(id=input.file)
    store.fill_info()

    table = models.File.objects.create(
        dataset_id=input.dataset,
        creator=info.context.request.user,
        name=input.name,
        store=store,
    )

    return table


@strawberry.input
class DeleteFileInput:
    id: strawberry.ID


def delete_era(
    info: Info,
    input: DeleteFileInput,
) -> strawberry.ID:
    item = models.File.objects.get(id=input.id)
    item.delete()
    return input.id
