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
class ExperimentFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]

    
@strawberry_django.filter(models.ModelCollection)
class ModelCollectionFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    
    
@strawberry_django.filter(models.Simulation)
class SimulationFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    
    
@strawberry_django.filter(models.Recording)
class RecordingFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]
    
@strawberry_django.filter(models.Recording)
class StimulusFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]


@strawberry_django.filter(models.NeuronModel)
class NeuronModelFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: Optional[FilterLookup[str]]

@strawberry_django.filter(models.Instrument)
class InstrumentFilter:
    id: auto
    name: auto


@strawberry_django.filter(models.View)
class ViewFilter:
    is_global: auto



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
class ROIFilter(IDFilterMixin):
    id: auto
    kind: auto
    image: strawberry.ID | None = None
    search: str | None

    def filter_image(self, queryset, info):
        if self.image is None:
            return queryset
        return queryset.filter(image_id=self.image)
    
    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(image__name__contains=self.search)
    

