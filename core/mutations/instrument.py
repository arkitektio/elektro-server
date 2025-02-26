from kante.types import Info
import strawberry
from core import types, models


@strawberry.input
class InstrumentInput:
    serial_number: str
    manufacturer: str | None = None
    name: str | None = None
    model: str | None = None


@strawberry.input
class PinInstrumentInput:
    id: strawberry.ID
    pin: bool


def pin_instrument(
    info: Info,
    input: PinInstrumentInput,
) -> types.Instrument:
    raise NotImplementedError("TODO")


@strawberry.input()
class DeleteInstrumentInput:
    id: strawberry.ID


def delete_instrument(
    info: Info,
    input: DeleteInstrumentInput,
) -> strawberry.ID:
    item = models.Instrument.objects.get(id=input.id)
    item.delete()
    return input.id


def create_instrument(
    info: Info,
    input: InstrumentInput,
) -> types.Instrument:
    view, _ = models.Instrument.objects.update_or_create(
        serial_number=input.serial_number,
        defaults=dict(
        manufacturer=input.manufacturer,
        name=input.name,
        model=input.model,
        )
    )
    return view


def ensure_instrument(
    info: Info,
    input: InstrumentInput,
) -> types.Instrument:
    view, _ = models.Instrument.objects.get_or_create(
        serial_number=input.serial_number,
        defaults=dict(
            manufacturer=input.manufacturer,
            name=input.name,
            model=input.model,
        ),
    )
    return view
