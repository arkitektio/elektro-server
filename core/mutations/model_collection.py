from kante.types import Info
import strawberry
import kante
from pydantic import BaseModel
from core import types, models, scalars, enums
from core.base_models.input.graphql.biophysics import BiophysicsInput


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
        description=parsed.description,
    )

    exp.models.set(models.NeuronModel.objects.filter(id__in=parsed.models))

    return exp
