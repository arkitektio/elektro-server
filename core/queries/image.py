from kante.types import Info
import strawberry
from core import types, models, scalars
from strawberry import ID
import strawberry_django


def random_image(
    info: Info,
) -> types.Image:
    view = models.Image.objects.order_by("?").first()
    return view