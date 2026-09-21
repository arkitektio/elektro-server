"""What an upload delivered, recorded at the moment the store is finalized.

Ported from mikro's ``tests/test_upload_accounting.py``, minus its ``max_bytes`` half: elektro
deliberately carries no advertised-budget column, so there is nothing here to compare a
delivered size against. What remains is the part that answers "how big is this dataset on
disk", which nothing recorded before.

The measurement lives in ``fill_info`` rather than beside the finish mutation, and that is the
whole point of these tests. ``createArrayDataset`` and ``fromFileLike`` call ``fill_info``
themselves and never invoke ``finishZarrUpload`` -- so a size recorded only on the finish path
was null for essentially every real store here.

Assertions run against the compose RustFS, like the rest of ``tests/datalayer``: the zarr case
is a paginated listing over a prefix, and a listing that silently returns nothing looks exactly
like an empty store. Whether a real S3 behaves the way the code assumes is not something a mock
can vouch for.
"""

import uuid

import pytest
from asgiref.sync import sync_to_async

import datalayer.datalayer as datalayer_module
from core import models
from datalayer.models import BigFileStore, ZarrStore

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

T = [{"name": "t", "type": "TIME"}]


def sync(fn):  # noqa: ANN001, ANN201
    """Run a blocking ORM/boto call from an async test."""
    return sync_to_async(fn)


def put_chunks(s3_client, key: str, sizes: list[int]) -> int:
    """Write chunk objects beside a store's ``zarr.json`` and return their combined size."""
    for index, size in enumerate(sizes):
        s3_client.put_object(Bucket="zarr", Key=f"{key}/c/{index}", Body=b"x" * size)
    return sum(sizes)


def prefix_bytes(s3_client, key: str) -> int:
    """The true size of everything under a store's prefix, read independently of the code under test."""
    total = 0
    for page in s3_client.get_paginator("list_objects_v2").paginate(Bucket="zarr", Prefix=f"{key}/"):
        total += sum(item["Size"] for item in page.get("Contents", []))
    return total


async def test_a_dataset_made_the_ordinary_way_records_every_levels_size(create_array_dataset, zarr_store, s3_client, aexecute):
    """The path that carries the traffic, and the one that used to record nothing.

    Each pyramid level is its own zarr store, so each is measured on its own -- there is no
    single object whose ``ContentLength`` answers for a level, let alone for the dataset.
    """
    dataset = await create_array_dataset("Measured", [1000], axes=T, levels=[([500], "AREA")])

    keys = [key async for key in models.DataArray.objects.filter(dataset_id=dataset["id"]).order_by("level").values_list("store__key", flat=True)]
    assert len(keys) == 2 and all(keys), "every level must really have a store, or this test asserts nothing"

    async for array in models.DataArray.objects.filter(dataset_id=dataset["id"]).select_related("store"):
        expected = await sync(prefix_bytes)(s3_client, array.store.key)
        assert expected > 0, "the fixture seeds a real zarr.json, so the prefix is not empty"
        assert array.store.size_bytes == expected, f"level {array.level} did not record its size"


async def test_a_size_is_the_sum_over_the_prefix_not_the_object_at_it(zarr_store, s3_client):
    """A zarr's key names a directory. ``head_object`` on it answers for nothing.

    The same confusion that made ``DeleteObject`` on a prefix delete nothing, which is why
    ``measure_bytes`` and ``purge_bytes`` split on the identical ``is_prefix`` flag.
    """
    store = await zarr_store(shape=[1000], dimension_names=["t"])
    chunk_bytes = await sync(put_chunks)(s3_client, store.key, [512, 128])
    expected = await sync(prefix_bytes)(s3_client, store.key)
    assert expected > chunk_bytes, "the manifest counts too"

    layer = datalayer_module.get_current_datalayer()
    await sync(store.fill_info)(layer)

    store = await ZarrStore.objects.aget(pk=store.pk)
    assert store.populated is True
    assert store.size_bytes == expected


async def test_a_single_object_store_measures_the_object(bigfile_store):
    """The other half of the ``is_prefix`` split: one key, one HEAD.

    Worth pinning beside the zarr case because the two take entirely different S3 calls, and
    a store type that ends up on the wrong side of the split reports a confident zero.
    """
    body = b"y" * 2048
    store = await bigfile_store(content=body)

    layer = datalayer_module.get_current_datalayer()
    await sync(store.fill_info)(layer)

    store = await BigFileStore.objects.aget(pk=store.pk)
    assert store.populated is True
    assert store.size_bytes == len(body)


async def test_a_file_reports_the_size_its_store_measured(aexecute, bigfile_store):
    """``File.size`` and ``store.sizeBytes`` are one number, read once.

    ``fromFileLike`` used to take its own HEAD -- passing the raw ``key`` rather than
    ``build_object_key``, so under a bucket with a configured ``subpath`` it asked about the
    wrong object. Reading what ``fill_info`` already measured removes both the second call and
    the chance of two answers.
    """
    body = b"z" * 777
    store = await bigfile_store(content=body)

    result = await aexecute(
        "mutation F($input: FromFileLike!) { fromFileLike(input: $input) { id size store { sizeBytes } } }",
        {"input": {"file": str(store.pk), "fileName": "cell3.abf"}},
    )

    assert not result.errors, result.errors
    file = result.data["fromFileLike"]
    assert file["size"] == len(body)
    assert file["store"]["sizeBytes"] == len(body)


async def test_a_finalization_survives_a_measurement_it_cannot_take(zarr_store, monkeypatch):
    """Accounting must never cost an upload.

    The bytes are written and the manifest is parsed by the time this runs, so a listing that
    fails is a bookkeeping problem. Losing the store over it would trade something that matters
    for something that does not.
    """
    store = await zarr_store(shape=[1000], dimension_names=["t"])

    def refuse(*args, **kwargs):
        raise RuntimeError("listing is unavailable")

    monkeypatch.setattr(datalayer_module.Datalayer, "measure_prefix_bytes", refuse)
    layer = datalayer_module.get_current_datalayer()
    await sync(store.fill_info)(layer)

    store = await ZarrStore.objects.aget(pk=store.pk)
    assert store.populated is True
    assert store.size_bytes is None


async def test_a_failed_measurement_does_not_erase_a_recorded_size(zarr_store, s3_client, monkeypatch):
    """A re-``fill_info`` that cannot measure must leave the last good number alone.

    Null means "not measured". Overwriting a real size with it would turn a transient listing
    failure into a permanent loss of the only record of how big a dataset is.
    """
    store = await zarr_store(shape=[1000], dimension_names=["t"])
    await sync(put_chunks)(s3_client, store.key, [256])
    expected = await sync(prefix_bytes)(s3_client, store.key)

    layer = datalayer_module.get_current_datalayer()
    await sync(store.fill_info)(layer)
    store = await ZarrStore.objects.aget(pk=store.pk)
    assert store.size_bytes == expected

    def refuse(*args, **kwargs):
        raise RuntimeError("listing is unavailable")

    monkeypatch.setattr(datalayer_module.Datalayer, "measure_prefix_bytes", refuse)
    await sync(store.fill_info)(layer)

    store = await ZarrStore.objects.aget(pk=store.pk)
    assert store.size_bytes == expected


async def test_an_absent_prefix_measures_zero_rather_than_raising(zarr_store):
    """An unfinished or already-purged store reports the truth instead of an error.

    ``measure_prefix_bytes`` is reached by the sweeper's neighbours and by any re-finalization,
    both of which can run against a prefix that is no longer there.
    """
    layer = datalayer_module.get_current_datalayer()
    assert await sync(layer.measure_prefix_bytes)("zarr", uuid.uuid4().hex) == 0
