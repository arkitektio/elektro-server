from kante.types import Info
import strawberry
from core import types, models


@strawberry.input
class ChannelInput:
    name: str


@strawberry.input
class DeleteChannelInput:
    id: strawberry.ID


@strawberry.input
class PinChannelInput:
    id: strawberry.ID
    pin: bool


def pin_channel(
    info: Info,
    input: PinChannelInput,
) -> types.Channel:
    raise NotImplementedError("TODO")


def create_channel(
    info: Info,
    input: ChannelInput,
) -> types.Channel:
    view = models.Channel.objects.create(
        name=input.name,
    )
    return view


def delete_channel(
    info: Info,
    input: DeleteChannelInput,
) -> strawberry.ID:
    item = models.Channel.objects.get(id=input.id)
    item.delete()
    return input.id


def ensure_channel(
    info: Info,
    input: ChannelInput,
) -> types.Channel:
    view, _ = models.Channel.objects.get_or_create(
        name=input.name,
    )
    return view
