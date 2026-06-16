import datetime
import strawberry
from core import models, enums, scalars
from strawberry import auto
from typing import Optional
from strawberry_django.filters import FilterLookup
import strawberry_django
import kante


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
class SearchFilterMixin:
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


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
    id: auto
    label: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)


@strawberry_django.filter_type(models.ExperimentStimulusView)
class ExperimentStimulusViewFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    label: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)


@strawberry_django.filter_type(models.ModelCollection)
class ModelCollectionFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]


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
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.Recording)
class StimulusFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter_type(models.NeuronModel)
class NeuronModelFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
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
    id: auto
    name: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry_django.filter_type(models.View)
class ViewFilter:
    is_global: auto


@strawberry_django.filter_type(models.TimelineView)
class ContinousScanViewFilter(ViewFilter):
    start_time: auto
    end_time: auto


@strawberry_django.filter_type(models.Trace)
class TraceFilter:
    name: Optional[FilterLookup[str]]
    ids: list[strawberry.ID] | None
    dataset: DatasetFilter | None
    not_derived: bool | None = None
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)

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
    id: auto
    kind: auto
    trace: strawberry.ID | None = None
    search: str | None

    def filter_image(self, queryset, info):
        if self.trace is None:
            return queryset
        return queryset.filter(trace_id=self.trace)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(image__name__contains=self.search)


@strawberry_django.filter_type(models.Block)
class BlockFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
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
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry_django.filter_type(models.BlockGroup)
class BlockGroupFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry_django.filter_type(models.AnalogSignal)
class AnalogSignalFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    label: Optional[FilterLookup[str]]
    session: strawberry.ID | None = None
    search: str | None

    def filter_session(self, queryset, info):
        if self.session is None:
            return queryset
        return queryset.filter(session_id=self.session)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)


@strawberry_django.filter_type(models.IrregularlySampledSignal)
class IrregularlySampledSignalFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    label: Optional[FilterLookup[str]]
    session: strawberry.ID | None = None
    search: str | None

    def filter_session(self, queryset, info):
        if self.session is None:
            return queryset
        return queryset.filter(session_id=self.session)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)


@strawberry_django.filter_type(models.SpikeTrain)
class SpikeTrainFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    label: Optional[FilterLookup[str]]
    session: strawberry.ID | None = None
    search: str | None

    def filter_session(self, queryset, info):
        if self.session is None:
            return queryset
        return queryset.filter(session_id=self.session)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)


@strawberry_django.filter_type(models.AnalogSignalChannel)
class AnalogSignalChannelFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    label: Optional[FilterLookup[str]]
    session: strawberry.ID | None = None
    search: str | None

    def filter_session(self, queryset, info):
        if self.session is None:
            return queryset
        return queryset.filter(session_id=self.session)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)


@strawberry_django.filter_type(models.Mechanism)
class MechanismFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry_django.filter_type(models.ModEnvironment)
class ModEnvironmentFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


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
