from kante.types import Info
import strawberry
import kante
from pydantic import BaseModel
from core import types, models, scalars, enums
from core.base_models.input.graphql.biophysics import BiophysicsInput
from core.scoping import for_org


class ViewInputModel(BaseModel):
    stimulus: str | None = None
    recording: str | None = None
    offset: float | None = None
    duration: float | None = None
    label: str | None = None


@kante.pydantic_input(ViewInputModel)
class ViewInput:
    stimulus: strawberry.ID | None = None
    recording: strawberry.ID | None = None
    offset: float | None = None
    duration: float | None = None
    label: str | None = None


class CreateModelCollectionInputModel(BaseModel):
    name: str
    models: list[str]
    description: str | None = None


@kante.pydantic_input(CreateModelCollectionInputModel)
class CreateModelCollectionInput:
    name: str
    models: list[strawberry.ID]
    description: str | None = None


def create_model_collection(
    info: Info,
    input: CreateModelCollectionInput,
) -> types.ModelCollection:
    parsed = input.to_pydantic()
    exp = models.ModelCollection.objects.create(
        name=parsed.name,
        creator=info.context.request.user,
        organization=info.context.request.organization,
        description=parsed.description,
    )

    # Scoped, and strict: an id from another organization is an error, not a silently shorter collection.
    members = list(for_org(models.NeuronModel, info).filter(id__in=parsed.models))
    missing = sorted(set(map(str, parsed.models)) - {str(member.pk) for member in members})
    if missing:
        raise ValueError(f"No neuron model{'' if len(missing) == 1 else 's'} with id {', '.join(missing)} in this organization.")
    exp.models.set(members)

    return exp
