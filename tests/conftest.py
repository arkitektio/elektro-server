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

        # `initc` runs `rc alias set ... http://rustfs:9000` as its first step, but
        # compose only waits for rustfs's container to *start* (service_started), not
        # for it to accept connections — so without this it races rustfs and dies with
        # "connection refused". Gate it on rustfs's /health (200 once serving).
        e.add_health_check(
            url="http://localhost:6890/health",
            service="rustfs",
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

        # The suite builds its schema straight from the models (migrations disabled), so the
        # cube extension migration never runs here -- but CREATE TABLE for
        # Annotation.bbox_cube needs the type to exist. Install it into template1 so the test
        # database pytest-django creates from it inherits it, and into testdb itself for
        # anything connecting directly.
        for dbname in ("template1", "testdb"):
            with psycopg.connect(dbname=dbname, user="test", password="test", host="localhost", port=5555, autocommit=True) as connection:
                connection.execute("CREATE EXTENSION IF NOT EXISTS cube")

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
def bot_context(db, backend_stack) -> HttpContext:
    """A non-admin user (static token "bottest") in the SAME org as authenticated_context.

    Holds only the "bot" role, so the delete guard actually applies to it -- the context used
    to exercise the denial path through GraphQL. Vendored from mikro's conftest.
    """
    user, _ = User.objects.get_or_create(
        sub="2", iss="static_issuer", defaults={"username": "static_issuer_2"}
    )
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="static_org")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
        defaults={"roles": ["bot"]},
    )

    request = UniversalRequest(
        _extensions={"token": "bottest"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": "Bearer bottest"}, type="http")


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


def fresh_request(ctx: HttpContext) -> HttpContext:
    """A new request for the same identity.

    Per-request memos live on the context (kante's ``_loaders``): the placement search of an
    experiment is built once per request and reused by every view that asks. A test that
    executes two documents against one context object is therefore not making two requests,
    and would read the first one's answers back after a mutation changed them.
    """
    request = UniversalRequest(
        _extensions=dict(ctx.request._extensions),
        _client=ctx.request._client,
        _user=ctx.request._user,
        _organization=ctx.request._organization,
    )
    request.set_membership(ctx.request._membership)  # type: ignore[arg-type]
    return HttpContext(request=request, response=TemporalResponse(), headers=ctx.headers, type="http")


@pytest.fixture
def aexecute(authenticated_context):
    """Run a GraphQL document against the schema, as one request, defaulting to the authed identity."""
    from elektro_server.schema import schema

    async def _run(query, variables=None, context=None):
        return await schema.execute(
            query,
            variable_values=variables or {},
            context_value=fresh_request(context or authenticated_context),
        )

    return _run


def zarr_v3_metadata(shape: list[int], dimension_names: list[str | None] | None = None) -> dict:
    """Minimal valid Zarr v3 array metadata -- enough for Datalayer.get_zarr_metadata.

    The server reads this and never a chunk, so a store is fully described by it: its shape
    is what an axis declaration is checked against, and its dimension names, when present,
    are what the declared axis names must agree with.
    """
    metadata = {
        "zarr_format": 3,
        "node_type": "array",
        "shape": list(shape),
        "data_type": "float64",
        "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": list(shape)}},
        "chunk_key_encoding": {"name": "default"},
        "fill_value": 0,
        "codecs": [],
    }
    if dimension_names is not None:
        metadata["dimension_names"] = list(dimension_names)
    return metadata


# A one-dimensional signal: the one shape whose axes need no declaring (a single TIME axis).
ZARR_V3_METADATA = zarr_v3_metadata([8])


@pytest.fixture
def s3_client(backend_stack):
    """boto3 S3 client pointed at the compose RustFS (see settings_test.DATALAYER)."""
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
def zarr_store(authenticated_context, s3_client):
    """Factory: create a ZarrStore row and (by default) seed its zarr.json in RustFS."""
    from datalayer.models import ZarrStore

    @sync_to_async
    def _make(context=None, seed=True, shape=None, dimension_names=None):
        ctx = context or authenticated_context
        key = uuid.uuid4().hex
        store = ZarrStore.objects.create(
            organization=ctx.request.organization,
            key=key,
            bucket="zarr",
        )
        if seed:
            metadata = zarr_v3_metadata(shape, dimension_names) if shape is not None else ZARR_V3_METADATA
            s3_client.put_object(
                Bucket="zarr",
                Key=f"{key}/zarr.json",
                Body=json.dumps(metadata).encode("utf-8"),
            )
        return store

    return _make


CREATE_ARRAY_DATASET = """
mutation ($input: CreateArrayDatasetInput!) {
  createArrayDataset(input: $input) {
    id
    name
    shape
    axisNames
    valueUnit
    spec
    multiscale
    folder { id name }
    intrinsicSystem { id name axes { name type unit } }
    dataArrays { id level shape scaleMethod }
    anchors { id coordinates channelLabel { label } valueUnit { unit } }
  }
}
"""

#: The axes a store of a given rank is declared with when a test does not say: a recording.
_DEFAULT_AXES = {
    1: [{"name": "t", "type": "TIME"}],
    2: [{"name": "t", "type": "TIME"}, {"name": "c", "type": "CHANNEL"}],
}


@pytest.fixture
def create_array_dataset(aexecute, zarr_store):
    """Factory: an array dataset made the way a client makes one -- a real zarr.json in RustFS, then ``createArrayDataset``.

    The first of the two steps every interpretation test takes: data enters here, and
    ``createBlock`` / ``createSimulation`` then name it by id. Returns the mutation's payload,
    or the raw result when ``raw=True`` (for a test about a refusal).
    """

    async def _make(name="dataset", shape=None, *, axes=None, value_unit=None, anchors=None, levels=None, derived_from=None, folder=None, context=None, raw=False):
        shape = list(shape or [1000])
        axes = axes or _DEFAULT_AXES[len(shape)]
        names = [axis["name"] for axis in axes]
        store = await zarr_store(context=context, shape=shape, dimension_names=names)
        scales = []
        for level, (level_shape, method) in enumerate(levels or [], start=1):
            level_store = await zarr_store(context=context, shape=list(level_shape), dimension_names=names)
            scales.append({"level": level, "array": str(level_store.pk), **({"scaleMethod": method} if method else {})})

        all_anchors = list(anchors or [])
        if value_unit is not None:
            all_anchors.append({"axisAnchors": [], "valueUnit": {"unit": value_unit}})

        payload = {"data": str(store.pk), "scales": scales, "name": name, "axes": axes}
        if all_anchors:
            payload["anchors"] = all_anchors
        if derived_from is not None:
            payload["derivedFrom"] = derived_from
        if folder is not None:
            payload["folder"] = str(folder)

        result = await aexecute(CREATE_ARRAY_DATASET, {"input": payload}, context=context)
        if raw:
            return result
        assert not result.errors, result.errors
        return result.data["createArrayDataset"]

    return _make


@pytest.fixture
def bigfile_store(authenticated_context, s3_client):
    """Factory: create a BigFileStore row and (by default) put its bytes in RustFS.

    ``fromFileLike`` reads the object's size off the store, so a file made from a store whose
    upload never happened is refused -- pass ``content=None`` for that case.
    """
    from datalayer.models import BigFileStore

    @sync_to_async
    def _make(context=None, content=b"elektro", **kwargs):
        ctx = context or authenticated_context
        key = uuid.uuid4().hex
        store = BigFileStore.objects.create(organization=ctx.request.organization, key=key, bucket="media", **kwargs)
        if content is not None:
            s3_client.put_object(Bucket="media", Key=key, Body=content)
        return store

    return _make


@pytest.fixture
def make_dataset(authenticated_context):
    """Factory: create an ArrayDataset row with no grid and no levels -- for tests about filing and tenancy, not about the graph."""
    from core.models import ArrayDataset

    @sync_to_async
    def _make(context=None, name="dataset", folder=None):
        ctx = context or authenticated_context
        return ArrayDataset.objects.create(
            name=name,
            folder=folder,
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
    """Factory: NeuronModel -> Simulation on its clock -> a Recording and a Stimulus, each over its own dataset.

    Built the way ``createSimulation`` builds it, without an object store (see
    ``tests/seed.py``): every dataset owns its sample grid and gets its own timing edge onto
    the run's one clock. ``timing`` picks how -- ``"sampling"`` for a sampling law (a fixed
    recording interval, the default) or ``"lookup"`` for a times dataset (a variable time step).

    Returns a namespace with .neuron_model/.simulation/.clock/.recording/.stimulus,
    .grid (the recording's sample grid), .stimulus_grid, and .time_dataset, which is None
    unless the run is timed by a lookup.
    """
    from core import models
    from core.logic import clocks
    from tests import seed

    @sync_to_async
    def _make(context=None, *, name="sim", samples=400, rate="10 kHz", t_start="0 ms", timing="sampling", unit="millisecond"):
        from kanne_server import scalars as quantities

        def parse(scalar, text):
            """A pint string, lowered to kanne's canonical integer exactly as the API boundary lowers it."""
            return quantities.SCALAR_MAP[scalar].parse_value(text)

        ctx = context or authenticated_context
        creation = seed._creation(ctx)
        environment = models.ModEnvironment.objects.create(name=f"env-{uuid.uuid4().hex}", organization=ctx.request.organization)
        nm = models.NeuronModel.objects.create(name="NeuronModel", hash=uuid.uuid4().hex, json_model={}, creator=ctx.request.user, environment=environment)

        clock = clocks.create_clock(name=f"{name}/clock", unit=unit, ctx=creation)
        sim = models.Simulation.objects.create(model=nm, clock=clock, name=name, duration=parse(quantities.Duration, "40 ms"), creator=ctx.request.user)

        rec_dataset = seed._seed_array_dataset_sync(ctx, f"{name}/soma.v", seed.T_AXES, [[samples]], None, "mV", None)
        stim_dataset = seed._seed_array_dataset_sync(ctx, f"{name}/iclamp", seed.T_AXES, [[samples]], None, "nA", None)
        rec = models.Recording.objects.create(simulation=sim, dataset=rec_dataset, kind="VOLTAGE", cell="soma", location="0", position=0.5)
        stim = models.Stimulus.objects.create(simulation=sim, dataset=stim_dataset, kind="CURRENT", cell="soma", location="0", position=0.5)

        time_dataset = None
        if timing != "sampling":
            time_dataset = seed._seed_array_dataset_sync(ctx, f"{name}/times", seed.T_AXES, [[samples]], None, unit, None)
        # One edge per dataset, all onto the run's one clock.
        for dataset in (rec_dataset, stim_dataset):
            if time_dataset is None:
                clocks.write_sampling_law(grid=dataset.coordinate_system, clock=clock, sampling_rate=parse(quantities.Frequency, rate), t_start=parse(quantities.Duration, t_start), ctx=creation)
            else:
                clocks.write_time_lookup(grid=dataset.coordinate_system, clock=clock, times=time_dataset, input_axis="t", ctx=creation)

        return SimpleNamespace(
            neuron_model=nm,
            simulation=sim,
            clock=clock,
            grid=rec_dataset.coordinate_system,
            stimulus_grid=stim_dataset.coordinate_system,
            recording=rec,
            stimulus=stim,
            time_dataset=time_dataset,
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
