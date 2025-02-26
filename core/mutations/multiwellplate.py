from kante.types import Info
import strawberry
from core import types, models, scalars


@strawberry.input
class MultiWellPlateInput:
    name: str
    columns: int | None = None
    rows: int | None = None


@strawberry.input
class DeleteMultiWellInput:
    id: strawberry.ID


@strawberry.input
class PintMultiWellPlateInput:
    id: strawberry.ID
    pin: bool


def pin_multi_well_plate(
    info: Info,
    input: PintMultiWellPlateInput,
) -> types.MultiWellPlate:
    raise NotImplementedError("TODO")


def delete_multi_well_plate(
    info: Info,
    input: DeleteMultiWellInput,
) -> strawberry.ID:
    item = models.MultiWellPlate.objects.get(id=input.id)
    item.delete()
    return input.id


def create_multi_well_plate(
    info: Info,
    input: MultiWellPlateInput,
) -> types.MultiWellPlate:
    item = models.MultiWellPlate.objects.create(
        name=input.name,
        columns=input.columns,
        rows=input.rows,
    )
    return item


def ensure_multi_well_plate(
    info: Info,
    input: MultiWellPlateInput,
) -> types.MultiWellPlate:
    item, _ = models.MultiWellPlate.objects.update_or_create(
        name=input.name,
        defaults=dict(
            columns=input.columns,
            rows=input.rows,
        ),
    )
    return item
