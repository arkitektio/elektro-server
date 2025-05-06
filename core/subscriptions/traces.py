from typing import AsyncGenerator

import strawberry
import strawberry_django
from kante.types import Info
from core import models, scalars, types, channels

@strawberry.type
class TraceEvent:
    create: types.Trace | None = None
    update: types.Trace    | None = None

    delete: strawberry.ID | None = None


async def traces(
    self,
    info: Info,
    dataset: strawberry.ID | None = None,
) -> AsyncGenerator[TraceEvent, None]:
    """Join and subscribe to message sent tso the given rooms."""

    if dataset is None:
        schannels = ["images"]
    else:
        schannels = ["dataset_images_" + str(dataset)]

    async for message in channels.trace_channel.listen(info.context, schannels):
        print("Received message", message)
        if message.create:
            roi = await models.Trace.objects.aget(
                id=message.create
            )
            yield TraceEvent(create=roi)

        elif message.delete:
            yield TraceEvent(delete=message.delete)

        elif message.update:
            roi = await models.Trace.objects.aget(
                id=message.update
            )
            yield TraceEvent(update=roi)

