from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from core import models, channels
from core import managers
from core import models



@receiver(post_save, sender=models.Trace)
def my_roi_handler(sender, instance=None, created=None, **kwargs):
    if created:
        channels.trace_channel.broadcast(
            channels.TraceSignal(create=instance.id),
            ["traces"],
        )
    else:
        channels.trace_channel.broadcast(
            channels.TraceSignal(update=instance.id),
            ["traces"],
        )
      

@receiver(pre_delete, sender=models.Trace)
def my_roi_delete_handler(sender, instance=None, **kwargs):
     channels.trace_channel.broadcast(
        channels.TraceSignal(delete=instance.id),
        ["traces"],
    )
