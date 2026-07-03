"""Canonical physical-dimension semantics for mechanism parameter units.

A mechanism parameter may declare a ``reference_unit`` (e.g. ``"mV"`` or
``"S/cm2"``). From that unit string we derive a *canonical dimensionality*
string that is used to (a) validate that any alternative/proposed units share
the same physical dimension and (b) let the UI group units for a dropdown.

The heavy lifting is done by ``pint``. We reuse kanne_server's process-wide
``pint.UnitRegistry`` (``kanne_server.registry.get_registry``) rather than building a
fresh one, so we inherit its ``autoconvert_offset_to_baseunit`` handling (``degC``)
and any custom ``KANNE["definitions"]``. This mirrors
``rekuest_core.units.dimensionality_of``.
"""

import re

from kanne_server.registry import get_registry

DIMENSIONLESS = "dimensionless"

# NEURON unit spellings are not always pint-parseable as written. Whole-token
# aliases handled before pint sees the string.
_NEURON_ALIASES = {
    "mho": "siemens",
}

# A letter immediately followed by digits denotes an exponent in NEURON units
# ("cm2" -> "cm**2"), which pint writes as "**". The lookbehind avoids mangling
# scientific notation such as "1e3".
_EXPONENT_RE = re.compile(r"(?<![0-9.])([a-zA-Z])(\d+)")


def _normalize_neuron_unit(expression: str) -> str:
    """Rewrite NEURON unit spelling into something pint can parse.

    ``"S/cm2"`` -> ``"S/cm**2"``, ``"mho/cm2"`` -> ``"siemens/cm**2"``.
    """
    normalized = _EXPONENT_RE.sub(r"\1**\2", expression)
    for neuron, pint_name in _NEURON_ALIASES.items():
        normalized = re.sub(rf"\b{re.escape(neuron)}\b", pint_name, normalized)
    return normalized


def _render_dimensionality(dims) -> str:
    """Deterministic string form of a pint dimensionality mapping.

    ``str(UnitsContainer)`` is not order-stable (it depends on the registry's
    cache history within the process), so exact-string comparison and
    cross-process persistence need our own canonical rendering: terms sorted
    alphabetically, positive exponents as the numerator, negative ones appended
    as divisions. The result is itself parseable by ``get_dimensionality``.
    """
    positive = sorted((dim, exp) for dim, exp in dims.items() if exp > 0)
    negative = sorted((dim, exp) for dim, exp in dims.items() if exp < 0)
    if not positive and not negative:
        return DIMENSIONLESS

    def term(dim: str, exp) -> str:
        exp = abs(exp)
        return dim if exp == 1 else f"{dim} ** {exp:g}"

    rendered = " * ".join(term(dim, exp) for dim, exp in positive) if positive else "1"
    for dim, exp in negative:
        rendered += f" / {term(dim, exp)}"
    return rendered


def dimensionality_of(expression: str) -> str:
    """Canonical dimensionality string for a unit or dimension expression.

    Accepts unit names ("mV", "S/cm2"), dimensionality expressions
    ("[mass] * [length] ** 2 / [time] ** 3 / [current]") and the special
    "dimensionless" sentinel, returning the identical canonical string for
    equal dimensions. Raises ValueError on anything pint cannot parse, so
    pydantic surfaces it as a normal validation error.
    """
    import pint

    if expression.strip() == DIMENSIONLESS:
        # pint's parser cannot resolve the sentinel of an empty dimensionality.
        return DIMENSIONLESS
    normalized = _normalize_neuron_unit(expression)
    try:
        dims = get_registry().get_dimensionality(normalized)
    except (pint.PintError, KeyError, ValueError, TypeError) as e:
        raise ValueError(f"Unknown or unparseable unit '{expression}': {e}") from e
    return _render_dimensionality(dims)


def quantity_dimension(raw: str) -> str:
    """Canonical dimension of a full quantity string (magnitude + unit).

    ``"0.12 S/cm2"`` -> the same canonical string as ``dimensionality_of("S/cm2")``,
    so a set value can be compared against a parameter's declared dimension.
    """
    import pint

    normalized = _normalize_neuron_unit(raw)
    try:
        quantity = get_registry().Quantity(normalized)
    except (pint.PintError, KeyError, ValueError, TypeError) as e:
        raise ValueError(f"Unknown or unparseable quantity '{raw}': {e}") from e
    return _render_dimensionality(quantity.dimensionality)
