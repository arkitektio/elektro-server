from kante.types import Info
import strawberry

from core import types, models, scalars
from core.datalayer import get_current_datalayer
import json
from django.conf import settings
from django.contrib.auth import get_user_model


@strawberry.input()
class RequestMediaUploadInput:
    key: str
    datalayer: str


def request_media_upload(info: Info, input: RequestMediaUploadInput) -> types.PresignedPostCredentials:
    """Request upload credentials for a given key"""

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

    response = datalayer.s3v4.generate_presigned_post(
            Bucket=settings.MEDIA_BUCKET,
            Key=input.key,
            Fields=None,
            Conditions=None,
            ExpiresIn=50000,
        )

    print(response)

    path = f"s3://{settings.MEDIA_BUCKET}/{input.key}"

    store, _ = models.MediaStore.objects.get_or_create(
        path=path, key=input.key, bucket=settings.MEDIA_BUCKET
    )

    aws = {
        "key": response["fields"]["key"],
        "x_amz_algorithm": response["fields"]["x-amz-algorithm"],
        "x_amz_credential": response["fields"]["x-amz-credential"],
        "x_amz_date": response["fields"]["x-amz-date"],
        "x_amz_signature": response["fields"]["x-amz-signature"],
        "policy": response["fields"]["policy"],
        "bucket": settings.MEDIA_BUCKET,
        "datalayer": input.datalayer,
        "store": store.id,
    }

    return types.PresignedPostCredentials(**aws)
