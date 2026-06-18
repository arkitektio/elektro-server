from kante.types import Info
import strawberry
import kante
from core import types, models, scalars, enums
from core.base_models.input.graphql.model import ModelConfigInput
from core.base_models.input.model import ModelConfigInputModel
from pydantic import BaseModel
import hashlib
import json
from koherent.utils import get_or_create_task

import hashlib
import json
import strawberry
from operator import itemgetter


def get_model_hash(model_instance, float_precision: int = 5) -> str:
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


class CreateNeuronModelInputModel(BaseModel):
    name: str
    environment: str | None = None
    parent: str | None = None
    description: str | None = None
    config: ModelConfigInputModel


@kante.pydantic_input(CreateNeuronModelInputModel)
class CreateNeuronModelInput:
    name: str
    environment: strawberry.ID | None = None
    parent: strawberry.ID | None = None
    description: str | None = None
    config: ModelConfigInput


BUILT_IN_MECHANISMS = {"hh", "pas", "leak", "extracellular", "capacitance"}


def create_neuron_model(
    info: Info,
    input: CreateNeuronModelInput,
) -> types.NeuronModel:
    parsed = input.to_pydantic()

    

    parent = models.NeuronModel.objects.get(id=parsed.parent) if parsed.parent is not None else None

    if parsed.environment is not None:
        environment = models.ModEnvironment.objects.get(id=parsed.environment)
    elif parent is not None:
        # Inherit the environment from the parent when none is given explicitly.
        environment = parent.environment
    else:
        environment = None

    if environment is None:
        # environment is NOT NULL at the database level; fail with a clear message
        # rather than letting the insert raise an opaque IntegrityError.
        raise ValueError("An environment is required, either directly or inherited from a parent.")

    for cell in parsed.config.cells:
        if cell.biophysics is not None:
            for comp in cell.biophysics.compartments:
                for mech in comp.mechanisms:
                    if not models.Mechanism.objects.filter(name=mech, environment=environment).exists():
                        if mech not in BUILT_IN_MECHANISMS:
                            raise ValueError(f"Mechanism with name {mech} not found in environment {environment.name}. And not a built-in mechanism.")

    config_dict = parsed.config.model_dump(mode="json")

    model, _ = models.NeuronModel.objects.update_or_create(
        # Hash the strawberry config object (unchanged from before this refactor)
        # so dedup keeps matching pre-existing rows. json_model uses model_dump(),
        # which is byte-identical to the previous strawberry.asdict() output.
        hash=get_model_hash(input.config),
        defaults=dict(
            creator=info.context.request.user,
            parent=parent,
            environment=environment,
            description=parsed.description,
            name=parsed.name,
            json_model=config_dict,
        ),
    )

    return model
