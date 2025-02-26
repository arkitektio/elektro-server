from kante.types import Info
import strawberry
from core import types, models


@strawberry.input
class ObjectiveInput:
    serial_number: str
    name: str | None = None
    na: float | None = None
    magnification: float | None = None
    immersion: str | None = None


@strawberry.input
class PinObjectiveInput:
    id: strawberry.ID
    pin: bool


def pin_objective(
    info: Info,
    input: PinObjectiveInput,
) -> types.Objective:
    raise NotImplementedError("TODO")


@strawberry.input()
class DeleteObjectiveInput:
    id: strawberry.ID


def delete_objective(
    info: Info,
    input: DeleteObjectiveInput,
) -> strawberry.ID:
    item = models.Objective.objects.get(id=input.id)
    item.delete()
    return input.id


def create_objective(
    info: Info,
    input: ObjectiveInput,
) -> types.Objective:
    view = models.Objective.objects.create(
        serial_number=input.serial_number,
        na=input.na,
        name=input.name,
        magnification=input.magnification,
        immersion=input.immersion,
    )
    return view


def ensure_objective(
    info: Info,
    input: ObjectiveInput,
) -> types.Objective:
    view, _ = models.Objective.objects.get_or_create(
        serial_number=input.serial_number,
        defaults=dict(
            name=input.name,
            na=input.na,
            magnification=input.magnification,
            immersion=input.immersion,
        ),
    )
    return view
