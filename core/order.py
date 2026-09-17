"""Orderings for the coordinate graph. Vendored from mikro's ``core/order.py``; this service keeps its other orderings in ``core/filters.py``."""

import strawberry_django
from strawberry import auto

from core import models


@strawberry_django.order_type(models.Lens)
class LensOrder:
    id: auto


@strawberry_django.order_type(models.CoordinateSystem)
class CoordinateSystemOrder:
    name: auto
    created_at: auto
    id: auto


@strawberry_django.order_type(models.Transformation)
class TransformationOrder:
    order: auto
    created_at: auto
    id: auto


@strawberry_django.order_type(models.Annotation)
class AnnotationOrder:
    name: auto
    id: auto


@strawberry_django.order_type(models.AnnotationCollection)
class AnnotationCollectionOrder:
    name: auto
    created_at: auto
    id: auto


# --- The data layer (vendored from mikro's core/order.py) ---------------------------------------


@strawberry_django.order_type(models.Folder)
class FolderOrder:
    created_at: auto
    name: auto
    id: auto


@strawberry_django.order_type(models.File)
class FileOrder:
    created_at: auto
    name: auto
    size: auto
    content_type: auto
    id: auto


@strawberry_django.order_type(models.FileLink)
class FileLinkOrder:
    """Ordering for file links."""

    created_at: auto
    direction: auto
    id: auto


@strawberry_django.order_type(models.ArrayDataset)
class ArrayDatasetOrder:
    created_at: auto
    name: auto
    id: auto


@strawberry_django.order_type(models.DataArray)
class DataArrayOrder:
    level: auto
    id: auto
