"""Unit/dimension validation on mechanism parameters.

These are pure-pydantic tests (no DB, no docker) mirroring rekuest's
``tests/models/test_quantity_ports.py``. They exercise ``ParameterInputModel``'s
``check_units`` validator and ``core.units.dimensionality_of``.
"""

import pytest

from core.parameters import ParameterInputModel, ParameterKind, ParameterModel
from core.units import DIMENSIONLESS, dimensionality_of


def _param(**kwargs):
    base = dict(key="p", kind=ParameterKind.FLOAT)
    base.update(kwargs)
    return ParameterInputModel(**base)


# --- derivation --------------------------------------------------------------


def test_reference_unit_derives_dimension():
    p = _param(reference_unit="mV")
    assert p.dimension == dimensionality_of("volt")


def test_neuron_density_units_accepted():
    # The two NEURON units that have no kanne scalar class.
    assert _param(reference_unit="S/cm2").dimension == dimensionality_of("S/cm2")
    assert _param(reference_unit="mA/cm2").dimension == dimensionality_of("mA/cm2")


def test_dimension_is_idempotent():
    once = _param(reference_unit="S/cm2").dimension
    twice = _param(reference_unit="S/cm2", dimension=once).dimension
    assert once == twice


def test_proposed_units_same_dimension_pass():
    p = _param(reference_unit="S/cm2", proposed_units=["S/cm2", "mS/cm2"])
    assert p.dimension == dimensionality_of("S/cm2")


# --- rejections --------------------------------------------------------------


def test_inconsistent_explicit_dimension_rejected():
    with pytest.raises(ValueError, match="inconsistent"):
        _param(reference_unit="mV", dimension=dimensionality_of("farad"))


def test_proposed_unit_wrong_dimension_rejected():
    with pytest.raises(ValueError, match="proposed unit"):
        _param(reference_unit="mV", proposed_units=["pF"])


def test_unit_on_string_kind_rejected():
    with pytest.raises(ValueError, match="cannot carry a unit"):
        _param(kind=ParameterKind.STRING, reference_unit="mV")


def test_dimension_without_reference_unit_rejected():
    with pytest.raises(ValueError, match="without a reference_unit"):
        _param(dimension=DIMENSIONLESS)


def test_proposed_units_without_reference_unit_rejected():
    with pytest.raises(ValueError, match="without a reference_unit"):
        _param(proposed_units=["mV"])


def test_unparseable_unit_rejected():
    with pytest.raises(ValueError, match="Unknown or unparseable"):
        _param(reference_unit="notaunit")


# --- back-compat -------------------------------------------------------------


def test_read_model_permissive_without_units():
    # A parameter persisted before units existed must still hydrate.
    p = ParameterModel(key="gnabar", kind=ParameterKind.FLOAT)
    assert p.reference_unit is None
    assert p.dimension is None


def test_no_unit_input_is_unchanged():
    p = _param()
    assert p.reference_unit is None
    assert p.dimension is None


# --- end-to-end through the schema -------------------------------------------

CREATE_WITH_UNITS = """
mutation ($input: CreateModEnvironmentInput!) {
  createModEnvironment(input: $input) { id }
}
"""

QUERY_MECHANISMS = """
query {
  mechanisms {
    name
    parameters { key referenceUnit proposedUnits dimension }
  }
}
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_units_round_trip_through_schema(aexecute, bigfile_store):
    store = await bigfile_store()
    res = await aexecute(
        CREATE_WITH_UNITS,
        {
            "input": {
                "name": "UnitEnv",
                "zipFile": str(store.id),
                "mechanisms": [
                    {
                        "name": "hh",
                        "parameters": [
                            {
                                "key": "gnabar",
                                "kind": "FLOAT",
                                "referenceUnit": "S/cm2",
                                "proposedUnits": ["S/cm2", "mS/cm2"],
                            }
                        ],
                    }
                ],
            }
        },
    )
    assert not res.errors, res.errors

    res = await aexecute(QUERY_MECHANISMS, {})
    assert not res.errors, res.errors
    mech = next(m for m in res.data["mechanisms"] if m["name"] == "hh")
    param = mech["parameters"][0]
    assert param["referenceUnit"] == "S/cm2"
    assert param["proposedUnits"] == ["S/cm2", "mS/cm2"]
    # dimension was derived server-side, not supplied by the client.
    assert param["dimension"] == dimensionality_of("S/cm2")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_bad_unit_rejected_by_schema(aexecute, bigfile_store):
    store = await bigfile_store()
    res = await aexecute(
        CREATE_WITH_UNITS,
        {
            "input": {
                "name": "BadUnitEnv",
                "zipFile": str(store.id),
                "mechanisms": [
                    {
                        "name": "hh",
                        "parameters": [
                            {"key": "gnabar", "kind": "FLOAT", "referenceUnit": "notaunit"}
                        ],
                    }
                ],
            }
        },
    )
    assert res.errors
