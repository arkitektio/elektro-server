from kante.types import Info
import strawberry

from core import types, models, scalars
from datalayer.datalayer import get_current_datalayer
from datalayer.scalars import BigFileLike
import json
from django.conf import settings

from datalayer import models as datalayer_models


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
class FromModFileInput:
    name: str
    mod_file: BigFileLike


def from_mod_file(
    info: Info,
    input: FromModFileInput,
) -> types.Mechanism:
    store = datalayer_models.BigFileStore.objects.get(id=input.mod_file)
    store.fill_info()

    table, _ = models.Mechanism.objects.update_or_create(
        name=input.name,
        organization=info.context.request.organization,
        defaults={"store": store},
    )

    return table


@strawberry.input
class DeleteMechanismInput:
    id: strawberry.ID


def delete_mechanism(
    info: Info,
    input: DeleteMechanismInput,
) -> strawberry.ID:
    item = models.Mechanism.objects.get(id=input.id)
    item.delete()
    return input.id
