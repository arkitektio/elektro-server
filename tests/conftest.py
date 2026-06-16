import os
import time

import boto3
import psycopg
import pytest
from moto import mock_aws

from authentikate.models import Client, Organization, User, Membership
from django.contrib.contenttypes.management import create_contenttypes
from django.db.models.signals import post_migrate
from kante.context import HttpContext, UniversalRequest
from strawberry.http.temporal_response import TemporalResponse
from dokker import testing


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
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")


@pytest.fixture
def create_bucket1(s3):
    s3.create_bucket(Bucket="babanana")


@pytest.fixture
def create_bucket2(s3):
    s3.create_bucket(Bucket="cabanana")


@pytest.fixture(scope="session")
def backend_stack():
    docker_compose_path = os.path.join(os.path.dirname(__file__), "integration", "docker-compose.yaml")

    with testing(docker_compose_path) as e:
        e.inspect()

        e.down()

        e.up()

        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(
                    dbname="testdb",
                    user="test",
                    password="test",
                    host="localhost",
                    port=5555,
                    connect_timeout=1,
                ) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)

        yield


@pytest.fixture(scope="session")
def django_db_modify_db_settings(backend_stack):
    """Start the backend services before pytest-django configures the test DB."""
    yield


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    # Every transaction=True test teardown flushes the DB and re-fires
    # post_migrate, which rebuilds all contenttypes and permissions from the
    # model registry (~1s per test). The rows never change between tests, so
    # snapshot them once and swap the rebuild for a bulk re-insert with the
    # original pks (keeps guardian FKs and the ContentType pk cache valid).
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    with django_db_blocker.unblock():
        contenttypes = list(ContentType.objects.all())
        permissions = list(Permission.objects.all())

    post_migrate.disconnect(dispatch_uid="django.contrib.auth.management.create_permissions")
    post_migrate.disconnect(create_contenttypes)

    def restore_contenttypes_and_permissions(sender, **kwargs):
        # post_migrate fires once per app config on flush; restore once.
        if getattr(sender, "label", None) != "contenttypes":
            return
        ContentType.objects.bulk_create(contenttypes, ignore_conflicts=True)
        Permission.objects.bulk_create(permissions, ignore_conflicts=True)

    post_migrate.connect(
        restore_contenttypes_and_permissions,
        dispatch_uid="tests.restore_contenttypes_and_permissions",
    )
    yield

    # The async tests run sync ORM code in asgiref's executor threads, whose
    # connections outlive the tests and block dropping the test database
    # ("database is being accessed by other users"). Kill them before
    # pytest-django's teardown drops the database.
    from django.db import connections

    with django_db_blocker.unblock():
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        connections.close_all()


@pytest.fixture(scope="function")
def authenticated_context(db, backend_stack):
    # Match the identity the static "test" token resolves to (see settings_test
    # STATIC_TOKENS + authentikate's token expansion), so the org/user on this
    # context is the same one the schema's AuthentikateExtension authenticates as
    # at resolve time — otherwise organization-scoped queries see no data.
    user, _ = User.objects.get_or_create(
        sub="1", iss="static_issuer", defaults={"username": "static_issuer_1"}
    )
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="static_org")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
    )

    request = UniversalRequest(
        _extensions={"token": "test"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": "Bearer test"}, type="http")


@pytest.fixture(scope="function")
def other_org_context(db, backend_stack) -> HttpContext:
    """A context for a user in a different organization (static token "othertest")."""
    user, _ = User.objects.get_or_create(
        sub="9", iss="static_issuer", defaults={"username": "static_issuer_9"}
    )
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="other_org")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
    )

    request = UniversalRequest(
        _extensions={"token": "othertest"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": "Bearer othertest"}, type="http")


@pytest.fixture(scope="function")
def simple_api_context(db, backend_stack) -> HttpContext:
    user, _ = User.objects.get_or_create(
        sub="1", iss="static_issuer", defaults={"username": "static_issuer_1"}
    )
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="static_org")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
    )

    request = UniversalRequest(
        _extensions={"token": "test"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": "Bearer test"}, type="http")
