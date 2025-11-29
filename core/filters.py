import datetime
import strawberry
from core import models, enums, scalars
from strawberry import auto
from typing import Optional
from strawberry_django.filters import FilterLookup
import strawberry_django

print("Test")


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


@strawberry_django.order(models.Trace)
class TraceOrder:
    created_at: auto


@strawberry_django.filter(models.Dataset)
class DatasetFilter:
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter(models.File)
class FileFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter(models.Experiment)
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


@strawberry_django.filter(models.ModelCollection)
class ModelCollectionFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter(models.Simulation)
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


@strawberry_django.order(models.Simulation)
class SimulationOrder:
    created_at: auto


@strawberry_django.order(
    models.Experiment,
)
class ExperimentOrder:
    created_at: auto


@strawberry_django.filter(models.Recording)
class RecordingFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.order(models.Recording)
class RecordingOrder:
    created_at: auto


@strawberry_django.filter(models.Recording)
class StimulusFilter(IDFilterMixin, SearchFilterMixin, CreatedAtFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter(models.NeuronModel)
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


@strawberry_django.filter(models.Instrument)
class InstrumentFilter:
    id: auto
    name: auto


@strawberry_django.filter(models.View)
class ViewFilter:
    is_global: auto


@strawberry_django.order(models.Block)
class BlockOrder:
    created_at: auto


@strawberry_django.order(models.Stimulus)
class StimulusOrder:
    created_at: auto


@strawberry_django.order(models.NeuronModel)
class NeuronModelOrder:
    created_at: auto


@strawberry_django.filter(models.TimelineView)
class ContinousScanViewFilter(ViewFilter):
    start_time: auto
    end_time: auto


@strawberry_django.filter(models.Trace)
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
        print("Filtering not derived")
        if self.not_derived is None:
            return queryset
        return queryset.filter(derived_views=None)


@strawberry_django.filter(models.ROI)
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


@strawberry_django.filter(models.Block)
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


@strawberry_django.filter(models.BlockSegment)
class BlockSegmentFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry_django.filter(models.BlockGroup)
class BlockGroupFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    description: Optional[FilterLookup[str]]
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry_django.filter(models.AnalogSignal)
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


@strawberry_django.filter(models.IrregularlySampledSignal)
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


@strawberry_django.filter(models.SpikeTrain)
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


@strawberry_django.filter(models.AnalogSignalChannel)
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
