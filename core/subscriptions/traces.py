from typing import AsyncGenerator

import strawberry
import strawberry_django
from kante.types import Info
from core import models, scalars, types
from core.channel import image_listen


@strawberry.type
class TraceEvent:
    create: types.Trace | None = None
    delete: strawberry.ID | None = None
    update: types.Trace    | None = None


async def traces(
    self,
    info: Info,
    dataset: strawberry.ID | None = None,
) -> AsyncGenerator[TraceEvent, None]:
    """Join and subscribe to message sent tso the given rooms."""

    if dataset is None:
        channels = ["images"]
    else:
        channels = ["dataset_images_" + str(dataset)]

    async for message in image_listen(info, channels):
        print("Received message", message)
        if message["type"] == "create":
            roi = await models.Image.objects.aget(
                id=message["id"]
            )
            yield ImageEvent(create=roi)

        elif message["type"] == "delete":
            yield ImageEvent(delete=message["id"])

        elif message["type"] == "update":
            roi = await models.Image.objects.aget(
                id=message["id"]
            )
            yield ImageEvent(update=roi)

