"""kanne_server Unit and Dimension scalars (pydantic-side validators)."""

import pytest
from pydantic import BaseModel, ValidationError

from kanne_server import quantities as pq
from kanne_server.scalars import parse_dimension


class UModel(BaseModel):
    u: pq.Unit


class DModel(BaseModel):
    d: pq.Dimension


# --- Unit --------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["mV", "S/cm2", "second", "mS/cm2", "dimensionless"])
def test_unit_accepts_valid_units(unit):
    assert UModel(u=unit).u == unit  # given spelling preserved


def test_unit_rejects_unknown_unit():
    with pytest.raises(ValidationError):
        UModel(u="notaunit")


def test_unit_rejects_a_quantity():
    # A magnitude-bearing quantity is not a unit.
    with pytest.raises(ValidationError):
        UModel(u="5 mV")


def test_unit_rejects_a_dimension():
    with pytest.raises(ValidationError):
        UModel(u="[length]")


def test_unit_rejects_empty():
    with pytest.raises(ValidationError):
        UModel(u="   ")


# --- Dimension ---------------------------------------------------------------


def test_dimension_accepts_bracket_syntax():
    assert DModel(d="[length]").d == "[length]"


def test_dimension_canonicalizes_and_is_order_stable():
    # A unit expression is reduced to its (canonical, order-stable) dimensionality,
    # and equal dimensions render identically regardless of input spelling.
    assert DModel(d="S/cm2").d == parse_dimension("mS/cm**2")
    assert DModel(d="mV").d == parse_dimension("volt")


def test_dimension_dimensionless_sentinel():
    assert DModel(d="dimensionless").d == "dimensionless"


def test_dimension_rejects_bogus():
    with pytest.raises(ValidationError):
        DModel(d="[bogus]")


# --- arbitrary units (a.u.) opt-out ------------------------------------------


@pytest.mark.parametrize("spelling", ["a.u.", "A.U.", "arbitrary units", "arbitrary_unit", "arb"])
def test_unit_accepts_arbitrary(spelling):
    assert UModel(u=spelling).u == "a.u."  # canonicalized


def test_dimension_of_arbitrary_is_bracket_arbitrary():
    assert DModel(d="a.u.").d == "[arbitrary]"
    assert DModel(d="[arbitrary]").d == "[arbitrary]"  # idempotent


def test_bare_au_is_still_astronomical_unit_not_arbitrary():
    # "au" is pint's astronomical unit; it must NOT be hijacked as arbitrary.
    assert UModel(u="au").u == "au"
    assert DModel(d="au").d != "[arbitrary]"


def test_generic_quantity_arbitrary_value():
    from kanne_server import quantities as pqq

    class G(BaseModel):
        v: pqq.GenericQuantity

    g = G(v="5 a.u.")
    dumped = g.model_dump(mode="json")
    assert dumped["v"] == {"magnitude": 5.0, "unit": "a.u.", "dimension": "[arbitrary]"}
    # round-trips from the stored struct
    assert G(**dumped).v == "5.0 a.u."


# --- None passes through (optional fields) -----------------------------------


def test_optional_none_passes():
    class M(BaseModel):
        u: pq.Unit | None = None
        d: pq.Dimension | None = None

    m = M()
    assert m.u is None and m.d is None
