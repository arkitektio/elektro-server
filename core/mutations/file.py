from kante.types import Info
import strawberry

from core import types, models, scalars
from core.datalayer import get_current_datalayer
import json
from django.conf import settings


@strawberry.input()
class RequestFileUploadInput:
    key: str
    datalayer: str
    hash: str | None = None


@strawberry.input
class DeleteFileInput:
    id: strawberry.ID


def delete_file(
    info: Info,
    input: DeleteFileInput,
) -> strawberry.ID:
    view = models.File.objects.get(
        id=input.id,
    )
    view.delete()
    return input.id


@strawberry.input
class PinFileInput:
    id: strawberry.ID
    pin: bool


def pin_file(
    info: Info,
    input: PinFileInput,
) -> types.File:
    raise NotImplementedError("TODO")


def request_file_upload(info: Info, input: RequestFileUploadInput) -> types.Credentials:
    """Request upload credentials for a given key"""
    print("Desired Datalayer")

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

    datalayer = get_current_datalayer()

    response = datalayer.sts.assume_role(
        RoleArn="arn:xxx:xxx:xxx:xxxx",
        RoleSessionName="sdfsdfsdf",
        Policy=json.dumps(policy, separators=(",", ":")),
        DurationSeconds=40000,
    )

    print(response)

    path = f"s3://{settings.FILE_BUCKET}/{input.key}"

    store = models.BigFileStore.objects.create(path=path, key=input.key, bucket=settings.FILE_BUCKET)

    aws = {
        "access_key": response["Credentials"]["AccessKeyId"],
        "secret_key": response["Credentials"]["SecretAccessKey"],
        "session_token": response["Credentials"]["SessionToken"],
        "status": "success",
        "key": input.key,
        "bucket": settings.FILE_BUCKET,
        "datalayer": input.datalayer,
        "store": store.id,
    }

    return types.Credentials(**aws)


def request_file_upload_presigned(info: Info, input: RequestFileUploadInput) -> types.PresignedPostCredentials:
    """Request upload credentials for a given key with"""
    print("Desired Datalayer")

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

    datalayer = get_current_datalayer()

    response = datalayer.s3v4.generate_presigned_post(
        Bucket=settings.FILE_BUCKET,
        Key=input.key,
        Fields=None,
        Conditions=None,
        ExpiresIn=50000,
    )

    print(response)

    path = f"s3://{settings.FILE_BUCKET}/{input.key}"

    store, _ = models.BigFileStore.objects.get_or_create(path=path, key=input.key, bucket=settings.FILE_BUCKET)

    aws = {
        "key": response["fields"]["key"],
        "x_amz_algorithm": response["fields"]["x-amz-algorithm"],
        "x_amz_credential": response["fields"]["x-amz-credential"],
        "x_amz_date": response["fields"]["x-amz-date"],
        "x_amz_signature": response["fields"]["x-amz-signature"],
        "policy": response["fields"]["policy"],
        "bucket": settings.FILE_BUCKET,
        "datalayer": input.datalayer,
        "store": store.id,
    }

    return types.PresignedPostCredentials(**aws)


@strawberry.input()
class RequestFileAccessInput:
    store: strawberry.ID
    duration: int | None


def request_file_access(info: Info, input: RequestFileAccessInput) -> types.AccessCredentials:
    """Request upload credentials for a given key"""

    store = models.BigFileStore.objects.get(id=input.store)

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

    datalayer = get_current_datalayer()

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
class FromFileLike:
    name: str
    file: scalars.FileLike
    origins: list[strawberry.ID] | None = None
    dataset: strawberry.ID | None = None


def from_file_like(
    info: Info,
    input: FromFileLike,
) -> types.File:
    store = models.BigFileStore.objects.get(id=input.file)
    store.fill_info()

    table = models.File.objects.create(
        dataset_id=input.dataset,
        creator=info.context.request.user,
        name=input.name,
        store=store,
    )

    return table


@strawberry.input
class DeleteFileInput:
    id: strawberry.ID


def delete_era(
    info: Info,
    input: DeleteFileInput,
) -> strawberry.ID:
    item = models.File.objects.get(id=input.id)
    item.delete()
    return input.id
