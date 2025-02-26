from typing import AsyncGenerator
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from kante.types import Info
import logging


logger = logging.getLogger(__name__)


class Channel:
    """A GraphQL channel."""


    def __init__(self, name) -> None:
        self.name = name
        print("CHANNEL", name)
        pass

    def broadcast(self, message, groups=None):
        """Broadcast a message to the given groups."""
        if groups is None:
            groups = ["default"]

        channel = get_channel_layer()

        for group in groups:
            logger.debug(f"Sending message to group {group}")
            async_to_sync(channel.group_send)(
                group,
                {
                    "type": f"channel.{self.name}",
                    "message": message,
                },
            )

    async def listen(self, info: Info, groups=None) -> AsyncGenerator[None, None]:
        if groups is None:
            groups = ["default"]
        ws = info.context.consumer
        channel_layer = ws.channel_layer

        for group in groups:
            # Join room group
            logger.debug(f"Joining group {group} for channel {ws.channel_name}")
            print("GROUP", group , ws.channel_name)
            await channel_layer.group_add(group, ws.channel_name)

        async with ws.listen_to_channel(f"channel.{self.name}", groups=groups) as cm:
            async for message in cm:
                print("MESSAGE", message)
                yield message["message"]


def build_channel(name):
    """Build a channel name for the given name."""

    x = Channel(name)
    return x.broadcast, x.listen
