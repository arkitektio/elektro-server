from pydantic import BaseModel
from kante.types import Info
import strawberry
from core import types, models
from strawberry.file_uploads import Upload
from django.conf import settings
from core.datalayer import get_current_datalayer
from strawberry.experimental import pydantic

class OverlayInputModel(BaseModel):
    object: str
    identifier: str
    color: str
    x: int
    y: int

@pydantic.input(OverlayInputModel)
class OverlayInput:
    object: str
    identifier: str
    color: str
    x: int
    y: int


class RenderedPlotInputModel(BaseModel):
    plot: str
    overlays: list[OverlayInputModel]

@pydantic.input(RenderedPlotInputModel)
class RenderedPlotInput:
    plot: Upload
    name: str
    overlays: list[OverlayInput] | None = None


@strawberry.input()
class DeleteRenderedPlot:
    id: strawberry.ID


@strawberry.input
class PinSnapshotInput:
    id: strawberry.ID
    pin: bool


def pin_rendered_plot(
    info: Info,
    input: PinSnapshotInput,
) -> types.Snapshot:
    raise NotImplementedError("TODO")


def delete_snapshot(
    info: Info,
    input: DeleteRenderedPlot,
) -> strawberry.ID:
    item = models.RenderedPlot.objects.get(id=input.id)
    item.delete()
    return input.id


def create_rendered_plot(
    info: Info,
    input: RenderedPlotInput,
) -> types.RenderedPlot:
    media_store, _ = models.MediaStore.objects.get_or_create(
        bucket=settings.MEDIA_BUCKET,
        key=input.name,
        path=f"s3://{settings.MEDIA_BUCKET}/{input.name}",
    )

    datalayer = get_current_datalayer()
    media_store.put_file(datalayer, input.plot)

    item = models.RenderedPlot.objects.create(
        name=input.name, store=media_store, 
    )
    return item
