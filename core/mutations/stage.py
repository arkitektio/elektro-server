from kante.types import Info
import strawberry
from core import types, models


@strawberry.input
class StageInput:
    name: str
    instrument: strawberry.ID | None = None


@strawberry.input()
class DeleteStageInput:
    id: strawberry.ID


@strawberry.input
class PinStageInput:
    id: strawberry.ID
    pin: bool


def pin_stage(
    info: Info,
    input: PinStageInput,
) -> types.Stage:
    raise NotImplementedError("TODO")


def delete_stage(
    info: Info,
    input: DeleteStageInput,
) -> strawberry.ID:
    item = models.Stage.objects.get(id=input.id)
    item.delete()
    return input.id


def create_stage(
    info: Info,
    input: StageInput,
) -> types.Stage:
    view = models.Stage.objects.create(
        name=input.name,
        instrument=input.instrument,
    )
    return view
