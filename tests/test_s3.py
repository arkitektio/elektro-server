from strawberry_django.test.client import TestClient
import boto3

def test_s3_directly(s3):
    s3.create_bucket(Bucket="somebucket")

    result = s3.list_buckets()
    assert len(result["Buckets"]) == 1

def test_bucket_creation(create_bucket1, create_bucket2):
    buckets = boto3.client("s3").list_buckets()
    assert len(buckets["Buckets"]) == 2
