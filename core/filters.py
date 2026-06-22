import datetime
import strawberry
from core import models, enums, scalars
from strawberry import auto
from typing import ClassVar, Optional
from strawberry_django.filters import FilterLookup
import strawberry_django
import kante
from django.db.models import Q, F, Value, FloatField
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
            .annotate(
                _relevance=Greatest("_similarity", "_rank", output_field=FloatField())
            )
            .order_by("-_relevance")
        )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@strawberry_django.filter_type(models.Dataset)
class DatasetFilter:
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.File)
class FileFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.Experiment)
class ExperimentFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]
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


@strawberry_django.filter_type(models.ExperimentRecordingView)
class ExperimentRecordingViewFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["label"]
    id: auto
    label: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.ExperimentStimulusView)
class ExperimentStimulusViewFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["label"]
    id: auto
    label: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.ModelCollection)
class ModelCollectionFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.ModelWorkspace)
class ModelWorkspaceFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.WorkspaceMapping)
class WorkspaceMappingFilter(IDFilterMixin):
    id: auto


@strawberry_django.filter_type(models.Simulation)
class SimulationFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]

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


@strawberry_django.filter_type(models.Recording)
class RecordingFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    SEARCH_FIELDS = ["label"]
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.Recording)
class StimulusFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    SEARCH_FIELDS = ["label"]
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.NeuronModel)
class NeuronModelFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    name: Optional[FilterLookup[str]]
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


@strawberry_django.filter_type(models.Instrument)
class InstrumentFilter:
    id: auto
    name: auto


@strawberry_django.filter_type(models.ViewCollection)
class ViewCollectionFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["name"]
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.View)
class ViewFilter:
    is_global: auto


@strawberry_django.filter_type(models.TimelineView)
class ContinousScanViewFilter(ViewFilter):
    start_time: auto
    end_time: auto


@strawberry_django.filter_type(models.Trace)
class TraceFilter(SearchFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    name: Optional[FilterLookup[str]]
    ids: list[strawberry.ID] | None
    dataset: DatasetFilter | None
    not_derived: bool | None = None

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_not_derived(self, queryset, info):
        if self.not_derived is None:
            return queryset
        return queryset.filter(derived_views=None)


@strawberry_django.filter_type(models.ROI)
class ROIFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    SEARCH_FIELDS = ["label"]
    id: auto
    kind: auto
    trace: strawberry.ID | None = None

    def filter_image(self, queryset, info):
        if self.trace is None:
            return queryset
        return queryset.filter(trace_id=self.trace)


@strawberry_django.filter_type(models.Block)
class BlockFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    label: Optional[FilterLookup[str]]
    trace: strawberry.ID | None = None
    groups: list[strawberry.ID] | None = None

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

    def filter_trace(self, queryset, info):
        if self.trace is None:
            return queryset
        return queryset.filter(trace_id=self.trace)

    def filter_groups(self, queryset, info):
        if self.groups is None:
            return queryset
        return queryset.filter(groups__id__in=self.groups).distinct()


@strawberry_django.filter_type(models.BlockSegment)
class BlockSegmentFilter(IDFilterMixin, SearchFilterMixin):
    # BlockSegment has no free-text field; search is a graceful no-op.
    SEARCH_FIELDS = []
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.BlockGroup)
class BlockGroupFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["label"]
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.AnalogSignal)
class AnalogSignalFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    label: Optional[FilterLookup[str]]
    session: strawberry.ID | None = None

    def filter_session(self, queryset, info):
        if self.session is None:
            return queryset
        return queryset.filter(session_id=self.session)


@strawberry_django.filter_type(models.IrregularlySampledSignal)
class IrregularlySampledSignalFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["name"]
    id: auto
    label: Optional[FilterLookup[str]]
    session: strawberry.ID | None = None

    def filter_session(self, queryset, info):
        if self.session is None:
            return queryset
        return queryset.filter(session_id=self.session)


@strawberry_django.filter_type(models.SpikeTrain)
class SpikeTrainFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["name"]
    id: auto
    label: Optional[FilterLookup[str]]
    session: strawberry.ID | None = None

    def filter_session(self, queryset, info):
        if self.session is None:
            return queryset
        return queryset.filter(session_id=self.session)


@strawberry_django.filter_type(models.AnalogSignalChannel)
class AnalogSignalChannelFilter(IDFilterMixin, SearchFilterMixin):
    SEARCH_FIELDS = ["name", "description"]
    id: auto
    label: Optional[FilterLookup[str]]
    session: strawberry.ID | None = None

    def filter_session(self, queryset, info):
        if self.session is None:
            return queryset
        return queryset.filter(session_id=self.session)


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


@strawberry_django.order_type(models.Trace)
class TraceOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.Dataset)
class DatasetOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.File)
class FileOrder:
    id: auto
    created_at: auto


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


@strawberry_django.order_type(models.Simulation)
class SimulationOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.Experiment)
class ExperimentOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.ExperimentRecordingView)
class ExperimentRecordingViewOrder:
    id: auto


@strawberry_django.order_type(models.ExperimentStimulusView)
class ExperimentStimulusViewOrder:
    id: auto


@strawberry_django.order_type(models.Recording)
class RecordingOrder:
    id: auto


@strawberry_django.order_type(models.Block)
class BlockOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.BlockSegment)
class BlockSegmentOrder:
    id: auto


@strawberry_django.order_type(models.BlockGroup)
class BlockGroupOrder:
    id: auto


@strawberry_django.order_type(models.Stimulus)
class StimulusOrder:
    id: auto


@strawberry_django.order_type(models.NeuronModel)
class NeuronModelOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.ROI)
class ROIOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.ViewCollection)
class ViewCollectionOrder:
    id: auto


@strawberry_django.order_type(models.AnalogSignal)
class AnalogSignalOrder:
    id: auto


@strawberry_django.order_type(models.AnalogSignalChannel)
class AnalogSignalChannelOrder:
    id: auto


@strawberry_django.order_type(models.SpikeTrain)
class SpikeTrainOrder:
    id: auto


@strawberry_django.order_type(models.IrregularlySampledSignal)
class IrregularlySampledSignalOrder:
    id: auto


@strawberry_django.order_type(models.ModEnvironment)
class ModEnvironmentOrder:
    id: auto
    created_at: auto


@strawberry_django.order_type(models.Mechanism)
class MechanismOrder:
    id: auto
    created_at: auto
