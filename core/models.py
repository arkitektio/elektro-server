import random
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.forms import FileField
from taggit.managers import TaggableManager
from core import enums
from koherent.fields import HistoryField, HistoricForeignKey
import koherent.signals
from django_choices_field import TextChoicesField
from core.fields import S3Field
from core.datalayer import Datalayer
# Create your models here.
import boto3
import json
from django.conf import settings
from django.core.cache import cache


class DatasetManager(models.Manager):
    def get_current_default_for_user(self, user):
        potential = self.filter(creator=user, is_default=True).first()
        if not potential:
            return self.create(creator=user, name="Default", is_default=True)

        return potential


class Dataset(models.Model):
    """
    A dataset is a collection of data files and metadata files.
    It mimics the concept of a folder in a file system and is the top level
    object in the data model.

    """

    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="created_datasets",
        help_text="The user that created the dataset",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="The time the dataset was created"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    name = models.CharField(max_length=200, help_text="The name of the dataset")
    description = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="The description of the dataset",
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_datasets",
        blank=True,
        help_text="The users that have pinned the dataset",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Whether the dataset is the current default dataset for the user",
    )
    tags = TaggableManager(help_text="Tags for the dataset")
    history = HistoryField()

    objects = DatasetManager()

    def __str__(self) -> str:
        return super().__str__()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["creator", "is_default"],
                name="unique_default_per_creator",
                condition=models.Q(is_default=True),
            ),
        ]


class Objective(models.Model):
    serial_number = models.CharField(max_length=1000, unique=True)
    name = models.CharField(max_length=1000)
    magnification = models.FloatField(blank=True, null=True)
    na = models.FloatField(blank=True, null=True)
    immersion = models.CharField(max_length=1000, blank=True, null=True)

    history = HistoryField()


class Camera(models.Model):
    serial_number = models.CharField(max_length=1000, unique=True)
    name = models.CharField(max_length=1000, unique=True)
    model = models.CharField(max_length=1000, blank=True, null=True)
    bit_depth = models.IntegerField(blank=True, null=True)
    sensor_size_x = models.IntegerField(blank=True, null=True)
    sensor_size_y = models.IntegerField(blank=True, null=True)
    pixel_size_x = models.FloatField(blank=True, null=True)
    pixel_size_y = models.FloatField(blank=True, null=True)
    manufacturer = models.CharField(max_length=1000, blank=True, null=True)

    history = HistoryField()


class Instrument(models.Model):
    name = models.CharField(max_length=1000)
    manufacturer = models.CharField(max_length=1000, null=True, blank=True)
    model = models.CharField(max_length=1000, null=True, blank=True)
    serial_number = models.CharField(max_length=1000, unique=True)

    history = HistoryField()


class S3Store(models.Model):
    path = S3Field(
        null=True, blank=True, help_text="The store of the image", unique=True
    )
    key = models.CharField(max_length=1000)
    bucket = models.CharField(max_length=1000)
    populated = models.BooleanField(default=False)


class ZarrStore(S3Store):
    shape = models.JSONField(null=True, blank=True)
    chunks = models.JSONField(null=True, blank=True)
    dtype = models.CharField(max_length=1000, null=True, blank=True)

    def fill_info(self, datalayer: Datalayer) -> None:
        # Create a boto3 S3 client
        s3 = datalayer.s3v4

        # Extract the bucket and key from the S3 path
        bucket_name, prefix = self.path.replace("s3://", "").split("/", 1)

        # List all files under the given prefix
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)

        zarr_info = {}

        # Check if the '.zarray' file exists and retrieve its content
        for obj in response.get("Contents", []):
            if obj["Key"].endswith(".zarray"):
                array_name = obj["Key"].split("/")[-2]
                print(array_name)

                # Get the content of the '.zarray' file
                zarray_file = s3.get_object(Bucket=bucket_name, Key=obj["Key"])
                zarray_content = zarray_file["Body"].read().decode("utf-8")
                zarray_json = json.loads(zarray_content)

                # Retrieve the 'shape' and 'chunks' attributes
                zarr_info[array_name] = {
                    "shape": zarray_json.get("shape"),
                    "chunks": zarray_json.get("chunks"),
                    "dtype": zarray_json.get("dtype"),
                }

        

        self.dtype = zarr_info["data"]["dtype"]
        self.shape = zarr_info["data"]["shape"]
        self.chunks = zarr_info["data"]["chunks"]
        self.populated = True
        self.save()

    @property
    def c_size(self):
        return self.shape[0]
    
    @property
    def t_size(self):
        return self.shape[1]
    
    @property
    def z_size(self):
        return self.shape[2]
    
    @property
    def y_size(self):
        return self.shape[3]
    
    @property
    def x_size(self):
        return self.shape[4]


class ParquetStore(S3Store):
    pass

    def fill_info(self) -> None:
        pass

    @property
    def duckdb_string(self):
        return f"read_parquet('s3://{self.bucket}/{self.key}')"


class BigFileStore(S3Store):
    pass

    def fill_info(self) -> None:
        pass

    def get_presigned_url(self, info, datalayer: Datalayer, host: str | None = None, ) -> str:
        s3 = datalayer.s3
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self.key,
            },
            ExpiresIn=3600,
        )
        return url.replace(settings.AWS_S3_ENDPOINT_URL, host or "")


class MediaStore(S3Store):
    
    def get_presigned_url(self, info,  datalayer: Datalayer, host: str | None = None) -> str:
        cache_key = f"presigned_url:{self.bucket}:{self.key}:{host}"
        # Check if the URL is in the cache
        url = cache.get(cache_key)
        
        if not url:
            # Generate a new presigned URL if not cached
            s3 = datalayer.s3
            url = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": self.key,
                },
                ExpiresIn=3600,
            )
            # Replace the endpoint URL
            url = url.replace(settings.AWS_S3_ENDPOINT_URL, host or "")
            # Cache the URL with a timeout of 3600 seconds (same as ExpiresIn)
            cache.set(cache_key, url, timeout=3600)

        return url

    def put_file(self, datalayer: Datalayer, file: FileField):
        s3 = datalayer.s3
        s3.upload_fileobj(file, self.bucket, self.key)
        self.save()


class File(models.Model):
    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, null=True, blank=True, related_name="files"
    )
    origins = models.ManyToManyField(
        "self",
        related_name="derived",
        symmetrical=False,
    )
    store = models.ForeignKey(
        BigFileStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the file",
    )
    name = models.CharField(
        max_length=1000, help_text="The name of the file", default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, null=True)


class Table(models.Model):
    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, null=True, blank=True, related_name="tables"
    )
    origins = models.ManyToManyField(
        "self",
        related_name="derived",
        symmetrical=False,
    )
    store = models.ForeignKey(
        ParquetStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the table",
    )
    name = models.CharField(
        max_length=1000, help_text="The name of the image", default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, null=True)

    tags = TaggableManager()

    history = HistoryField()



class Experiment(models.Model):
    name = models.CharField(max_length=1000, help_text="The name of the experiment")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the experiment",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoryField()




class Image(models.Model):
    """A Representation is 5-dimensional representation of an image

    Mikro stores each image as sa 5-dimensional representation. The dimensions are:
    - t: time
    - c: channel
    - z: z-stack
    - x: x-dimension
    - y: y-dimension

    This ensures a unified api for all images, regardless of their original dimensions.
      Another main
    determining factor for a representation is its variety:
    A representation can be a raw image representating voxels (VOXEL)
    or a segmentation mask representing instances of a class. (MASK)
    It can also representate a human perception of the image (RGB)
    or a human perception of the mask (RGBMASK)


    #Origins and Derivations

    Images can be filtered, which means that a new representation
    is created from the other (original) representations.
    This new representation is then linked to the original representations.
    This way, we can always trace back to the original representation.
    Both are encapsulaed in the origins and derived fields.

    Representations belong to *one* sample. Every transaction to our image data
    is still part of the original acuqistion, so also filtered
      images are refering back to the sample
    Each iamge has also a name, which is used to identify the image.
    The name is unique within a sample.
    File and Rois that are used to create images are saved in
      the file origins and roi origins repectively.


    """

    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, null=True, blank=True, related_name="images"
    )
    store = models.ForeignKey(
        ZarrStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the image",
    )

    name = models.CharField(
        max_length=1000, help_text="The name of the image", default=""
    )

    description = models.CharField(max_length=1000, null=True, blank=True)
    kind = TextChoicesField(
        choices_enum=enums.ImageKind,
        default=enums.ImageKind.UNKNOWN.value,
        help_text="The Representation can have vasrying kind, consult your API",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)

    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_images",
        help_text="The users that have pinned the images",
    )
    history = HistoryField()

    tags = TaggableManager()

    class Meta:
        permissions = [("inspect_image", "Can view image")]

    def __str__(self) -> str:
        return f"Representation {self.id}"


class Render(models.Model):
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, null=True)

    class Meta:
        abstract = True


class Blurhash(Render):
    image = HistoricForeignKey(
        Image, on_delete=models.CASCADE, related_name="blurhashes"
    )
    hash = models.CharField(max_length=1000, help_text="The blurhash of the image")

    history = HistoryField()


class Video(Render):
    image = HistoricForeignKey(Image, on_delete=models.CASCADE, related_name="videos")
    store = models.ForeignKey(
        MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the video",
        related_name="videos",
    )
    thumbnail = models.ForeignKey(
        MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the video",
        related_name="thumbnails",
    )

    history = HistoryField()


class Snapshot(Render):
    image = HistoricForeignKey(
        Image, on_delete=models.CASCADE, related_name="snapshots"
    )
    context = models.ForeignKey(    
        "RGBRenderContext",
        on_delete=models.SET_NULL,
        related_name="snapshots",
        null=True,
        blank=True,
        help_text="The context of the snapshot",
    )
    store = models.ForeignKey(
        MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the file",
    )
    name = models.CharField(
        max_length=1000, help_text="The name of the snapshot", default=""
    )

    history = HistoryField()




class Channel(models.Model):
    name = models.CharField(max_length=1000, help_text="The name of the channel")
    emission_wavelength = models.FloatField(
        help_text="The emmission wavelength of the fluorophore in nm",
        null=True,
        blank=True,
    )
    excitation_wavelength = models.FloatField(
        help_text="The excitation wavelength of the fluorophore in nm",
        null=True,
        blank=True,
    )
    acquisition_mode = models.CharField(
        max_length=1000,
        help_text="The acquisition mode of the channel",
        null=True,
        blank=True,
    )
    color = models.CharField(
        max_length=1000,
        help_text="The default color for the channel ",
        null=True,
        blank=True,
    )

    history = HistoryField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "emission_wavelength", "excitation_wavelength"],
                name="Only one channel per name, "
                "emmission_wavelength and excitation_wavelength",
            )
        ]


# TODO: Rename Stage
class Stage(models.Model):

    """A stage is a 3D space corresponding to a
    a 3D space on a microscope during an experiment.

    Stages are used to define governign context for
    transformations and therefore are used to contextualize
    images according to their real world physical location.

    Stages are not meant to be reused outside of the original
    sample context and are therefore not meant to be shared, between
    experiments or samples.

    """

    name = models.CharField(max_length=1000, help_text="The name of the stage")
    kind = models.CharField(max_length=1000)
    instrument = models.ForeignKey(
        Instrument, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="The time the stages was created"
    )
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The user that created the stage",
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_stages",
        blank=True,
        help_text="The users that have pinned the stage",
    )

    history = HistoryField()


class MultiWellPlate(models.Model):
    name = models.CharField(
        max_length=1000,
        help_text="A name for the multiwell plate",
        null=True,
        blank=True,
    )
    description = models.CharField(
        max_length=1000,
        help_text="A description for the multiwell plate",
        null=True,
        blank=True,
    )
    rows = models.IntegerField(help_text="The number of rows in the multiwell plate", null=True, blank=True)
    columns = models.IntegerField(
        help_text="The number of columns in the multiwell plate",  null=True, blank=True
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_multiwellplates",
        blank=True,
        help_text="The users that have pinned the stage",
    )

    history = HistoryField()


# TODO: Rename Stage
class Era(models.Model):

    """A stage is a time space corresponding to a
    a time space on a microscope during an experiment.

    Stages are used to define governign context for
    transformations and therefore are used to contextualize
    images according to their real world physical location.

    Stages are not meant to be reused outside of the original
    sample context and are therefore not meant to be shared, between
    experiments or samples.

    """

    name = models.CharField(max_length=1000, help_text="The name of the stage")
    kind = models.CharField(max_length=1000)
    instrument = models.ForeignKey(
        Instrument, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="The time the stages was created"
    )
    begin = models.DateTimeField(
        help_text="The time the era started", null=True, blank=True
    )
    end = models.DateTimeField(
        help_text="The time the era ended", null=True, blank=True
    )

    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The user that created the stage",
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_eras",
        blank=True,
        help_text="The users that have pinned the era",
    )

    history = HistoryField()


class ViewCollection(models.Model):
    """A ViewCollection is a collection of views.

    It is used to group views together, for example to group all views
    that are used to represent a specific channel.

    """

    name = models.CharField(max_length=1000, help_text="The name of the view")
    history = HistoryField()


class View(models.Model):
    image = HistoricForeignKey(Image, on_delete=models.CASCADE)
    collection = models.ForeignKey(
        ViewCollection, on_delete=models.CASCADE, null=True, blank=True
    )
    z_min = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    z_max = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    x_min = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    x_max = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    y_min = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    y_max = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    t_min = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    t_max = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    c_min = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    c_max = models.IntegerField(
        help_text="The index of the channel", null=True, blank=True
    )
    is_global = models.BooleanField(
        help_text="Whether the view is global or not", default=False
    )

    class Meta:
        abstract = True




class OpticsView(View):
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="views"
    )
    objective = models.ForeignKey(
        Objective, on_delete=models.CASCADE, related_name="views", null=True
    )
    camera = models.ForeignKey(
        Camera, on_delete=models.CASCADE, related_name="views", null=True
    )

    history = HistoryField()

    class Meta:
        default_related_name = "optics_views"


class ScaleView(View):
    parent = models.ForeignKey(
        "Image", on_delete=models.CASCADE, related_name="derived_scale_views"
    )
    scale_x = models.FloatField(help_text="The scale in x direction")
    scale_y = models.FloatField(help_text="The scale in y direction")
    scale_z = models.FloatField(help_text="The scale in z direction")
    scale_t = models.FloatField(help_text="The scale in t direction")
    scale_c = models.FloatField(help_text="The scale in c direction")

    history = HistoryField()

    class Meta:
        default_related_name = "scale_views"


class AlphaView(View):
    is_alpha_for = models.ForeignKey(
        ViewCollection, on_delete=models.CASCADE, related_name="attached_alpha_views"
    )

    class Meta:
        default_related_name = "alpha_views"


class ContinousScanView(View):
    direction = TextChoicesField(
        choices_enum=enums.ContinousScanDirection,
        help_text="The direction of the scan",
    )

    class Meta:
        default_related_name = "continousscan_views"


class WellPositionView(View):
    well = models.ForeignKey(
        MultiWellPlate, on_delete=models.CASCADE, related_name="views"
    )
    row = models.IntegerField(help_text="The row of the well")
    column = models.IntegerField(help_text="The column of the well")

    history = HistoryField()

    class Meta:
        default_related_name = "wellposition_views"


class ChannelView(View):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="views")

    history = HistoryField()

    class Meta:
        default_related_name = "channel_views"


class StructureView(View):
    structure = models.CharField(
        max_length=1000,
        help_text="The entity that this view is for",
        null=True,
        blank=True,
    )

    history = HistoryField()

    class Meta:
        default_related_name = "structure_views"


class FileView(View):
    """ A FileView is a view on a file
    
    This means that the image part  represents the context of a file in a specific
    context.
    
    
    """

    file = models.ForeignKey(File, on_delete=models.CASCADE, related_name="views")
    series_identifier = models.CharField(
        max_length=1000,
        help_text="The series identifier of the file",
        null=True,
        blank=True,
    )



    history = HistoryField()

    class Meta:
        default_related_name = "file_views"


class TableView(View):
    """ A TablieView is a view on a file
    
    This means that the image part was created from a table and represents the context of
    the table in a specific context (i.e the table represent localisations in SMLIM
    
    
    """

    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name="views")
    series_identifier = models.CharField(
        max_length=1000,
        help_text="The series identifier of the file",
        null=True,
        blank=True,
    )



    history = HistoryField()

    class Meta:
        default_related_name = "table_views"


class DerivedView(View):
    """ A DerivedView

    A DerivedView is a view that describes the process of creating the image from
    another image. It is metadata that describes that the image was created from
    another image and is used to describe the context of the image.
    
    
    """

    origin_image = models.ForeignKey(Image, on_delete=models.CASCADE, related_name="derived_from_views")
    operation = models.CharField(
        max_length=1000,
        help_text="The operation that was used to create the image",
        null=True,
    )



    history = HistoryField()

    class Meta:
        default_related_name = "derived_views"





class ROIView(View):
    """ A Roi View
    
    RoiViews describe that the section of the image represents the cut roi of
    another image (the parent image). This is used to describe that the image
    is a cutout of another image and is used to describe the context of the
    image.
    
    """
    roi = models.ForeignKey("ROI", on_delete=models.CASCADE, related_name="views")

    history = HistoryField()


    class Meta:
        default_related_name = "roi_views"


class Accessor(models.Model):
    table = HistoricForeignKey(Table, on_delete=models.CASCADE)
    keys = models.JSONField(max_length=1000, help_text="The key of the column")
    min_index = models.IntegerField(
        help_text="The index of the row where this view starts (null if all rows)", null=True, blank=True
    )
    max_index = models.IntegerField(
        help_text="The index of the row where this view ends (null if all rows)", null=True, blank=True
    )
    is_global = models.BooleanField(
        help_text="Whether the view is global or not", default=False
    )

    

    class Meta:
        abstract = True





class LabelAccessor(Accessor):
    """ An lable accessor declares the values as pixel_values of an associated pixel_view on image"""
    pixel_view =  models.ForeignKey(
        "PixelView", on_delete=models.CASCADE, related_name="label_accessors"
    )


    class Meta:
        default_related_name = "label_accessors"




class ImageAccessor(Accessor):
    """ An image accessor declares the values as ids of an associated image"""
    pass

    class Meta:
        default_related_name = "image_accessors"






class RGBRenderContext(models.Model):
    """A RGBRenderContext is a collection of views.

    It is used to group views together, for example to group all views
    that are used to represent a specific channel.

    """
    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, related_name="rgb_contexts",
    )
    description = models.CharField(max_length=8000, help_text="The description of the view", null=True, blank=True)
    name = models.CharField(max_length=1000, help_text="The name of the view")
    history = HistoryField()
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_rgbcontexts",
        blank=True,
        help_text="The users that have pinned the era",
    )
    blending = TextChoicesField(
        choices_enum=enums.BlendingChoices,
        default=enums.BlendingChoices.ADDITIVE.value,
        help_text="The blending of the channel",
    )
    z = models.IntegerField(
        help_text="The index of the z (if not in 3D mode)", default=0
    )
    t = models.IntegerField(
        help_text="The index of the t (if not in hypermode)", default=0
    )
    c = models.IntegerField(
        help_text="The index of the c (if not in multi-channel mode)", default=0
    )





class RenderTree(models.Model):
    name = models.CharField(max_length=1000, help_text="The name of the tree", default="")

    linked_contexts = models.ManyToManyField(
        RGBRenderContext, related_name="linked_trees"
    )
    tree = models.JSONField()


class AcquisitionView(View):
    """A AcquisitionView 

    The AcquisitionView is a view that describes the process of acquiring the
    image. It is used to describe the acquisition time of the image, the operator
    and the entity that the image has measured.

    """
    description = models.CharField(
        max_length=8000,
        help_text="A cleartext description of the image acquisition",
        null=True,
    )
    acquired_at = models.DateTimeField(
        auto_now_add=True, help_text="The time the image was acquired"
    )
    entity_id = models.CharField(
        max_length=1000,
        help_text="The entity that this view is for",
        null=True,
        blank=True,
    )
    operator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The user that created the image",
    )

    class Meta:
        default_related_name = "acquisition_views"


def create_default_color():
    return [255, 255, 255, 255]

class RGBView(View):
    contexts = models.ManyToManyField(
        RGBRenderContext, related_name="views"
    )
    contrast_limit_min = models.FloatField(
        help_text="The limits of the channel", null=True, blank=True
    )
    contrast_limit_max = models.FloatField(
        help_text="The limits of the channel", null=True, blank=True
    )
    gamma = models.FloatField(
        help_text="The gamma of the channel", null=True, blank=True
    )
    rescale = models.BooleanField(
        help_text="Whether the channel should be rescaled", default=False
    )
    active = models.BooleanField(
        help_text="Whether the viewis active", default=True
    )
    color_map = TextChoicesField(
        choices_enum=enums.ColorMapChoices,
        default=enums.ColorMapChoices.VIRIDIS.value,
        help_text="The applying color map of the channel",
    )
    base_color = models.JSONField(
        help_text="The base color of the channel (if using a mapped scaler) (RGBA)", default=create_default_color
    )


    history = HistoryField()

    class Meta:
        default_related_name = "rgb_views"


class TimepointView(View):
    era = models.ForeignKey(Era, on_delete=models.CASCADE, related_name="views")
    ms_since_start = models.FloatField(
        help_text="The time in ms since the start of the era",
        null=True,
        blank=True,
    )
    index_since_start = models.IntegerField(
        help_text="The index of the timepoint since the start of the era",
        null=True,
        blank=True,
    )

    history = HistoryField()

    class Meta:
        default_related_name = "timepoint_views"


class LabelView(View):
    label = models.CharField(
        max_length=1000,
        help_text="The label of the entity class",
        null=True,
    )


    history = HistoryField()

    class Meta:
        default_related_name = "label_views"


class AffineTransformationView(View):
    stage = models.ForeignKey(
        Stage, on_delete=models.CASCADE, related_name="affine_views"
    )
    affine_matrix = models.JSONField()

    history = HistoryField()

    class Meta:
        default_related_name = "affine_transformation_views"


class PixelView(View):
    """A PixelView is a view on a representation"""

    meaning = models.CharField(
        max_length=1000,
        help_text="The meaning of the pixel view",
        null=True,
        blank=True,
    )

    is_instance_mask = models.BooleanField(
        help_text="Whether the pixel view is an instance mask", default=False
    )

    history = HistoryField()

    class Meta:
        default_related_name = "pixel_views"


class ROIGroup(models.Model):
    """A ROIGroup is a collection of ROIs.

    It is used to group ROIs together, for example to group all ROIs
    that are used to represent a specific channel.

    """

    name = models.CharField(max_length=1000, help_text="The name of the ROI group")
    history = HistoryField()





def random_color():
    levels = range(32,256,32)
    return tuple(random.choice(levels) for _ in range(3))




class ROI(models.Model):
    """A ROI is a region of interest in a representation.

    This region is to be regarded as a view on the representation. Depending
    on the implementatoin (type) of the ROI, the view can be constructed
    differently. For example, a rectangular ROI can be constructed by cropping
    the representation according to its 2 vectors. while
      a polygonal ROI can be constructed by masking the
    representation with the polygon.

    The ROI can also store a name and a description. T
    his is used to display the ROI in the UI.

    """

    group = models.ForeignKey(
        ROIGroup,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rois",
        help_text="The group this ROI belongs to",
    )
    entity = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
    )

    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        help_text="The user that created the ROI",
    )
    vectors = models.JSONField(
        max_length=3000,
        help_text="A list of the ROI Vectors (specific for each type)",
        default=list,
    )
    kind = TextChoicesField(
        choices_enum=enums.RoiKindChoices,
        default=enums.RoiKindChoices.PATH.value,
        help_text="The Roi can have vasrying kind, consult your API",
    )
    color = models.CharField(
        max_length=100, blank=True, null=True, help_text="The color of the ROI (for UI)"
    )
    created_at = models.DateTimeField(
        auto_now=True, help_text="The time the ROI was created"
    )
    image = models.ForeignKey(
        Image,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="rois",
        help_text="The Representation this ROI was original used to create (drawn on)",
    )
    label = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="The label of the ROI (for UI)",
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_rois",
        blank=True,
        help_text="The users that pinned this ROI",
    )

    history = HistoryField()

    def __str__(self):
        return f"ROI creatsed by {self.creator} on {self.image.name}"


class PixelLabel(models.Model):
    """A Label is a region of interest in a representation.

    This region is to be regarded as a view on the representation. Depending
    on the implementatoin (type) of the ROI, the view can be constructed
    differently. For example, a rectangular ROI can be constructed by cropping
    the representation according to its 2 vectors. while
      a polygonal ROI can be constructed by masking the
    representation with the polygon.

    The ROI can also store a name and a description. T
    his is used to display the ROI in the UI.

    """

    value = models.FloatField()
    created_at = models.DateTimeField(
        auto_now=True, help_text="The time the ROI was created"
    )
    entity = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
    )
    view = models.ForeignKey(
        PixelView,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="labels",
        help_text="The Representation this ROI was original used to create (drawn on)",
    )
    label = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="The label of the ROI (for UI)",
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_labels",
        blank=True,
        help_text="The users that pinned this ROI",
    )

    def __str__(self):
        return f"Label on {self.view.image.name}"






class Plot(models.Model):
    entity = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
    )


    class Meta:
        abstract = True


class RenderedPlot(Plot):
    name = models.CharField(max_length=1000, help_text="The name of the plot")
    store = models.ForeignKey(
        MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the file",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoryField()







from core import signals