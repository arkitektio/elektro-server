"""compare_models: quantity structs collapse to one human-readable change row."""

from core.types import compare_models, ChangeType


def _kanne_q(canonical, given, unit="femtovolt"):
    return {"canonical": canonical, "given": given, "unit": unit}


def _generic_q(magnitude, unit, dimension="[arbitrary]"):
    return {"magnitude": magnitude, "unit": unit, "dimension": dimension}


def test_quantity_change_is_single_human_readable_row():
    a = {"vInit": _kanne_q(-67_000_000_000_000, "-67 mV")}
    b = {"vInit": _kanne_q(-70_000_000_000_000, "-70 mV")}
    changes = compare_models(a, b)
    assert len(changes) == 1  # not one row for canonical + one for given
    c = changes[0]
    assert c.type == ChangeType.CHANGED
    assert c.path == ["vInit"]
    assert c.value_a == "-67 mV" and c.value_b == "-70 mV"


def test_generic_quantity_change_condensed():
    a = {"gbar": _generic_q(0.12, "siemens / centimeter ** 2", "[current] ...")}
    b = {"gbar": _generic_q(0.24, "siemens / centimeter ** 2", "[current] ...")}
    changes = compare_models(a, b)
    assert len(changes) == 1
    assert changes[0].value_a == "0.12 siemens / centimeter ** 2"
    assert changes[0].value_b == "0.24 siemens / centimeter ** 2"


def test_unchanged_quantity_yields_no_change():
    q = _kanne_q(-70_000_000_000_000, "-70 mV")
    assert compare_models({"vInit": dict(q)}, {"vInit": dict(q)}) == []


def test_added_and_removed_quantity_are_human_readable():
    added = compare_models({}, {"vInit": _kanne_q(-70_000_000_000_000, "-70 mV")})
    assert len(added) == 1 and added[0].type == ChangeType.ADDED
    assert added[0].value_b == "-70 mV"

    removed = compare_models({"vInit": _kanne_q(-70_000_000_000_000, "-70 mV")}, {})
    assert len(removed) == 1 and removed[0].type == ChangeType.REMOVED
    assert removed[0].value_a == "-70 mV"


def test_quantity_inside_list_is_condensed():
    # e.g. an ion's reversal_potential inside compartments[].ions[]
    a = {"ions": [{"ion": "na", "e": _kanne_q(50_000_000_000_000, "50 mV")}]}
    b = {"ions": [{"ion": "na", "e": _kanne_q(55_000_000_000_000, "55 mV")}]}
    changes = compare_models(a, b)
    assert len(changes) == 1
    assert changes[0].path == ["ions", "0", "e"]
    assert changes[0].value_a == "50 mV" and changes[0].value_b == "55 mV"


def test_non_quantity_dicts_still_recurse():
    # A regular nested dict must still diff key-by-key (not be treated as a quantity).
    a = {"topology": {"nseg": 1, "L": 20}}
    b = {"topology": {"nseg": 3, "L": 20}}
    changes = compare_models(a, b)
    assert len(changes) == 1
    assert changes[0].path == ["topology", "nseg"]
    assert changes[0].value_a == 1 and changes[0].value_b == 3
