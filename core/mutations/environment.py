from kante.types import Info
import strawberry

from core import types, models, scalars
from datalayer.datalayer import get_current_datalayer
from datalayer.scalars import BigFileLike
import json
from django.conf import settings
from rekuest_core.inputs import models as rekuest_models
from rekuest_core.inputs import types as rekuest_types
from datalayer import models as datalayer_models
import kante
from pydantic import BaseModel


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


class MechanismInputModel(BaseModel):
    name: str
    description: str | None = None
    parameters: list[rekuest_models.ArgPortInputModel]


@kante.pydantic_input(MechanismInputModel, description="Input for creating a mechanism")
class MechanismInput:
    name: str
    description: str | None = None
    parameters: list[rekuest_types.ArgPortInput]


class ModEnvironmentInputModel(BaseModel):
    name: str
    description: str | None = None
    zip_file: str
    mechanisms: list[MechanismInputModel]


@kante.pydantic_input(ModEnvironmentInputModel, description="Input for creating a mod environment")
class CreateModEnvironmentInput:
    name: str
    description: str | None = None
    zip_file: BigFileLike
    mechanisms: list[MechanismInput]


def create_mod_environment(
    info: Info,
    input: CreateModEnvironmentInput,
) -> types.ModEnvironment:
    input = input.to_pydantic()

    store = datalayer_models.BigFileStore.objects.get(id=input.zip_file)
    store.fill_info()

    environment = models.ModEnvironment.objects.create(
        name=input.name,
        description=input.description,
        organization=info.context.request.organization,
        store=store,
    )

    for mechanism_input in input.mechanisms:
        models.Mechanism.objects.create(
            name=mechanism_input.name,
            description=mechanism_input.description,
            parameters=[p.model_dump() for p in mechanism_input.parameters],
            environment=environment,
        )

    return environment


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
