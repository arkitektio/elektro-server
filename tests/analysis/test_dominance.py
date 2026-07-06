"""Unit tests for the analytic per-section dominance score.

Standalone — pure Python over the pydantic config, no database or object store. Run with
``uv run pytest tests/analysis/test_dominance.py`` (or the container runner).
"""

import math

import pytest

from core.analysis import compute_dominance
from core.analysis.dominance import _section_geometry
from core.base_models.type.model import ModelConfigModel


# --- fixtures / builders -----------------------------------------------------


def _cell(sections, compartments=None, cid="cell0"):
    return {
        "id": cid,
        "biophysics": {"compartments": compartments or []},
        "topology": {"sections": sections},
    }


def _config(cells, **kw):
    return ModelConfigModel(**{"cells": cells, **kw})


def _by_id(results):
    return {(r.cell_id, r.section_id): r for r in results}


# A compact soma (large membrane area, low input resistance) and a thin, shorter
# dendrite hanging off it — the soma genuinely carries more membrane than the dendrite.
SOMA = {"id": "soma", "category": "soma", "diam": "25 um", "length": "25 um"}
THIN_DEND = {
    "id": "dend",
    "category": "dend",
    "diam": "0.5 um",
    "length": "200 um",
    "parent": {"parent": "soma"},
}


def _uniform_param(param, mechanism, value):
    return {
        "param": param,
        "mechanism": mechanism,
        "distribution": {"kind": "uniform", "value": value},
    }


# --- tests -------------------------------------------------------------------


def test_soma_outscores_thin_distal_dendrite():
    config = _config([_cell([SOMA, THIN_DEND])])
    r = _by_id(compute_dominance(config))
    soma = r[("cell0", "soma")]
    dend = r[("cell0", "dend")]
    # A big soma dominates a thin distal dendrite both globally and toward the soma.
    assert soma.global_score > dend.global_score
    assert soma.reference_score > dend.reference_score


def test_reference_attenuates_with_electrotonic_distance():
    config = _config([_cell([SOMA, THIN_DEND])])
    r = _by_id(compute_dominance(config))
    soma = r[("cell0", "soma")]
    dend = r[("cell0", "dend")]
    # The reference (soma) is not attenuated; a distal section is.
    assert soma.is_reference is True
    assert soma.transfer_weight == pytest.approx(1.0)
    assert dend.electrotonic_distance > 0
    assert dend.transfer_weight < 1.0
    # Distal reference weighting sinks the dendrite's reference share below its global share.
    assert dend.reference_score < dend.global_score


def test_active_conductance_raises_score():
    # Two geometrically identical dendrites; one carries a dense active conductance.
    active_sec = {"id": "a", "category": "active", "diam": "1 um", "length": "200 um"}
    bare_sec = {
        "id": "b",
        "category": "bare",
        "diam": "1 um",
        "length": "200 um",
        "parent": {"parent": "a"},
    }
    comp = {
        "id": "active",
        "mechanisms": ["hh"],
        "section_params": [_uniform_param("gnabar", "hh", "0.12 S/cm2")],
    }
    config = _config([_cell([active_sec, bare_sec], compartments=[comp])])
    r = _by_id(compute_dominance(config))
    assert r[("cell0", "a")].conductance_load > r[("cell0", "b")].conductance_load
    assert r[("cell0", "a")].global_score > r[("cell0", "b")].global_score


def test_pt3d_area_matches_equivalent_cylinder():
    stylized = _config([_cell([{"id": "s", "diam": "2 um", "length": "100 um"}])])
    pt3d = _config(
        [
            _cell(
                [
                    {
                        "id": "s",
                        "coords": [
                            {"x": "0 um", "y": "0 um", "z": "0 um", "diam": "2 um"},
                            {"x": "0 um", "y": "0 um", "z": "100 um", "diam": "2 um"},
                        ],
                    }
                ]
            )
        ]
    )
    a_stylized = compute_dominance(stylized)[0].area
    a_pt3d = compute_dominance(pt3d)[0].area
    assert a_pt3d == pytest.approx(a_stylized, rel=1e-9)
    # Sanity: π·d·L with d=2µm, L=100µm, in cm².
    expected = math.pi * (2e-4) * (100e-4)
    assert a_stylized == pytest.approx(expected, rel=1e-9)


def test_scores_normalize_to_one():
    config = _config([_cell([SOMA, THIN_DEND])])
    results = compute_dominance(config)
    assert sum(r.global_score for r in results) == pytest.approx(1.0)
    assert sum(r.reference_score for r in results) == pytest.approx(1.0)


def test_single_section_scores_one():
    config = _config([_cell([{"id": "only", "category": "soma", "diam": "10 um", "length": "10 um"}])])
    (only,) = compute_dominance(config)
    assert only.global_score == pytest.approx(1.0)
    assert only.reference_score == pytest.approx(1.0)
    assert only.is_reference is True


def test_empty_model_returns_empty():
    assert compute_dominance(_config([])) == []


def test_reference_selection_explicit_beats_soma():
    config = _config([_cell([SOMA, THIN_DEND])])
    r = _by_id(compute_dominance(config, reference={"section_id": "dend"}))
    assert r[("cell0", "dend")].is_reference is True
    assert r[("cell0", "dend")].transfer_weight == pytest.approx(1.0)
    assert r[("cell0", "soma")].is_reference is False
    # The soma is now one electrotonic hop away, so it is attenuated.
    assert r[("cell0", "soma")].transfer_weight < 1.0


def test_reference_selection_falls_back_to_root_without_soma():
    # No section carries category 'soma', so the tree root becomes the reference.
    root = {"id": "root", "category": "dend", "diam": "5 um", "length": "50 um"}
    child = {
        "id": "child",
        "category": "dend",
        "diam": "1 um",
        "length": "100 um",
        "parent": {"parent": "root"},
    }
    r = _by_id(compute_dominance(_config([_cell([root, child])])))
    assert r[("cell0", "root")].is_reference is True
    assert r[("cell0", "child")].is_reference is False


def test_weights_shift_the_global_score():
    # Same model, two extreme weightings. A capacitance-only blend and an axial-only blend
    # must produce different soma/dend global-score splits than each other (both factors
    # are non-zero for this geometry-only fixture).
    config = _config([_cell([SOMA, THIN_DEND])])
    cap_only = _by_id(compute_dominance(config, weights=(0.0, 1.0, 0.0)))
    axial_only = _by_id(compute_dominance(config, weights=(0.0, 0.0, 1.0)))
    cap_ratio = cap_only[("cell0", "soma")].global_score / cap_only[("cell0", "dend")].global_score
    axial_ratio = axial_only[("cell0", "soma")].global_score / axial_only[("cell0", "dend")].global_score
    assert cap_ratio != pytest.approx(axial_ratio)


def test_custom_weights_still_normalize_to_one():
    config = _config([_cell([SOMA, THIN_DEND])])
    results = compute_dominance(config, weights=(0.2, 0.7, 0.1))
    assert sum(r.global_score for r in results) == pytest.approx(1.0)
    assert sum(r.reference_score for r in results) == pytest.approx(1.0)


def test_geometry_helper_stylized_cylinder():
    config = _config([_cell([{"id": "s", "diam": "3 um", "length": "40 um"}])])
    section = config.cells[0].topology.sections[0]
    geom = _section_geometry(section)
    assert geom.diam == pytest.approx(3e-4)  # cm
    assert geom.length == pytest.approx(40e-4)  # cm
    assert geom.area == pytest.approx(math.pi * 3e-4 * 40e-4)
