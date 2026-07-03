from kante.types import Info
import strawberry
import kante
from core import types, models, scalars, enums, units
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

    def _declared_dimension(param: dict) -> str | None:
        # Prefer the canonical dimension derived at declaration time; fall back to
        # deriving it from the reference_unit so mechanisms created outside the
        # ParameterInput validator (e.g. directly via the ORM) still get checked.
        if param.get("dimension"):
            return param["dimension"]
        if param.get("reference_unit"):
            return units.dimensionality_of(param["reference_unit"])
        return None

    # Catalog of the environment's mechanisms -> {declared parameter key -> its
    # declared canonical dimension (or None)}. Built-in mechanisms (hh, pas, ...)
    # have no catalog here, so their params are accepted unchecked.
    env_mechs = {
        m.name: {
            p["key"]: _declared_dimension(p)
            for p in (m.parameters or [])
            if isinstance(p, dict) and p.get("key")
        }
        for m in models.Mechanism.objects.filter(environment=environment)
    }

    def check_mechanism(mech: str) -> None:
        if mech not in env_mechs and mech not in BUILT_IN_MECHANISMS:
            raise ValueError(f"Mechanism with name {mech} not found in environment {environment.name}. And not a built-in mechanism.")

    def check_param(mech: str, param: str, where: str) -> None:
        # Only catalog mechanisms can be validated; built-ins are accepted as-is.
        if mech in env_mechs and param not in env_mechs[mech]:
            raise ValueError(f"Parameter {param!r} for mechanism {mech!r} in {where} is not among the mechanism's declared parameters ({sorted(env_mechs[mech])}).")

    def check_value_dimension(mech: str, param: str, value, where: str) -> None:
        # The value is a GenericQuantity in-memory string (or None). Enforce that
        # its physical dimension matches the parameter's declared dimension — only
        # possible for catalog mechanisms whose param declares a unit.
        if value is None or mech not in env_mechs:
            return
        declared = env_mechs[mech].get(param)
        if declared is None or declared == units.ARBITRARY_DIMENSION:
            # No declared unit, or the parameter opts out via arbitrary units (a.u.).
            return
        actual = units.quantity_dimension(value)
        if actual != declared:
            raise ValueError(
                f"Parameter {param!r} of mechanism {mech!r} in {where} was set to a "
                f"value with dimension {actual!r}, but the mechanism declares "
                f"dimension {declared!r}."
            )

    for cell in parsed.config.cells:
        if cell.biophysics is not None:
            for comp in cell.biophysics.compartments:
                for mech in comp.mechanisms:
                    check_mechanism(mech)
                for sp in comp.section_params:
                    where = f"compartment {comp.id}"
                    check_param(sp.mechanism, sp.param, where)
                    dist = sp.distribution
                    for value in (dist.value, dist.proximal_value, dist.distal_value):
                        check_value_dimension(sp.mechanism, sp.param, value, where)

    for mg in parsed.config.mechanism_globals:
        check_mechanism(mg.mechanism)
        check_param(mg.mechanism, mg.param, "mechanism_globals")
        check_value_dimension(mg.mechanism, mg.param, mg.value, "mechanism_globals")

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
