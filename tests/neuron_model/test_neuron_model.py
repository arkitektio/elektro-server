"""createNeuronModel executed against the schema.

Exercises the pydantic-backed nested config input end-to-end (the layer the
recent to_pydantic refactor touched), including the optional-field-omission
regression (environment/parent) and the in-environment mechanism validation.
"""

import pytest

from core.models import ModEnvironment, NeuronModel

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_NEURON_MODEL = """
mutation ($input: CreateNeuronModelInput!) {
  createNeuronModel(input: $input) { id name }
}
"""


def _config(cells=None):
    return {
        "cells": cells or [],
        "vInit": -67.0,
        "celsius": 36.0,
        "environments": [],
    }


def _cell(mechanisms):
    return {
        "id": "cell0",
        "biophysics": {"compartments": [{"id": "soma", "mechanisms": mechanisms}]},
        "topology": {"sections": [{"id": "soma"}]},
    }


async def test_create_neuron_model_minimal(aexecute):
    # environment/parent omitted entirely -> guards the optional-default bug fixed earlier.
    res = await aexecute(CREATE_NEURON_MODEL, {"input": {"name": "NM", "config": _config()}})
    assert not res.errors, res.errors
    assert res.data["createNeuronModel"]["name"] == "NM"
    assert await NeuronModel.objects.filter(name="NM").aexists()


async def test_create_neuron_model_builtin_mechanism(aexecute, authenticated_context, bigfile_store):
    store = await bigfile_store()
    env = await ModEnvironment.objects.acreate(
        name="env", store=store, organization=authenticated_context.request.organization
    )
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "WithEnv", "environment": str(env.id), "config": _config([_cell(["hh"])])}},
    )
    # "hh" is a built-in mechanism, so validation passes even though env has no mechanisms.
    assert not res.errors, res.errors
    assert await NeuronModel.objects.filter(name="WithEnv").aexists()


# --- negatives ---------------------------------------------------------------


async def test_create_neuron_model_unknown_mechanism(aexecute, authenticated_context, bigfile_store):
    store = await bigfile_store()
    env = await ModEnvironment.objects.acreate(
        name="env2", store=store, organization=authenticated_context.request.organization
    )
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {
            "input": {
                "name": "BadMech",
                "environment": str(env.id),
                "config": _config([_cell(["definitely_not_a_mechanism"])]),
            }
        },
    )
    # Resolver raises ValueError -> surfaced as a GraphQL error.
    assert res.errors


async def test_create_neuron_model_missing_config(aexecute):
    # config is required on CreateNeuronModelInput.
    res = await aexecute(CREATE_NEURON_MODEL, {"input": {"name": "NoConfig"}})
    assert res.errors
