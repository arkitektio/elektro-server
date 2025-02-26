from typing import AsyncGenerator

import strawberry
import strawberry_django
from kante.types import Info
from core import models, scalars, types
from core.channel import file_listen


@strawberry.type
class FileEvent:
    create: types.File | None = None
    delete: strawberry.ID | None = None
    update: types.File    | None = None
    moved: types.File | None = None


async def files(
    self,
    info: Info,
    dataset: strawberry.ID | None = None,
) -> AsyncGenerator[FileEvent, None]:
    """Join and subscribe to message sent to the given rooms."""

    if dataset is None:
        channels = ["files"]
    else:
        channels = ["dataset_files_" + str(dataset)]



    async for message in file_listen(info, channels):
        print("Received message", message)
        if message["type"] == "create":
            roi = await models.File.objects.aget(
                id=message["id"]
            )
            yield FileEvent(create=roi)

        elif message["type"] == "delete":
            yield FileEvent(delete=message["id"])

        elif message["type"] == "update":
            roi = await models.File.objects.aget(
                id=message["id"]
            )
            yield FileEvent(update=roi)

