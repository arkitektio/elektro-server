"""The array dataset subscription: created, updated and deleted datasets of the subscriber's organization."""

from typing import AsyncGenerator

import strawberry
from kante.types import Info

from core import channels, models, scoping, types
from core.signals import array_dataset_channels


@strawberry.type(description="One change to an array dataset: exactly one of the three fields is set")
class ArrayDatasetEvent:
    """A created, updated or deleted array dataset."""

    create: types.ArrayDataset | None = None
    update: types.ArrayDataset | None = None
    delete: strawberry.ID | None = None


async def array_datasets(
    self,  # noqa: ANN001 - strawberry's root value
    info: Info,
    folder: strawberry.ID | None = None,
) -> AsyncGenerator[ArrayDatasetEvent, None]:
    """Subscribe to the array datasets of this organization, or of one of its folders.

    Tenancy is the channel's name: a subscriber listens on its own organization's channel, or
    on a folder's after that folder was looked up *through* the organization -- so another
    organization's events, deletes included, never reach it. The rows are fetched scoped as
    well, which costs nothing and means a mistake in a channel name cannot become a leak.
    """
    organization = info.context.request.organization
    if folder is None:
        listen_on = array_dataset_channels(organization.pk)[:1]
    else:
        owned = await scoping.aget_for_org(models.Folder, info, id=folder)
        listen_on = array_dataset_channels(organization.pk, owned.pk)[1:]

    async for message in channels.array_dataset_channel.listen(info.context, listen_on):
        if message.delete:
            yield ArrayDatasetEvent(delete=strawberry.ID(str(message.delete)))
            continue

        try:
            dataset = await scoping.aget_for_org(models.ArrayDataset, info, id=message.create or message.update)
        except models.ArrayDataset.DoesNotExist:
            continue  # Deleted between the broadcast and this read, or not this organization's.
        yield ArrayDatasetEvent(create=dataset) if message.create else ArrayDatasetEvent(update=dataset)
