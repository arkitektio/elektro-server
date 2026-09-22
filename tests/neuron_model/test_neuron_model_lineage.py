"""A neuron model's ancestry is an edge of the coordinate graph, not a column.

`NeuronModel.parent` used to be a self-FK that recorded no validity, no value relation and no
provenance, was exposed nowhere in GraphQL, and that `lineageGraph` could not see. These pin
the replacement: a model owns a space, its lineage is an UNMAPPABLE derivation edge out of it,
and every walk that answers for a table or a dataset now answers for a model too.
"""

import pytest

from core.models import Axis, CoordinateSystem, ModEnvironment, NeuronModel, Transformation

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_NEURON_MODEL = """
mutation ($input: CreateNeuronModelInput!) {
  createNeuronModel(input: $input) {
    id
    name
    coordinateSystem { id axes { name type } }
    derivedFrom { id kind output { id } }
  }
}
"""

MODEL_LINEAGE = """
query ($id: ID!) {
  neuronModel(id: $id) {
    id
    derivedFrom { id kind }
    derivedInto { __typename ... on NeuronModel { id name } }
  }
}
"""

LINEAGE_GRAPH = """
query ($coordinateSystem: ID!) {
  lineageGraph(coordinateSystem: $coordinateSystem) {
    nodes { __typename ... on NeuronModel { id name } }
    edges { id kind }
  }
}
"""


def _config(v_init="-67 mV"):
    return {"cells": [], "vInit": v_init, "temperature": "36 degC"}


async def _env(context, name):
    return await ModEnvironment.objects.acreate(name=name, organization=context.request.organization)


async def test_a_created_model_owns_a_space_with_one_index_axis(aexecute, authenticated_context):
    env = await _env(authenticated_context, "env-space")
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "Solo", "environment": str(env.id), "config": _config()}},
    )
    assert not res.errors, res.errors

    system = res.data["createNeuronModel"]["coordinateSystem"]
    assert system is not None
    # One INDEX axis and nothing placeable -- the same degenerate space a table with no
    # coordinate columns gets. Named "object", not "cell": an INDEX axis claims integer
    # positions, and a model's cells are addressed by string id.
    assert [(axis["name"], axis["type"]) for axis in system["axes"]] == [("object", "INDEX")]
    # A model written from scratch came from nothing.
    assert res.data["createNeuronModel"]["derivedFrom"] == []


async def test_derived_from_records_the_parent_as_an_unmappable_edge(aexecute, make_neuron_model):
    parent = await make_neuron_model(name="Ancestor")
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {
            "input": {
                "name": "Descendant",
                "config": _config(),
                "derivedFrom": [{"kind": "NEURON_MODEL", "neuronModel": str(parent.id), "valueRelation": "TRANSFORMED"}],
            }
        },
    )
    assert not res.errors, res.errors

    edges = res.data["createNeuronModel"]["derivedFrom"]
    assert len(edges) == 1
    assert edges[0]["kind"] == "UNMAPPABLE"
    assert edges[0]["output"]["id"] == str(parent.coordinate_system_id)


async def test_parent_sugar_and_derived_from_produce_the_same_edge(aexecute, make_neuron_model):
    parent = await make_neuron_model(name="SugarParent")

    sugared = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "ViaSugar", "parent": str(parent.id), "config": _config("-60 mV")}},
    )
    explicit = await aexecute(
        CREATE_NEURON_MODEL,
        {
            "input": {
                "name": "ViaDerivedFrom",
                "config": _config("-61 mV"),
                "derivedFrom": [{"kind": "NEURON_MODEL", "neuronModel": str(parent.id)}],
            }
        },
    )
    assert not sugared.errors, sugared.errors
    assert not explicit.errors, explicit.errors

    def shape(res):
        return [(edge["kind"], edge["output"]["id"]) for edge in res.data["createNeuronModel"]["derivedFrom"]]

    assert shape(sugared) == shape(explicit)


async def test_naming_the_parent_twice_is_refused(aexecute, make_neuron_model):
    # The sugar and the explicit entry could disagree about order, and order is priority here.
    parent = await make_neuron_model(name="DoubleNamed")
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {
            "input": {
                "name": "Ambiguous",
                "parent": str(parent.id),
                "config": _config(),
                "derivedFrom": [{"kind": "NEURON_MODEL", "neuronModel": str(parent.id)}],
            }
        },
    )
    assert res.errors
    assert not await NeuronModel.objects.filter(name="Ambiguous").aexists()


async def test_environment_is_inherited_through_the_derivation(aexecute, authenticated_context, make_neuron_model):
    # Inheritance used to ride on the `parent` column. It now reads the first NEURON_MODEL
    # source, which is the primary parent whichever way it was written.
    env = await _env(authenticated_context, "inherited-env")
    parent = await make_neuron_model(name="EnvSource", environment=env)
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {
            "input": {
                "name": "Inheritor",
                "config": _config(),
                "derivedFrom": [{"kind": "NEURON_MODEL", "neuronModel": str(parent.id)}],
            }
        },
    )
    assert not res.errors, res.errors
    child = await NeuronModel.objects.aget(name="Inheritor")
    assert child.environment_id == env.id


async def test_derived_into_is_the_other_end_of_derived_from(aexecute, make_neuron_model):
    parent = await make_neuron_model(name="Upstream")
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {
            "input": {
                "name": "Downstream",
                "config": _config(),
                "derivedFrom": [{"kind": "NEURON_MODEL", "neuronModel": str(parent.id)}],
            }
        },
    )
    assert not res.errors, res.errors

    back = await aexecute(MODEL_LINEAGE, {"id": str(parent.id)})
    assert not back.errors, back.errors
    # Read off the same edges, never a stored back-reference that could disagree with them.
    assert [node["name"] for node in back.data["neuronModel"]["derivedInto"]] == ["Downstream"]
    assert back.data["neuronModel"]["derivedFrom"] == []


async def test_a_model_is_a_node_of_the_lineage_graph(aexecute, make_neuron_model):
    parent = await make_neuron_model(name="GraphRoot")
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {
            "input": {
                "name": "GraphChild",
                "config": _config(),
                "derivedFrom": [{"kind": "NEURON_MODEL", "neuronModel": str(parent.id)}],
            }
        },
    )
    assert not res.errors, res.errors

    graph = await aexecute(LINEAGE_GRAPH, {"coordinateSystem": str(parent.coordinate_system_id)})
    assert not graph.errors, graph.errors
    names = {node["name"] for node in graph.data["lineageGraph"]["nodes"] if node["__typename"] == "NeuronModel"}
    # This is the whole point of the change: the walk had no node to stand on before.
    assert names == {"GraphRoot", "GraphChild"}
    assert [edge["kind"] for edge in graph.data["lineageGraph"]["edges"]] == ["UNMAPPABLE"]


async def test_recreating_an_identical_config_does_not_duplicate_the_space_or_the_edge(aexecute, make_neuron_model):
    # createNeuronModel dedups on the config hash, so an unchanged re-create lands on a row that
    # already has a space and already has its edges. Minting again would abandon the old space
    # (PROTECT makes it undeletable) and write_derivation_edges does not dedup, so a second
    # UNMAPPABLE edge would appear -- and because order is priority, that changes which is primary.
    parent = await make_neuron_model(name="StableParent")
    payload = {
        "input": {
            "name": "Stable",
            "config": _config(),
            "derivedFrom": [{"kind": "NEURON_MODEL", "neuronModel": str(parent.id)}],
        }
    }
    first = await aexecute(CREATE_NEURON_MODEL, payload)
    assert not first.errors, first.errors

    second = await aexecute(CREATE_NEURON_MODEL, payload)
    assert not second.errors, second.errors

    assert first.data["createNeuronModel"]["id"] == second.data["createNeuronModel"]["id"]
    assert first.data["createNeuronModel"]["coordinateSystem"]["id"] == second.data["createNeuronModel"]["coordinateSystem"]["id"]

    child = await NeuronModel.objects.aget(name="Stable")
    assert await Transformation.objects.filter(input=child.coordinate_system_id, parent__isnull=True).acount() == 1
    assert await NeuronModel.objects.filter(name="Stable").acount() == 1
