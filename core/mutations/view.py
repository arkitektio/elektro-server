from typing import List
from kante.types import Info
import strawberry
from core import types, models, scalars, enums
from strawberry import ID
import strawberry_django
from datetime import datetime
from django.contrib.auth import get_user_model

@strawberry_django.input(models.View, description="""                       
A input type to generate a view of a slice of an image.                      
""")
class ViewInput:
    """A general view of a region of an image

    
    """
    collection: strawberry.ID | None  = strawberry.field(default=None,  description="The collection this view belongs to")
    z_min: int | None =  strawberry.field(default=None, description="The minimum z coordinate of the view") 
    z_max: int | None =  strawberry.field(default=None, description="The maximum z coordinate of the view")
    x_min: int | None = strawberry.field(default=None, description="The minimum x coordinate of the view")
    x_max: int | None = strawberry.field( default=None, description="The maximum x coordinate of the view") 
    y_min: int | None= strawberry.field( default=None, description="The minimum y coordinate of the view")
    y_max: int | None = strawberry.field(default=None, description="The maximum y coordinate of the view")
    t_min: int | None = strawberry.field(default=None, description="The minimum t coordinate of the view")
    t_max: int | None = strawberry.field( default=None, description="The maximum t coordinate of the view")
    c_min: int | None = strawberry.field( default=None, description="The minimum c (channel) coordinate of the view")
    c_max: int | None = strawberry.field( default=None, description="The maximum c (channel) coordinate of the view")


@strawberry_django.input(models.ChannelView)
class PartialChannelViewInput(ViewInput):
    """Input for creating a view of a specific channel"""
    channel: strawberry.ID = strawberry.field(description="The ID of the channel this view is for")


@strawberry_django.input(models.ChannelView)
class ChannelViewInput(PartialChannelViewInput):
    """Input for creating a complete channel view including the image"""
    image: strawberry.ID = strawberry.field( description="The ID of the image this view is for")


@strawberry_django.input(models.AffineTransformationView)
class PartialAffineTransformationViewInput(ViewInput):
    stage: ID | None = None
    affine_matrix: scalars.FourByFourMatrix


@strawberry_django.input(models.LabelView)
class PartialLabelViewInput(ViewInput):
    label: str 


@strawberry_django.input(models.RGBView)
class PartialRGBViewInput(ViewInput):
    context: ID | None = None
    gamma: float | None = None
    contrast_limit_min: float | None = None
    contrast_limit_max: float | None = None
    rescale: bool | None = None
    scale: float | None = None
    active: bool | None = None
    color_map: enums.ColorMap | None = None
    base_color: list[float] | None = None

@strawberry_django.input(models.AcquisitionView)
class PartialAcquisitionViewInput(ViewInput):
    description: str | None = None
    acquired_at: datetime | None = None
    operator: ID | None = None

@strawberry_django.input(models.ROIView)
class PartialROIViewInput(ViewInput):
    roi: ID 

@strawberry_django.input(models.DerivedView)
class PartialDerivedViewInput(ViewInput):
    origin_image: ID 
@strawberry_django.input(models.FileView)
class PartialFileViewInput(ViewInput):
    file: ID 
    series_identifier: str | None = None



@strawberry_django.input(models.OpticsView)
class PartialOpticsViewInput(ViewInput):
    instrument: ID | None = None
    objective: ID | None = None
    camera: ID | None = None


@strawberry_django.input(models.ScaleView)
class PartialScaleViewInput(ViewInput):
    parent: ID | None = None
    scale_x: float | None = None
    scale_y: float | None = None
    scale_z: float | None = None
    scale_t: float | None = None
    scale_c: float | None = None


@strawberry.input()
class RangePixelLabel:
    group: ID | None = None
    entity_kind: ID
    min: int
    max: int

@strawberry_django.input(models.PixelView)
class PartialPixelViewInput(ViewInput):
    linked_view: ID | None = None
    range_labels: List[RangePixelLabel] | None = None






@strawberry_django.input(models.StructureView)
class PartialStructureViewInput(ViewInput):
    structure: scalars.StructureString 


@strawberry_django.input(models.WellPositionView)
class PartialWellPositionViewInput(ViewInput):
    well: ID | None = None
    row: int | None = None
    column: int | None = None


@strawberry_django.input(models.ContinousScanView)
class PartialContinoussScanViewInput(ViewInput):
    direction: enums.ScanDirection


@strawberry_django.input(models.TimepointView)
class PartialTimepointViewInput(ViewInput):
    era: ID | None = None
    ms_since_start: scalars.Milliseconds | None = None
    index_since_start: int | None = None


@strawberry_django.input(models.AffineTransformationView)
class AffineTransformationViewInput(PartialAffineTransformationViewInput):
    image: ID


@strawberry_django.input(models.LabelView)
class LabelViewInput(PartialLabelViewInput):
    image: ID


@strawberry_django.input(models.AcquisitionView)
class AcquisitionViewInput(PartialAcquisitionViewInput):
    image: ID


@strawberry_django.input(models.RGBView)
class RGBViewInput(PartialRGBViewInput):
    image: ID
    context: ID


@strawberry_django.input(models.ContinousScanView)
class ContinousScanViewInput(PartialContinoussScanViewInput):
    image: ID


@strawberry_django.input(models.DerivedView)
class DerivedViewInput(PartialDerivedViewInput):
    image: ID


@strawberry_django.input(models.WellPositionView)
class WellPositionViewInput(PartialWellPositionViewInput):
    image: ID


@strawberry_django.input(models.LabelView)
class TimepointViewInput(PartialTimepointViewInput):
    image: ID


@strawberry_django.input(models.OpticsView)
class OpticsViewInput(PartialOpticsViewInput):
    image: ID


@strawberry_django.input(models.StructureView)
class StructureViewInput(PartialStructureViewInput):
    image: ID

@strawberry_django.input(models.ROIView)
class ROIViewInput(PartialROIViewInput):
    image: ID

@strawberry_django.input(models.FileView)
class FileViewInput(PartialFileViewInput):
    image: ID


@strawberry_django.input(models.PixelView)
class PixelViewInput(PartialPixelViewInput):
    image: ID

def view_kwargs_from_input(input: ChannelViewInput) -> dict:
    is_global = all(
        x is None
        for x in [
            input.z_min,
            input.z_max,
            input.x_min,
            input.x_max,
            input.y_min,
            input.y_max,
            input.t_min,
            input.t_max,
            input.c_min,
            input.c_max,
        ]
    )

    return dict(
        z_min=input.z_min,
        z_max=input.z_max,
        x_min=input.x_min,
        x_max=input.x_max,
        y_min=input.y_min,
        y_max=input.y_max,
        t_min=input.t_min,
        t_max=input.t_max,
        c_min=input.c_min,
        c_max=input.c_max,
        is_global=is_global,
        collection_id=input.collection,
    )


@strawberry.input()
class DeleteViewInput:
    id: strawberry.ID


def delete_view(
    info: Info,
    input: DeleteViewInput,
) -> strawberry.ID:
    item = models.View.objects.get(id=input.id)
    item.delete()
    return input.id


@strawberry.input
class PinViewInput:
    id: strawberry.ID
    pin: bool


def pin_view(
    info: Info,
    input: PinViewInput,
) -> types.View:
    raise NotImplementedError("TODO")


def create_new_view(
    info: Info,
    input: ViewInput,
) -> types.View:
    image = models.Image.objects.get(id=input.image)

    view = models.View.objects.create(
        image=image,
        **view_kwargs_from_input(input),
    )
    return view


def create_channel_view(
    info: Info,
    input: ChannelViewInput,
) -> types.ChannelView:
    image = models.Image.objects.get(id=input.image)

    view = models.ChannelView.objects.create(
        image=image,
        channel=models.Channel.objects.get(id=input.channel),
        **view_kwargs_from_input(input),
    )
    return view


def delete_channel_view(
    info: Info,
    input: DeleteViewInput,
) -> strawberry.ID:
    item = models.ChannelView.objects.get(id=input.id)
    item.delete()
    return input.id


def create_rgb_view(
    info: Info,
    input: RGBViewInput,
) -> types.RGBView:
    image = models.Image.objects.get(id=input.image)

    view = models.RGBView.objects.create(
        image=image,
        context=models.RGBRenderContext.objects.get(id=input.context)
        if input.context
        else models.RGBRenderContext.objects.create(name=f"Unknown for {image.name}"),
        r_scale=input.r_scale,
        g_scale=input.g_scale,
        b_scale=input.b_scale,
        **view_kwargs_from_input(input),
    )
    return view

def create_structure_view(
    info: Info,
    input: StructureViewInput,
) -> types.StructureView:
    image = models.Image.objects.get(id=input.image)

    view = models.StructureView.objects.create(
        image=image,
        structure=input.structure,
        **view_kwargs_from_input(input),
    )
    return view


def delete_rgb_view(
    info: Info,
    input: DeleteViewInput,
) -> strawberry.ID:
    item = models.RGBView.objects.get(id=input.id)
    item.delete()
    return input.id


def create_affine_transformation_view(
    info: Info,
    input: AffineTransformationViewInput,
) -> types.AffineTransformationView:
    image = models.Image.objects.get(id=input.image)

    view = models.AffineTransformationView.objects.create(
        image=image,
        stage=models.Stage.objects.get(id=input.stage)
        if input.stage
        else models.Stage.objects.create(name=f"Unknown for {image.name}"),
        affine_matrix=input.affine_matrix,
        **view_kwargs_from_input(input),
    )
    return view


def delete_affine_transformation_view(
    info: Info,
    input: DeleteViewInput,
) -> strawberry.ID:
    item = models.AffineTransformationView.objects.get(id=input.id)
    item.delete()
    return input.id


def create_label_view(
    info: Info,
    input: LabelViewInput,
) -> types.LabelView:
    image = models.Image.objects.get(id=input.image)

    view = models.LabelView.objects.create(
        image=image,
        label=input.label,
        **view_kwargs_from_input(input),
    )
    return view


def create_derived_view(
    info: Info,
    input: DerivedViewInput,
) -> types.DerivedView:
    image = models.Image.objects.get(id=input.image)

    view = models.DerivedView.objects.create(
        image=image,
        origin_image=input.origin_image,
        **view_kwargs_from_input(input),
    )
    return view



def create_roi_view(
    info: Info,
    input: ROIViewInput,
) -> types.ROIView:
    image = models.Image.objects.get(id=input.image)

    view = models.ROIView.objects.create(
        image=image,
        roi=models.ROI.objects.get(id=input.roi),
        **view_kwargs_from_input(input),
    )
    return view


def create_file_view(
    info: Info,
    input: FileViewInput,
) -> types.FileView:
    image = models.Image.objects.get(id=input.image)

    view = models.FileView.objects.create(
        image=image,
        file=models.File.objects.get(id=input.file),
        series_identifier=input.series_identifier,
        **view_kwargs_from_input(input),
    )
    return view


def create_acquisition_view(
    info: Info,
    input: AcquisitionViewInput,
) -> types.AcquisitionView:
    image = models.Image.objects.get(id=input.image)

    view = models.AcquisitionView.objects.create(
        image=image,
        description=input.description,
        acquired_at=input.acquired_at,
        operator=get_user_model().objects.get(id=input.operator) if input.operator else None,
        **view_kwargs_from_input(input),
    )
    return view


def create_continous_scan_view(
    info: Info,
    input: ContinousScanViewInput,
) -> types.ContinousScanView:
    image = models.Image.objects.get(id=input.image)

    view = models.ContinousScanView.objects.create(
        image=image,
        direction=input.direction,
        **view_kwargs_from_input(input),
    )
    return view


def create_well_position_view(
    info: Info,
    input: WellPositionViewInput,
) -> types.WellPositionView:
    image = models.Image.objects.get(id=input.image)

    well = models.MultiWellPlate.objects.get(id=input.well) if input.well else None

    view = models.WellPositionView.objects.create(
        image=image,
        well=well,
        row=input.row,
        column=input.column,
        **view_kwargs_from_input(input),
    )
    return view


def delete_label_view(
    info: Info,
    input: DeleteViewInput,
) -> strawberry.ID:
    item = models.LabelView.objects.get(id=input.id)
    item.delete()
    return input.id


def create_timepoint_view(
    info: Info,
    input: TimepointViewInput,
) -> types.TimepointView:
    image = models.Image.objects.get(id=input.image)

    view = models.TimepointView.objects.create(
        image=image,
        era=models.Era.objects.get(id=input.fluorophore)
        if input.era
        else models.Era.objects.create(name=f"Unknown for {image.name}"),
        **view_kwargs_from_input(input),
    )
    return view




def delete_timepoint_view(
    info: Info,
    input: DeleteViewInput,
) -> strawberry.ID:
    item = models.TimepointView.objects.get(id=input.id)
    item.delete()
    return input.id


def create_optics_view(
    info: Info,
    input: OpticsViewInput,
) -> types.OpticsView:
    image = models.Image.objects.get(id=input.image)

    view = models.OpticsView.objects.create(
        image=image,
        objective_id=input.objective,
        instrument_id=input.instrument,
        camera_id=input.camera,
        **view_kwargs_from_input(input),
    )
    return view


def delete_optics_view(
    info: Info,
    input: DeleteViewInput,
) -> strawberry.ID:
    item = models.OpticsView.objects.get(id=input.id)
    item.delete()
    return input.id


def _create_pixel_view_from_partial(image, input: PartialPixelViewInput) -> types.PixelView:
    view = models.PixelView.objects.create(
        image=image,
        **view_kwargs_from_input(input),
    )



    if input.range_labels:
        for range_label in input.range_labels:

            if range_label.group:
                group = models.EntityGroup.objects.get(id=input.group)
            else:
                group, _ = models.EntityGroup.objects.get_or_create(name="All entitites")

            for i in range(range_label.min, range_label.max + 1):
                x = models.EntityKind.objects.get(id=range_label.entity_kind)

                models.PixelLabel.objects.create(
                    view=view,
                    entity=x.create_entity(group),
                    value=i,
                )

    return view



def create_pixel_view(
    info: Info,
    input: PixelViewInput,
) -> types.PixelView:
    image = models.Image.objects.get(id=input.image)
    return _create_pixel_view_from_partial(image, input)
    
    

