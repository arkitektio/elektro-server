import json
import os
import time
import uuid
from types import SimpleNamespace

import boto3
import psycopg
import pytest
from asgiref.sync import sync_to_async
from botocore.config import Config
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

        # `initc` runs `mc alias set ... http://minio:9000` as its first step, but
        # compose only waits for minio's container to *start* (service_started), not
        # for it to accept connections — so without this it races minio and dies with
        # "connection refused". Gate it on minio's /minio/health/live (200 once serving).
        e.add_health_check(
            url="http://localhost:6890/minio/health/live",
            service="minio",
            max_retries=30,
            timeout=1,  # ~30s total, matching the postgres deadline below
        )
        e.check_health()

        e.run("initc", command="python init.py")

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


# ---------------------------------------------------------------------------
# Mutation-test helpers: execute against the schema + build prerequisite rows.
# ---------------------------------------------------------------------------


@pytest.fixture
def aexecute(authenticated_context):
    """Run a GraphQL document against the schema, defaulting to the authed context."""
    from elektro_server.schema import schema

    async def _run(query, variables=None, context=None):
        return await schema.execute(
            query,
            variable_values=variables or {},
            context_value=context or authenticated_context,
        )

    return _run


# Minimal valid Zarr v3 array metadata — enough for Datalayer.get_zarr_metadata.
ZARR_V3_METADATA = {
    "zarr_format": 3,
    "node_type": "array",
    "shape": [4, 4],
    "data_type": "float64",
    "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": [4, 4]}},
    "chunk_key_encoding": {"name": "default"},
    "fill_value": 0,
    "codecs": [],
}


@pytest.fixture
def minio_client(backend_stack):
    """boto3 S3 client pointed at the compose MinIO (see settings_test.DATALAYER)."""
    from django.conf import settings

    dl = settings.DATALAYER
    client = boto3.client(
        "s3",
        aws_access_key_id=dl["access_key"],
        aws_secret_access_key=dl["secret_key"],
        endpoint_url=f"{dl['protocol']}://{dl['host']}:{dl['port']}",
        region_name=dl["region"],
        config=Config(signature_version="s3v4"),
    )
    # `initc` provisions these, but create-if-missing guards against init races.
    for bucket in ("zarr", "media", "parquet"):
        try:
            client.create_bucket(Bucket=bucket)
        except Exception:
            pass
    return client


@pytest.fixture
def zarr_store(authenticated_context, minio_client):
    """Factory: create a ZarrStore row and (by default) seed its zarr.json in MinIO."""
    from datalayer.models import ZarrStore

    @sync_to_async
    def _make(context=None, seed=True):
        ctx = context or authenticated_context
        key = uuid.uuid4().hex
        store = ZarrStore.objects.create(
            organization=ctx.request.organization,
            key=key,
            bucket="zarr",
        )
        if seed:
            minio_client.put_object(
                Bucket="zarr",
                Key=f"{key}/zarr.json",
                Body=json.dumps(ZARR_V3_METADATA).encode("utf-8"),
            )
        return store

    return _make


@pytest.fixture
def bigfile_store(authenticated_context):
    """Factory: create a BigFileStore row (fill_info is local, no S3 needed)."""
    from datalayer.models import BigFileStore

    @sync_to_async
    def _make(context=None):
        ctx = context or authenticated_context
        return BigFileStore.objects.create(
            organization=ctx.request.organization,
            key=uuid.uuid4().hex,
            bucket="media",
        )

    return _make


@pytest.fixture
def make_trace(authenticated_context):
    """Factory: create a Trace row (store is nullable, so no object store needed)."""
    from core.models import Trace

    @sync_to_async
    def _make(context=None, name="trace", dataset=None):
        ctx = context or authenticated_context
        return Trace.objects.create(
            name=name,
            dataset=dataset,
            creator=ctx.request.user,
            organization=ctx.request.organization,
        )

    return _make


@pytest.fixture
def make_neuron_model(authenticated_context):
    """Factory: create a NeuronModel row (unique hash per row).

    environment is NOT NULL on NeuronModel, so one is minted automatically when
    not supplied by the caller.
    """
    from core.models import ModEnvironment, NeuronModel

    @sync_to_async
    def _make(context=None, name="NeuronModel", environment=None, json_model=None):
        ctx = context or authenticated_context
        if environment is None:
            environment = ModEnvironment.objects.create(
                name=f"env-{uuid.uuid4().hex}", organization=ctx.request.organization
            )
        return NeuronModel.objects.create(
            name=name,
            hash=uuid.uuid4().hex,
            json_model=json_model if json_model is not None else {},
            creator=ctx.request.user,
            environment=environment,
        )

    return _make


@pytest.fixture
def make_simulation_chain(authenticated_context):
    """Factory: NeuronModel -> Trace -> Simulation -> Recording + Stimulus.

    Returns a namespace with .neuron_model/.time_trace/.simulation/.recording/.stimulus
    so experiment tests can reference real Stimulus/Recording ids without an object store.
    """
    from core import models

    @sync_to_async
    def _make(context=None):
        ctx = context or authenticated_context
        environment = models.ModEnvironment.objects.create(
            name=f"env-{uuid.uuid4().hex}", organization=ctx.request.organization
        )
        nm = models.NeuronModel.objects.create(
            name="NeuronModel",
            hash=uuid.uuid4().hex,
            json_model={},
            creator=ctx.request.user,
            environment=environment,
        )
        time_trace = models.Trace.objects.create(
            name="time", creator=ctx.request.user, organization=ctx.request.organization
        )
        sim = models.Simulation.objects.create(
            model=nm, time_trace=time_trace, name="sim", duration=400.0, creator=ctx.request.user
        )
        rec = models.Recording.objects.create(
            simulation=sim, trace=time_trace, kind="VOLTAGE", cell="soma", location="0", position="0.5"
        )
        stim = models.Stimulus.objects.create(
            simulation=sim, trace=time_trace, kind="CURRENT", cell="soma", location="0", position="0.5"
        )
        return SimpleNamespace(
            neuron_model=nm, time_trace=time_trace, simulation=sim, recording=rec, stimulus=stim
        )

    return _make


@pytest.fixture
def upload_zarr_to_grant(backend_stack):
    """Write a real Zarr v3 array straight to MinIO through obstore, using the
    credentials/bucket/key returned by a requestZarrUpload grant."""
    from django.conf import settings

    @sync_to_async
    def _upload(grant, shape=(4, 4), chunks=(4, 4)):
        import numpy as np
        import zarr
        from obstore.store import S3Store
        from zarr.storage import ObjectStore

        dl = settings.DATALAYER
        kwargs = dict(
            prefix=grant["key"],
            access_key_id=grant["accessKey"],
            secret_access_key=grant["secretKey"],
            endpoint=f"{dl['protocol']}://{dl['host']}:{dl['port']}",
            region=dl.get("region", "us-east-1"),
            virtual_hosted_style_request=False,  # MinIO uses path-style addressing
            client_options={"allow_http": True},  # http:// endpoint
        )
        if grant.get("sessionToken"):
            kwargs["session_token"] = grant["sessionToken"]

        s3 = S3Store(grant["bucket"], **kwargs)
        arr = zarr.create_array(store=ObjectStore(s3), shape=shape, chunks=chunks, dtype="float64")
        arr[:] = np.arange(int(np.prod(shape)), dtype="float64").reshape(shape)

    return _upload


@pytest.fixture
def read_zarr_from_grant(backend_stack):
    """Read a Zarr array back from MinIO through obstore using the credentials/
    bucket/key returned by a requestZarrAccess grant. Returns the numpy array."""
    from django.conf import settings

    @sync_to_async
    def _read(grant):
        import zarr
        from obstore.store import S3Store
        from zarr.storage import ObjectStore

        dl = settings.DATALAYER
        kwargs = dict(
            prefix=grant["key"],
            access_key_id=grant["accessKey"],
            secret_access_key=grant["secretKey"],
            endpoint=f"{dl['protocol']}://{dl['host']}:{dl['port']}",
            region=dl.get("region", "us-east-1"),
            virtual_hosted_style_request=False,
            client_options={"allow_http": True},
        )
        if grant.get("sessionToken"):
            kwargs["session_token"] = grant["sessionToken"]

        s3 = S3Store(grant["bucket"], **kwargs)
        arr = zarr.open_array(store=ObjectStore(s3, read_only=True), mode="r")
        return arr[:]

    return _read
