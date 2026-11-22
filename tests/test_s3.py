import boto3
from botocore.client import BaseClient


def test_s3_directly(s3: BaseClient) -> None:
    s3.create_bucket(Bucket="somebucket")

    result = s3.list_buckets()
    assert len(result["Buckets"]) == 1


def test_bucket_creation(create_bucket1: None, create_bucket2: None) -> None:
    buckets = boto3.client("s3").list_buckets()
    assert len(buckets["Buckets"]) == 2
