"""Cells and sections by compound id: `cell(id: "model:cell")`, `section(id: "model:cell:section")`.

A cell or section id is only unique within its model -- ``soma`` is in most of them -- so a
detail query needs the model in the id. Each part is percent-encoded, so a ``:`` inside a
section id cannot make the compound ambiguous; ``compoundId`` on the types is exactly what the
queries take, and ``id`` stays the config's own id, which the recording sites name.
"""

import pytest

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

CONFIG = {
    "cells": [
        {
            "id": "pyr",
            "biophysics": {"compartments": []},
            "topology": {"sections": [{"id": "soma", "length": "20 um"}, {"id": "dend:1", "length": "200 um", "parent": {"parent": "soma"}}]},
        },
        {"id": "int", "biophysics": {"compartments": []}, "topology": {"sections": [{"id": "soma", "length": "10 um"}]}},
    ]
}

CONFIG_IDS = "query ($id: ID!) { neuronModel(id: $id) { config { cells { id compoundId topology { sections { id compoundId } } } } } }"
CELL = "query ($id: ID!) { cell(id: $id) { id compoundId model { id } topology { sections { id } } } }"
SECTION = "query ($id: ID!) { section(id: $id) { id compoundId model { id } cell { id compoundId } sessions { datasets { id } } } }"


async def test_every_cell_and_section_carries_the_compound_id_its_detail_query_takes(aexecute, make_neuron_model):
    nm = await make_neuron_model(name="two cells", json_model=CONFIG)
    res = await aexecute(CONFIG_IDS, {"id": str(nm.id)})
    assert not res.errors, res.errors
    cells = res.data["neuronModel"]["config"]["cells"]
    assert [(c["id"], c["compoundId"]) for c in cells] == [("pyr", f"{nm.id}:pyr"), ("int", f"{nm.id}:int")]
    assert [(s["id"], s["compoundId"]) for s in cells[0]["topology"]["sections"]] == [("soma", f"{nm.id}:pyr:soma"), ("dend:1", f"{nm.id}:pyr:dend%3A1")], "a ':' in an id is encoded"

    for cell in cells:
        got = await aexecute(CELL, {"id": cell["compoundId"]})
        assert not got.errors, got.errors
        assert (got.data["cell"]["id"], got.data["cell"]["compoundId"], got.data["cell"]["model"]) == (cell["id"], cell["compoundId"], {"id": str(nm.id)})
        for section in cell["topology"]["sections"]:
            detail = await aexecute(SECTION, {"id": section["compoundId"]})
            assert not detail.errors, detail.errors
            assert detail.data["section"]["id"] == section["id"] and detail.data["section"]["compoundId"] == section["compoundId"], "round trip"
            assert detail.data["section"]["cell"] == {"id": cell["id"], "compoundId": cell["compoundId"]}
            assert detail.data["section"]["sessions"] == []


async def test_a_section_id_is_its_cells(aexecute, make_neuron_model):
    """`soma` of `int` is not `soma` of `pyr`: the compound id says which."""
    nm = await make_neuron_model(name="two cells", json_model=CONFIG)
    res = await aexecute(CELL, {"id": f"{nm.id}:int"})
    assert not res.errors, res.errors
    assert res.data["cell"]["topology"]["sections"] == [{"id": "soma"}]


@pytest.mark.parametrize(
    ("query", "compound", "refusal"),
    [
        (CELL, "{model}", "not a compound id of the form 'model:cell'"),
        (CELL, "{model}:pyr:soma", "not a compound id of the form 'model:cell'"),
        (SECTION, "{model}:pyr", "not a compound id of the form 'model:cell:section'"),
        (SECTION, "{model}::soma", "not a compound id"),
        (CELL, "{model}:basket", "has no cell 'basket'. Its cells are ['int', 'pyr']"),
        (SECTION, "{model}:int:dend%3A1", "Cell 'int' of model 'two cells' has no section 'dend:1'. Its sections are ['soma']"),
    ],
    ids=["cell-without-cell", "cell-with-section", "section-without-section", "empty-part", "unknown-cell", "section-of-another-cell"],
)
async def test_a_compound_id_names_something_the_model_has(aexecute, make_neuron_model, query, compound, refusal):
    nm = await make_neuron_model(name="two cells", json_model=CONFIG)
    res = await aexecute(query, {"id": compound.format(model=nm.id)})
    assert res.errors and refusal in str(res.errors[0]), res.errors


async def test_a_compound_id_is_scoped_by_its_model(aexecute, make_neuron_model, other_org_context):
    theirs = await make_neuron_model(context=other_org_context, name="theirs", json_model=CONFIG)
    for query, compound in ((CELL, f"{theirs.id}:pyr"), (SECTION, f"{theirs.id}:pyr:soma")):
        res = await aexecute(query, {"id": compound})
        assert res.errors and res.data is None, "another organization's model is not found, whatever cell is asked of it"
