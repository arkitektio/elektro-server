import pytest
import boto3
import moto
from moto import mock_s3
import os

import pytest
from core.models import Image, Dataset
from django.contrib.auth import get_user_model
from authentikate.models import App
from mikro_server.schema import schema
from guardian.shortcuts import get_perms
from asgiref.sync import sync_to_async
from kante.context import ChannelsContext, EnhancendChannelsHTTPRequest




@pytest.fixture(scope="function")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

@pytest.fixture(scope="function")
def s3(aws_credentials):
    with mock_s3():
        yield boto3.client("s3", region_name="us-east-1")

@pytest.fixture
def create_bucket1(s3):
    s3.create_bucket(Bucket="babanana")

@pytest.fixture
def create_bucket2(s3):
    s3.create_bucket(Bucket="cabanana")




@pytest.fixture
@pytest.mark.asyncio
def authenticated_context(db) :
    user =  get_user_model().objects.create(username="fart", password="123456789")

    app = App.objects.create(client_id="oinsoins")

    return ChannelsContext(
            request=EnhancendChannelsHTTPRequest(
                user=user,
                app=app,
                body="",
                scopes=["openid"],
                consumer=None,
            ),
            response=None,
        ),