"""GraphQL type for an experiment: mikro's Scene, over time.

Its layers -- mikro's ``Layer``, one table discriminated by kind -- and the placement fields
they carry live in :mod:`core.types.layers`. A layer belongs to exactly one experiment, so that
is the one place "where does this data sit on the timeline" has a single right answer;
everything else about a space is asked of the space.
"""

import datetime
from typing import Annotated, List, Optional, cast

import strawberry
import strawberry_django
from kante.types import Info
from koherent.strawberry.types import ProvenanceEntry
from strawberry import auto

from authentikate.strawberry.types import User

from core import filters, models
from core.types._shared import OrgScoped
from core.types.annotation import AnnotationCollection
from core.types.coords import CoordinateSystem


@strawberry_django.type(models.Experiment, filters=filters.ExperimentFilter, ordering=filters.ExperimentOrder, pagination=True)
class Experiment(OrgScoped):
    """Data laid out on one timeline, as layers. mikro's Scene, over time."""

    id: auto
    name: str
    description: str | None
    created_at: datetime.datetime
    creator: User | None
    layers: List[Annotated["ExperimentLayer", strawberry.lazy("core.types.layers")]] = strawberry_django.field(
        filters=filters.ExperimentLayerFilter,
        description="What this experiment draws, top to bottom: traces, spike rasters, event tables and annotation collections. Each carries its own placement on the timeline, derived from the graph",
    )
    annotation_collection: Optional[AnnotationCollection] = strawberry_django.field(
        description="The collection minted as this experiment's own drawing surface by `createAnnotation(experiment:)`, or null before anything was drawn on it. Its shapes are in the world's coordinates"
    )
    provenance_entries: List[ProvenanceEntry] = strawberry_django.field()
    world: Optional[CoordinateSystem] = strawberry_django.field(
        description=(
            "The space this experiment composes over: its timeline. Adopted, never owned -- several experiments may share one, and deleting an experiment never deletes it. Ask it for "
            "`registrations` (the clocks laid into it), `placedSystems` and `inView(region:)`; ask a layer for `pathToWorld`"
        )
    )

    @strawberry_django.field(description="Is this experiment pinned by the current user")
    def pinned(self, info: Info) -> bool:
        return cast(models.Experiment, self).pinned_by.filter(id=info.context.request.user.id).exists()
