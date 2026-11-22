"""A list of array datasets reads what each row shows with the list, not row by row.

``multiscale``, ``shape``, ``axisNames``, ``valueUnit`` and ``simulation`` are each derived
from a related row. They are prefetched for the whole list, so a page of datasets costs
the same number of statements whether it holds two datasets or six -- and every row still
answers what it answered when asked alone.
"""

import pytest

from tests.coords._helpers import counted
from tests.seed import SOMA_MODEL

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

ROWS = """query { arrayDatasets(ordering: [{id: ASC}]) {
  id name multiscale shape axisNames valueUnit spec simulation { duration model { id name } }
} }"""
ALONE = """query ($id: ID!) { arrayDataset(id: $id) { id name multiscale shape axisNames valueUnit spec simulation { duration model { id name } } } }"""


async def _make(create_array_dataset, model, i: int) -> None:
    if i % 3 == 0:
        await create_array_dataset(f"run-{i}", [1600], anchors=[{"axisAnchors": [], "valueUnit": {"unit": "mV"}, "simulation": {"model": str(model.id), "duration": "40 ms", "dt": "25 us"}}])
    elif i % 3 == 1:
        await create_array_dataset(f"pyramid-{i}", [1000], value_unit="pA", levels=[([500], None)])
    else:
        await create_array_dataset(f"bare-{i}", [2, 300])


async def test_rows_answer_as_alone_and_cost_the_same_for_any_page(aexecute, make_neuron_model, create_array_dataset):
    model = await make_neuron_model(json_model=SOMA_MODEL)
    for i in range(3):
        await _make(create_array_dataset, model, i)
    few, few_statements = await counted(aexecute, ROWS)

    rows = few["arrayDatasets"]
    for row in rows:
        alone = await aexecute(ALONE, {"id": row["id"]})
        assert not alone.errors, alone.errors
        assert alone.data["arrayDataset"] == row
    by_name = {row["name"].split("-")[0]: row for row in rows}
    assert by_name["run"]["simulation"] == {"duration": "40 ms", "model": {"id": str(model.id), "name": model.name}}
    assert (by_name["run"]["valueUnit"], by_name["run"]["multiscale"]) == ("mV", False)
    assert (by_name["pyramid"]["valueUnit"], by_name["pyramid"]["multiscale"], by_name["pyramid"]["shape"]) == ("pA", True, [1000])
    assert (by_name["bare"]["valueUnit"], by_name["bare"]["simulation"], by_name["bare"]["shape"]) == (None, None, [2, 300])

    for i in range(3, 9):
        await _make(create_array_dataset, model, i)
    many, many_statements = await counted(aexecute, ROWS)
    assert len(many["arrayDatasets"]) == 9
    assert many_statements == few_statements, "a longer page asks the same questions, once each"


EXPERIMENTS = "query ($id: ID!) { arrayDataset(id: $id) { experiments { id } experimentLayers { experiment { id } } } }"


async def test_experiments_drawing_a_dataset_each_once(aexecute, authenticated_context):
    from tests import seed
    from tests.coords._helpers import add_layer, create_experiment

    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Drawn")
    lenses = [await seed.create_lens(ctx, dataset), await seed.create_lens(ctx, dataset, slices=[{"axis": "y", "start": 0, "stop": 4}])]
    first = await create_experiment(ctx, "First")
    second = await create_experiment(ctx, "Second")
    await add_layer(ctx, first, lenses[0])
    await add_layer(ctx, first, lenses[1])
    await add_layer(ctx, second, lenses[0])
    undrawn = await seed.create_array_dataset(ctx, "Undrawn")

    res = await aexecute(EXPERIMENTS, {"id": str(dataset.pk)})
    assert not res.errors, res.errors
    assert [e["id"] for e in res.data["arrayDataset"]["experiments"]] == [str(first.pk), str(second.pk)]
    assert len(res.data["arrayDataset"]["experimentLayers"]) == 3
    none = await aexecute(EXPERIMENTS, {"id": str(undrawn.pk)})
    assert none.data["arrayDataset"]["experiments"] == []
