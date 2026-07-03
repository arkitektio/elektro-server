from kante.types import Info
import strawberry
import kante
from pydantic import BaseModel
from core import types, models, inputs
from core.guards import enforce_delete
from typing import cast


class CreateDatasetInputModel(BaseModel):
    name: str


@kante.pydantic_input(CreateDatasetInputModel)
class CreateDatasetInput:
    name: str


class DeleteDatasetInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteDatasetInputModel)
class DeleteDatasetInput:
    id: strawberry.ID


class PinDatasetInputModel(BaseModel):
    id: str
    pin: bool


@kante.pydantic_input(PinDatasetInputModel)
class PinDatasetInput:
    id: strawberry.ID
    pin: bool


def pin_dataset(
    info: Info,
    input: PinDatasetInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    dataset = models.Dataset.objects.get(id=parsed.id)
    user = info.context.request.user
    if parsed.pin:
        dataset.pinned_by.add(user)
    else:
        dataset.pinned_by.remove(user)
    return cast(types.Dataset, dataset)


class ChangeDatasetInputModel(BaseModel):
    id: str
    name: str


@kante.pydantic_input(ChangeDatasetInputModel)
class ChangeDatasetInput:
    id: strawberry.ID
    name: str


class RevertInputModel(BaseModel):
    id: str
    history_id: str


@kante.pydantic_input(RevertInputModel)
class RevertInput:
    id: strawberry.ID
    history_id: strawberry.ID


def create_dataset(
    info: Info,
    input: CreateDatasetInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    view = models.Dataset.objects.create(name=parsed.name, creator=info.context.request.user, organization=info.context.request.organization, membership=info.context.request.membership)
    return cast(types.Dataset, view)


def delete_dataset(
    info: Info,
    input: DeleteDatasetInput,
) -> strawberry.ID:
    parsed = input.to_pydantic()
    view = models.Dataset.objects.get(
        id=parsed.id,
    )
    enforce_delete(info, view)
    view.delete()
    return parsed.id


def update_dataset(
    info: Info,
    input: ChangeDatasetInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    view = models.Dataset.objects.get(
        id=parsed.id,
    )
    view.name = parsed.name
    view.save()
    return view


def revert_dataset(
    info: Info,
    input: RevertInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    dataset = models.Dataset.objects.get(
        id=parsed.id,
    )
    historic = dataset.history.get(history_id=parsed.history_id)
    historic.instance.save()
    return historic.instance


def put_datasets_in_dataset(
    info: Info,
    input: inputs.AssociateInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    parent = models.Dataset.objects.get(
        id=parsed.other,
    )

    for i in parsed.selfs:
        dataset = models.Dataset.objects.get(
            id=i,
        )
        dataset.parent = parent
        dataset.save()

    return dataset


def release_datasets_from_dataset(
    info: Info,
    input: inputs.DesociateInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    for i in parsed.selfs:
        dataset = models.Dataset.objects.get(
            id=i,
        )
        dataset.parent = None
        dataset.save()
    return dataset


def put_images_in_dataset(
    info: Info,
    input: inputs.AssociateInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    parent = models.Dataset.objects.get(
        id=parsed.other,
    )

    for i in parsed.selfs:
        image = models.Trace.objects.get(
            id=i,
        )
        image.dataset = parent
        image.save()

    return parent


def release_images_from_dataset(
    info: Info,
    input: inputs.DesociateInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    parent = models.Dataset.objects.get(
        id=parsed.other,
    )
    for i in parsed.selfs:
        image = models.Trace.objects.get(
            id=i,
        )
        image.dataset = None
        image.save()
    return parent


def put_files_in_dataset(
    info: Info,
    input: inputs.AssociateInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    parent = models.Dataset.objects.get(
        id=parsed.other,
    )

    for i in parsed.selfs:
        image = models.File.objects.get(
            id=i,
        )
        image.dataset = parent
        image.save()

    return parent


def release_files_from_dataset(
    info: Info,
    input: inputs.DesociateInput,
) -> types.Dataset:
    parsed = input.to_pydantic()
    parent = models.Dataset.objects.get(
        id=parsed.other,
    )
    for i in parsed.selfs:
        file = models.File.objects.get(
            id=i,
        )
        file.dataset = None
        file.save()
    return parent
