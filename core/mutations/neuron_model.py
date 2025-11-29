from kante.types import Info
import strawberry
from core import types, models, scalars, enums
from core.base_models.input.graphql.model import ModelConfigInput
from pydantic import BaseModel
import hashlib
import json


import hashlib
import json
import strawberry
from operator import itemgetter


def get_model_hash(model_instance: ModelConfigInput, float_precision: int = 5) -> str:
    """
    Generates a deterministic SHA256 hash for a Strawberry/Pydantic model.

    Args:
        model_instance: The input model instance.
        float_precision: The number of decimal places to round floats to.
    """

    def _normalize_value(value):
        # 1. Handle Floats: Format to fixed precision string to avoid IEEE 754 issues
        if isinstance(value, float):
            return f"{value:.{float_precision}f}"

        # 2. Handle Lists: Recursively normalize and SORT them
        # Sorting is crucial: [A, B] must hash the same as [B, A]
        if isinstance(value, list):
            normalized_list = [_normalize_value(item) for item in value]

            # Try to sort by 'id' if possible (common in your models),
            # otherwise sort by the string representation of the object
            try:
                # Assuming items are dicts with an 'id' after normalization
                return sorted(normalized_list, key=lambda x: x.get("id", str(x)))
            except (AttributeError, TypeError):
                # Fallback: Sort by the string dump of the item
                return sorted(normalized_list, key=lambda x: json.dumps(x, sort_keys=True))

        # 3. Handle Strawberry Inputs / Objects: Convert to dict and recurse
        if hasattr(value, "__dict__") or isinstance(value, object) and hasattr(value, "__annotations__"):
            # strawberry.asdict can be used, but vars() is often lighter for inputs
            # We filter out private attributes starting with _
            d = {k: _normalize_value(v) for k, v in vars(value).items() if not k.startswith("_")}
            return d

        # 4. Handle Enum: Return value or name
        if hasattr(value, "value"):
            return value.value

        # 5. Primitives (str, int, None)
        return value

    # 1. Normalize the entire object tree
    normalized_data = _normalize_value(model_instance)

    # 2. Dump to JSON string with sorted keys (ensures dict key order doesn't matter)
    # separators=(',', ':') removes whitespace to make hash compact and strict
    serialized = json.dumps(normalized_data, sort_keys=True, separators=(",", ":"))

    # 3. Generate Hash
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@strawberry.input()
class CreateNeuronModelInput:
    name: str
    parent: strawberry.ID | None
    description: str | None = None
    config: ModelConfigInput


def create_neuron_model(
    info: Info,
    input: CreateNeuronModelInput,
) -> types.NeuronModel:
    model, _ = models.NeuronModel.objects.update_or_create(
        hash=get_model_hash(input.config),
        defaults=dict(
            creator=info.context.request.user,
            parent=input.parent,
            description=input.description,
            name=input.name,
            json_model=strawberry.asdict(input.config),
        ),
    )

    return model
