"""Deleting data eventually deletes its bytes, and never deletes bytes something still wants.

Ported from mikro's ``tests/test_store_purging.py``, without its mesh, table and sparse cases
(no such store exists here) and without ``measure_prefix_bytes``, which was deliberately not
vendored.

mikro asserts against a ``moto`` S3. These assert against the compose RustFS -- the same real
object store every other test here uses -- because the bug being fixed is precisely that a call
was made and deleted nothing: a zarr key is a *prefix*, and `DeleteObject` on a prefix returns
204 having removed no chunk at all. Whether a given S3 implementation really behaves that way
is not something a mock can vouch for.

The buckets are shared by the whole session and never emptied, so every assertion here is about
the keys *this test* wrote (each store's key is a fresh uuid) rather than about a bucket's whole
listing. The database is flushed per test, so the sweeper only ever sees this test's stores.

The two safety properties matter more than the feature:

- a store still referenced by anything is never purged (stores can be shared), and
- a store that was never flagged is never purged, because an unreferenced store is the normal
  state of an upload in flight rather than a sign of garbage.
"""

import datetime
from io import StringIO
from types import SimpleNamespace

import pytest
from asgiref.sync import sync_to_async
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from core import models
from core.logic import storage
from core.mutations.delete import delete_flagging_stores
from datalayer.datalayer import get_current_datalayer
from datalayer.models import BigFileStore, DatalayerStore, ZarrStore
from tests.seed import create_file, create_folder

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

DELETE_FILE = "mutation D($input: DeleteFileInput!) { deleteFile(input: $input) }"
DELETE_ARRAY_DATASET = "mutation D($input: DeleteArrayDatasetInput!) { deleteArrayDataset(input: $input) }"
DELETE_DATA_ARRAY = "mutation D($input: DeleteDataArrayInput!) { deleteDataArray(input: $input) }"

ZYX = [{"name": "z", "type": "SPACE"}, {"name": "y", "type": "SPACE"}, {"name": "x", "type": "SPACE"}]


@pytest.fixture()
def buckets(s3_client):
    """The real S3 the datalayer is configured against, with its buckets created.

    mikro's fixture of this name swaps in ``moto`` and resets the memoized ``GLOBAL_DL`` around
    it. Nothing is swapped here: ``layer`` is the process's own datalayer, pointed at the compose
    RustFS by ``settings_test.DATALAYER``, and ``s3_client`` (which this depends on) has made sure
    the ``zarr`` / ``parquet`` / ``media`` buckets exist. What the tests put beside a store's own
    objects is removed again on the way out.
    """
    extra: list[tuple[str, str]] = []
    yield SimpleNamespace(layer=get_current_datalayer(), client=s3_client, extra=extra)
    for bucket, key in extra:
        s3_client.delete_object(Bucket=bucket, Key=key)


def keys_in(buckets, bucket_key: str, prefix: str) -> set[str]:  # noqa: ANN001
    """Every object key currently under ``prefix`` in one of the datalayer's buckets."""
    bucket = buckets.layer.get_bucket_config(bucket_key).bucket
    keys: set[str] = set()
    for page in buckets.client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.update(item["Key"] for item in page.get("Contents", []))
    return keys


def put(buckets, bucket_key: str, key: str) -> None:  # noqa: ANN001
    """Put one object into a datalayer bucket."""
    bucket = buckets.layer.get_bucket_config(bucket_key).bucket
    buckets.client.put_object(Bucket=bucket, Key=key, Body=b"bytes")
    buckets.extra.append((bucket, key))


def purge(**options) -> str:
    """Run the sweeper and return its output."""
    out = StringIO()
    call_command("purge_orphaned_stores", stdout=out, stderr=out, **options)
    return out.getvalue()


def age(store: DatalayerStore, days: int) -> None:
    """Backdate a store's orphaning so the grace period has elapsed."""
    DatalayerStore.objects.filter(pk=store.pk).update(orphaned_at=timezone.now() - datetime.timedelta(days=days))


def sync(fn):  # noqa: ANN001, ANN201
    """Run a blocking ORM/boto call from an async test."""
    return sync_to_async(fn)


# --------------------------------------------------------------------------------------
# The headline: a delete flags, the sweeper collects.
# --------------------------------------------------------------------------------------


async def test_deleting_a_file_flags_its_store_and_the_sweeper_purges_it(aexecute, authenticated_context, bigfile_store, buckets):
    ctx = authenticated_context
    store = await bigfile_store(content=b"bytes", populated=True)
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "cell3.abf", folder, store=store)
    assert await sync(keys_in)(buckets, "bigfile", store.key) == {store.key}

    result = await aexecute(DELETE_FILE, {"input": {"id": str(file.id)}})
    assert not result.errors, result.errors

    # The request does no S3 work: the bytes are still there, the store is merely flagged.
    assert await sync(keys_in)(buckets, "bigfile", store.key) == {store.key}
    store = await DatalayerStore.objects.aget(pk=store.pk)
    assert store.orphaned_at is not None

    await sync(age)(store, 30)
    output = await sync(purge)()

    assert "purged" in output
    assert await sync(keys_in)(buckets, "bigfile", store.key) == set()
    assert not await DatalayerStore.objects.filter(pk=store.pk).aexists()


async def test_deleting_a_dataset_purges_every_pyramid_level(aexecute, create_array_dataset, buckets):
    """The stores hang off DataArray rows, not off the dataset -- a one-hop walk misses them.

    And each is a zarr, so each needs the prefix delete: `delete_object` against the level's key
    would succeed and leave every chunk in place.

    Made through the real mutation, so each level has a real store with a real `zarr.json`
    (mikro's seed helper attaches none, and its test has to bolt them on afterwards).
    """
    dataset = await create_array_dataset("Cells", [8, 64, 64], axes=ZYX, levels=[([8, 32, 32], "AREA"), ([8, 16, 16], "AREA")])

    store_keys = [key async for key in models.DataArray.objects.filter(dataset_id=dataset["id"]).order_by("level").values_list("store__key", flat=True)]
    assert len(store_keys) == 3 and all(store_keys), "every level must really have a store, or this test asserts nothing"

    for key in store_keys:
        for suffix in ("c/0/0", "c/0/1"):
            await sync(put)(buckets, "zarr", f"{key}/{suffix}")
        assert await sync(keys_in)(buckets, "zarr", f"{key}/") == {f"{key}/zarr.json", f"{key}/c/0/0", f"{key}/c/0/1"}
    # A sibling prefix that merely shares a leading substring must survive.
    await sync(put)(buckets, "zarr", f"{store_keys[0]}-untouched/zarr.json")

    result = await aexecute(DELETE_ARRAY_DATASET, {"input": {"id": dataset["id"]}})
    assert not result.errors, result.errors

    flagged = [store async for store in DatalayerStore.objects.filter(orphaned_at__isnull=False)]
    assert len(flagged) == 3, "every level's store must be flagged, not just the dataset's own"
    # Gathered first: a generator with an `await` in it is an async generator, and `all()` over
    # one is a TypeError rather than a check.
    survivors = [await sync(keys_in)(buckets, "zarr", f"{key}/") for key in store_keys]
    assert all(survivors), "and the request itself removed nothing"

    for store in flagged:
        await sync(age)(store, 30)
    output = await sync(purge)()
    assert output.count("purged  prefix") == 3, output

    for key in store_keys:
        assert await sync(keys_in)(buckets, "zarr", f"{key}/") == set(), "every chunk under the level's prefix, not just the key itself"
    remaining = await sync(keys_in)(buckets, "zarr", store_keys[0])
    assert remaining == {f"{store_keys[0]}-untouched/zarr.json"}, f"only the sibling prefix should remain, got {remaining}"
    assert not await DatalayerStore.objects.filter(pk__in=[store.pk for store in flagged]).aexists()


async def test_deleting_one_level_flags_only_that_levels_store(aexecute, create_array_dataset, buckets):
    """`deleteDataArray` goes through the same straddle, and the dataset's other bytes are not its business."""
    dataset = await create_array_dataset("Long", [10000], levels=[([100], "MAX")])
    base, overview = [array async for array in models.DataArray.objects.filter(dataset_id=dataset["id"]).select_related("store").order_by("level")]

    result = await aexecute(DELETE_DATA_ARRAY, {"input": {"id": str(overview.pk)}})
    assert not result.errors, result.errors

    flagged = [pk async for pk in DatalayerStore.objects.filter(orphaned_at__isnull=False).values_list("pk", flat=True)]
    assert flagged == [overview.store_id]

    await sync(age)(overview.store, 30)
    await sync(purge)()

    assert await sync(keys_in)(buckets, "zarr", f"{overview.store.key}/") == set()
    assert await sync(keys_in)(buckets, "zarr", f"{base.store.key}/") == {f"{base.store.key}/zarr.json"}, "level 0 is still the dataset's data"
    assert await DatalayerStore.objects.filter(pk=base.store_id, orphaned_at__isnull=True).aexists()


# --------------------------------------------------------------------------------------
# The two safety properties.
# --------------------------------------------------------------------------------------


async def test_a_shared_store_is_never_purged(aexecute, authenticated_context, bigfile_store, buckets):
    """Two Files on one store: deleting one must not destroy the other's bytes.

    Nothing stops this today -- no `store` FK has a unique constraint and store ids are
    client-supplied with no already-attached check -- so the sweeper's re-check is the only
    thing between a shared store and data loss.
    """
    ctx = authenticated_context
    store = await bigfile_store(content=b"bytes", populated=True)
    folder = await create_folder(ctx, "DS")
    doomed = await create_file(ctx, "first.abf", folder, store=store)
    await create_file(ctx, "second.abf", folder, store=store)

    result = await aexecute(DELETE_FILE, {"input": {"id": str(doomed.id)}})
    assert not result.errors, result.errors

    # Flagged or not by the delete, a flag is a candidate and never an authority: force the
    # candidate, so that what is under test is the sweeper's own re-check.
    await sync(age)(store, 30)
    output = await sync(purge)()

    assert "keep" in output and "still referenced" in output
    assert await sync(keys_in)(buckets, "bigfile", store.key) == {store.key}
    refreshed = await DatalayerStore.objects.aget(pk=store.pk)
    assert refreshed.orphaned_at is None, "a re-checked store must be un-flagged, not left as a standing candidate"


async def test_an_upload_in_flight_is_never_touched(bigfile_store, buckets):
    """An unreferenced store is not garbage -- it is the normal state of a live upload.

    `requestFileUpload` creates the row before the client has uploaded anything and long
    before a data row attaches. Sweeping unreferenced stores would delete uploads in progress,
    which is why only *flagged* rows are ever collectable.
    """
    store = await bigfile_store(content=b"bytes", populated=False)

    await sync(purge)(older_than=0)

    assert await sync(keys_in)(buckets, "bigfile", store.key) == {store.key}
    assert await DatalayerStore.objects.filter(pk=store.pk).aexists()


async def test_the_grace_period_holds(aexecute, authenticated_context, bigfile_store, buckets):
    """A store flagged just now survives a default run -- that is the recovery window."""
    ctx = authenticated_context
    store = await bigfile_store(content=b"bytes", populated=True)
    folder = await create_folder(ctx, "DS")
    file = await create_file(ctx, "fresh.abf", folder, store=store)

    result = await aexecute(DELETE_FILE, {"input": {"id": str(file.id)}})
    assert not result.errors, result.errors

    await sync(purge)()
    assert await sync(keys_in)(buckets, "bigfile", store.key) == {store.key}, "the default grace period must protect a fresh delete"

    await sync(purge)(older_than=0)
    assert await sync(keys_in)(buckets, "bigfile", store.key) == set(), "--older-than 0 must collect it"


async def test_the_grace_period_is_a_setting(aexecute, authenticated_context, bigfile_store, buckets, settings):
    """`DATALAYER_STORE_GRACE_DAYS` is what a run with no `--older-than` reads; seven days when unset."""
    ctx = authenticated_context
    store = await bigfile_store(content=b"bytes", populated=True)
    file = await create_file(ctx, "week-old.abf", await create_folder(ctx, "DS"), store=store)
    result = await aexecute(DELETE_FILE, {"input": {"id": str(file.id)}})
    assert not result.errors, result.errors
    await sync(age)(store, 3)

    assert "nothing orphaned longer than 7 day(s)" in await sync(purge)()
    assert await sync(keys_in)(buckets, "bigfile", store.key) == {store.key}

    settings.DATALAYER_STORE_GRACE_DAYS = 2
    assert "purged" in await sync(purge)()
    assert await sync(keys_in)(buckets, "bigfile", store.key) == set()


async def test_dry_run_deletes_nothing(bigfile_store, buckets):
    store = await bigfile_store(content=b"bytes", populated=True)
    await sync(age)(store, 30)

    output = await sync(purge)(dry_run=True)

    assert "would purge" in output
    assert await sync(keys_in)(buckets, "bigfile", store.key) == {store.key}
    assert await DatalayerStore.objects.filter(pk=store.pk).aexists()


# --------------------------------------------------------------------------------------
# Collection, in isolation from the sweeper.
# --------------------------------------------------------------------------------------


async def test_a_delete_that_rolls_back_flags_nothing(authenticated_context, bigfile_store):
    """Collection happens before the delete and flagging after it, in one transaction.

    mikro pins this by patching `File.delete` to raise. Nothing is patched here: the production
    straddle is run inside a transaction that then really rolls back, which is the situation the
    rule exists for -- "the bytes must not vanish inside a transaction that might roll back", and
    neither may a flag that says they should.
    """
    ctx = authenticated_context
    store = await bigfile_store(populated=True)
    file = await create_file(ctx, "kept.abf", await create_folder(ctx, "DS"), store=store)
    # Kept aside: `Model.delete()` sets the instance's pk to None on the way out, and the
    # rollback restores the row, not the instance -- so `file.pk` would look up nothing.
    file_pk = file.pk

    def delete_then_fail() -> None:
        with transaction.atomic():
            delete_flagging_stores(file)
            assert DatalayerStore.objects.get(pk=store.pk).orphaned_at is not None, "flagged inside the transaction"
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await sync(delete_then_fail)()

    assert await models.File.objects.filter(pk=file_pk).aexists(), "the delete rolled back"
    refreshed = await DatalayerStore.objects.aget(pk=store.pk)
    assert refreshed.orphaned_at is None, "a delete that did not happen must leave no store flagged"


async def test_a_refused_delete_flags_nothing(aexecute, authenticated_context, bot_context, create_array_dataset):
    """The guard runs before the straddle, so a caller who may not delete cannot start anyone's grace period either."""
    dataset = await create_array_dataset("Guarded", [10000], levels=[([100], "MAX")])

    denied = await aexecute(DELETE_ARRAY_DATASET, {"input": {"id": dataset["id"]}}, context=bot_context)

    assert denied.errors and "You are not allowed to delete this ArrayDataset." in str(denied.errors[0])
    assert await ZarrStore.objects.acount() == 2
    assert not await DatalayerStore.objects.filter(orphaned_at__isnull=False).aexists()


async def test_stores_orphaned_by_walks_the_cascade_to_every_level(create_array_dataset):
    """`DataArray` takes Django's fast-delete shortcut, so its rows are in `collector.fast_deletes` and never in `collector.data`: reading only the latter flagged nothing at all."""
    dataset = await create_array_dataset("Cells", [8, 64, 64], axes=ZYX, levels=[([8, 32, 32], "AREA")])
    instance = await models.ArrayDataset.objects.aget(pk=dataset["id"])

    orphaned = await sync(storage.stores_orphaned_by)(instance)

    expected = {pk async for pk in models.DataArray.objects.filter(dataset=instance).values_list("store_id", flat=True)}
    assert {store.pk for store in orphaned} == expected and len(expected) == 2
    assert not await DatalayerStore.objects.filter(orphaned_at__isnull=False).aexists(), "collecting is not flagging: the delete belongs between the two"


async def test_referrers_of_sees_a_store_a_file_points_at(authenticated_context, bigfile_store, zarr_store):
    """A store something still points at is never purged, however it is pointed at.

    Read off the *real* (downcast) class's relations: `File.store` points at `BigFileStore` and
    `DataArray.store` at `ZarrStore`, neither at `DatalayerStore`, so the base class's
    `related_objects` sees no referrer at all.
    """
    ctx = authenticated_context
    store = await bigfile_store(populated=True)
    assert await sync(storage.referrers_of)(store) == [], "a fresh store is referenced by nothing"

    await create_file(ctx, "held.abf", await create_folder(ctx, "DS"), store=store)
    base = await DatalayerStore.objects.non_polymorphic().aget(pk=store.pk)
    assert type(base) is DatalayerStore
    assert await sync(storage.referrers_of)(base), "a referenced store is still in use -- these bytes must not be collected"

    zarr = await zarr_store()
    assert await sync(storage.referrers_of)(zarr) == []
    dataset = await models.ArrayDataset.objects.acreate(name="held", creator=ctx.request.user, organization=ctx.request.organization)
    await models.DataArray.objects.acreate(level=0, dataset=dataset, store=zarr, shape=[8], chunk_shape=[8])
    assert await sync(storage.referrers_of)(zarr)


# --------------------------------------------------------------------------------------
# The "I mean it, now" path.
# --------------------------------------------------------------------------------------


async def test_deleting_a_store_row_purges_its_bytes_prefix_and_all(zarr_store, bigfile_store, buckets):
    """`DatalayerStore.delete()` ignores the grace period: bytes first, then the row, and a zarr by prefix."""
    zarr = await zarr_store(shape=[8, 8])
    await sync(put)(buckets, "zarr", f"{zarr.key}/c/0/0")
    await sync(put)(buckets, "zarr", f"{zarr.key}-sibling/zarr.json")
    blob = await bigfile_store(content=b"bytes")
    assert ZarrStore.is_prefix and not BigFileStore.is_prefix

    await sync(zarr.delete)()
    await sync(blob.delete)()

    assert await sync(keys_in)(buckets, "zarr", f"{zarr.key}/") == set()
    assert await sync(keys_in)(buckets, "zarr", zarr.key) == {f"{zarr.key}-sibling/zarr.json"}
    assert await sync(keys_in)(buckets, "bigfile", blob.key) == set()
    assert not await DatalayerStore.objects.filter(pk__in=[zarr.pk, blob.pk]).aexists()
