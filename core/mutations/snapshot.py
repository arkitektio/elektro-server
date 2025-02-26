from kante.types import Info
import strawberry
from core import types, models
from strawberry.file_uploads import Upload
from django.conf import settings
from core.datalayer import get_current_datalayer

@strawberry.input
class SnapshotInput:
    file: Upload
    image: strawberry.ID


@strawberry.input()
class DeleteSnaphotInput:
    id: strawberry.ID


@strawberry.input
class PinSnapshotInput:
    id: strawberry.ID
    pin: bool


def pin_snapshot(
    info: Info,
    input: PinSnapshotInput,
) -> types.Snapshot:
    raise NotImplementedError("TODO")


def delete_snapshot(
    info: Info,
    input: DeleteSnaphotInput,
) -> strawberry.ID:
    item = models.Snapshot.objects.get(id=input.id)
    item.delete()
    return input.id


def create_snapshot(
    info: Info,
    input: SnapshotInput,
) -> types.Snapshot:
    media_store, _ = models.MediaStore.objects.get_or_create(
        bucket=settings.MEDIA_BUCKET,
        key=input.file.name,
        path=f"s3://{settings.MEDIA_BUCKET}/{input.file.name}",
    )

    datalayer = get_current_datalayer()
    media_store.put_file(datalayer, input.file)

    item = models.Snapshot.objects.create(
        name=input.file.name, store=media_store, image_id=input.image
    )
    return item
