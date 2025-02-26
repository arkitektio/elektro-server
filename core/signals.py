from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from core import models
from core.channel import image_broadcast, roi_update_broadcast, file_broadcast
from core import managers
from core import models



@receiver(post_save, sender=models.ROI)
def my_roi_handler(sender, instance=None, created=None, **kwargs):
    print("ROI HANDLER")
    roi_update_broadcast({"id": instance.id, "type": "create" if created else "update"}, ["rois", f"image_roi_{instance.image.id}"] )

@receiver(pre_delete, sender=models.ROI)
def my_roi_delete_handler(sender, instance=None, **kwargs):
    roi_update_broadcast({"id": instance.id, "type": "delete"}, ["rois", f"image_roi_{instance.image.id}"])


@receiver(post_save, sender=models.Trace)
def my_image_handler(sender, instance=None, created=None, **kwargs):
    print("ROI HANDLER")
    image_broadcast({"id": instance.id, "type": "create" if created else "update"}, ["images"] + [f"dataset_images_{instance.dataset.id}"] )

@receiver(pre_delete, sender=models.Trace)
def my_image_delete_handler(sender, instance=None, **kwargs):
    image_broadcast({"id": instance.id, "type": "delete"}, ["images"] + [f"dataset_images_{instance.dataset.id}"])

@receiver(post_save, sender=models.File)
def my_file_handler(sender, instance=None, created=None, **kwargs):
    channels = ["files"] 
    if instance.dataset:

        channels += [f"dataset_files_{instance.dataset.id}"]
    file_broadcast({"id": instance.id, "type": "create" if created else "update"}, channels )

@receiver(pre_delete, sender=models.File)
def my_file_delete_handler(sender, instance=None, **kwargs):
    channels = ["files"] 
    if instance.dataset:

        channels += [f"dataset_files_{instance.dataset.id}"]

    file_broadcast({"id": instance.id, "type": "delete"},channels)