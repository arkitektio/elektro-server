from kante.types import Info
import strawberry
import kante
from pydantic import BaseModel
from core import types, models


class CreateModelWorkspaceInputModel(BaseModel):
    name: str
    description: str | None = None


@kante.pydantic_input(CreateModelWorkspaceInputModel)
class CreateModelWorkspaceInput:
    name: str
    description: str | None = None


class UpdateModelWorkspaceInputModel(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None


@kante.pydantic_input(UpdateModelWorkspaceInputModel)
class UpdateModelWorkspaceInput:
    id: strawberry.ID
    name: str | None = None
    description: str | None = None


class PinModelWorkspaceInputModel(BaseModel):
    id: str
    pin: bool


@kante.pydantic_input(PinModelWorkspaceInputModel)
class PinModelWorkspaceInput:
    id: strawberry.ID
    pin: bool


def create_model_workspace(
    info: Info,
    input: CreateModelWorkspaceInput,
) -> types.ModelWorkspace:
    parsed = input.to_pydantic()
    workspace = models.ModelWorkspace.objects.create(
        name=parsed.name,
        description=parsed.description,
        creator=info.context.request.user,
    )
    return workspace


def update_model_workspace(
    info: Info,
    input: UpdateModelWorkspaceInput,
) -> types.ModelWorkspace:
    parsed = input.to_pydantic()
    workspace = models.ModelWorkspace.objects.get(id=parsed.id)
    if parsed.name is not None:
        workspace.name = parsed.name
    if parsed.description is not None:
        workspace.description = parsed.description
    workspace.save()
    return workspace


def pin_model_workspace(
    info: Info,
    input: PinModelWorkspaceInput,
) -> types.ModelWorkspace:
    parsed = input.to_pydantic()
    workspace = models.ModelWorkspace.objects.get(id=parsed.id)
    user = info.context.request.user
    if parsed.pin:
        workspace.pinned_by.add(user)
    else:
        workspace.pinned_by.remove(user)
    return workspace
