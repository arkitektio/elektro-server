"""GraphQL types for annotations and the collections that own their drawing space.

Vendored from mikro (``AnnotationCollection`` and ``Annotation`` in
``mikro/core/types/array_dataset.py``). What differs: a collection may be minted for an
*experiment* rather than a scene, there are no folders or file links, and both types are
tenant-scoped through the mixin every type of this service uses.
"""

import datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

import strawberry
from kante.types import Info
from koherent.strawberry.types import ProvenanceEntry
from strawberry import auto

import kante
from authentikate.strawberry.types import User

from core import enums, filters, models, order
from core.logic import graph as graph_logic
from core.types._shared import OrgScoped, build_prescoped_queryset
from core.types.coords import CoordinateSystem, Transformation

if TYPE_CHECKING:
    # Only for the lazy annotations below: `core.types.experiment` imports this module.
    from core.types.experiment import Experiment, ExperimentAnnotationView


@kante.type(description="A discrete coordinate an annotation is pinned to, e.g. a channel or a sweep")
class Coordinate:
    """A discrete coordinate an annotation is pinned to."""

    name: str = strawberry.field(description="The name of the coordinate, e.g. 'c' or 'sweep'")
    value: int = strawberry.field(description="The value along that coordinate")


@kante.type(description="An axis-aligned bounding box, as a min and a max corner")
class BoundingBox:
    """An axis-aligned bounding box, as a min and a max corner."""

    min: list[float] = strawberry.field(description="The lower corner, in the coordinate order of the coordinate system")
    max: list[float] = strawberry.field(description="The upper corner, in the coordinate order of the coordinate system")


@kante.django_type(
    models.AnnotationCollection,
    filters=filters.AnnotationCollectionFilter,
    ordering=order.AnnotationCollectionOrder,
    pagination=True,
    description=(
        "A named set of annotations, owning the coordinate system they are drawn in. All its shapes share one drawing space and so one placement story: the collection is related "
        "to other spaces by edges, the shapes just have vectors. Drawn over a dataset's sample grid it marks that dataset; drawn on a segment's clock it marks every signal of the "
        "segment at once -- which is what Neo's events and epochs are; drawn on an experiment's world it marks the timeline"
    ),
)
class AnnotationCollection(OrgScoped):
    """A named set of annotations, owning the space they are drawn in."""

    id: auto
    name: auto
    description: str | None
    experiment: Optional[Annotated["Experiment", strawberry.lazy("core.types.experiment")]] = kante.django_field(
        description="The experiment this collection was minted for as its default drawing surface, or null for a collection drawn over a dataset, a clock, or nothing. Bookkeeping, not placement: the registration edge is what places it"
    )
    coordinate_system: CoordinateSystem = kante.django_field(description="The coordinate system the annotations' vectors are expressed in. The collection owns it; `derivedFrom` relates it to whatever the shapes are drawn over")
    annotations: List[Annotated["Annotation", strawberry.lazy("core.types.annotation")]] = kante.django_field(description="The annotations in this collection")
    experiment_views: List[Annotated["ExperimentAnnotationView", strawberry.lazy("core.types.experiment")]] = kante.django_field(description="The experiments this collection is shown in, one view each")
    created_at: datetime.datetime
    creator: User | None
    provenance_entries: List[ProvenanceEntry] = kante.django_field(description="Provenance entries for this annotation collection")

    @kante.django_field(
        description=(
            "Every edge from this collection's space back into what the shapes are drawn over, in declared order -- the first is the primary parent, the one that places it. An edge "
            "into a dataset's sample grid for a collection drawn over a dataset, into a clock for one marking a whole segment. Empty for a freestanding collection, and for an "
            "experiment-minted one: its edge lands in a world, which is a registration (see `coordinateSystem { registrations }` on the world), not a lineage"
        )
    )
    def derived_from(self, info: Info) -> List[Transformation]:
        """The edges relating this collection's space to the ones it is drawn over."""
        system = getattr(self, "coordinate_system", None)
        return graph_logic.collection_derivation_edges(system) if system else []


@kante.django_type(
    models.Annotation,
    filters=filters.AnnotationFilter,
    ordering=order.AnnotationOrder,
    pagination=True,
    description="A mark on a dataset, a clock or a timeline: an event, an epoch, a measurement, in its collection's coordinate system. It belongs to the collection, not to an experiment: delete the experiment and the annotation survives",
)
class Annotation:
    """A drawn shape in its collection's coordinate system, described by its vectors and the discrete coordinates it is pinned to."""

    id: auto
    collection: AnnotationCollection = kante.django_field(description="The collection this annotation belongs to; its vectors are expressed in the collection's own coordinate system")
    name: auto
    description: str | None
    kind: enums.AnnotationKind
    vectors: list[list[float]] = kante.django_field(description="The annotation's vertices: one list per vertex, its components in the order of the collection's axes")
    created_with_transforms: int
    stroke_color: list[int] | None = kante.django_field(description="The stroke (outline) color of the geometry, as RGBA")
    fill_color: list[int] | None = kante.django_field(description="The fill color of the geometry, as RGBA, or null for no fill")
    stroke_width: float = kante.django_field(description="The stroke width of the geometry, in the drawing space's units. One number for every direction, so it is a well-defined length only where that space's axes share a scale")
    filled: bool = kante.django_field(description="Whether the geometry is filled with fill_color")
    creator: User | None
    provenance_entries: List[ProvenanceEntry] = kante.django_field(description="Provenance entries for this annotation")

    @kante.django_field(description="The coordinate system this annotation's vectors are expressed in: its collection's own system")
    def coordinate_system(self, info: Info) -> CoordinateSystem | None:
        """The collection's coordinate system, surfaced for convenience."""
        return self.collection.coordinate_system_or_none

    @kante.django_field(description="The discrete coordinates this annotation is pinned to. A coordinate the annotation does not pin is one it spans")
    def coordinates(self, info: Info) -> list[Coordinate]:
        """The annotation's discrete pins, unpacked from the stored name-keyed dict."""
        return [Coordinate(name=name, value=value) for name, value in (self.coordinates or {}).items()]

    @kante.django_field(
        description=(
            "The annotation's bounding box in the frame its collection names, derived from every corner of its geometry (an affine-transformed box is not a box: min/max alone gives a "
            "strictly too-small answer under shear). For an event the box is a point; for an epoch it is the epoch. Not a world box: one collection can sit in two experiments under two "
            "registrations. **Not always a dataset's sample grid**: a registration, or a derivation that changes rank, is not something a box can be pushed across -- it says nothing about "
            "the axes it does not name -- and the box then stays in the collection's own drawing space. Boxes compare only within one frame, which is why the spatial filters require a "
            "collection or coordinate system alongside"
        )
    )
    def intrinsic_bbox(self, info: Info) -> BoundingBox | None:
        """The annotation's bounding box in the frame its collection's chain reaches."""
        if not self.intrinsic_bbox:
            return None
        return BoundingBox(min=self.intrinsic_bbox["min"], max=self.intrinsic_bbox["max"])

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):  # noqa: ANN001, ANN206 - strawberry_django's hook
        """Scope the list to the request's organization, carrying the system along.

        Through the required collection FK -- the annotation carries no organization column
        of its own. The select_related is for the `coordinateSystem` resolver, which walks
        collection -> system per row and would otherwise cost two queries per annotation.
        """
        return build_prescoped_queryset(info, queryset).select_related("collection__coordinate_system")
