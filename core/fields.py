from django.db import models
from django.core.exceptions import ValidationError
import re


def validate_s3(value: str) -> None:
    s3_pattern = r"^s3://.+/.+/.+"
    if not re.match(s3_pattern, value):
        raise ValidationError(
            "Invalid S3 path format. Should be s3://datalayer/bucket_name/object_key",
            code="invalid",
        )


class S3Field(models.CharField):
    description = "CharField to store S3 path for Zarr dataset with validation"

    def __init__(self, *args, **kwargs) -> None:
        kwargs["max_length"] = kwargs.get("max_length", 500)

        super().__init__(*args, **kwargs)
