from kante.types import Info
import strawberry
import kante
from django.db import transaction
from core import types, models, scalars, enums, units
from core.creation import CreationContext
from core.inputs.coords import AxisInputModel, DerivedFromInput, DerivedFromSpec
from core.logic import coordinate_system as coordinate_system_logic
from core.logic import graph as graph_logic
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
from core.scoping import get_for_org


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
    derived_from: list[DerivedFromSpec] | None = None


@kante.pydantic_input(CreateNeuronModelInputModel)
class CreateNeuronModelInput:
    name: str
    environment: strawberry.ID | None = None
    parent: strawberry.ID | None = strawberry.field(
        default=None,
        description=(
            "The model this one was edited out of. Sugar for a single NEURON_MODEL entry in `derivedFrom`, placed first -- so it becomes the primary parent and produces exactly "
            "the same UNMAPPABLE edge. Use `derivedFrom` instead when the model has several sources; giving both is refused"
        ),
    )
    description: str | None = None
    config: ModelConfigInput
    derived_from: list[DerivedFromInput] | None = strawberry.field(
        default=None,
        description=(
            "Where this model came from, as edges of the coordinate graph rather than a parent column: one entry per source, the first being the primary parent. A model's space "
            "carries no placeable axes, so an edge out of it is UNMAPPABLE -- it records the lineage and claims no geometry, which is the whole truth for a retuned conductance. "
            "State `valueRelation` to say what the edit did to the model"
        ),
    )


BUILT_IN_MECHANISMS = {"hh", "pas", "leak", "extracellular", "capacitance"}

#: The degenerate space of a neuron model: one axis enumerating the things the model declares.
#: No unit (nothing to measure between one cell and the next), no second axis (cells are named
#: in `json_model`, not indexed by position), and deliberately not called "cell" -- an INDEX axis
#: claims integer-addressable positions, while a model's cells are addressed by string id through
#: `sites.compound_id`. Its only honest edge to a source is UNMAPPABLE.
_MODEL_AXES = [AxisInputModel(name="object", type=enums.AxisType.INDEX)]


def _lower_parent_sugar(parsed) -> list:  # noqa: ANN001 - the parsed input model
    """The derivation entries this create states, with `parent` lowered into one of them.

    ``parent`` predates the graph: it was a column, and it is kept as sugar for the one shape it
    expressed -- a model edited out of exactly one other. It lowers to a single NEURON_MODEL
    entry placed *first*, which is what makes it the primary parent, so the sugar and the
    explicit form produce the same edge and there is only one thing to read.

    Naming a parent twice -- once as sugar and once in `derivedFrom` -- is refused rather than
    merged: the two could disagree about order, and order is priority here.
    """
    derived_from = list(parsed.derived_from or [])
    if parsed.parent is None:
        return derived_from

    if any(entry.kind == enums.DerivationSourceKind.NEURON_MODEL for entry in derived_from):
        raise ValueError(
            "A model's parent was given both as `parent` and as a NEURON_MODEL entry in `derivedFrom`. "
            "`parent` is sugar for exactly that entry, so state it once -- use `derivedFrom` alone when the model has several sources."
        )

    from core.inputs.coords import NeuronModelDerivedFromInputModel

    return [NeuronModelDerivedFromInputModel(kind=enums.DerivationSourceKind.NEURON_MODEL, neuron_model=parsed.parent), *derived_from]


def _inherited_environment(info: Info, parsed, derived_from: list):  # noqa: ANN001, ANN201
    """The environment this model belongs to: stated, or inherited from its first model source.

    Inheritance used to ride on `parent` directly. With `parent` lowered into `derivedFrom` the
    rule has to be said out loud, and saying it is an improvement: the environment comes from the
    *first* NEURON_MODEL source, which is the primary parent whether it was written as sugar or
    as an explicit entry.
    """
    if parsed.environment is not None:
        return get_for_org(models.ModEnvironment, info, id=parsed.environment)

    first_model = next((entry for entry in derived_from if entry.kind == enums.DerivationSourceKind.NEURON_MODEL), None)
    if first_model is None:
        # environment is NOT NULL at the database level; fail with a clear message
        # rather than letting the insert raise an opaque IntegrityError.
        raise ValueError("An environment is required, either directly or inherited from a parent.")

    return get_for_org(models.NeuronModel, info, id=first_model.neuron_model).environment


def create_neuron_model(
    info: Info,
    input: CreateNeuronModelInput,
) -> types.NeuronModel:
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)

    derived_from = _lower_parent_sugar(parsed)
    environment = _inherited_environment(info, parsed, derived_from)

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

    with transaction.atomic():
        # **Org in the lookup, not the defaults.** `hash` used to be globally unique and this
        # call was unscoped, so one organization's create matched -- and overwrote -- another's
        # row. The lookup now matches the `one_model_per_hash_per_organization` constraint
        # exactly. Not `for_org(...).update_or_create(...)`: Django builds the created instance
        # from lookup kwargs plus defaults and does not inject a queryset's filter, so a
        # filtered queryset would create a row with no organization.
        model, created = models.NeuronModel.objects.update_or_create(
            organization=ctx.organization,
            # Hash the strawberry config object (unchanged from before this refactor)
            # so dedup keeps matching pre-existing rows. json_model uses model_dump(),
            # which is byte-identical to the previous strawberry.asdict() output.
            hash=get_model_hash(input.config),
            defaults=dict(
                creator=info.context.request.user,
                environment=environment,
                description=parsed.description,
                name=parsed.name,
                json_model=config_dict,
            ),
        )

        # **Both of these are gated on `created`, and that gate is the whole point.** This
        # mutation dedups on the config hash, so an unchanged re-create lands here with a row
        # that already has a space and already has its edges. Minting again would abandon the
        # old space -- which PROTECT then makes undeletable -- and `write_derivation_edges`
        # does not dedup, so it would add a second UNMAPPABLE edge between the same pair every
        # time. Order is priority here, so duplicates do not merely accumulate: they change
        # which edge is primary. The old `parent=parent` in `defaults` was idempotent by
        # accident; an edge is not.
        if created:
            system = models.CoordinateSystem.objects.create(
                name=f"{model.name}/model",
                creator=ctx.user,
                organization=ctx.organization,
            )
            graph_logic.create_pixel_axes(system, _MODEL_AXES)
            model.coordinate_system = system
            model.save(update_fields=["coordinate_system"])
            coordinate_system_logic.write_derivation_edges(info, name=model.name, own_system=system, derived_from=derived_from, ctx=ctx)
        elif derived_from:
            # A lineage was stated for a config that already exists. Re-stating the *same* one is
            # the ordinary idempotent re-create and writes nothing; stating a *different* one is
            # refused rather than appended, because an edge is an authored fact and two
            # authorships of one space's lineage are two answers to one question. A row that has
            # no edges yet -- one written before this column existed -- takes the first statement.
            existing = graph_logic.collection_derivation_edges(model.coordinate_system)
            if existing:
                stated = [coordinate_system_logic.resolve_derivation_source(info, entry.lower())[0].pk for entry in derived_from]
                if [edge.output_id for edge in existing] != stated:
                    raise ValueError(
                        f"Neuron model '{model.name}' already records where it came from, and this create states a different lineage. "
                        "A derivation is authored once; edit the edges directly if it needs to change."
                    )
            else:
                coordinate_system_logic.write_derivation_edges(info, name=model.name, own_system=model.coordinate_system, derived_from=derived_from, ctx=ctx)

    return model
