from kante.types import Info
import strawberry
from core import types, models, inputs
from typing import cast


@strawberry.input
class CreateDatasetInput:
    name: str


@strawberry.input
class DeleteDatasetInput:
    id: strawberry.ID


@strawberry.input
class PinDatasetInput:
    id: strawberry.ID
    pin: bool


def pin_dataset(
    info: Info,
    input: PinDatasetInput,
) -> types.Dataset:
    raise NotImplementedError("TODO")


@strawberry.input()
class ChangeDatasetInput(CreateDatasetInput):
    id: strawberry.ID


@strawberry.input()
class RevertInput:
    id: strawberry.ID
    history_id: strawberry.ID


def create_dataset(
    info: Info,
    input: CreateDatasetInput,
) -> types.Dataset:
    view = models.Dataset.objects.create(name=input.name, creator=info.context.request.user, organization=info.context.request.organization, membership=info.context.request.membership)
    return cast(types.Dataset, view)


def delete_dataset(
    info: Info,
    input: DeleteDatasetInput,
) -> strawberry.ID:
    view = models.Dataset.objects.get(
        id=input.id,
    )
    view.delete()
    return input.id


def update_dataset(
    info: Info,
    input: ChangeDatasetInput,
) -> types.Dataset:
    view = models.Dataset.objects.get(
        id=input.id,
    )
    view.name = input.name
    view.save()
    return view


def revert_dataset(
    info: Info,
    input: RevertInput,
) -> types.Dataset:
    dataset = models.Dataset.objects.get(
        id=input.id,
    )
    historic = dataset.history.get(history_id=input.history_id)
    historic.instance.save()
    return historic.instance


def put_datasets_in_dataset(
    info: Info,
    input: inputs.AssociateInput,
) -> types.Dataset:
    parent = models.Dataset.objects.get(
        id=input.other,
    )

    for i in input.selfs:
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
    for i in input.selfs:
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
    parent = models.Dataset.objects.get(
        id=input.other,
    )

    for i in input.selfs:
        image = models.Images.objects.get(
            id=i,
        )
        image.dataset = parent
        image.save()

    return parent


def release_images_from_dataset(
    info: Info,
    input: inputs.DesociateInput,
) -> types.Dataset:
    for i in input.selfs:
        dataset = models.Image.objects.get(
            id=i,
        )
        dataset.parent = None
        dataset.save()
    return dataset


def put_files_in_dataset(
    info: Info,
    input: inputs.AssociateInput,
) -> types.Dataset:
    parent = models.Dataset.objects.get(
        id=input.other,
    )

    for i in input.selfs:
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
    for i in input.selfs:
        dataset = models.File.objects.get(
            id=i,
        )
        dataset.parent = None
        dataset.save()
    return dataset
