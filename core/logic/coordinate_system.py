"""Creating coordinate systems: shared spaces, the edges into them, and a lens' own space.

**Vendored from mikro** (``mikro/core/logic/coordinate_system.py``). A source here is a
dataset, a lens or a bare coordinate system; ``write_key_edges`` (a table keyed by a label
mask) is gone with the tables it wrote edges for. The clocks and sampling laws this
service writes on top of these primitives live in :mod:`core.logic.clocks`.

A SHARED system is the one coordinate system with no owner (see
:mod:`core.models.coords`): a reference space (a world, an atlas) that datasets, tables
and mesh collections are registered into, and that scenes later adopt as their world.
This is where those registration edges are authored -- explicitly, exactly as
``createTransformation`` authors one, never fabricated.
:func:`core.logic.scene.bootstrap_scene_from_system` only *reads* them.

Everything here makes *spaces and edges*, and none of it takes a scene. That is the line
this module draws against :mod:`core.logic.scene`, which makes scenes and layers: a lens'
coordinate system is a fact about a dataset's spaces, answerable with no composition in
sight, and it lived in the scene module only because the scene bootstrap happened to be the
caller.
"""

import datetime
from collections.abc import Sequence

from django.db import transaction

from core import enums, models
from core.creation import CreationContext
from core.inputs.coords import IDENTITY_TRANSFORM, PhysicalAxisInputModel
from core.logic import graph as graph_logic
from core.scoping import get_for_org


def create_world_space(
    *,
    name: str,
    axes: list | None = None,
    epoch: datetime.datetime | None = None,
    ctx: CreationContext,
) -> "models.CoordinateSystem":
    """Mint an ownerless shared space with physical axes, for a scene to adopt.

    The convenience half of `createScene`: a client that passes no `coordinateSystem` gets
    one of these and a scene over it, which is the same pair of rows `createCoordinateSystem`
    followed by `createScene(coordinateSystem:)` produces. It is a *space* either way -- no
    scene owns it, it outlives every scene over it, and only `deleteCoordinateSystem` removes
    it -- which is why the minting lives here and not in the scene module.

    The epoch lands on this system, not on the scene adopting it: it is the origin of the
    *space's* time axis, and two compositions over one space cannot disagree about it.
    """
    axes = axes or DEFAULT_WORLD_AXES
    with transaction.atomic():
        world = models.CoordinateSystem.objects.create(
            name=name,
            epoch=epoch,
            creator=ctx.user,
            organization=ctx.organization,
        )
        graph_logic.create_physical_axes(world, axes)
    return world


def create_coordinate_system(
    *,
    name: str,
    axes: list,
    epoch: datetime.datetime | None = None,
    registrations: Sequence[tuple["models.CoordinateSystem", "models.ZarrStore | None", object]] = (),
    ctx: CreationContext,
) -> "models.CoordinateSystem":
    """Create a shared coordinate system, and author one edge per registered source into it.

    It is created with no owner FK at all, which is exactly what *makes* it SHARED:
    there is no kind to pass because ownership decides it.

    ``registrations`` are ``(source_system, field, spec)`` triples the caller has already
    resolved and scoped; ``spec.transform`` carries the edge's kind and parameters as the
    flat union, or is None for the identity a source that is simply *in* the space states.
    Every edge points source -> space, the direction a placement path walks, and is
    validated by the same :func:`~core.logic.graph.build_registration_edge` the
    transformation mutation uses.
    """
    with transaction.atomic():
        system = models.CoordinateSystem.objects.create(
            name=name,
            epoch=epoch,
            creator=ctx.user,
            organization=ctx.organization,
        )
        graph_logic.create_physical_axes(system, axes)

        for source_system, field, spec in registrations:
            lowered = spec.transform.lower() if spec.transform else IDENTITY_TRANSFORM
            graph_logic.build_registration_edge(
                input_system=source_system,
                output_system=system,
                kind=lowered.kind,
                name=spec.name,
                scale=lowered.scale,
                translation=lowered.translation,
                affine=lowered.affine,
                input_axes=lowered.input_axes,
                output_axes=lowered.output_axes,
                field=field,
                reason=lowered.reason,
                validity=spec.validity,
                ctx=ctx,
            )

    return system


def resolve_source_system(
    *,
    dataset: "models.ArrayDataset | None" = None,
    lens: "models.Lens | None" = None,
    annotation_collection: "models.AnnotationCollection | None" = None,
    coordinate_system: "models.CoordinateSystem | None" = None,
) -> "models.CoordinateSystem":
    """The coordinate system a source is placed by, given the already-fetched owner.

    Exactly one owner must be non-null. A dataset is reached through its sample grid, a lens
    through its own space, an annotation collection through the space it owns, a coordinate
    system directly.

    Shared by registrations and derivations: both name "some container", and the answer to
    "which space stands for it" cannot sensibly differ between them.
    """
    provided = [value for value in (dataset, lens, annotation_collection, coordinate_system) if value is not None]
    if len(provided) != 1:
        raise ValueError("A registration must name exactly one source: a dataset, a lens, an annotation collection, or a coordinate system.")

    if coordinate_system is not None:
        return coordinate_system

    if lens is not None:
        # An unsliced lens owns no system -- its space *is* the dataset's sample grid --
        # so a derivation from it is a derivation from the grid, one hop shorter.
        system = graph_logic.lens_source_system(lens)
        if system is None:
            raise ValueError(f"Lens {lens.pk} has no coordinate system, so there is no space to derive from. Its dataset was created without axes: give the dataset its sample grid first.")
        return system

    if annotation_collection is not None:
        system = annotation_collection.coordinate_system_or_none
        if system is None:
            raise ValueError(f"Annotation collection '{annotation_collection.name}' has no coordinate system to register.")
        return system

    system = dataset.intrinsic_coordinate_system
    if system is None:
        raise ValueError(f"Dataset '{dataset.name}' has no coordinate system to register: it was created without axes, so it is not in the graph.")
    return system


#: The model each `DerivationSourceKind` names, and the keyword `resolve_source_system`
#: takes it under. The one place the discriminator meets the ORM -- `core.inputs.coords`
#: must not learn about `core.models`, so the lowered member carries an unresolved id and
#: this table is what turns it into a row.
_DERIVATION_SOURCES: dict[str, tuple[type, str]] = {
    enums.DerivationSourceKind.LENS.value: (models.Lens, "lens"),
    enums.DerivationSourceKind.DATASET.value: (models.ArrayDataset, "dataset"),
    enums.DerivationSourceKind.ANNOTATION_COLLECTION.value: (models.AnnotationCollection, "annotation_collection"),
    enums.DerivationSourceKind.COORDINATE_SYSTEM.value: (models.CoordinateSystem, "coordinate_system"),
}


def source_label(model: type, source) -> str:  # noqa: ANN001 - any container row
    """What to call a source in an edge name or an error, whatever kind it is.

    ``f"{child} <- {source}"`` used to read the source's *dataset* name -- which a table, a
    mesh collection or a bare coordinate system does not have. A ``MeshCollection`` carries
    ``version`` instead of ``name``, and reading the wrong one is an AttributeError rather
    than a sentence, so the fallback chain lives here and every caller shares it.
    """
    return getattr(source, "name", None) or getattr(source, "version", None) or f"{model.__name__} {source.pk}"


def resolve_derivation_source(info, lowered) -> "tuple[models.CoordinateSystem, str]":  # noqa: ANN001 - kante's Info, and a LoweredDerivation
    """The space a derivation derives *from*, and a label for the edge's name.

    Org-scoped through ``get_for_org`` like every other id a client sends, and returned
    with a human label because ``f"{child} <- {source}"`` used to read the source's
    *dataset* name -- which a table, a mesh collection or a bare coordinate system does
    not have.
    """
    model, keyword = _DERIVATION_SOURCES[lowered.source_kind]
    source = get_for_org(model, info, id=lowered.source_id)
    system = resolve_source_system(**{keyword: source})
    return system, source_label(model, source)


def write_derivation_edges(info, *, name: str, own_system: "models.CoordinateSystem", derived_from: Sequence, ctx: CreationContext) -> list["models.Transformation"]:
    """Write one edge per source this data was computed from, child space -> source space.

    The one writer for every container. An array dataset, a table, a mesh collection and an
    annotation collection are all saying the same sentence -- *my space, and how it relates
    to the one I came from* -- and each used to say it in its own code: the dataset through
    lenses only, the three collections through a bare coordinate system, none of them able
    to name the other kinds.

    **The order is the priority, and the first entry is the primary parent.** Written in
    input order so pk order *is* the creator's declared priority, which is the rule
    ``primary_derivation_edge`` and the placement walks act on. A mappable entry hiding
    behind an UNMAPPABLE first entry would silently break that -- the walks refuse the
    primary while a workable parent sits behind it -- so that ordering is rejected before
    anything is written.

    Everything is resolved before anything is written, for the same reason: a mistyped
    transform on the third entry must not leave the first two behind as a half-recorded
    lineage.
    """
    if not derived_from:
        return []

    lowered = [entry.lower() for entry in derived_from]

    # Keyed on (kind, id), not the id alone: two entries naming different sorts of source
    # could share a numeric id, and two naming the same table could not collide at all
    # while the key was the lens field.
    named = [(low.source_kind, low.source_id) for low in lowered]
    duplicates = sorted({f"{kind} {source_id}" for kind, source_id in named if named.count((kind, source_id)) > 1})
    if duplicates:
        raise ValueError(f"Each derivedFrom entry must name a distinct source, but {', '.join(duplicates)} appear{'s' if len(duplicates) == 1 else ''} more than once. One entry per source: its transform already says everything about how the data maps back")

    unmappable = enums.TransformKind.UNMAPPABLE.value
    if lowered[0].transform.kind == unmappable and any(low.transform.kind != unmappable for low in lowered):
        raise ValueError(
            "The first derivedFrom entry is the primary parent -- the one that places this data -- so it cannot be UNMAPPABLE while a mappable entry follows. "
            "An entry with no `transform` *is* UNMAPPABLE: naming a source claims no geometry. Put the mappable source first, or state its transform"
        )

    sources = [resolve_derivation_source(info, low) for low in lowered]
    fields = [get_for_org(models.CoordinateSystem, info, id=low.transform.field) if low.transform.field else None for low in lowered]

    edges: list[models.Transformation] = []
    with transaction.atomic():
        for low, (source_system, label), field in zip(lowered, sources, fields):
            transform = low.transform
            edges.append(
                graph_logic.write_relation_edge(
                    name=f"{name} <- {label}",
                    input_system=own_system,
                    output_system=source_system,
                    kind=transform.kind,
                    scale=transform.scale,
                    translation=transform.translation,
                    affine=transform.affine,
                    input_axes=transform.input_axes,
                    output_axes=transform.output_axes,
                    field=field,
                    reason=transform.reason,
                    value_relation=low.value_relation,
                    ctx=ctx,
                )
            )
    return edges


# An experiment's world space, when the caller does not author one: a clock.
#
# One TIME axis in seconds and nothing else. Every dataset this service holds is a signal
# over time, so time is the one axis two recordings can always be laid out along; a
# CHANNEL axis is something a view *selects*, not a place two recordings share. A caller
# that wants a spatial world (a probe, an atlas) authors its axes explicitly.
#
# Seconds, not a sample index: a world is a *calibrated* space, and `t` is a duration from
# its origin. The world has no `epoch` by default -- trial-aligned time has no wall clock.
DEFAULT_WORLD_AXES = [
    PhysicalAxisInputModel(name="t", type=enums.AxisType.TIME, unit="second"),
]

#: The axis types a world can be navigated along. A CHANNEL axis is something a view
#: *samples* -- it is not a place, so it does not belong to a shared space two recordings
#: are registered into.
NAVIGABLE_TYPES = (enums.AxisTypeChoices.TIME.value, enums.AxisTypeChoices.SPACE.value, enums.AxisTypeChoices.FREQUENCY.value)


def create_lens(
    dataset: "models.ArrayDataset",
    slices: list,
    ctx: CreationContext,
) -> "models.Lens":
    """Create a lens -- and, only if it slices, its coordinate system and the edge recording the shift.

    The lens' shape and axes are not written: they follow from the dataset and the slices,
    and a second copy could only drift from the first. The same rule decides whether it
    gets a coordinate system at all: an unsliced lens selects everything, so its space is
    the dataset's sample grid *by definition* -- materializing a second node for it, joined
    by an identity edge, would store nothing. Lenses are immutable, so the decision is
    final at creation.
    """
    intrinsic = dataset.intrinsic_coordinate_system
    if intrinsic is None:
        raise ValueError(f"Dataset {dataset.pk} has no coordinate system: it was created without axes, so there is no sample grid for a lens to select over")

    if dataset.data_arrays.order_by("level").first() is None:
        raise ValueError(f"Dataset {dataset.pk} has no level-0 data array to place the lens against")

    slice_models = [slice.model_dump() for slice in slices]
    sliced = any(slice_models)

    unknown = sorted({entry["axis"] for entry in slice_models} - set(dataset.axis_names))
    if unknown:
        raise ValueError(f"A lens slices the axes its dataset has, but {unknown} {'is' if len(unknown) == 1 else 'are'} not among {dataset.axis_names}")

    # An unsliced lens lives in the dataset's own grid -- it selects everything, so its space
    # *is* that space -- and points at the same node. Only a sliced one needs a space of its
    # own, and gets it before the lens so there is one write each.
    lens_system = intrinsic
    if sliced:
        lens_system = models.CoordinateSystem.objects.create(
            name=f"{dataset.name}/lens",
            creator=ctx.user,
            organization=ctx.organization,
        )

    lens = models.Lens.objects.create(
        dataset=dataset,
        coordinate_system=lens_system,
        slices=slice_models,
    )

    if not lens.slices_list:
        return lens

    # A lens sees the same axes as the array it slices; only the extent changes.
    graph_logic.create_pixel_axes(lens_system, dataset.axes)

    # Without this edge, slicing shifts sample indices and nothing records the shift:
    # sample 0 of a window would read as sample 0 of the recording.
    graph_logic.create_lens_edge(
        lens_system=lens_system,
        parent_system=intrinsic,
        dataset_axis_names=dataset.axis_names,
        slices=lens.slices_list,
        ctx=ctx,
    )

    return lens
