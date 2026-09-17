"""Broadcasts for the array dataset subscription.

Channels carry the organization in their name, so tenancy is decided by *which channel a
subscriber may listen on* rather than by a check per message. That matters most for a delete:
the message is only an id, the row is already gone, and there is nothing left to scope it by.
"""

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from core import channels, models


def array_dataset_channels(organization_id: int, folder_id: int | None = None) -> list[str]:
    """The channels a dataset's events go out on: its organization's, and its folder's if it is filed in one."""
    names = [f"array_datasets_org_{organization_id}"]
    if folder_id is not None:
        names.append(f"array_datasets_folder_{folder_id}")
    return names


@receiver(post_save, sender=models.ArrayDataset)
def array_dataset_saved(sender, instance=None, created=None, **kwargs):  # noqa: ANN001, ANN201, ANN003 - a django signal receiver
    """Announce a created or updated dataset."""
    signal = channels.ArrayDatasetSignal(create=instance.id) if created else channels.ArrayDatasetSignal(update=instance.id)
    channels.array_dataset_channel.broadcast(signal, array_dataset_channels(instance.organization_id, instance.folder_id))


@receiver(pre_delete, sender=models.ArrayDataset)
def array_dataset_deleted(sender, instance=None, **kwargs):  # noqa: ANN001, ANN201, ANN003 - a django signal receiver
    """Announce a dataset that is about to be deleted."""
    channels.array_dataset_channel.broadcast(channels.ArrayDatasetSignal(delete=instance.id), array_dataset_channels(instance.organization_id, instance.folder_id))
