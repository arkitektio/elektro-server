"""Mutations for annotations: the drawn, editable marks on a dataset, a clock or a timeline.

Vendored from mikro's ``core/mutations/annotation.py``; "scene" became "experiment" and the
layer it mints is an :class:`~core.models.ExperimentAnnotationView`.

``createAnnotation`` takes either a collection or an experiment, exactly one. The
experiment path is the sugar that makes marking a timeline feel direct: the first shape
drawn on an experiment mints that experiment's collection -- its own coordinate system
copying the world's axes, an identity registration into the world, and one annotation view
-- and every later shape appends to it. The edge is authored here, at collection creation:
this is not a view mutation fabricating placement, it is a creation flow stating where a
brand-new space sits, once.
"""

from django.db import IntegrityError, transaction
from kante.types import Info
import strawberry
from pydantic import BaseModel, field_validator, model_validator
from simple_history.utils import bulk_create_with_history

import kante
from core import enums, models, types
from core.creation import CreationContext
from core.input_unions import camel_field, prose_errors
from core.inputs.coords import AxisInputModel, CoordinateInput, CoordinateInputModel
from core.inputs.validators import assert_rgba, assert_shape_vectors
from core.logic import graph as graph_logic
from core import guards
from core.scoping import get_for_org


class _ShapeInputModel(BaseModel):
    """The geometry and styling a drawn shape is authored with, and their rules.

    Shared by the three inputs that carry a shape -- one drawn, one of a batch, one
    edited -- so the rules cannot hold on one path and not the others. Every field is
    optional here and the subclasses restate the ones they require, which is the only
    difference between drawing a shape and editing one.
    """

    kind: enums.AnnotationKind | None = None
    vectors: list[list[float]] | None = None
    stroke_color: list[int] | None = None
    fill_color: list[int] | None = None

    @field_validator("stroke_color", "fill_color")
    @classmethod
    def _colors_are_rgba(cls, color: list[int] | None, info) -> list[int] | None:  # noqa: ANN001 - pydantic's own ValidationInfo
        if color is not None:
            assert_rgba(color, field=camel_field(info.field_name), maximum=255)
        return color

    @model_validator(mode="after")
    def _geometry_describes_the_kind(self) -> "_ShapeInputModel":
        # Checked together because the rule depends on both: how many vertices a shape
        # needs is a fact about its kind. On an edit either may be omitted, and then the
        # stored one still governs -- so the kind is read off the model only when given,
        # and the count check is skipped when it is not.
        if self.vectors is not None:
            assert_shape_vectors(self.vectors, kind=self.kind.value if self.kind else None)
        return self


class CreateAnnotationInputModel(_ShapeInputModel):
    collection: str | None = None
    experiment: str | None = None
    kind: enums.AnnotationKind
    name: str | None = None
    description: str | None = None
    coordinates: list[CoordinateInputModel] | None = None
    stroke_width: float | None = None
    filled: bool | None = None


@prose_errors
@kante.pydantic_input(
    CreateAnnotationInputModel,
    description="Input for drawing an annotation. Provide exactly one of `collection` (append to it) or `experiment` (draw on the experiment's timeline: its annotation collection is found, or minted on first use together with its coordinate system, its registration into the world, and its view)",
)
class CreateAnnotationInput:
    """Input for drawing an annotation into a collection or onto an experiment."""

    collection: strawberry.ID | None = strawberry.field(default=None, description="The annotation collection to draw into. Exclusive with `experiment`")
    experiment: strawberry.ID | None = strawberry.field(
        default=None,
        description="The experiment to draw on. Its annotation collection is reused when it exists; the first annotation mints it -- a coordinate system copying the world's axes, an identity registration into the world, and one annotation view. Vertices are then in the world's own units (seconds, on a default timeline). Exclusive with `collection`",
    )
    kind: enums.AnnotationKind = strawberry.field(description="The kind of annotation to draw: EVENT, EVENTS, EPOCH, LINE, PATH or POLYGON. This determines how the vectors are interpreted and drawn")
    name: str | None = strawberry.field(default=None, description="Optional name for the annotation. Defaults to a name derived from its collection")
    description: str | None = strawberry.field(default=None, description="A free-form description of the annotation")
    vectors: list[list[float]] = strawberry.field(default=None, description="The annotation's vertices, in the collection's own coordinates: one list per vertex, its components in the order of the collection's axes. `[[12.5]]` is an event at 12.5 on a time axis; `[[3.0], [4.5]]` is an epoch")
    coordinates: list[CoordinateInput] | None = strawberry.field(
        default=None, description="The discrete coordinates this annotation is pinned to, e.g. [{name: 'c', value: 3}] for an event on channel 3, or [{name: 'sweep', value: 12}]. A coordinate the annotation does not pin is one it spans"
    )
    stroke_color: list[int] | None = strawberry.field(default=None, description="Stroke (outline) color of the geometry, as RGBA: four components, each 0..255 (default white)")
    fill_color: list[int] | None = strawberry.field(default=None, description="Fill color of the geometry, as RGBA: four components, each 0..255, or null for no fill")
    stroke_width: float | None = strawberry.field(default=None, description="Stroke width, in the drawing space's units (default 1.0)")
    filled: bool | None = strawberry.field(default=None, description="Whether the geometry is filled with fill_color (default false)")


def _mint_experiment_collection(experiment: "models.Experiment", ctx: CreationContext) -> "models.AnnotationCollection":
    """The experiment's default drawing surface: collection + system + registration + view, atomically.

    The world's axes are copied onto the collection's own system, which is exactly the
    claim the identity registration then makes -- so the edge is exact by construction
    and wears VALIDATED -- an identity between two spaces with the same axes is exact.

    That copying is also why ``create_identity_registration`` may write its edge without
    running ``assert_edge_rank``, as every other edge writer does: the two spaces are
    axis-for-axis the same *by construction here*, so there is nothing for a rank check to
    disagree with.
    """
    world = experiment.world
    if world is None:
        raise ValueError(f"Experiment {experiment.pk} has no world coordinate system to draw in.")
    world_axes = list(world.axes.all())

    collection = models.AnnotationCollection.objects.create(
        name=f"{experiment.name}/annotations",
        experiment=experiment,
        creator=ctx.user,
        organization=ctx.organization,
        **ctx.provenance_kwargs(),
    )
    system = graph_logic.create_collection_system(
        name=f"{collection.name}/drawing",
        axes=[AxisInputModel(name=axis.name, type=enums.AxisType(axis.type), long_name=axis.long_name, description=axis.description) for axis in world_axes],
        owner=collection,
        ctx=ctx,
    )
    graph_logic.create_identity_registration(
        input_system=system,
        world=world,
        shared=[axis.name for axis in world_axes],
        name=f"{collection.name} -> {experiment.name} (drawn)",
        validity=enums.PlacementValidityChoices.VALIDATED.value,
        ctx=ctx,
    )
    # After the registration, not before: asking once everything is written is how the
    # answer stays independent of the order.
    graph_logic.record_bbox_frame(collection, system)

    order = experiment.recording_views.count() + experiment.stimulus_views.count() + experiment.annotation_views.count()
    models.ExperimentAnnotationView.objects.create(experiment=experiment, collection=collection, visible=True, order=order)
    return collection


def _find_or_mint_experiment_collection(experiment: "models.Experiment", ctx: CreationContext) -> "models.AnnotationCollection":
    """The experiment's annotation collection, minting it on first use.

    The OneToOne on ``AnnotationCollection.experiment`` is what makes this race-safe: a
    concurrent first draw loses on the unique constraint, and the loser re-reads the
    winner's collection instead of forking the experiment's annotations.
    """
    existing = getattr(experiment, "annotation_collection", None)
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            return _mint_experiment_collection(experiment, ctx)
    except IntegrityError:
        experiment.refresh_from_db()
        existing = getattr(experiment, "annotation_collection", None)
        if existing is None:
            raise
        return existing


# A shape's coordinate pins are deliberately *not* checked against the axes of the space it
# is drawn in. A pin is a slice selector over the *data* the shape was drawn against, and the
# documented example is `c` -- which a timeline never carries, because a world holds only
# navigable axes (see `NAVIGABLE_TYPES`) and a channel is something a view samples rather
# than a place. So a pin naming an axis the drawing space lacks is the ordinary case, and a
# typo is indistinguishable from it here.
def create_annotation(
    info: Info,
    input: CreateAnnotationInput,
) -> types.Annotation:
    """Draw an annotation into a collection or onto an experiment, and derive its bounding box."""
    model = input.to_pydantic()

    if bool(model.collection) == bool(model.experiment):
        raise ValueError("Provide exactly one of `collection` or `experiment`: an annotation is drawn into a collection, and an experiment names the collection minted for it.")

    ctx = CreationContext.from_info(info)

    if model.collection:
        collection = get_for_org(models.AnnotationCollection, info, id=model.collection)
    else:
        experiment = get_for_org(models.Experiment, info, id=model.experiment)
        collection = _find_or_mint_experiment_collection(experiment, ctx)

    system = collection.coordinate_system_or_none
    if system is None:
        raise ValueError(f"Annotation collection {collection.pk} has no coordinate system to draw in.")

    vectors = model.vectors or []

    # Pushed through every corner of the box, not just the two extremes: an
    # affine-transformed AABB is not an AABB, and min/max alone is strictly too
    # small under any rotation or shear. Intrinsic, not world -- see Annotation.
    intrinsic_bbox = graph_logic.compute_intrinsic_bbox(system, vectors, padding=graph_logic.vertex_padding(system))

    annotation = models.Annotation.objects.create(
        collection=collection,
        name=model.name or f"Annotation in {collection.name}",
        description=model.description,
        kind=model.kind.value,
        vectors=vectors,
        # Stored keyed by coordinate name -- the same shape as
        # CoordinateAnchor.coordinates, and GIN-queryable. The API keeps the
        # typed list shape.
        coordinates={coordinate.name: coordinate.value for coordinate in (model.coordinates or [])},
        intrinsic_bbox=intrinsic_bbox,
        # The same box again as a Postgres cube: the GiST-indexed search copy.
        bbox_cube=intrinsic_bbox,
        created_with_transforms=graph_logic.transform_version(system),
        stroke_color=model.stroke_color if model.stroke_color is not None else [255, 255, 255, 255],
        fill_color=model.fill_color,
        stroke_width=model.stroke_width if model.stroke_width is not None else 1.0,
        filled=model.filled if model.filled is not None else False,
        creator=ctx.user,
        **ctx.provenance_kwargs(),
    )

    return annotation


class UpdateAnnotationInputModel(_ShapeInputModel):
    id: str
    name: str | None = None
    description: str | None = None
    coordinates: list[CoordinateInputModel] | None = None
    stroke_width: float | None = None
    filled: bool | None = None


@prose_errors
@kante.pydantic_input(UpdateAnnotationInputModel, description="Input for editing an annotation. Only the supplied fields change; new vectors re-derive the bounding box against the current transform chain")
class UpdateAnnotationInput:
    """Input for editing an annotation."""

    id: strawberry.ID = strawberry.field(description="The ID of the annotation to edit")
    name: str | None = strawberry.field(default=None, description="A new name for the annotation")
    description: str | None = strawberry.field(default=None, description="A new description for the annotation")
    kind: enums.AnnotationKind | None = strawberry.field(default=None, description="A new kind, changing how the vectors are interpreted")
    vectors: list[list[float]] | None = strawberry.field(default=None, description="Replacement vertices, in the collection's own coordinates. The bounding box is re-derived")
    coordinates: list[CoordinateInput] | None = strawberry.field(default=None, description="Replacement coordinate pins. The whole set is replaced, not merged")
    stroke_color: list[int] | None = strawberry.field(default=None, description="A new stroke (outline) color, as RGBA: four components, each 0..255")
    fill_color: list[int] | None = strawberry.field(default=None, description="A new fill color, as RGBA: four components, each 0..255")
    stroke_width: float | None = strawberry.field(default=None, description="A new stroke width, in the drawing space's units")
    filled: bool | None = strawberry.field(default=None, description="Whether the geometry is filled with fill_color")


def update_annotation(info: Info, input: UpdateAnnotationInput) -> types.Annotation:
    """Edit an annotation: the CRUD half of being human-drawn."""
    model = input.to_pydantic()

    annotation = get_for_org(models.Annotation, info, id=model.id)

    if model.name is not None:
        annotation.name = model.name
    if model.description is not None:
        annotation.description = model.description
    if model.kind is not None:
        annotation.kind = model.kind.value
    if model.coordinates is not None:
        annotation.coordinates = {coordinate.name: coordinate.value for coordinate in model.coordinates}
    if model.stroke_color is not None:
        annotation.stroke_color = model.stroke_color
    if model.fill_color is not None:
        annotation.fill_color = model.fill_color
    if model.stroke_width is not None:
        annotation.stroke_width = model.stroke_width
    if model.filled is not None:
        annotation.filled = model.filled
    if model.vectors is not None:
        annotation.vectors = model.vectors
        system = annotation.collection.coordinate_system_or_none
        if system is None:
            raise ValueError(f"Annotation collection {annotation.collection.pk} has no coordinate system to derive a bounding box in.")
        annotation.intrinsic_bbox = graph_logic.compute_intrinsic_bbox(system, model.vectors, padding=graph_logic.vertex_padding(system))
        annotation.bbox_cube = annotation.intrinsic_bbox
        annotation.created_with_transforms = graph_logic.transform_version(system)

    annotation.save()
    return annotation


class AnnotationSpecInputModel(_ShapeInputModel):
    kind: enums.AnnotationKind
    name: str | None = None
    description: str | None = None
    coordinates: list[CoordinateInputModel] | None = None
    stroke_width: float | None = None
    filled: bool | None = None


@prose_errors
@kante.pydantic_input(AnnotationSpecInputModel, description="One shape of a bulk draw: the per-annotation subset of CreateAnnotationInput, without the collection/experiment target")
class AnnotationSpecInput:
    """Input for one shape within a bulk annotation draw."""

    kind: enums.AnnotationKind = strawberry.field(description="The kind of annotation to draw: EVENT, EVENTS, EPOCH, LINE, PATH or POLYGON")
    name: str | None = strawberry.field(default=None, description="Optional name for the annotation. Defaults to a name derived from its collection")
    description: str | None = strawberry.field(default=None, description="A free-form description of the annotation")
    vectors: list[list[float]] = strawberry.field(default=None, description="The annotation's vertices, in the collection's own coordinates: one list per vertex, its components in the order of the collection's axes. `[[12.5]]` is an event at 12.5 on a time axis; `[[3.0], [4.5]]` is an epoch")
    coordinates: list[CoordinateInput] | None = strawberry.field(default=None, description="The discrete coordinates this annotation is pinned to. A coordinate the annotation does not pin is one it spans")
    stroke_color: list[int] | None = strawberry.field(default=None, description="Stroke (outline) color of the geometry, as RGBA: four components, each 0..255 (default white)")
    fill_color: list[int] | None = strawberry.field(default=None, description="Fill color of the geometry, as RGBA: four components, each 0..255, or null for no fill")
    stroke_width: float | None = strawberry.field(default=None, description="Stroke width, in the drawing space's units (default 1.0)")
    filled: bool | None = strawberry.field(default=None, description="Whether the geometry is filled with fill_color (default false)")


class CreateAnnotationsInputModel(BaseModel):
    collection: str | None = None
    experiment: str | None = None
    annotations: list[AnnotationSpecInputModel]


@kante.pydantic_input(
    CreateAnnotationsInputModel,
    description="Input for drawing many annotations in one call -- a detector's whole output. Provide exactly one of `collection` or `experiment` (same semantics as createAnnotation); the transform chain and version resolve once for the whole batch",
)
class CreateAnnotationsInput:
    """Input for drawing many annotations into one collection or onto one experiment."""

    collection: strawberry.ID | None = strawberry.field(default=None, description="The annotation collection to draw into. Exclusive with `experiment`")
    experiment: strawberry.ID | None = strawberry.field(default=None, description="The experiment to draw on; its annotation collection is reused or minted exactly as createAnnotation does. Exclusive with `collection`")
    annotations: list[AnnotationSpecInput] = strawberry.field(description="The shapes to draw, in order")


def create_annotations(
    info: Info,
    input: CreateAnnotationsInput,
) -> list[types.Annotation]:
    """Draw many annotations in one call: one collection resolve, one chain resolve, one insert.

    The per-batch work (find-or-mint the collection, resolve the transform chain,
    read the transform version) happens once; the per-shape work is pure geometry.
    History rows are written through simple_history's bulk path, which fires the
    same pre-create hook single creates do, so provenance attribution is intact.
    """
    model = input.to_pydantic()

    if bool(model.collection) == bool(model.experiment):
        raise ValueError("Provide exactly one of `collection` or `experiment`: an annotation is drawn into a collection, and an experiment names the collection minted for it.")

    ctx = CreationContext.from_info(info)

    if model.collection:
        collection = get_for_org(models.AnnotationCollection, info, id=model.collection)
    else:
        experiment = get_for_org(models.Experiment, info, id=model.experiment)
        collection = _find_or_mint_experiment_collection(experiment, ctx)

    system = collection.coordinate_system_or_none
    if system is None:
        raise ValueError(f"Annotation collection {collection.pk} has no coordinate system to draw in.")

    chain = graph_logic.intrinsic_chain(system)
    version = graph_logic.transform_version(system)
    padding = graph_logic.vertex_padding(system)

    rows = []
    for spec in model.annotations:
        vectors = spec.vectors or []
        bbox = graph_logic.bbox_along_chain(chain, vectors, padding=padding)
        rows.append(
            models.Annotation(
                collection=collection,
                name=spec.name or f"Annotation in {collection.name}",
                description=spec.description,
                kind=spec.kind.value,
                vectors=vectors,
                coordinates={coordinate.name: coordinate.value for coordinate in (spec.coordinates or [])},
                intrinsic_bbox=bbox,
                bbox_cube=bbox,
                created_with_transforms=version,
                stroke_color=spec.stroke_color if spec.stroke_color is not None else [255, 255, 255, 255],
                fill_color=spec.fill_color,
                stroke_width=spec.stroke_width if spec.stroke_width is not None else 1.0,
                filled=spec.filled if spec.filled is not None else False,
                creator=ctx.user,
                **ctx.provenance_kwargs(),
            )
        )

    with transaction.atomic():
        return bulk_create_with_history(rows, models.Annotation)


class DeleteAnnotationInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteAnnotationInputModel, description="Input for deleting an annotation by ID")
class DeleteAnnotationInput:
    """Input for deleting an annotation by ID."""

    id: strawberry.ID = strawberry.field(description="The ID of the annotation to delete")


def delete_annotation(info: Info, input: DeleteAnnotationInput) -> strawberry.ID:
    """Delete one annotation. Its collection, and the space it was drawn in, stay."""
    model = input.to_pydantic()
    annotation = get_for_org(models.Annotation, info, id=model.id)
    guards.enforce_delete(info, annotation)
    annotation.delete()
    return strawberry.ID(model.id)
