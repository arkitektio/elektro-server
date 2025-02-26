from typing import AsyncGenerator, Type, Generic, Optional, List, TypeVar, Any
from channels.layers import get_channel_layer, BaseChannelLayer
from asgiref.sync import async_to_sync
from kante.types import Info
import logging
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class Gateway(Generic[T]):
    """A GraphQL Gteway."""

    channel_layer: BaseChannelLayer

    def __init__(
        self,
        name: str,
        pydantic_type: Type[T],
        channel_layer: Optional[BaseChannelLayer] = None,
    ) -> None:
        self.name = name
        self.pydantic_type = pydantic_type
        self.channel_layer = channel_layer or get_channel_layer()
        pass

    def broadcast(self, message: T, groups: Optional[List[str]] = None) -> None:
        """Broadcast a message to the given groups."""
        if groups is None:
            groups = ["default"]

        for group in groups:
            logger.debug(f"Sending message to group {group}")
            async_to_sync(self.channel_layer.group_send)(
                group,
                {
                    "type": f"gateway.{self.name}",
                    "message": message.json(),
                },
            )

    async def abroadcast(self, message: T, groups: Optional[List[str]] = None) -> None:
        if groups is None:
            groups = ["default"]

        for group in groups:
            logger.debug(f"Sending message to group {group}")
            await self.channel_layer.group_send(
                group,
                {
                    "type": f"gateway.{self.name}",
                    "message": message.json(),
                },
            )

    async def alisten(
        self, info: Info, groups: Optional[List[str]] = None
    ) -> AsyncGenerator[T, None]:
        if groups is None:
            groups = ["default"]
        ws = info.context.consumer

        for group in groups:
            # Join room group
            logger.debug(f"Joining group {group} for channel {ws.channel_name}")
            await self.channel_layer.group_add(group, ws.channel_name)

        async with ws.listen_to_channel(f"gateway.{self.name}", groups=groups) as cm:
            async for message in cm:
                yield self.pydantic_type.parse_raw(message["message"])

    def listen(
        self, info: Info, groups: Optional[List[str]] = None
    ) -> AsyncGenerator[T, None]:
        raise NotImplementedError("Async version only. Use alisten instead.")


def build_gateway(
    name: str, pydantic_type: Type[T], channel_layer: Optional[BaseChannelLayer] = None
) -> Gateway[T]:
    """Build a channel name for the given name."""

    gateway = Gateway(name, pydantic_type=pydantic_type, channel_layer=channel_layer)
    return gateway
