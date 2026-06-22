from kante.types import Info
import strawberry
import kante
from pydantic import BaseModel
from core import types, models, inputs


class AddModelsToWorkspaceInputModel(BaseModel):
    workspace: str
    models: list[str]
    workspace_group: str = ""


@kante.pydantic_input(AddModelsToWorkspaceInputModel)
class AddModelsToWorkspaceInput:
    workspace: strawberry.ID
    models: list[strawberry.ID]
    workspace_group: str = ""


class UpdateWorkspaceMappingInputModel(BaseModel):
    id: str
    workspace_group: str


@kante.pydantic_input(UpdateWorkspaceMappingInputModel)
class UpdateWorkspaceMappingInput:
    id: strawberry.ID
    workspace_group: str


def add_models_to_workspace(
    info: Info,
    input: AddModelsToWorkspaceInput,
) -> types.ModelWorkspace:
    parsed = input.to_pydantic()
    workspace = models.ModelWorkspace.objects.get(id=parsed.workspace)

    for model_id in parsed.models:
        models.WorkspaceMapping.objects.get_or_create(
            workspace=workspace,
            model_id=model_id,
            defaults={"workspace_group": parsed.workspace_group},
        )

    return workspace


def remove_models_from_workspace(
    info: Info,
    input: inputs.DesociateInput,
) -> types.ModelWorkspace:
    parsed = input.to_pydantic()
    workspace = models.ModelWorkspace.objects.get(id=parsed.other)
    models.WorkspaceMapping.objects.filter(
        workspace=workspace,
        model_id__in=parsed.selfs,
    ).delete()
    return workspace


def update_workspace_mapping(
    info: Info,
    input: UpdateWorkspaceMappingInput,
) -> types.WorkspaceMapping:
    parsed = input.to_pydantic()
    mapping = models.WorkspaceMapping.objects.get(id=parsed.id)
    mapping.workspace_group = parsed.workspace_group
    mapping.save()
    return mapping
