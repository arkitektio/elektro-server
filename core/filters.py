import datetime
import strawberry
from core import models, enums, scalars
from strawberry import auto
from typing import ClassVar, Optional
from strawberry_django.filters import FilterLookup
import strawberry_django
import kante
from django.db.models import F, FloatField, Q, QuerySet, Value
from embeddings.search import hybrid_search
from django.db.models.functions import Coalesce, Greatest
from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramSimilarity,
)


@strawberry.input
class IDFilterMixin:
    ids: list[strawberry.ID] | None

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)


@strawberry.input
class CreatedAtFilterMixin:
    created_before: datetime.datetime | None
    created_after: datetime.datetime | None

    def filter_created_before(self, queryset, info):
        if self.created_before is None:
            return queryset
        return queryset.filter(created_at__lt=self.created_before)

    def filter_created_after(self, queryset, info):
        if self.created_after is None:
            return queryset
        return queryset.filter(created_at__gt=self.created_after)


@strawberry.input
class CreatorFilterMixin:
    """Filter by who created a record, via the direct ``creator`` FK.

    Universal: works on any model carrying a ``creator`` FK, independent of
    whether the model tracks provenance history. ``mine`` is the common,
    biologist-facing case ("show only what I made").
    """

    created_by: strawberry.ID | None
    mine: bool | None

    def filter_created_by(self, queryset, info):
        if self.created_by is None:
            return queryset
        return queryset.filter(creator_id=self.created_by)

    def filter_mine(self, queryset, info):
        if self.mine is None:
            return queryset
        user = info.context.request.user
        if self.mine:
            return queryset.filter(creator_id=user.id)
        return queryset.exclude(creator_id=user.id)


@strawberry.input
class ProvenanceFilterMixin:
    """Flat, biologist-friendly filters over a model's provenance history.

    Requires the model to carry a :func:`koherent.fields.ProvenanceField`
    (reverse relation ``provenance_entries``). Traversing that one-to-many
    history relation joins one row per matching entry, so every method ends in
    ``.distinct()`` to keep an instance from being returned once per match (same
    pattern the experiment filters use).

    Only apply this mixin to a filter whose model has ``provenance_entries`` —
    otherwise these lookups raise ``FieldError`` at query time.

    NB: this is the deliberately *flat* counterpart to koherent's own nested
    ``koherent.strawberry.ProvenanceFilterMixin`` (a ``provenance: {...}`` input).
    Both can coexist; koherent's is never imported here, so there is no clash.
    """

    # The human-readable task id string (Task.task_id), not the FK pk. We
    # traverse ``task__task_id`` deliberately: ``provenance_entries__task_id``
    # would resolve to the FK's pk column, a different (and confusing) field.
    provenance_task: str | None
    provenance_root_task: str | None
    created_with: str | None
    created_by_agent: bool | None

    def filter_provenance_task(self, queryset, info):
        if self.provenance_task is None:
            return queryset
        return queryset.filter(
            provenance_entries__task__task_id=self.provenance_task
        ).distinct()

    def filter_provenance_root_task(self, queryset, info):
        if self.provenance_root_task is None:
            return queryset
        return queryset.filter(
            provenance_entries__task__root_task_id=self.provenance_root_task
        ).distinct()

    def filter_created_with(self, queryset, info):
        if self.created_with is None:
            return queryset
        # A change can be attributed to a client directly (on the history row)
        # or via the task's executing agent; match either.
        return queryset.filter(
            Q(provenance_entries__client__client_id=self.created_with)
            | Q(provenance_entries__task__agent_client_id=self.created_with)
        ).distinct()

    def filter_created_by_agent(self, queryset, info):
        if self.created_by_agent is None:
            return queryset
        if self.created_by_agent:
            # Produced/modified under an automated provenance task.
            return queryset.filter(provenance_entries__task__isnull=False).distinct()
        # Human / direct-API only: no provenance entry carries a task.
        return queryset.exclude(provenance_entries__task__isnull=False).distinct()


# Minimum trigram similarity for a fuzzy match to be considered a hit. Postgres'
# default ``pg_trgm.similarity_threshold`` is 0.3; we loosen it so short / partial
# terms still surface typo-tolerant matches.
TRIGRAM_THRESHOLD = 0.15


@strawberry.input
class SearchFilterMixin:
    """Fuzzy, case-insensitive, full-text search over one or more text fields.

    Subclasses declare which fields to search via the ``SEARCH_FIELDS`` class
    attribute (a plain ``ClassVar`` so it is *not* exposed as a GraphQL input).
    A match is any of:

    * ``icontains`` — case-insensitive substring (keeps exact/partial matches)
    * trigram similarity above :data:`TRIGRAM_THRESHOLD` — typo tolerance
    * full-text ``SearchQuery`` (websearch) — word stemming, multi-word, order-independent

    Results are ranked by a combined relevance score (best matches first).
    """

    search: str | None

    # Overridden per filter. Empty list disables search gracefully.
    SEARCH_FIELDS: ClassVar[list[str]] = ["name"]

    def filter_search(self, queryset, info):
        if not self.search:
            return queryset
        term = self.search.strip()
        fields = type(self).SEARCH_FIELDS
        if not term or not fields:
            return queryset

        # Full-text vector over all fields (NULL-safe via COALESCE).
        vector = None
        for f in fields:
            v = SearchVector(Coalesce(F(f), Value("")))
            vector = v if vector is None else vector + v
        query = SearchQuery(term, search_type="websearch")

        # Best trigram similarity across the searched fields, for ranking.
        sim_exprs = [TrigramSimilarity(f, term) for f in fields]
        similarity = sim_exprs[0] if len(sim_exprs) == 1 else Greatest(*sim_exprs)

        # WHERE: full-text match OR trigram similarity above threshold OR
        # case-insensitive substring on any field. ``_similarity`` is the best
        # trigram score across all fields, so this honours TRIGRAM_THRESHOLD
        # (looser than pg_trgm's default 0.3 GUC used by ``__trigram_similar``).
        predicate = Q(_rank__gt=0.0) | Q(_similarity__gte=TRIGRAM_THRESHOLD)
        for f in fields:
            predicate |= Q(**{f"{f}__icontains": term})

        return (
            queryset.annotate(
                _similarity=Coalesce(similarity, Value(0.0), output_field=FloatField()),
                _rank=SearchRank(vector, query),
            )
            .filter(predicate)
            .annotate(_relevance=Greatest("_similarity", "_rank", output_field=FloatField()))
            .order_by("-_relevance")
        )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@strawberry_django.filter_type(models.Experiment)
class ExperimentFilter(
    IDFilterMixin,
    SearchFilterMixin,
    CreatedAtFilterMixin,
    CreatorFilterMixin,
    ProvenanceFilterMixin,
):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]
    world: strawberry.ID | None = None

    def filter_world(self, queryset, info):
        """Experiments composing over this space. Several may share one world."""
        if self.world is None:
            return queryset
        return queryset.filter(world_id=self.world)


@strawberry_django.filter_type(models.ModelCollection)
class ModelCollectionFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin, CreatorFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.ModelWorkspace)
class ModelWorkspaceFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin, CreatorFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.WorkspaceMapping)
class WorkspaceMappingFilter(IDFilterMixin):
    id: auto


@strawberry_django.filter_type(models.NeuronModel)
class NeuronModelFilter(
    IDFilterMixin,
    SearchFilterMixin,
    CreatedAtFilterMixin,
    CreatorFilterMixin,
    ProvenanceFilterMixin,
):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.Mechanism)
class MechanismFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.ModEnvironment)
class ModEnvironmentFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]


# ---------------------------------------------------------------------------
# Ordering
#
# Every type exposes an ordering input. Models that track a creation timestamp
# default to ordering by ``created_at`` (and ``id``); the rest fall back to the
# always-present ``id`` field as a sensible, stable default.
# ---------------------------------------------------------------------------


@strawberry_django.order_type(models.ModelCollection)
class ModelCollectionOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.ModelWorkspace)
class ModelWorkspaceOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.WorkspaceMapping)
class WorkspaceMappingOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.Experiment)
class ExperimentOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.NeuronModel)
class NeuronModelOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.ModEnvironment)
class ModEnvironmentOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.Mechanism)
class MechanismOrder:
    id: auto
    created_at: auto


# --- The coordinate graph (vendored from mikro's core/filters.py) -----------------------------
#
# These are `filter_field` resolvers where the filters above are `filter_<name>` methods.
# Both work here, but this service runs strawberry-django with USE_DEPRECATED_FILTERS, and
# in that mode an explicit `null` reaches a resolver instead of being skipped. mikro's
# `uninhabited` is `condition if value else ~condition`, which would read `uninhabited: null`
# as "inhabited only" -- so every resolver below states what null means: no constraint.

from kante.types import Info  # noqa: E402
from core.logic import graph as graph_logic  # noqa: E402
from core.scoping import for_org  # noqa: E402


@strawberry.input
class IdsFilterMixin:
    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, info: Info, value: list[strawberry.ID] | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}id__in": value})


@strawberry.input
class NameSearchFilterMixin:
    @kante.filter_field(description="Search by name (case-insensitive substring)")
    def search(self, info: Info, value: str | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}name__icontains": value})


@strawberry.input
class SemanticNameSearchFilterMixin:
    """``search`` = substring of the name OR semantic similarity to name + description.

    For the models that carry an embedding (``embeddings.models.EmbeddedDescriptionMixin``:
    the array, table and sparse datasets). Substring hits rank first, then by similarity;
    nested use (``prefix``) stays lexical. An explicit ``null`` reaches this resolver under
    USE_DEPRECATED_FILTERS and means no constraint.
    """

    @kante.filter_field(description="Search by name (case-insensitive substring) or by the meaning of the query against name and description. Substring matches rank first, then by similarity; an explicit `ordering` replaces that ranking")
    def search(self, info: Info, queryset: QuerySet, value: str | None, prefix: str) -> tuple[QuerySet, Q]:
        """Annotate the distance and OR the semantic predicate onto the substring one."""
        if value is None:
            return queryset, Q()
        return hybrid_search(queryset, prefix, value, Q(**{f"{prefix}name__icontains": value}))


@strawberry.input
class OwnedFilterMixin:
    @kante.filter_field(description="Filter for items created before this datetime")
    def created_before(self, info: Info, value: datetime.datetime | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}created_at__lt": value})

    @kante.filter_field(description="Filter for items created after this datetime")
    def created_after(self, info: Info, value: datetime.datetime | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}created_at__gt": value})

    @kante.filter_field(description="Filter by the creator's subject ID")
    def owner(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}creator__sub": value})


def _placeable_destination(info: Info, value: strawberry.ID) -> "models.CoordinateSystem | None":
    """The space a `placeableIn` filter is asking about, or None when there is no such space here.

    Organization-scoped: the walk it feeds reads another org's edges otherwise, and "which of my
    datasets are placeable in your world" is an answer this server has no reason to give. `None`
    rather than a raise, because a filter naming a space that is not there should return
    nothing, not fail the whole query.
    """
    return for_org(models.CoordinateSystem, info).filter(pk=value).first()


@strawberry.input(
    description=(
        "A `placeableIn` question: the destination space, and the narrowing of it. Placeable means *affinely* placeable -- reaching the space across steps that compose into one "
        "affine map. A spike train or an irregularly sampled signal reaches its clock through a FIELD and is therefore not in this set, although an experiment view over it can "
        "still be created: a timeline can draw spike times without a matrix. This filter answers 'what can I lay out with one map', not 'what can I show'"
    )
)
class PlaceableFilter:
    """The destination space of a `placeableIn` question, and the narrowing of it."""

    space: strawberry.ID = strawberry.field(description="The space to be placed into. A *space*, not an experiment: every experiment over one world offers the same candidates. Pass `experiment.world.id` to ask it of an experiment")
    derived_only: bool | None = strawberry.field(
        default=None,
        description="Keep only what *needed* a lineage tree to get here: the filtered, decimated and sorted datasets placed by an ancestor's registration. What the space registers directly is dropped",
    )
    require_affine: bool | None = strawberry.field(
        default=None,
        description=(
            "(elektro) Set false to ask *what is in this space* rather than *what can be drawn in it*: also admit what reaches it across a FIELD -- a variable-step run timed onto its "
            "clock by a lookup, a spike train. What is in a session is what is placed onto its clock; a picker keeps the strict default, which only offers what one affine map can draw"
        ),
    )


@kante.filter_type(models.CoordinateSystem)
class CoordinateSystemFilter(IdsFilterMixin, NameSearchFilterMixin, OwnedFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]

    @kante.filter_field(description="Filter to the spaces nothing lives in: pure reference frames -- the clocks and worlds that datasets are sampled onto and registered into. False finds the spaces some data actually occupies")
    def uninhabited(self, info: Info, value: bool | None, prefix: str) -> Q:
        if value is None:
            return Q()
        # One list, in `core.logic.graph.CONTAINERS`. A hand-written copy here answers
        # "nothing lives in this space" while something does.
        condition = Q(**{f"{prefix}{related_name}__isnull": True for related_name in graph_logic.RESIDENT_RELATIONS})
        return condition if value else ~condition

    @kante.filter_field(description="Filter to the spaces this dataset's data lives in: its own sample grid, and the grids of its sliced lenses")
    def dataset(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}datasets__id": value}) | Q(**{f"{prefix}lenses__dataset_id": value}) | Q(**{f"{prefix}data_arrays__dataset_id": value})

    @kante.filter_field(description="Filter to the spaces something composes over without living in them: an experiment's world. False finds the spaces nothing is laid out in")
    def composed_over(self, info: Info, value: bool | None, prefix: str) -> Q:
        if value is None or not graph_logic.WORLD_RELATIONS:
            return Q()
        unused = Q(**{f"{prefix}{related_name}__isnull": True for related_name in graph_logic.WORLD_RELATIONS})
        return ~unused if value else unused


@kante.filter_type(models.Axis)
class AxisFilter(IdsFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    type: auto

    @kante.filter_field(description="Filter by the coordinate system this axis belongs to")
    def coordinate_system(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}coordinate_system_id": value})


@kante.filter_type(models.Transformation)
class TransformationFilter(IdsFilterMixin, OwnedFilterMixin):
    id: auto
    kind: auto

    # Not `auto`: that would mint a second SDL enum from the TextChoices twin
    # (PlacementValidityChoices) beside the strawberry PlacementValidity every
    # other field uses.
    @kante.filter_field(description="Filter by how much the edge's map is actually known, e.g. INFERRED to list every sampling law read from acquisition metadata")
    def validity(self, info: Info, value: enums.PlacementValidity | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}validity": value.value})

    @kante.filter_field(description="Filter by the coordinate system this transformation maps from")
    def input(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}input_id": value})

    @kante.filter_field(description="Filter by the coordinate system this transformation maps to")
    def output(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}output_id": value})

    # There is deliberately no `experiment` filter: an edge is not a member of a composition.
    # An edge *into a space* is `output: <systemId>` above, and the field form of that same
    # question is `CoordinateSystem.registrations`.

    @kante.filter_field(description="Show only top-level edges, excluding the children of SEQUENCE / BY_DIMENSION wrappers")
    def roots_only(self, info: Info, value: bool | None, prefix: str) -> Q:
        return Q(**{f"{prefix}parent__isnull": True}) if value else Q()


@kante.filter_type(models.Lens)
class LensFilter(IdsFilterMixin):
    id: auto

    @kante.filter_field(description="Filter by the dataset this lens selects over")
    def dataset(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}dataset_id": value})

    @kante.filter_field(description="Filter to lenses placeable into a coordinate system: those whose space reaches it across steps that compose into one affine map, walking the transformation edges")
    def placeable_in(self, info: Info, value: PlaceableFilter | None, prefix: str) -> Q:
        if value is None:
            return Q()
        space = _placeable_destination(info, value.space)
        if space is None:
            return Q(pk__in=[])
        # Placeability is a property of the *dataset*, so every lens of a placeable dataset is
        # placeable and this stays a plain indexed `dataset_id__in` with no `distinct()`.
        # `bool(...)`: an omitted nested field can arrive as `strawberry.UNSET`, which is not None.
        return Q(**{f"{prefix}dataset_id__in": graph_logic.placeable_lens_dataset_ids(space, derived_only=bool(value.derived_only), require_affine=value.require_affine is not False)})


# --- Annotations (vendored from mikro's core/filters.py) ---------------------------------------

from core.inputs.coords import BoundingBoxInput, CoordinateInput  # noqa: E402


def _systems_drawn_over_dataset(dataset_id: strawberry.ID):  # noqa: ANN202 - a values() queryset
    """The collection systems whose derivation edge lands in this dataset, or in a lens of it.

    A subquery rather than a join: `Transformation.input`/`output` are declared
    `related_name="+"`, so there is no reverse accessor to filter across, and a collection keeps
    no dataset column of its own -- the edge is the only place that fact lives, and duplicating it
    onto the collection is the copy this whole graph exists to avoid. (It is the copy `ROI.trace`
    was.)
    """
    return models.Transformation.objects.filter(parent__isnull=True, input__isnull=False).filter(Q(output__datasets__id=dataset_id) | Q(output__lenses__dataset_id=dataset_id) | Q(output__data_arrays__dataset_id=dataset_id)).values("input_id")


def _systems_drawn_over_system(system_id: strawberry.ID):  # noqa: ANN202 - a values() queryset
    """The collection systems with an edge landing in this space: a clock, a world, a sample grid."""
    return models.Transformation.objects.filter(parent__isnull=True, input__isnull=False, input__annotation_collections__isnull=False, output_id=system_id).values("input_id")


@kante.filter_type(models.AnnotationCollection)
class AnnotationCollectionFilter(IdsFilterMixin, NameSearchFilterMixin, OwnedFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]

    @kante.filter_field(description="Filter by the experiment this collection was minted for as its default drawing surface")
    def experiment(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}experiment_id": value})

    @kante.filter_field(description="Filter by the coordinate system the annotations are drawn in (the collection's own)")
    def coordinate_system(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}coordinate_system__id": value})

    @kante.filter_field(description="Filter to the collections drawn over this dataset (or over a lens of it), following the derivation edge")
    def dataset(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}coordinate_system__in": _systems_drawn_over_dataset(value)})

    @kante.filter_field(description="Filter to the collections drawn over this coordinate system: pass a segment's clock for the events and epochs marking the whole segment, or an experiment's world for those on its timeline")
    def drawn_over(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}coordinate_system__in": _systems_drawn_over_system(value)})


@kante.filter_type(models.Annotation)
class AnnotationFilter(IdsFilterMixin, NameSearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]
    kind: auto

    @kante.filter_field(description="Filter by the collection this annotation belongs to")
    def collection(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}collection_id": value})

    @kante.filter_field(description="Filter by the coordinate system this annotation is drawn in (its collection's own)")
    def coordinate_system(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}collection__coordinate_system__id": value})

    @kante.filter_field(description="Filter to the annotations drawn over this dataset (or over a lens of it), following their collection's derivation edge")
    def dataset(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}collection__coordinate_system__in": _systems_drawn_over_dataset(value)})

    def _require_frame(self, op: str) -> None:
        # Boxes only compare within one frame: every collection's bbox lives in its own
        # nearest-intrinsic space, so an unscoped range predicate would compare samples with
        # seconds and call the mismatches results. `None` as well as UNSET: this service's
        # filter mode lets an explicit null through.
        if self.collection in (strawberry.UNSET, None) and self.coordinate_system in (strawberry.UNSET, None):
            raise ValueError(f"`{op}` compares boxes within one frame: pass `collection` or `coordinateSystem` alongside it.")

    @kante.filter_field(
        description="Filter to annotations pinned to every one of these coordinates, e.g. [{name: 'c', value: 3}]. GIN-backed containment on the stored coordinate dict; an annotation that spans a coordinate does not match a pin on it"
    )
    def pinned_to(self, info: Info, value: list[CoordinateInput] | None, prefix: str) -> Q:
        if not value:
            return Q()
        return Q(**{f"{prefix}coordinates__contains": {coordinate.name: coordinate.value for coordinate in value}})

    @kante.filter_field(
        description=(
            "Filter to annotations whose bounding box overlaps this box (GiST-backed) -- every event and epoch between two instants is `{min: [t0], max: [t1]}`. Only meaningful "
            "within one frame: pass `collection` or `coordinateSystem` alongside. A box of lower rank is zero-filled on the missing coordinates"
        )
    )
    def intersects(self, info: Info, value: BoundingBoxInput | None, prefix: str) -> Q:
        if value is None:
            return Q()
        self._require_frame("intersects")
        return Q(**{f"{prefix}bbox_cube__overlaps": (value.min, value.max)})

    @kante.filter_field(description="Filter to annotations whose bounding box contains this point (GiST-backed): the epochs in force at one instant. Only meaningful within one frame: pass `collection` or `coordinateSystem` alongside")
    def contains_point(self, info: Info, value: list[float] | None, prefix: str) -> Q:
        if value is None:
            return Q()
        self._require_frame("containsPoint")
        return Q(**{f"{prefix}bbox_cube__contains_point": value})


# --- The data layer (vendored from mikro's core/filters.py) -------------------------------------
#
# Folders, files, file links, array datasets, their levels and their anchors. As with the
# coordinate filters above, every resolver states what an explicit `null` means -- no
# constraint -- because this service runs strawberry-django's deprecated filter mode.

from django.db.models import Count, Exists, OuterRef, QuerySet  # noqa: E402
from kanne_server import scalars as kanne_scalars  # noqa: E402
from core.logic import file_link as file_link_logic  # noqa: E402


@strawberry.input
class FolderChildrenFilter:
    show_children: bool | None = None
    search: str | None = None


@strawberry.input(
    description=(
        "One container a file link points at: `kind` says which sort of thing it is, `id` says which one. Structured rather than a bare ID because a link can name two "
        "different kinds of container and their ids are drawn from separate sequences -- dataset 3 and annotation collection 3 both exist, and an unqualified 3 could not choose"
    )
)
class FileLinkContainerRef:
    """One container a file link points at."""

    kind: enums.FileLinkContainerKind = strawberry.field(description="Which sort of container. It fixes which column the filter reads")
    id: strawberry.ID = strawberry.field(description="The container's ID, in the sequence its `kind` names")


#: The extensions each `FileMimeGroup` recognizes. Deliberately a filter-side table and not a
#: stored column: nothing to migrate, nothing to backfill, and no way for the label to drift
#: from the file it describes -- change this dict and every existing file reclassifies.
#:
#: Extension first, `contentType` only as a fallback, because an ABF or a vendor recording
#: uploads as `application/octet-stream`: a content-type rule would file every one of them
#: under OTHER, which is exactly the set worth being able to find.
_MIME_GROUP_EXTENSIONS: dict[str, tuple[str, ...]] = {
    enums.FileMimeGroup.RECORDING.value: ("abf", "nwb", "axgd", "axgx", "smr", "smrx", "wcp", "dat", "pxp", "ibw", "plx", "pl2", "nev", "ns1", "ns2", "ns3", "ns4", "ns5", "ns6", "nex", "nex5", "rhd", "rhs", "edf", "bdf", "mat", "h5", "hdf5", "kwik"),
    enums.FileMimeGroup.MODEL.value: ("hoc", "mod", "swc", "asc", "nml", "ses"),
    enums.FileMimeGroup.TABLE.value: ("csv", "tsv", "parquet", "feather", "arrow", "xlsx", "xls"),
    enums.FileMimeGroup.DOCUMENT.value: ("pdf", "txt", "md", "rst", "docx", "json", "yaml", "yml"),
    enums.FileMimeGroup.ARCHIVE.value: ("zip", "tar", "gz", "tgz", "bz2", "7z"),
}

#: The `contentType` prefix each group falls back to when the extension says nothing.
_MIME_GROUP_PREFIXES: dict[str, tuple[str, ...]] = {
    enums.FileMimeGroup.TABLE.value: ("text/csv", "text/tab-separated-values"),
    enums.FileMimeGroup.DOCUMENT.value: ("text/", "application/pdf"),
    enums.FileMimeGroup.ARCHIVE.value: ("application/zip", "application/x-tar", "application/gzip"),
}


def _mime_group_q(prefix: str, group: enums.FileMimeGroup) -> Q:
    """Files whose extension -- or failing that, whose content type -- puts them in this group.

    OTHER is the complement rather than a list of its own: anything no group claims. Built
    that way so the groups stay exhaustive by construction, and adding an extension to one of
    them removes it from OTHER in the same edit.
    """
    value = group.value if hasattr(group, "value") else group

    def claim(name: str) -> Q:
        query = Q()
        for extension in _MIME_GROUP_EXTENSIONS.get(name, ()):
            query |= Q(**{f"{prefix}name__iendswith": f".{extension}"})
        for content_type in _MIME_GROUP_PREFIXES.get(name, ()):
            query |= Q(**{f"{prefix}content_type__istartswith": content_type})
        return query

    if value != enums.FileMimeGroup.OTHER.value:
        return claim(value)

    claimed = Q()
    for name in _MIME_GROUP_EXTENSIONS:
        claimed |= claim(name)
    return ~claimed


def _file_ids_with_links(direction: str | None = None) -> QuerySet:
    """The ids of every file carrying a link, or only one in the given direction.

    A values-list for a `pk__in` test rather than a join to negate: see `not_derived`.
    """
    links = models.FileLink.objects.all()
    if direction is not None:
        links = links.filter(direction=direction)
    return links.values("file_id")


def _link_exclusion(prefix: str, ids: QuerySet, *, negate: bool) -> Q:
    """`pk__in` these ids, or its complement."""
    matches = Q(**{f"{prefix}id__in": ids})
    return ~matches if negate else matches


def _container_link_q(prefix: str, ref: "FileLinkContainerRef", direction: str | None = None) -> Q:
    """Files linked to the container this ref names, optionally in one direction only.

    The kind -> column mapping comes from `core.logic.file_link.column_for_kind`, which is
    composed from the same two tables the writers use -- so a filter and a mutation cannot
    disagree about which column a kind means.
    """
    column = file_link_logic.column_for_kind(ref.kind)
    lookup = {f"{prefix}links__{column}_id": ref.id}
    if direction is not None:
        lookup[f"{prefix}links__direction"] = direction
    return Q(**lookup)


@strawberry.input
class PinnedFilterMixin:
    @kante.filter_field(description="Filter by whether the current user has pinned the item")
    def pinned(self, info: Info, value: bool | None, prefix: str) -> Q:
        if value is None:
            return Q()
        if value:
            return Q(**{f"{prefix}pinned_by": info.context.request.user})
        return ~Q(**{f"{prefix}pinned_by": info.context.request.user})


@strawberry.input
class TagsFilterMixin:
    @kante.filter_field(description="Filter by tag names")
    def tags(self, info: Info, queryset: QuerySet, value: list[str] | None, prefix: str) -> tuple[QuerySet, Q]:
        if value is None:
            return queryset, Q()
        # Multiple matching tags would duplicate rows on the join.
        return queryset.distinct(), Q(**{f"{prefix}tags__name__in": value})


@strawberry.input
class CreatedThroughFilterMixin:
    @kante.filter_field(description="Filter by the rekuest task id the item was created through")
    def created_through_task(self, info: Info, value: str | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}created_through__task_id": value})

    @kante.filter_field(description="Filter by the database ID of the task the item was created through (the `createdThrough { id }` field)")
    def created_through(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        """Match items created through the task with this database ID."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}created_through_id": value})

    @kante.filter_field(description="Filter by the sub of the user that assigned the creating task")
    def assigned_by(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        # Hits the denormalized FK on the model itself; the join through the
        # (very large) task table would scale with the user's task count.
        return Q(**{f"{prefix}created_through_by__sub": value})

    @kante.filter_field(description="Filter by the database ID of the user that assigned the creating task (the `createdThroughBy { id }` field)")
    def created_through_by(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        """Match items whose creating task was assigned by the user with this database ID."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}created_through_by_id": value})


@kante.filter_type(models.Folder)
class FolderFilter(IdsFilterMixin, SearchFilterMixin, OwnedFilterMixin, PinnedFilterMixin, TagsFilterMixin, CreatedThroughFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]
    is_default: Optional[bool]

    @kante.filter_field(description="Filter for folders with (true) or without (false) a parent")
    def parentless(self, info: Info, value: bool | None, prefix: str) -> Q:
        if value is None:
            return Q()
        if value:
            return Q(**{f"{prefix}parent": None})
        return ~Q(**{f"{prefix}parent": None})

    @kante.filter_field(description="Filter by the parent folder (list the children of a folder)")
    def parent(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        """Match folders that are direct children of the folder with this ID."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}parent_id": value})


@kante.filter_type(models.File)
class FileFilter(IdsFilterMixin, NameSearchFilterMixin, OwnedFilterMixin, CreatedThroughFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    size: Optional[FilterLookup[int]]
    content_type: Optional[FilterLookup[str]]

    @kante.filter_field(description="Filter by the folder this file belongs to")
    def folder(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}folder_id": value})

    @kante.filter_field(description="Filter by a list of folder IDs")
    def folders(self, info: Info, value: list[strawberry.ID] | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}folder_id__in": value})

    @kante.filter_field(
        description=(
            "Filter for files nothing was exported into: the raw sources a converter read, as opposed to the files written out of data already here. Reads the file's links, "
            "which replaced the `origins` M2M -- that column was never written by any resolver, so this filter used to answer `true` for every file in the database"
        )
    )
    def not_derived(self, info: Info, value: bool | None, prefix: str) -> Q:
        """Match files nothing here was exported into."""
        if value is None:
            return Q()
        # A subquery, not `~Q(links__direction=...)`. Negating a to-many lookup is correct on
        # its own, but the moment a second `links__` lookup lands in the same query -- say
        # `{notDerived: true, sourceOf: {...}}` -- Django builds a second join and the
        # negation stops meaning what it reads as. `_derived_dataset_ids` already draws this
        # line on the dataset side; this is the same shape.
        return _link_exclusion(prefix, _file_ids_with_links(direction=enums.FileLinkDirectionChoices.RENDITION.value), negate=value)

    @kante.filter_field(
        description=(
            "Filter for files no data references at all -- the uploads nothing was ever converted from and nothing was ever written into. The orphans, in other words: what a "
            "cleanup view wants. `notDerived` is the weaker question (nothing was *exported* into it), so every unlinked file is also notDerived, and not the reverse"
        )
    )
    def unlinked(self, info: Info, value: bool | None, prefix: str) -> Q:
        """Match files with no links in either direction."""
        if value is None:
            return Q()
        return _link_exclusion(prefix, _file_ids_with_links(), negate=value)

    @kante.filter_field(
        description=(
            "Filter to the files this container was produced from -- the ABF a converter read to write its arrays. The file-side mirror of `ArrayDatasetFilter.sourceFile`, and the "
            "reason this takes a `{kind, id}` rather than a bare ID: dataset 3 and annotation collection 3 both exist, so an unqualified id could not say which was meant"
        )
    )
    def source_of(self, info: Info, queryset: QuerySet, value: "FileLinkContainerRef | None", prefix: str) -> tuple[QuerySet, Q]:
        """Match files this container was produced from."""
        if value is None:
            return queryset, Q()
        return queryset.distinct(), _container_link_q(prefix, value, direction=enums.FileLinkDirectionChoices.SOURCE.value)

    @kante.filter_field(description="Filter to the files written out of this container -- the NWB file a dataset was exported to. The opposite direction from `sourceOf`")
    def exported_from(self, info: Info, queryset: QuerySet, value: "FileLinkContainerRef | None", prefix: str) -> tuple[QuerySet, Q]:
        """Match files written out of this container."""
        if value is None:
            return queryset, Q()
        return queryset.distinct(), _container_link_q(prefix, value, direction=enums.FileLinkDirectionChoices.RENDITION.value)

    @kante.filter_field(description="Filter to the files linked to this container in *either* direction: read into it or written out of it. Use `sourceOf` or `exportedFrom` when the direction matters")
    def linked_to(self, info: Info, queryset: QuerySet, value: "FileLinkContainerRef | None", prefix: str) -> tuple[QuerySet, Q]:
        """Match files linked to this container in either direction."""
        if value is None:
            return queryset, Q()
        return queryset.distinct(), _container_link_q(prefix, value)

    @kante.filter_field(description="Filter to files linked under this series of a multi-series file -- 'series-3' of an NWB file. Matches on any link, in either direction")
    def series_identifier(self, info: Info, queryset: QuerySet, value: str | None, prefix: str) -> tuple[QuerySet, Q]:
        """Match files with a link naming this series."""
        if value is None:
            return queryset, Q()
        return queryset.distinct(), Q(**{f"{prefix}links__series_identifier": value})

    @kante.filter_field(description="Filter by whether the file's bytes ever arrived: false finds the `File` rows whose upload was granted and never completed, which carry no store at all")
    def has_store(self, info: Info, value: bool | None, prefix: str) -> Q:
        """Match files that do or do not have a store."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}store__isnull": not value})

    @kante.filter_field(
        description=(
            "Filter by whether the upload completed. **Implies a store**: a file with no store at all is `hasStore: false`, not `populated: false`, so the two are not "
            "complementary and combining `hasStore: false` with `populated: false` matches nothing"
        )
    )
    def populated(self, info: Info, value: bool | None, prefix: str) -> Q:
        """Match files whose store is (or is not) populated. Storeless files match neither."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}store__populated": value})

    @kante.filter_field(
        description=(
            "Filter by file extension, case-insensitively and with the leading dot optional: `abf`, `.abf` and `ABF` are the same request. "
            "A normalizing convenience over `name: {iEndsWith: \".abf\"}`, which is still there if you want the raw lookup"
        )
    )
    def extension(self, info: Info, value: str | None, prefix: str) -> Q:
        """Match files whose name ends in this extension."""
        if value is None:
            return Q()
        suffix = value.strip().lstrip(".")
        if not suffix:
            return Q()
        return Q(**{f"{prefix}name__iendswith": f".{suffix}"})

    @kante.filter_field(
        description=(
            "Filter to the files holding one sort of thing. Derived from the extension at query time and stored nowhere -- see `FileMimeGroup`, which explains why this reads "
            "the name rather than `contentType`. A curated list, so treat it as a picker convenience and filter on `name` or `contentType` when you need an exact answer"
        )
    )
    def mime_group(self, info: Info, value: enums.FileMimeGroup | None, prefix: str) -> Q:
        """Match files whose extension puts them in this group."""
        if value is None:
            return Q()
        return _mime_group_q(prefix, value)


@kante.filter_type(models.FileLink)
class FileLinkFilter(IdsFilterMixin, OwnedFilterMixin, CreatedThroughFilterMixin):
    """Filters for the links between a file and the data it encodes."""

    id: auto
    direction: Optional[enums.FileLinkDirection]
    series_identifier: Optional[FilterLookup[str]]
    value_relation: Optional[enums.ValueRelation]

    @kante.filter_field(description="Filter by the file side of the link")
    def file(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        """Match links whose file side is this file."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}file_id": value})


@kante.filter_type(models.ArrayDataset)
class ArrayDatasetFilter(IdsFilterMixin, SemanticNameSearchFilterMixin, OwnedFilterMixin, CreatedThroughFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]

    # Filing, not placement. `dataset` below and `placeableIn` ask where the data *is*;
    # these two ask where a user *keeps* it.
    @kante.filter_field(description="Filter by the folder this dataset is filed in")
    def folder(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        """Match array datasets filed in the folder with this ID."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}folder_id": value})

    @kante.filter_field(description="Filter by a list of folder IDs")
    def folders(self, info: Info, value: list[strawberry.ID] | None, prefix: str) -> Q:
        """Match array datasets filed in any of the given folders."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}folder_id__in": value})

    # What a dataset is, is materialized onto `stored_spec` at creation (see ArrayDataset.spec and
    # core.logic.graph.create_pixel_axes), so this reads the column rather than re-deriving the
    # spec in SQL. A stored list holds exactly one spatial member plus a modifier per acquisition
    # axis, so JSONB containment gives the all-of semantics directly: two spatial members can
    # never co-occur in a stored list, so `[IMAGE, VOLUME]` matches nothing, and a headless
    # dataset (empty list) is excluded by any non-empty request without a special guard.

    @kante.filter_field(
        description="Filter to datasets satisfying every one of these specs, e.g. [TIMESERIES, MULTICHANNEL] for multi-channel recordings. Materialized from the axes of the intrinsic coordinate system at creation. A dataset carries one spatial spec (by how many SPACE axes it has) plus a modifier per acquisition axis present, so two spatial specs together match nothing"
    )
    def spec(self, info: Info, queryset: QuerySet, value: list[enums.ArrayDatasetSpec] | None, prefix: str) -> tuple[QuerySet, Q]:
        if value is None:
            return queryset, Q()
        if not value:
            return queryset, Q()
        return queryset, Q(**{f"{prefix}stored_spec__contains": [spec.value for spec in value]})

    @kante.filter_field(description="Filter to datasets whose intrinsic coordinate system carries every one of these axis types, e.g. [TIME, CHANNEL]. The raw form of `spec`, for the types no spec names: COORDINATE, DISPLACEMENT, INDEX")
    def has_axis_types(self, info: Info, queryset: QuerySet, value: list[enums.AxisType] | None, prefix: str) -> tuple[QuerySet, Q]:
        if value is None:
            return queryset, Q()
        types = {axis_type.value for axis_type in value}
        if not types:
            return queryset, Q()
        queryset, alias = _annotate_axis_type_count(queryset, prefix, types)
        return queryset, Q(**{alias: len(types)})

    @kante.filter_field(description="Filter by whether the dataset carries a resolution pyramid: true for the multiscale ones, false for those with a single level")
    def multiscale(self, info: Info, queryset: QuerySet, value: bool | None, prefix: str) -> tuple[QuerySet, Q]:
        if value is None:
            return queryset, Q()
        # The same derivation as the `multiscale` property -- more than one level -- as a query.
        alias = f"_{prefix.replace('__', '_')}level_count"
        queryset = _annotate_once(queryset, alias, Count(f"{prefix}data_arrays", distinct=True))
        return queryset, Q(**{f"{alias}__gt": 1}) if value else Q(**{f"{alias}__lte": 1})

    @kante.filter_field(
        description="Filter by whether the dataset has an edge into a space with real units. False finds the data that is still only samples, with no sampling law or time lookup recorded -- the datasets nothing has timed yet"
    )
    def has_physical_space(self, info: Info, queryset: QuerySet, value: bool | None, prefix: str) -> tuple[QuerySet, Q]:
        if value is None:
            return queryset, Q()
        # A physical space is not a thing a dataset owns (RFC-9): it is an edge out of the
        # dataset's space into one whose axes carry units. So "has a physical space" is a
        # question about the graph, and it is asked as one -- an edge whose far side has a
        # united axis.
        physical_space = models.Transformation.objects.filter(
            input_id=OuterRef(f"{prefix}coordinate_system_id"),
            parent__isnull=True,
            output__axes__unit__isnull=False,
        ).exclude(kind=enums.TransformKindChoices.UNMAPPABLE.value)
        queryset = _annotate_once(queryset, "_has_physical_space", Exists(physical_space))
        return queryset, Q(_has_physical_space=value)

    @kante.filter_field(
        description=(
            "Filter to datasets placeable into a coordinate system: those with a lens whose space reaches it across steps that compose into one affine map, walking the transformation "
            "edges. A route crossing a FIELD is not one -- it relates the two spaces by the values of an array -- so a spike train or a variable-step run is not offered here, though "
            "`inView` reports it. Takes a *space*: pass an experiment's `world.id` to ask it of an experiment"
        )
    )
    def placeable_in(self, info: Info, value: "PlaceableFilter | None", prefix: str) -> Q:
        if value is None:
            return Q()
        if value is None:
            return Q()
        space = _placeable_destination(info, value.space)
        if space is None:
            return Q(pk__in=[])
        return Q(**{f"{prefix}id__in": graph_logic.placeable_lens_dataset_ids(space, derived_only=bool(value.derived_only), require_affine=value.require_affine is not False)})

    @kante.filter_field(description="Filter to the datasets living in this coordinate system. Usually one; several when datasets genuinely share a frame")
    def coordinate_system(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q() if value is None else Q(**{f"{prefix}coordinate_system_id": value})

    @kante.filter_field(description="Filter by the unit of the dataset's VALUES, as stated by its dataset-wide `ValueUnit` anchor, e.g. 'mV'. Compared after normalization, so 'mV' and 'millivolt' are the same request")
    def value_unit(self, info: Info, value: str | None, prefix: str) -> Q:
        if value is None:
            return Q()
        if value is None:
            return Q()
        spellings = {value, kanne_scalars.parse_unit(value)}
        try:
            spellings.add(str(kanne_scalars.get_registry().Unit(kanne_scalars.normalize_compact_units(value))))
        except Exception:  # noqa: BLE001 - an unknown unit simply matches nothing beyond its own spelling
            pass
        anchored = models.ValueUnit.objects.filter(anchor__coordinates={}, unit__in=spellings).values("anchor__dataset_id")
        return Q(**{f"{prefix}id__in": anchored})

    @kante.filter_field(
        description="Filter to the datasets computed from this one -- the filtered, decimated and sorted datasets that named a space of it as their parent. Every child, not just the ones it places: a fusion that named it second is listed, and so is a child whose derivation is UNMAPPABLE, since it still came from here"
    )
    def derived_from(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}id__in": _derived_dataset_ids(source_id=value)})

    @kante.filter_field(description="Filter for datasets that were acquired rather than computed: true for the roots, those with no derivation edge into another dataset's space")
    def not_derived(self, info: Info, value: bool | None, prefix: str) -> Q:
        if value is None:
            return Q()
        derived = Q(**{f"{prefix}id__in": _derived_dataset_ids()})
        return ~derived if value else derived

    @kante.filter_field(
        description=(
            "Filter to the datasets converted from this file -- every series of it, unless `sourceSeriesIdentifier` narrows that. A file link, not a derivation: this asks which "
            "bytes the arrays were read out of, where `derivedFrom` asks which data they were computed from. A dataset can honestly answer both"
        )
    )
    def source_file(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        """Match datasets converted from this file."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}file_links__file_id": value, f"{prefix}file_links__direction": enums.FileLinkDirectionChoices.SOURCE.value})

    @kante.filter_field(description="Filter to the datasets converted from one series of a file. Pair it with `sourceFile`; alone it matches that series identifier in any file")
    def source_series_identifier(self, info: Info, value: str | None, prefix: str) -> Q:
        """Match datasets converted from this series of a file."""
        if value is None:
            return Q()
        return Q(**{f"{prefix}file_links__series_identifier": value, f"{prefix}file_links__direction": enums.FileLinkDirectionChoices.SOURCE.value})


@kante.filter_type(models.DataArray)
class DataArrayFilter(IdsFilterMixin):
    id: auto
    level: Optional[FilterLookup[int]]

    @kante.filter_field(description="Filter by the dataset this array belongs to")
    def dataset(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}dataset_id": value})


@kante.filter_type(models.CoordinateAnchor)
class CoordinateAnchorFilter(IdsFilterMixin):
    id: auto
    dataset: Optional[FilterLookup[strawberry.ID]]
    table: Optional[FilterLookup[strawberry.ID]]
    sparse: Optional[FilterLookup[strawberry.ID]]


@kante.filter_type(models.RigState)
class RigStateFilter(IdsFilterMixin):
    id: auto

    @kante.filter_field(description="Filter by the coordinate anchor")
    def anchor(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}anchor_id": value})


@kante.filter_type(models.AcquisitionMetadata)
class AcquisitionMetadataFilter(IdsFilterMixin):
    id: auto

    @kante.filter_field(description="Filter by the coordinate anchor")
    def anchor(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}anchor_id": value})


@kante.filter_type(models.ValueHistogram)
class ValueHistogramFilter(IdsFilterMixin):
    id: auto
    min: Optional[FilterLookup[float]]
    max: Optional[FilterLookup[float]]

    @kante.filter_field(description="Filter by the coordinate anchor")
    def anchor(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}anchor_id": value})


@kante.filter_type(models.ChannelLabel)
class ChannelLabelFilter(IdsFilterMixin):
    id: auto
    label: Optional[FilterLookup[str]]

    @kante.filter_field(description="Filter by the coordinate anchor")
    def anchor(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}anchor_id": value})


@kante.filter_type(models.ValueUnit)
class ValueUnitFilter(IdsFilterMixin):
    id: auto
    unit: Optional[FilterLookup[str]]

    @kante.filter_field(description="Filter by the coordinate anchor")
    def anchor(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        if value is None:
            return Q()
        return Q(**{f"{prefix}anchor_id": value})


def _annotate_once(queryset: QuerySet, alias: str, expression) -> QuerySet:
    """Add an annotation unless the alias is already taken by an identical one.

    An alias is global to the queryset while a filter is not: `AND`/`OR` recurse with
    the same prefix, so two branches may annotate one queryset. Django keeps the first
    annotation of a repeated alias and silently drops the second, so callers must name
    an alias for the *expression* it stands for -- then a repeat is the same question
    asked twice, and skipping it is right. Never call this with an alias whose
    expression can vary.
    """
    if alias in queryset.query.annotations:
        return queryset
    return queryset.annotate(**{alias: expression})


def _derived_dataset_ids(source_id: strawberry.ID | None = None):
    """The ids of every dataset that was derived, or only those derived from one source.

    `graph_logic.derivation_edges` expressed as a query, and it has to agree with it.
    An edge is a derivation when it leaves a space a dataset *lives in* (so
    `input__datasets` is what names the child, and a mesh or table collection's edge is
    excluded -- it does not set out from one) and lands in a space some *other* dataset's
    data lives in. The Coalesce is `graph_logic.system_dataset` in SQL: whichever resident
    the output space has is the dataset it came from.

    The self-exclusion is the load-bearing part. A level edge and a lens edge land in the
    dataset's own grid, which would otherwise make a dataset its own parent.
    `derivation_edges` drops them with `source.pk != dataset.pk`; the same test here
    compares two columns of the one row, so no subquery correlation is needed. A
    physical-space edge needs no exclusion any more -- it lands in a space *nothing* lives in,
    so the Coalesce is null and the `_source_dataset__isnull` filter drops it.

    Kind-blind, exactly as `derivation_edges` is: an UNMAPPABLE derivation is still a
    derivation, and it is the one machine-readable answer to why a dataset cannot be
    placed. Filtering it here would restore the silence that kind was invented to break.
    """
    source_dataset = Coalesce(
        "output__datasets__id",
        "output__lenses__dataset_id",
        "output__data_arrays__dataset_id",
    )
    edges = (
        models.Transformation.objects.filter(parent__isnull=True, input__datasets__isnull=False)
        .annotate(_source_dataset=source_dataset)
        .filter(_source_dataset__isnull=False)
        .exclude(_source_dataset=F("input__datasets__id"))
    )
    if source_id is not None:
        edges = edges.filter(_source_dataset=source_id)
    return edges.values_list("input__datasets__id", flat=True)


def _annotate_axis_type_count(queryset: QuerySet, prefix: str, types: set[str]) -> tuple[QuerySet, str]:
    """Annotate how many of `types` a dataset's intrinsic axes match, and return the alias to compare against.

    Counts the distinct axis *types* matched, which is how an all-of test is written:
    it equals `len(types)` exactly when every requested type is present.

    The alias names the expression, because an alias is global to the queryset while
    a filter is not: `AND`/`OR` recurse with the same prefix, so two branches can
    annotate one queryset. Two branches asking the same question then share the one
    annotation (identical expression, so the guard skips the second), and two asking
    different questions get different aliases instead of one silently shadowing the
    other. The Count is distinct because another filter may join in rows that
    multiply these out.
    """
    axes = f"{prefix}coordinate_system__axes"
    alias = f"_{prefix.replace('__', '_')}matched_axis_types__{'_'.join(sorted(types))}"
    expression = Count(f"{axes}__type", filter=Q(**{f"{axes}__type__in": list(types)}), distinct=True)
    return _annotate_once(queryset, alias, expression), alias


# --- Sparse and table datasets (vendored from mikro's core/filters.py) ---------------------------
# elektro: every resolver states what `null` means (USE_DEPRECATED_FILTERS lets an explicit null
# reach it), and `placeableIn` takes a PlaceableFilter like every other `placeableIn` here.


@kante.filter_type(models.SparseDataset)
class SparseDatasetFilter(IdsFilterMixin, SemanticNameSearchFilterMixin, OwnedFilterMixin, CreatedThroughFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]

    @kante.filter_field(description="Filter by the folder this sparse dataset is filed in")
    def folder(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        """Match sparse datasets filed in the folder with this ID."""
        return Q() if value is None else Q(**{f"{prefix}folder_id": value})

    @kante.filter_field(description="Filter to datasets holding a layout indexed on this axis -- the ones that can answer about it in one contiguous read rather than by scanning")
    def indexes_axis(self, info: Info, value: str | None, prefix: str) -> Q:
        """Match sparse datasets whose stored layouts index an axis of this name."""
        return Q() if value is None else Q(**{f"{prefix}coordinate_system__axes__name": value})

    @kante.filter_field(description="Filter by whether the matrix has a TIME axis -- a spike raster, placed on a clock by a sampling law -- or only enumerations. elektro's own")
    def timed(self, info: Info, value: bool | None, prefix: str) -> Q:
        """Match sparse datasets with (true) or without (false) a TIME axis."""
        if value is None:
            return Q()
        # A subquery rather than a join across `axes`, which would repeat a row per TIME axis.
        timed = models.Axis.objects.filter(type=enums.AxisTypeChoices.TIME.value).values("coordinate_system_id")
        has_time = Q(**{f"{prefix}coordinate_system_id__in": timed})
        return has_time if value else ~has_time

    @kante.filter_field(description="Filter to sparse datasets placeable into a coordinate system across steps that compose into one affine map -- a raster's sampling law onto a clock is one")
    def placeable_in(self, info: Info, value: PlaceableFilter | None, prefix: str) -> Q:
        if value is None:
            return Q()
        space = _placeable_destination(info, value.space)
        if space is None:
            return Q(pk__in=[])
        placeable = graph_logic.placeable_system_ids_in(space, derived_only=bool(value.derived_only), require_affine=value.require_affine is not False)
        return Q(**{f"{prefix}coordinate_system_id__in": placeable})


@kante.filter_type(models.TableDataset)
class TableDatasetFilter(IdsFilterMixin, SemanticNameSearchFilterMixin, OwnedFilterMixin, CreatedThroughFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]

    @kante.filter_field(description="Filter by the folder this table dataset is filed in")
    def folder(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        """Match table datasets filed in the folder with this ID."""
        return Q() if value is None else Q(**{f"{prefix}folder_id": value})

    @kante.filter_field(description="Filter by a list of folder IDs")
    def folders(self, info: Info, value: list[strawberry.ID] | None, prefix: str) -> Q:
        """Match table datasets filed in any of the given folders."""
        return Q() if value is None else Q(**{f"{prefix}folder_id__in": value})

    @kante.filter_field(description="Filter by the dataset the table was computed from, following its derivation edge")
    def dataset(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}coordinate_system__in": _systems_derived_from_dataset(value)})

    @kante.filter_field(description="Filter to tables that declare a column of this role, e.g. LABEL")
    def has_column_role(self, info: Info, value: enums.ColumnRole | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}columns__role": value.value})

    @kante.filter_field(description="Filter by whether the table has a TIME coordinate column -- an event or epoch list, placeable on a clock -- or none (a unit table, a measurement table). elektro's own")
    def timed(self, info: Info, value: bool | None, prefix: str) -> Q:
        if value is None:
            return Q()
        # A subquery rather than a join across `axes`, which would repeat a row per TIME axis.
        timed = models.Axis.objects.filter(type=enums.AxisTypeChoices.TIME.value).values("coordinate_system_id")
        has_time = Q(**{f"{prefix}coordinate_system_id__in": timed})
        return has_time if value else ~has_time

    @kante.filter_field(description="Filter to table datasets placeable into this coordinate system: those whose own coordinate system reaches it across steps that compose into one affine map, walking the transformation edges")
    def placeable_in(self, info: Info, value: PlaceableFilter | None, prefix: str) -> Q:
        if value is None:
            return Q()
        space = _placeable_destination(info, value.space)
        if space is None:
            return Q(pk__in=[])
        return Q(**{f"{prefix}id__in": graph_logic.placeable_table_dataset_ids(space, require_affine=value.require_affine is not False)})


def _systems_derived_from_dataset(dataset_id: strawberry.ID):
    """The collection systems whose derivation edge lands in this dataset.

    A subquery rather than a join: `Transformation.input`/`output` are declared
    `related_name="+"`, so there is no reverse accessor to filter across, and a collection
    keeps no dataset column of its own -- the edge is the only place that fact lives.
    """
    return models.Transformation.objects.filter(
        parent__isnull=True,
        input__isnull=False,
    ).filter(
        Q(output__datasets__id=dataset_id) | Q(output__lenses__dataset_id=dataset_id) | Q(output__data_arrays__dataset_id=dataset_id)
    ).values("input_id")


# --- Experiment layers (elektro's counterpart of mikro's LayerFilter) -----------------------------


@kante.filter_type(models.ExperimentLayer)
class ExperimentLayerFilter(IdsFilterMixin):
    """The layers of an experiment. mikro's LayerFilter, for time series."""

    id: auto
    name: Optional[FilterLookup[str]]

    @kante.filter_field(description="Filter to the layers of this experiment")
    def experiment(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}experiment_id": value})

    @kante.filter_field(description="Filter by how the layer draws: TRACE, SPIKES, EVENTS or ANNOTATION")
    def kind(self, info: Info, value: enums.ExperimentLayerKind | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}kind": value.value})

    @kante.filter_field(description="Filter by whether the layer is shown")
    def visible(self, info: Info, value: bool | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}visible": value})

    @kante.filter_field(description="Filter to the layers drawing this array dataset, through any of its lenses")
    def dataset(self, info: Info, value: strawberry.ID | None, prefix: str) -> Q:
        return Q() if value is None else Q(**{f"{prefix}lens__dataset_id": value})
