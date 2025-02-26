from kante.types import Info
import strawberry

from core import types, models, scalars
import json
from django.conf import settings
from .accessor import *
from core.datalayer import get_current_datalayer


@strawberry.input()
class RequestTableUploadInput:
    key: str
    datalayer: str


@strawberry.input
class PinTableInput:
    id: strawberry.ID
    pin: bool


def pin_table(
    info: Info,
    input: PinTableInput,
) -> types.Table:
    raise NotImplementedError("TODO")


def request_table_upload(
    info: Info, input: RequestTableUploadInput
) -> types.Credentials:
    """Request upload credentials for a given key"""
    print("Desired Datalayer")
    datalayer = get_current_datalayer()
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowAllS3ActionsInUserFolder",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:*"],
                "Resource": "arn:aws:s3:::*",
            },
        ],
    }

    response = datalayer.sts.assume_role(
        RoleArn="arn:xxx:xxx:xxx:xxxx",
        RoleSessionName="sdfsdfsdf",
        Policy=json.dumps(policy, separators=(",", ":")),
        DurationSeconds=40000,
    )

    print(response)

    path = f"s3://{settings.PARQUET_BUCKET}/{input.key}"

    store = models.ParquetStore.objects.create(
        path=path, key=input.key, bucket=settings.PARQUET_BUCKET
    )

    aws = {
        "access_key": response["Credentials"]["AccessKeyId"],
        "secret_key": response["Credentials"]["SecretAccessKey"],
        "session_token": response["Credentials"]["SessionToken"],
        "status": "success",
        "key": input.key,
        "bucket": settings.PARQUET_BUCKET,
        "datalayer": input.datalayer,
        "store": store.id,
    }

    return types.Credentials(**aws)


@strawberry.input()
class RequestTableAccessInput:
    store: strawberry.ID
    duration: int | None


@strawberry.input()
class DeleteTableInput:
    id: strawberry.ID


def delete_table(
    info: Info,
    input: DeleteTableInput,
) -> strawberry.ID:
    item = models.Table.objects.get(id=input.id)
    item.delete()
    return input.id


def request_table_access(
    info: Info, input: RequestTableAccessInput
) -> types.AccessCredentials:
    """Request upload credentials for a given key"""

    store = models.ParquetStore.objects.get(id=input.store)

    datalayer = get_current_datalayer()
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowAllS3ActionsInUserFolder",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:*"],
                "Resource": "arn:aws:s3:::*",
            },
        ],
    }

    response = datalayer.sts.assume_role(
        RoleArn="arn:xxx:xxx:xxx:xxxx",
        RoleSessionName="sdfsdfsdf",
        Policy=json.dumps(policy, separators=(",", ":")),
        DurationSeconds=input.duration or 40000,
    )

    aws = {
        "access_key": response["Credentials"]["AccessKeyId"],
        "secret_key": response["Credentials"]["SecretAccessKey"],
        "session_token": response["Credentials"]["SessionToken"],
        "key": store.key,
        "bucket": store.bucket,
        "path": store.path,
    }

    return types.AccessCredentials(**aws)


@strawberry.input
class FromParquetLike:
    dataframe: scalars.ParquetLike = strawberry.field(description="The parquet dataframe to create the table from")
    name: str = strawberry.field(description="The name of the table")
    origins: list[strawberry.ID] | None = strawberry.field(default=None, description="The IDs of tables this table was derived from")
    dataset: strawberry.ID | None = strawberry.field(default=None, description="The dataset ID this table belongs to")
    label_accessors: list[PartialLabelAccessorInput] | None = strawberry.field(default=None, description="Label accessors to create for this table")
    image_accessors: list[PartialImageAccessorInput] | None = strawberry.field(default=None, description="Image accessors to create for this table")


def from_parquet_like(
    info: Info,
    input: FromParquetLike,
) -> types.Table:
    store = models.ParquetStore.objects.get(id=input.dataframe)
    store.fill_info()

    table = models.Table.objects.create(
        dataset_id=input.dataset,
        creator=info.context.request.user,
        name=input.name,
        store=store,
    )

    if input.label_accessors:
        for accessor in input.label_accessors:
            models.LabelAccessor.objects.create(
                table=table,
                pixel_view=models.PixelView.objects.get(id=accessor.pixel_view),
                **accessor_kwargs_from_input(accessor),
            )

    if input.image_accessors:
        for accessor in input.image_accessors:
            models.ImageAccessor.objects.create(
                table=table,
                **accessor_kwargs_from_input(accessor),
            )

    return table
