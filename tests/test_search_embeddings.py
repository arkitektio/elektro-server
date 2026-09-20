"""Array, table and sparse datasets embed their name + description on save; ``search`` is hybrid.

Real model (potion-base-8M), real Postgres with pgvector -- what the service runs. Where a
test needs rows at *known* distances from the query it writes the vectors directly: ``e0`` is
the real embedding of the query, ``_vec(d)`` a unit vector at cosine distance ``d`` from it.
Rows are built with the seed helpers (a dataset needs its coordinate graph), then given their
description through ``save()`` -- the path a user edit takes.
"""

import math

import numpy as np
import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from core.models import ArrayDataset, SparseDataset, TableDataset
from embeddings import engine
from embeddings.healer import reembed_all, reembed_stale
from tests.seed import create_array_dataset, create_sparse_dataset, create_table_dataset

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

QUERY = "detect cells"


def _query(field: str, filter_name: str, order_name: str) -> str:
    return f"""
    query ($filters: {filter_name}, $ordering: [{order_name}!]) {{
      {field}(filters: $filters, ordering: $ordering) {{ name }}
    }}
    """


async def _dataset(seed, ctx, name: str, description: str | None = None):
    row = await seed(ctx, name=name)
    if description is not None:
        row.description = description
        await row.asave()
    return row


MODELS = [
    pytest.param(ArrayDataset, create_array_dataset, _query("arrayDatasets", "ArrayDatasetFilter", "ArrayDatasetOrder"), id="array_dataset"),
    pytest.param(TableDataset, create_table_dataset, _query("tableDatasets", "TableDatasetFilter", "TableDatasetOrder"), id="table_dataset"),
    pytest.param(SparseDataset, create_sparse_dataset, _query("sparseDatasets", "SparseDatasetFilter", "SparseDatasetOrder"), id="sparse_dataset"),
]


def _unit_orthogonal(e0: np.ndarray) -> np.ndarray:
    axis = np.zeros_like(e0)
    axis[int(np.argmin(np.abs(e0)))] = 1.0
    u = axis - float(np.dot(axis, e0)) * e0
    return u / np.linalg.norm(u)


def _vec(e0: np.ndarray, distance: float) -> list[float]:
    theta = math.acos(1.0 - distance)
    return (math.cos(theta) * e0 + math.sin(theta) * _unit_orthogonal(e0)).astype(float).tolist()


async def _pin(model, row, e0, distance, embedding_model=None):
    await model.objects.filter(pk=row.pk).aupdate(embedding=_vec(e0, distance) if distance is not None else None, embedding_model=embedding_model or engine.model_id())


async def _names(aexecute, query, search, ordering=None):
    res = await aexecute(query, {"filters": {"search": search}, "ordering": ordering or []})
    assert not res.errors, res.errors
    return [row["name"] for row in next(iter(res.data.values()))]


@pytest.mark.parametrize(("model", "seed", "query"), MODELS)
async def test_create_embeds(authenticated_context, model, seed, query):
    row = await _dataset(seed, authenticated_context, "Segment nuclei", "Find cell nuclei in a fluorescence image")
    await row.arefresh_from_db()
    assert row.embedding is not None and len(row.embedding) == 256
    assert abs(sum(x * x for x in row.embedding) - 1.0) < 1e-4
    assert row.embedding_model == engine.model_id()


async def test_editing_the_description_reembeds_without_history(authenticated_context):
    row = await _dataset(create_array_dataset, authenticated_context, "Export", "Write a table to a spreadsheet")
    before = list((await ArrayDataset.objects.aget(pk=row.pk)).embedding)
    row = await ArrayDataset.objects.aget(pk=row.pk)
    row.description = "Detect mitochondria in electron micrographs"
    await row.asave()
    assert list((await ArrayDataset.objects.aget(pk=row.pk)).embedding) != before
    history = row.provenance.model
    assert not any(field.name in ("embedding", "embedding_model") for field in history._meta.get_fields())


async def test_healer_reembeds_rows_of_another_model(authenticated_context):
    models = [ArrayDataset, TableDataset, SparseDataset]
    rows = [await _dataset(seed, authenticated_context, "Blur", "Gaussian blur") for seed in (create_array_dataset, create_table_dataset, create_sparse_dataset)]
    for model, row in zip(models, rows, strict=True):
        await model.objects.filter(pk=row.pk).aupdate(embedding=None, embedding_model="some/older-model")
    assert await sync_to_async(reembed_all)(models) == 3
    for model, row in zip(models, rows, strict=True):
        fresh = await model.objects.aget(pk=row.pk)
        assert fresh.embedding is not None and fresh.embedding_model == engine.model_id()
    assert await sync_to_async(reembed_stale)(ArrayDataset) == 0


@pytest.mark.parametrize(("model", "seed", "query"), MODELS)
async def test_semantic_match_without_substring(aexecute, authenticated_context, model, seed, query):
    await _dataset(seed, authenticated_context, "Segment nuclei", "Find cell nuclei in a fluorescence image and detect every cell")
    await _dataset(seed, authenticated_context, "Export spreadsheet", "Write a table to an xlsx file on disk")
    names = await _names(aexecute, query, QUERY)
    assert "Segment nuclei" in names and "Export spreadsheet" not in names


@pytest.mark.parametrize(("model", "seed", "query"), MODELS)
async def test_lexical_only_when_disabled(aexecute, authenticated_context, model, seed, query):
    await _dataset(seed, authenticated_context, "Detect cells")
    await _dataset(seed, authenticated_context, "Segment nuclei", "detect cells in an image")
    with override_settings(EMBEDDINGS={**engine._settings(), "ENABLED": False}):
        assert await _names(aexecute, query, QUERY) == ["Detect cells"]


@pytest.mark.parametrize(("model", "seed", "query"), MODELS)
async def test_ranking_lexical_first_then_by_distance(aexecute, authenticated_context, model, seed, query):
    e0 = np.asarray(engine.embed_query(QUERY))
    await _pin(model, await _dataset(seed, authenticated_context, "Far"), e0, 0.5)
    await _pin(model, await _dataset(seed, authenticated_context, "Near"), e0, 0.1)
    await _pin(model, await _dataset(seed, authenticated_context, "Mid"), e0, 0.3)
    await _pin(model, await _dataset(seed, authenticated_context, "Beyond"), e0, 0.7)
    await _pin(model, await _dataset(seed, authenticated_context, "Detect cells here"), e0, None)
    assert await _names(aexecute, query, QUERY) == ["Detect cells here", "Near", "Mid", "Far"]


@pytest.mark.parametrize(("model", "seed", "query"), MODELS)
async def test_stale_embedding_model_is_not_a_vector_hit(aexecute, authenticated_context, model, seed, query):
    e0 = np.asarray(engine.embed_query(QUERY))
    await _pin(model, await _dataset(seed, authenticated_context, "Old model near"), e0, 0.05, "some/older-model")
    await _pin(model, await _dataset(seed, authenticated_context, "Old model detect cells"), e0, 0.05, "some/older-model")
    assert await _names(aexecute, query, QUERY) == ["Old model detect cells"]


@pytest.mark.parametrize(("model", "seed", "query"), MODELS)
async def test_explicit_ordering_replaces_the_ranking(aexecute, authenticated_context, model, seed, query):
    e0 = np.asarray(engine.embed_query(QUERY))
    await _pin(model, await _dataset(seed, authenticated_context, "Zeta"), e0, 0.1)
    await _pin(model, await _dataset(seed, authenticated_context, "Alpha"), e0, 0.4)
    assert await _names(aexecute, query, QUERY) == ["Zeta", "Alpha"]
    assert await _names(aexecute, query, QUERY, ordering=[{"name": "ASC"}]) == ["Alpha", "Zeta"]


async def test_null_search_means_no_constraint(aexecute, authenticated_context):
    """Under USE_DEPRECATED_FILTERS an explicit ``null`` reaches the resolver; it filters nothing."""
    await _dataset(create_array_dataset, authenticated_context, "Anything")
    res = await aexecute(_query("arrayDatasets", "ArrayDatasetFilter", "ArrayDatasetOrder"), {"filters": {"search": None}, "ordering": []})
    assert not res.errors, res.errors
    assert [row["name"] for row in res.data["arrayDatasets"]] == ["Anything"]


async def test_unloadable_model_degrades_to_substring(aexecute, authenticated_context):
    e0 = np.asarray(engine.embed_query(QUERY))
    await _pin(ArrayDataset, await _dataset(create_array_dataset, authenticated_context, "Near"), e0, 0.05)
    await _dataset(create_array_dataset, authenticated_context, "Detect cells")
    try:
        with override_settings(EMBEDDINGS={**engine._settings(), "MODEL_PATH": "/nonexistent/embeddings"}):
            engine.reset()
            assert await _names(aexecute, _query("arrayDatasets", "ArrayDatasetFilter", "ArrayDatasetOrder"), QUERY) == ["Detect cells"]
    finally:
        engine.reset()
