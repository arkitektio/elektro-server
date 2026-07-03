"""createNeuronModel executed against the schema.

Exercises the pydantic-backed nested config input end-to-end (the layer the
recent to_pydantic refactor touched), including the optional-field-omission
regression (environment/parent) and the in-environment mechanism validation.
"""

import pytest

from core.models import ModEnvironment, Mechanism, NeuronModel

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_NEURON_MODEL = """
mutation ($input: CreateNeuronModelInput!) {
  createNeuronModel(input: $input) { id name }
}
"""


def _config(cells=None):
    return {
        "cells": cells or [],
        "vInit": "-67 mV",
        "temperature": "36 degC",
    }


def _cell(mechanisms):
    return {
        "id": "cell0",
        # Compartments are matched to sections by the section's category, so the
        # soma section must carry category "soma" for the "soma" compartment.
        "biophysics": {"compartments": [{"id": "soma", "mechanisms": mechanisms}]},
        "topology": {"sections": [{"id": "soma", "category": "soma", "length": "20 um"}]},
    }


async def test_create_neuron_model_minimal(aexecute, authenticated_context):
    # environment is NOT NULL, so a minimal create must still supply one.
    env = await ModEnvironment.objects.acreate(
        name="env-min", organization=authenticated_context.request.organization
    )
    res = await aexecute(
        CREATE_NEURON_MODEL, {"input": {"name": "NM", "environment": str(env.id), "config": _config()}}
    )
    assert not res.errors, res.errors
    assert res.data["createNeuronModel"]["name"] == "NM"
    assert await NeuronModel.objects.filter(name="NM").aexists()


async def test_create_neuron_model_requires_environment(aexecute):
    # environment/parent both omitted -> NOT NULL environment can't be resolved.
    res = await aexecute(CREATE_NEURON_MODEL, {"input": {"name": "NoEnv", "config": _config()}})
    assert res.errors
    assert not await NeuronModel.objects.filter(name="NoEnv").aexists()


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


async def test_create_neuron_model_with_parent(aexecute, make_neuron_model):
    # Regression: parent is passed as a GraphQL ID (string), and the resolver must
    # assign it via parent_id. Assigning the raw string to the FK (parent=...) used
    # to raise "Cannot assign '<id>': NeuronModel.parent must be a NeuronModel instance".
    parent = await make_neuron_model(name="Parent")
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "Child", "parent": str(parent.id), "config": _config()}},
    )
    assert not res.errors, res.errors
    assert res.data["createNeuronModel"]["name"] == "Child"
    child = await NeuronModel.objects.aget(name="Child")
    assert child.parent_id == parent.id


async def test_create_neuron_model_inherits_parent_environment(
    aexecute, authenticated_context, bigfile_store, make_neuron_model
):
    # When parent is set but environment is omitted, the child inherits the
    # parent's environment.
    store = await bigfile_store()
    env = await ModEnvironment.objects.acreate(
        name="parent-env", store=store, organization=authenticated_context.request.organization
    )
    parent = await make_neuron_model(name="ParentWithEnv", environment=env)
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "Inheritor", "parent": str(parent.id), "config": _config()}},
    )
    assert not res.errors, res.errors
    child = await NeuronModel.objects.aget(name="Inheritor")
    assert child.environment_id == env.id


async def test_create_neuron_model_explicit_environment_overrides_parent(
    aexecute, authenticated_context, bigfile_store, make_neuron_model
):
    # An explicit environment wins over the parent's environment.
    parent_store = await bigfile_store()
    parent_env = await ModEnvironment.objects.acreate(
        name="parent-env2", store=parent_store, organization=authenticated_context.request.organization
    )
    parent = await make_neuron_model(name="ParentWithEnv2", environment=parent_env)

    own_store = await bigfile_store()
    own_env = await ModEnvironment.objects.acreate(
        name="own-env", store=own_store, organization=authenticated_context.request.organization
    )
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {
            "input": {
                "name": "OwnEnv",
                "parent": str(parent.id),
                "environment": str(own_env.id),
                "config": _config(),
            }
        },
    )
    assert not res.errors, res.errors
    child = await NeuronModel.objects.aget(name="OwnEnv")
    assert child.environment_id == own_env.id


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


def _cell_with_param(mechanism, param):
    # A cell whose compartment sets one section param on a catalog mechanism.
    return {
        "id": "cell0",
        "biophysics": {
            "compartments": [
                {
                    "id": "soma",
                    "mechanisms": [mechanism],
                    "sectionParams": [
                        {
                            "param": param,
                            "mechanism": mechanism,
                            "distribution": {"kind": "UNIFORM", "value": "0.1 S/cm2"},
                        }
                    ],
                }
            ]
        },
        "topology": {"sections": [{"id": "soma", "category": "soma", "length": "20 um"}]},
    }


async def test_create_neuron_model_section_param_valid_against_catalog(
    aexecute, authenticated_context, bigfile_store
):
    store = await bigfile_store()
    env = await ModEnvironment.objects.acreate(
        name="env-cat-ok", store=store, organization=authenticated_context.request.organization
    )
    # The mechanism's catalog declares param key "gkbar".
    await Mechanism.objects.acreate(
        name="kdr", environment=env, parameters=[{"key": "gkbar", "kind": "FLOAT"}]
    )
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "GoodParam", "environment": str(env.id), "config": _config([_cell_with_param("kdr", "gkbar")])}},
    )
    assert not res.errors, res.errors
    assert await NeuronModel.objects.filter(name="GoodParam").aexists()


async def test_create_neuron_model_section_param_not_in_catalog(
    aexecute, authenticated_context, bigfile_store
):
    store = await bigfile_store()
    env = await ModEnvironment.objects.acreate(
        name="env-cat-bad", store=store, organization=authenticated_context.request.organization
    )
    await Mechanism.objects.acreate(
        name="kdr", environment=env, parameters=[{"key": "gkbar", "kind": "FLOAT"}]
    )
    # "gbogus" is not a declared param of kdr -> resolver raises.
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "BadParam", "environment": str(env.id), "config": _config([_cell_with_param("kdr", "gbogus")])}},
    )
    assert res.errors
    assert not await NeuronModel.objects.filter(name="BadParam").aexists()


def _cell_with_value(mechanism, param, value):
    # A cell whose compartment sets `param` to a specific quantity `value`.
    return {
        "id": "cell0",
        "biophysics": {
            "compartments": [
                {
                    "id": "soma",
                    "mechanisms": [mechanism],
                    "sectionParams": [
                        {
                            "param": param,
                            "mechanism": mechanism,
                            "distribution": {"kind": "UNIFORM", "value": value},
                        }
                    ],
                }
            ]
        },
        "topology": {"sections": [{"id": "soma", "category": "soma", "length": "20 um"}]},
    }


async def test_section_param_value_matching_declared_dimension(
    aexecute, authenticated_context, bigfile_store
):
    store = await bigfile_store()
    env = await ModEnvironment.objects.acreate(
        name="env-dim-ok", store=store, organization=authenticated_context.request.organization
    )
    # gkbar declares a conductance-density unit; a value in mS/cm2 shares its dimension.
    await Mechanism.objects.acreate(
        name="kdr", environment=env,
        parameters=[{"key": "gkbar", "kind": "FLOAT", "reference_unit": "S/cm2"}],
    )
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "DimOk", "environment": str(env.id),
                   "config": _config([_cell_with_value("kdr", "gkbar", "10 mS/cm2")])}},
    )
    assert not res.errors, res.errors
    assert await NeuronModel.objects.filter(name="DimOk").aexists()


async def test_section_param_value_wrong_dimension_rejected(
    aexecute, authenticated_context, bigfile_store
):
    store = await bigfile_store()
    env = await ModEnvironment.objects.acreate(
        name="env-dim-bad", store=store, organization=authenticated_context.request.organization
    )
    await Mechanism.objects.acreate(
        name="kdr", environment=env,
        parameters=[{"key": "gkbar", "kind": "FLOAT", "reference_unit": "S/cm2"}],
    )
    # A voltage value for a conductance-density param -> dimension mismatch -> rejected.
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "DimBad", "environment": str(env.id),
                   "config": _config([_cell_with_value("kdr", "gkbar", "10 mV")])}},
    )
    assert res.errors


async def test_arbitrary_unit_param_opts_out_of_dimension_check(
    aexecute, authenticated_context, bigfile_store
):
    store = await bigfile_store()
    env = await ModEnvironment.objects.acreate(
        name="env-au", store=store, organization=authenticated_context.request.organization
    )
    # gkbar declares arbitrary units -> its values are not dimension-checked.
    await Mechanism.objects.acreate(
        name="kdr", environment=env,
        parameters=[{"key": "gkbar", "kind": "FLOAT", "reference_unit": "a.u."}],
    )
    res = await aexecute(
        CREATE_NEURON_MODEL,
        {"input": {"name": "AuOk", "environment": str(env.id),
                   "config": _config([_cell_with_value("kdr", "gkbar", "0.7 a.u.")])}},
    )
    assert not res.errors, res.errors
    assert await NeuronModel.objects.filter(name="AuOk").aexists()
    assert not await NeuronModel.objects.filter(name="DimBad").aexists()
