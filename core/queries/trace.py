from kante.types import Info
import strawberry
from core import types, models, scalars
from strawberry import ID
import strawberry_django


def random_trace(
    info: Info,
) -> types.Trace:
    view = models.Trace.objects.order_by("?").first()
    return view