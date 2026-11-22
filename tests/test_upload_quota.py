"""Who may upload, and how much: ``datalayer.upload_roles`` and ``datalayer.quotas``.

Vendored from mikro's test of the same name. Runs through the real schema against the dokker
stack. Usage is a sum of measured ``size_bytes``, so the "already holds N bytes" state is
written straight onto store rows -- the same number ``finish`` would have measured -- rather
than uploading gigabytes.
"""

from typing import Protocol

import arkitekt_datalayer.datalayer as datalayer_module
import pytest
from arkitekt_datalayer import quota
from arkitekt_datalayer.models import MediaStore, ZarrStore
from asgiref.sync import sync_to_async
from authentikate.models import Client, Membership, Organization, User
from kante.context import HttpContext, UniversalRequest
from pytest_django.fixtures import SettingsWrapper
from strawberry.http.temporal_response import TemporalResponse
from strawberry.types import ExecutionResult

from elektro_server.schema import schema
from tests.fixture_types import BackendStack

GIB = 1024**3

REQUEST_ZARR = "mutation { requestZarrUpload(input: {}) { store maxBytes } }"
REQUEST_MEDIA = """
mutation($size: ByteCount!) {
  requestMediaUpload(input: {originalFileName: "a.nwb", fileSize: $size}) { store maxBytes }
}
"""


def _context(token: str, sub: str, roles: list[str]) -> HttpContext:
    """A same-org context for the static ``token`` (see ``settings_test``), holding ``roles``."""
    user, _ = User.objects.get_or_create(
        sub=sub, iss="static_issuer", defaults={"username": f"static_issuer_{sub}"}
    )
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(identifier="static_issuer#static_org")
    membership, _ = Membership.objects.get_or_create(
        user=user, organization=org, defaults={"roles": roles}
    )

    request = UniversalRequest(
        _extensions={"token": token},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore
    return HttpContext(
        request=request,
        response=TemporalResponse(),
        headers={"Authorization": f"Bearer {token}"},
        type="http",
    )


@pytest.fixture()
def editor_context(db: None, backend_stack: BackendStack) -> HttpContext:
    return _context("editortest", "3", ["elektro_editor"])


@pytest.fixture()
def viewer_context(db: None, backend_stack: BackendStack) -> HttpContext:
    """In the org, but holding no role in ``upload_roles``."""
    return _context("viewertest", "4", [])


class QuotaConfigurer(Protocol):
    """``quotas(**block)``: set ``datalayer.quotas`` to ``block`` for the rest of the test."""

    def __call__(self, **block: object) -> None: ...


@pytest.fixture()
def quotas(
    settings: SettingsWrapper, monkeypatch: pytest.MonkeyPatch
) -> QuotaConfigurer:
    """Set ``datalayer.quotas`` for one test; the memoized datalayer is rebuilt around it."""
    monkeypatch.setattr(datalayer_module, "GLOBAL_DL", None)

    def configure(**block: object) -> None:
        settings.DATALAYER = {**settings.DATALAYER, "quotas": block}
        datalayer_module.GLOBAL_DL = None

    return configure


def _errors(result: ExecutionResult) -> str:
    return " ".join(error.message for error in result.errors or [])


@sync_to_async
def _hold(ctx: HttpContext, size: int, **kwargs: object) -> MediaStore:
    """Give the context's user a finished store of ``size`` measured bytes."""
    return MediaStore.objects.create(
        organization=kwargs.pop("organization", ctx.request.organization),
        creator=kwargs.pop("creator", ctx.request.user),
        key=f"held-{MediaStore.objects.count()}",
        bucket="media",
        populated=True,
        size_bytes=size,
        **kwargs,
    )


# --- roles -------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_editor_can_upload(
    db: None, editor_context: HttpContext, quotas: QuotaConfigurer
) -> None:
    quotas()
    result = await schema.execute(REQUEST_ZARR, context_value=editor_context)
    assert not result.errors, result.errors
    assert result.data is not None

    store = await ZarrStore.objects.aget(id=result.data["requestZarrUpload"]["store"])
    assert store.creator_id == editor_context.request.user.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_bot_can_upload(
    db: None, bot_context: HttpContext, quotas: QuotaConfigurer
) -> None:
    quotas()
    result = await schema.execute(REQUEST_ZARR, context_value=bot_context)
    assert not result.errors, result.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_role_outside_upload_roles_cannot_upload(
    db: None, viewer_context: HttpContext, quotas: QuotaConfigurer
) -> None:
    """With no ``upload_roles`` configured, uploading takes ``elektro_editor``, which a viewer lacks."""
    quotas()
    result = await schema.execute(REQUEST_ZARR, context_value=viewer_context)
    assert result.errors and "roles" in _errors(result)


# --- per-upload limit --------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_per_upload_quota_is_advertised_and_enforced(
    db: None, authenticated_context: HttpContext, quotas: QuotaConfigurer
) -> None:
    quotas(default={"max_upload_bytes": "500GiB"})

    result = await schema.execute(REQUEST_ZARR, context_value=authenticated_context)
    assert not result.errors, result.errors
    assert result.data is not None
    assert result.data["requestZarrUpload"]["maxBytes"] == 500 * GIB

    result = await schema.execute(
        REQUEST_MEDIA,
        variable_values={"size": 600 * GIB},
        context_value=authenticated_context,
    )
    assert result.errors and "per-upload quota" in _errors(result)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_without_quotas_the_bucket_default_is_advertised(
    db: None, authenticated_context: HttpContext, quotas: QuotaConfigurer
) -> None:
    quotas()
    result = await schema.execute(REQUEST_ZARR, context_value=authenticated_context)
    assert not result.errors, result.errors
    assert result.data is not None
    assert (
        result.data["requestZarrUpload"]["maxBytes"]
        == datalayer_module.get_current_datalayer()
        .get_bucket_config("zarr")
        .default_max_bytes
    )


# --- totals ------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_user_quota_counts_only_that_user(
    db: None,
    authenticated_context: HttpContext,
    editor_context: HttpContext,
    quotas: QuotaConfigurer,
) -> None:
    quotas(organizations={"static_issuer#static_org": {"max_user_bytes": 10 * GIB}})
    await _hold(authenticated_context, 10 * GIB)

    result = await schema.execute(REQUEST_ZARR, context_value=authenticated_context)
    assert result.errors and "Your storage quota" in _errors(result)

    result = await schema.execute(REQUEST_ZARR, context_value=editor_context)
    assert not result.errors, result.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_declared_size_counts_toward_the_user_quota(
    db: None, authenticated_context: HttpContext, quotas: QuotaConfigurer
) -> None:
    quotas(default={"max_user_bytes": 10 * GIB})
    await _hold(authenticated_context, 6 * GIB)

    result = await schema.execute(
        REQUEST_MEDIA,
        variable_values={"size": 5 * GIB},
        context_value=authenticated_context,
    )
    assert result.errors and "Your storage quota" in _errors(result)

    result = await schema.execute(
        REQUEST_MEDIA,
        variable_values={"size": 3 * GIB},
        context_value=authenticated_context,
    )
    assert not result.errors, result.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_user_override_beats_the_org_limit(
    db: None, authenticated_context: HttpContext, quotas: QuotaConfigurer
) -> None:
    quotas(
        organizations={
            "static_issuer#static_org": {
                "max_user_bytes": 1 * GIB,
                "users": {"1": {"max_user_bytes": "20GiB"}},
            }
        }
    )
    await _hold(authenticated_context, 10 * GIB)

    result = await schema.execute(REQUEST_ZARR, context_value=authenticated_context)
    assert not result.errors, result.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_org_quota_counts_everyone_and_stays_in_its_org(
    db: None,
    authenticated_context: HttpContext,
    editor_context: HttpContext,
    quotas: QuotaConfigurer,
) -> None:
    quotas(default={"max_org_bytes": 10 * GIB})
    await _hold(authenticated_context, 6 * GIB)
    await _hold(editor_context, 4 * GIB)
    other, _ = await Organization.objects.aget_or_create(
        identifier="static_issuer#other_org"
    )
    await _hold(authenticated_context, 50 * GIB, organization=other)

    result = await schema.execute(REQUEST_ZARR, context_value=editor_context)
    assert result.errors and "Organization storage quota" in _errors(result)

    assert (
        await sync_to_async(quota.organization_usage)(
            authenticated_context.request.organization.id
        )
        == 10 * GIB
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_orphaned_store_frees_its_bytes(
    db: None, authenticated_context: HttpContext, quotas: QuotaConfigurer
) -> None:
    from django.utils import timezone

    quotas(default={"max_user_bytes": 10 * GIB})
    await _hold(authenticated_context, 10 * GIB, orphaned_at=timezone.now())

    result = await schema.execute(REQUEST_ZARR, context_value=authenticated_context)
    assert not result.errors, result.errors


# --- resolution (no database) ------------------------------------------------


def test_resolution_is_most_specific_first() -> None:
    config = quota.QuotaConfig(
        default={
            "max_upload_bytes": "1GiB",
            "max_user_bytes": "1GiB",
            "max_org_bytes": "1GiB",
        },
        organizations={
            "lab": {
                "max_user_bytes": "2GiB",
                "users": {"alice": {"max_upload_bytes": "3GiB"}},
            }
        },
    )

    alice = quota.resolve_quota(config, "lab", "alice")
    assert (alice.max_upload_bytes, alice.max_user_bytes, alice.max_org_bytes) == (
        3 * GIB,
        2 * GIB,
        GIB,
    )

    bob = quota.resolve_quota(config, "lab", "bob")
    assert (bob.max_upload_bytes, bob.max_user_bytes) == (GIB, 2 * GIB)

    elsewhere = quota.resolve_quota(config, "other", "alice")
    assert (elsewhere.max_upload_bytes, elsewhere.max_user_bytes) == (GIB, GIB)

    assert quota.resolve_quota(quota.QuotaConfig(), "lab", None) == quota.Quota(
        None, None, None
    )
