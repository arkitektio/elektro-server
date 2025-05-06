from typing import AsyncGenerator

import strawberry
import strawberry_django
from kante.types import Info
from core import models, scalars, types, channels


@strawberry.type
class RoiEvent:
    create: types.ROI | None = None
    delete: strawberry.ID | None = None
    update: types.ROI    | None = None


async def rois(
    self,
    info: Info,
    trace: strawberry.ID,
) -> AsyncGenerator[RoiEvent, None]:
    """Join and subscribe to message sent to the given rooms."""



    if trace is None:
        schannels = ["rois"]
    else:
        schannels = ["rois_trace" + str(trace)]

    async for message in channels.trace_channel.listen(info.context, schannels):
        print("Received message", message)
        if message.create:
            roi = await models.ROI.objects.aget(
                id=message.create
            )
            yield RoiEvent(create=roi)

        elif message.delete:
            yield RoiEvent(delete=message.delete)

        elif message.update:
            roi = await models.ROI.objects.aget(
                id=message.update
            )
            yield RoiEvent(update=roi)

