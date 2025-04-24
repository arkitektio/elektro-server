from kante.types import Info
import strawberry
from core import types, models, scalars, enums
from core.base_models.input.graphql.model import ModelConfigInput
from pydantic import BaseModel
import hashlib
import json

def hash_model(config) -> str:
    # Convert to dict, dump as sorted JSON string
    model_json = json.dumps(strawberry.asdict(config), sort_keys=True)
    return hashlib.sha256(model_json.encode("utf-8")).hexdigest()


@strawberry.input()
class CreateNeuronModelInput:
    name: str
    parent: strawberry.ID | None
    config: ModelConfigInput


def create_neuron_model(
    info: Info,
    input: CreateNeuronModelInput,
) -> types.NeuronModel:



    model, _ = models.NeuronModel.objects.update_or_create(
        hash=hash_model(input.config),
        defaults=dict(
            creator=info.context.request.user,
            parent=input.parent,
            name=input.name,
            json_model=strawberry.asdict(input.config),
        ),
    )



    
    return model


