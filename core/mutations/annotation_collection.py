"""Mutations for annotation collections.

Vendored from mikro's ``core/mutations/annotation_collection.py``. An annotation collection
owns the coordinate system its shapes are drawn in, and an edge relates that system to
whatever the shapes were drawn over. The explicit create here is for a collection drawn
over a dataset, over a clock, or over nothing; the common path for a timeline -- drawing on an
experiment -- goes through ``createAnnotation``, which mints the experiment's collection on
first use.

What "drawn over" buys is decided by what the edge lands in:

* a **dataset's sample grid** (``derivedFrom: [{kind: DATASET, ...}]``): the shapes mark that
  dataset, and a vertex's time component is a sample index;
* a **clock** (``derivedFrom: [{kind: COORDINATE_SYSTEM, coordinateSystem: <segment clock>}]``):
  the shapes mark *every signal timed against that clock*, in its unit. This is what Neo's
  events and epochs are -- they belong to the segment, not to one signal of it.
"""

import strawberry
from django.db import transaction
from kante.types import Info
from pydantic import BaseModel, Field

import kante
from core import guards, models, types
from core.creation import CreationContext
from core.input_unions import prose_errors
from core.inputs.coords import AxisInput, AxisInputModel, DerivedFromInput, DerivedFromSpec
from core.logic import coordinate_system as coordinate_system_logic
from core.logic import graph as graph_logic
from core.logic import spaces as spaces_logic
from core.scoping import get_for_org


class CreateAnnotationCollectionInputModel(BaseModel):
    name: str
    description: str | None = None
    axes: list[AxisInputModel]
    derived_from: list[DerivedFromSpec] | None = None


@prose_errors
@kante.pydantic_input(
    CreateAnnotationCollectionInputModel,
    description="Input for creating an annotation collection. The collection gets a coordinate system of its own, and an edge relates it to the space the shapes are drawn over",
)
class CreateAnnotationCollectionInput:
    """Input for creating an annotation collection."""

    name: str = strawberry.field(description="The name of the annotation collection, e.g. 'detected spikes' or 'artifacts'. What the shapes in it *mean* is said here and in their names, never by their kind")
    description: str | None = strawberry.field(default=None, description="A free-form description of the collection")
    axes: list[AxisInput] = strawberry.field(
        description=(
            "The axes of the collection's own coordinate system, in order: the components of every vertex drawn in it. `[{name: 't', type: TIME}]` for events and epochs; add "
            "`{name: 'v', type: VALUE}` to draw measurements against the dataset's values, or `{name: 'c', type: CHANNEL}` to bound a run of channels. Required: the collection "
            "owns its space, and a derivation does not imply an identity to copy axes across"
        )
    )
    derived_from: list[DerivedFromInput] | None = strawberry.field(
        default=None,
        description=(
            "What this collection is drawn over. One entry per source; the first is the primary parent, the one that places it. Each names its source and how this collection's "
            "space relates to the source's: **omit the transform and the edge is UNMAPPABLE**, recording the lineage and claiming no correspondence. State BY_DIMENSION over the "
            "shared axes (`inputAxes: ['t'], outputAxes: ['t']`) when the shapes are drawn directly in the source's coordinates -- sample indices over a dataset, seconds over a clock"
        ),
    )


def create_annotation_collection(info: Info, input: CreateAnnotationCollectionInput) -> types.AnnotationCollection:
    """Create an annotation collection, in a coordinate system of its own.

    The collection owns its system, and an optional edge relates that system to the one the
    shapes are drawn over. A collection created here has no experiment -- the
    experiment-minted collection is ``createAnnotation``'s business.
    """
    model = input.to_pydantic()

    ctx = CreationContext.from_info(info)

    # Atomic, because the collection row is written before its axes are checked and before
    # its edges are: without this, an axis set the space refuses -- or a rank an edge
    # refuses -- leaves an orphan collection behind and returns an error.
    with transaction.atomic():
        collection = models.AnnotationCollection.objects.create(
            name=model.name,
            description=model.description,
            creator=ctx.user,
            organization=ctx.organization,
            **ctx.provenance_kwargs(),
        )

        system = graph_logic.create_collection_system(
            name=f"{collection.name}/drawing",
            axes=model.axes,
            owner=collection,
            ctx=ctx,
        )

        # Optional on purpose: a collection in some absolute space is drawn over nothing.
        coordinate_system_logic.write_derivation_edges(info, name=collection.name, own_system=system, derived_from=model.derived_from or [], ctx=ctx)
        # Once the derivation exists, because it is what decides the answer: a composable one
        # means the boxes are stored in the source's grid, and this is where the collection
        # says so. Inside the transaction with it -- a frame naming an edge that rolled back
        # would outlive the reason it was chosen.
        graph_logic.record_bbox_frame(collection, system)

    return collection


class DeleteAnnotationCollectionInputModel(BaseModel):
    id: str = Field(description="The ID of the annotation collection to delete")


@kante.pydantic_input(DeleteAnnotationCollectionInputModel, description="Input for deleting an annotation collection by ID")
class DeleteAnnotationCollectionInput:
    """Input for deleting an annotation collection by ID."""

    id: strawberry.ID = strawberry.field(description="The ID of the annotation collection to delete. Its annotations, its experiment view and its coordinate system go with it")


def delete_annotation_collection(info: Info, input: DeleteAnnotationCollectionInput) -> strawberry.ID:
    """Delete an annotation collection, its shapes, and the drawing space it owned.

    The collection goes first: its FK to the space is PROTECT. The space is then swept -- a
    drawing space nothing is drawn in is not a space anyone can use -- and the edge that
    placed it cascades with it. What it was drawn *over* is never touched.
    """
    model = input.to_pydantic()
    collection = get_for_org(models.AnnotationCollection, info, id=model.id)
    guards.enforce_delete(info, collection)

    with transaction.atomic():
        system_id = collection.coordinate_system_id
        collection.delete()
        spaces_logic.sweep_empty_systems([system_id])
    return strawberry.ID(model.id)
