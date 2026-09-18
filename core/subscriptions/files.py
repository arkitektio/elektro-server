from typing import AsyncGenerator

import strawberry
import strawberry_django
from kante.types import Info
from core import models, scalars, types, channels, scoping


@strawberry.type
class FileEvent:
    create: types.File | None = None
    delete: strawberry.ID | None = None
    update: types.File    | None = None
    moved: types.File | None = None


async def files(
    self,
    info: Info,
    folder: strawberry.ID | None = None,
) -> AsyncGenerator[FileEvent, None]:
    """Join and subscribe to message sent to the given rooms."""

    if folder is None:
        schannels = ["files"]
    else:
        schannels = ["folder_files_" + str(folder)]



    async for message in channels.file_channel.listen(info.context, schannels):
        if message["type"] == "create":
            roi = await scoping.aget_for_org(models.File, info, id=message["id"]
            )
            yield FileEvent(create=roi)

        elif message["type"] == "delete":
            yield FileEvent(delete=message["id"])

        elif message["type"] == "update":
            roi = await scoping.aget_for_org(models.File, info, id=message["id"]
            )
            yield FileEvent(update=roi)

