from kante.types import Info
import strawberry
import kante
from typing import Any
from pydantic import BaseModel

from core import types, models, scalars
from core.guards import enforce_delete
from core.mutations.trace import get_trace_dataset
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
    datalayer = get_current_datalayer()
    store = models.BigFileStore.objects.get(id=parsed.file)
    store.fill_info(datalayer)

    dataset_id = parsed.dataset or get_trace_dataset(info).id

    # Size is best-effort metadata: it requires an S3 head_object call, which may be
    # unavailable (e.g. object not yet readable). content_type comes straight off the store.
    try:
        size = store.calculate_size(datalayer)
    except Exception:
        size = None

    file = models.File.objects.create(
        dataset_id=dataset_id,
        creator=info.context.request.user,
        organization=info.context.request.organization,
        membership=info.context.request.membership,
        name=store.original_file_name or parsed.name,
        size=size,
        content_type=store.content_type,
        store=store,
    )

    if parsed.origins:
        file.origins.set(parsed.origins)

    return file


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


class CreateFileViewInputModel(BaseModel):
    file: str
    trace: str
    series_identifier: str | None = None
    a_min: int | None = None
    a_max: int | None = None
    t_min: int | None = None
    t_max: int | None = None
    c_min: int | None = None
    c_max: int | None = None
    is_global: bool = False


@kante.pydantic_input(CreateFileViewInputModel)
class CreateFileViewInput:
    file: strawberry.ID
    trace: strawberry.ID
    series_identifier: str | None = None
    a_min: int | None = None
    a_max: int | None = None
    t_min: int | None = None
    t_max: int | None = None
    c_min: int | None = None
    c_max: int | None = None
    is_global: bool = False


def create_file_view(
    info: Info,
    input: CreateFileViewInput,
) -> types.FileView:
    parsed = input.to_pydantic()
    return models.FileView.objects.create(
        file=models.File.objects.get(id=parsed.file),
        trace_id=parsed.trace,
        series_identifier=parsed.series_identifier,
        a_min=parsed.a_min,
        a_max=parsed.a_max,
        t_min=parsed.t_min,
        t_max=parsed.t_max,
        c_min=parsed.c_min,
        c_max=parsed.c_max,
        is_global=parsed.is_global,
    )
