"""Per-section *dominance score* for a NeuronModel — how much a compartment shapes
the whole simulation, estimated analytically from stored geometry + biophysics.

This server never runs NEURON (see module docstring in ``core.analysis``); a model is
only a description. But classical cable theory lets us estimate a section's electrical
influence directly from the values already stored in ``NeuronModel.json_model``, with
no simulation. For each section we combine physically-grounded factors:

- **Surface area** ``A`` (``π·diam·length``, or summed pt3d truncated-cone areas) —
  scales total membrane current, capacitance, and channel count.
- **Total capacitance** ``C = cm·A`` — charge storage / transient current sink.
- **Axial coupling conductance** ``g_axial = π·(diam/2)²/(Ra·length)`` — how tightly the
  section's voltage is yoked to the rest of the tree.
- **Conductance load** ``G = A·Σ gbar`` — the section's total membrane conductance
  (passive ``g_pas`` plus every active density like ``gnabar_hh``).
- **Electrotonic transfer weight** ``w = exp(-electrotonic distance to a reference)`` —
  attenuation of a section's influence with distance to the soma / recording site,
  using the length constant ``λ = sqrt(diam·Rm/(4·Ra))``.

Two scores per section, each returned raw and normalized to a ``[0, 1]`` fraction of the
model total:

- **global** — reference-independent, ``α·norm(G) + β·norm(C) + γ·norm(g_axial)`` — how
  big a player this section is in the cell overall.
- **reference** — ``w · global_raw`` — the global contribution attenuated by electrotonic
  distance to the reference (default: the soma, else the tree root). This is the
  "dominance toward the recording site" notion.

This is a deliberately transparent *first-order heuristic*. The principled measure —
steady-state transfer impedance via a Hines tree solve — is out of scope; the code is
structured so it could be added later as an opt-in mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core.base_models.type.biophysics import CompartmentModel, SectionParamMapModel
from core.base_models.type.cell import CellModel
from core.base_models.type.model import ModelConfigModel
from core.base_models.type.topology import SectionModel
from core.enums import DistributionKind
from kanne_server import scalars as _scalars
from kanne_server.registry import get_registry

# NEURON built-in fallbacks (used when a value is not set on the section or model).
DEFAULT_RA_OHM_CM = 35.4  # NEURON's built-in axial resistivity
DEFAULT_CM_UF_CM2 = 1.0  # NEURON's built-in specific membrane capacitance
# Specific membrane resistance used for the length constant when a model has no passive
# (``pas``/``leak``) conductance to derive it from. 10 kΩ·cm² is a common cortical value.
DEFAULT_RM_OHM_CM2 = 10_000.0

#: Passive/leak mechanisms whose conductance density gives the membrane resistance ``Rm``.
PASSIVE_MECHANISMS = frozenset({"pas", "leak"})

#: Relative weights of the three global factors: conductance load, capacitance, axial
#: coupling. Tunable; they only need to be sensible relative magnitudes since each factor
#: is normalized to a fraction before weighting.
DEFAULT_WEIGHTS = (0.5, 0.3, 0.2)


@dataclass
class SectionDominance:
    """The computed dominance of one section (within one cell)."""

    cell_id: str
    section_id: str
    category: Optional[str]

    # Normalized [0, 1] fractions of the model total.
    global_score: float
    reference_score: float

    # Raw (pre-normalization) composite scores.
    raw_global: float
    raw_reference: float

    # The underlying physical factors, in CGS-consistent units, for explainability.
    area: float  # cm²
    capacitance: float  # farad
    axial_conductance: float  # siemens
    conductance_load: float  # siemens
    electrotonic_distance: float  # dimensionless (length constants to the reference)
    transfer_weight: float  # dimensionless, exp(-electrotonic_distance)

    is_reference: bool = False


# --- unit helpers ------------------------------------------------------------
#
# Stored quantities are canonical integers (an int count of ``reference_unit / scale``);
# GenericQuantity values are normalized unit-bearing strings ("0.12 siemens / centimeter
# ** 2"). We convert both to plain floats in the units the formulas below expect.

_COND_DENSITY_DIM = get_registry().get_dimensionality("siemens / centimeter ** 2")


def _to_si(canonical: Optional[int], pint_cls: type, target_unit: str) -> Optional[float]:
    """Convert a stored canonical integer to a float in ``target_unit``.

    ``pint_cls`` is the ``kanne_server.scalars`` quantity class the field is typed as; its
    ``reference_unit``/``scale`` decode the integer.
    """
    if canonical is None:
        return None
    ureg = get_registry()
    value_in_reference = canonical / pint_cls.scale
    quantity = value_in_reference * ureg(pint_cls.reference_unit)
    return quantity.to(target_unit).magnitude


def _length_cm(canonical: Optional[int]) -> Optional[float]:
    return _to_si(canonical, _scalars.Length, "centimeter")


def _param_density_s_cm2(param: SectionParamMapModel) -> Optional[float]:
    """Conductance density (S/cm²) of a section parameter, or None if it is not one.

    A parameter counts as a conductance density only if its distribution value has the
    dimensionality of siemens/area. ``linear`` distributions use the mean of the
    proximal/distal values; ``expression`` distributions cannot be evaluated statically
    and are skipped.
    """
    dist = param.distribution
    kind = dist.kind
    # BaseConfig uses use_enum_values=True, so ``kind`` may be a str or an enum member.
    kind_value = getattr(kind, "value", kind)

    if kind_value == DistributionKind.EXPRESSION.value:
        return None
    if kind_value == DistributionKind.LINEAR.value:
        values = [dist.proximal_value, dist.distal_value]
    else:  # uniform (or anything else that carries a single value)
        values = [dist.value]

    densities: list[float] = []
    ureg = get_registry()
    for raw in values:
        if raw is None:
            continue
        try:
            quantity = ureg.Quantity(_scalars.normalize_compact_units(str(raw)))
        except Exception:
            continue
        if quantity.dimensionality != _COND_DENSITY_DIM:
            return None
        densities.append(quantity.to("siemens / centimeter ** 2").magnitude)

    if not densities:
        return None
    return sum(densities) / len(densities)


# --- geometry ----------------------------------------------------------------


@dataclass
class _Geometry:
    """Effective cable geometry of a section, in centimeters/cm²."""

    area: float  # cm² membrane surface area
    length: float  # cm
    diam: float  # cm (area-equivalent effective diameter when pt3d coords are used)


def _section_geometry(section: SectionModel) -> _Geometry:
    """Surface area + an effective (length, diameter) for a section.

    Uses pt3d ``coords`` when present (summing truncated-cone lateral areas), otherwise
    the stylized ``diam``/``length``. For pt3d the effective diameter is chosen so that
    ``π·diam·length == area`` — keeping the axial/length-constant formulas consistent
    with the true surface area.
    """
    coords = section.coords
    if coords and len(coords) >= 2:
        default_r = (_length_cm(section.diam) or 0.0) / 2.0
        pts = []
        for c in coords:
            r = (_length_cm(c.diam) or 0.0) / 2.0 if c.diam is not None else default_r
            pts.append((_length_cm(c.x) or 0.0, _length_cm(c.y) or 0.0, _length_cm(c.z) or 0.0, r))
        area = 0.0
        length = 0.0
        for (x1, y1, z1, r1), (x2, y2, z2, r2) in zip(pts, pts[1:]):
            slant = math.dist((x1, y1, z1), (x2, y2, z2))
            area += math.pi * (r1 + r2) * slant
            length += slant
        if length <= 0.0:
            length = 0.0
        eff_diam = (area / (math.pi * length)) if length > 0 else (2 * default_r)
        return _Geometry(area=area, length=length, diam=eff_diam)

    # Stylized geometry (length is guaranteed present when coords are absent).
    diam = _length_cm(section.diam) or 0.0
    length = _length_cm(section.length) or 0.0
    area = math.pi * diam * length
    return _Geometry(area=area, length=length, diam=diam)


# --- per-section biophysics --------------------------------------------------


def _compartment_for_section(section: SectionModel, cell: CellModel) -> Optional[CompartmentModel]:
    """The biophysics compartment bound to a section (by ``section.category == comp.id``)."""
    if section.category is None:
        return None
    for comp in cell.biophysics.compartments:
        if comp.id == section.category:
            return comp
    return None


def _section_ra(section: SectionModel, config: ModelConfigModel) -> float:
    for canonical in (section.ra, config.ra):
        if canonical is not None:
            value = _to_si(canonical, _scalars.Resistivity, "ohm * centimeter")
            if value is not None:
                return value
    return DEFAULT_RA_OHM_CM


def _section_cm(section: SectionModel, config: ModelConfigModel) -> float:
    for canonical in (section.cm, config.cm):
        if canonical is not None:
            value = _to_si(canonical, _scalars.SpecificCapacitance, "microfarad / centimeter ** 2")
            if value is not None:
                return value
    return DEFAULT_CM_UF_CM2


def _conductance_densities(comp: Optional[CompartmentModel]) -> tuple[float, float]:
    """(total conductance density, passive conductance density) in S/cm² for a compartment.

    The passive density (from ``pas``/``leak`` mechanisms) is returned separately because
    it sets the membrane resistance ``Rm`` used by the length constant.
    """
    if comp is None:
        return 0.0, 0.0
    total = 0.0
    passive = 0.0
    for param in comp.section_params:
        density = _param_density_s_cm2(param)
        if density is None:
            continue
        total += density
        if param.mechanism in PASSIVE_MECHANISMS:
            passive += density
    return total, passive


# --- electrotonic distance to the reference ----------------------------------


def _elec_length(geom: _Geometry, ra_ohm_cm: float, rm_ohm_cm2: float) -> float:
    """Electrotonic length ``L/λ`` of a section (dimensionless)."""
    if geom.length <= 0 or geom.diam <= 0 or ra_ohm_cm <= 0 or rm_ohm_cm2 <= 0:
        return 0.0
    lam = math.sqrt(geom.diam * rm_ohm_cm2 / (4.0 * ra_ohm_cm))  # cm
    if lam <= 0:
        return 0.0
    return geom.length / lam


def _reference_section(cell: CellModel, reference: Optional[dict]) -> Optional[str]:
    """Pick the reference section id for a cell: explicit arg > category 'soma' > root."""
    ids = {s.id for s in cell.topology.sections}
    if reference is not None:
        ref_cell = reference.get("cell_id")
        ref_section = reference.get("section_id")
        if ref_section in ids and (ref_cell is None or ref_cell == cell.id):
            return ref_section
    soma = next((s for s in cell.topology.sections if (s.category or "").lower() == "soma"), None)
    if soma is not None:
        return soma.id
    root = next((s for s in cell.topology.sections if s.parent is None), None)
    return root.id if root is not None else None


def _ancestors(section_id: str, parent_of: dict[str, Optional[str]]) -> list[str]:
    """Path of ids from ``section_id`` up to (and including) the root."""
    chain = []
    node: Optional[str] = section_id
    seen = set()
    while node is not None and node not in seen:
        chain.append(node)
        seen.add(node)
        node = parent_of.get(node)
    return chain


def _electrotonic_distances(
    cell: CellModel, elec_len: dict[str, float], ref_id: Optional[str]
) -> dict[str, float]:
    """Electrotonic distance from each section to ``ref_id`` along the tree.

    Distance along a tree is the sum of edge electrotonic lengths on the unique path
    connecting the two nodes: ``depth(section) + depth(ref) - 2·depth(LCA)``, where an
    edge's electrotonic length is attributed to its child section.
    """
    parent_of = {s.id: (s.parent.parent if s.parent else None) for s in cell.topology.sections}

    # Cumulative electrotonic depth from the root (root depth = 0; each section adds its
    # own edge length to its parent).
    depth: dict[str, float] = {}

    def _depth(sid: str) -> float:
        if sid in depth:
            return depth[sid]
        parent = parent_of.get(sid)
        d = 0.0 if parent is None else _depth(parent) + elec_len.get(sid, 0.0)
        depth[sid] = d
        return d

    for s in cell.topology.sections:
        _depth(s.id)

    if ref_id is None:
        return {s.id: 0.0 for s in cell.topology.sections}

    ref_ancestors = _ancestors(ref_id, parent_of)
    ref_ancestor_depth = {sid: depth[sid] for sid in ref_ancestors}

    distances: dict[str, float] = {}
    for s in cell.topology.sections:
        # Find the lowest common ancestor by walking up from the section until we hit an
        # ancestor of the reference.
        lca_depth = 0.0
        node: Optional[str] = s.id
        while node is not None:
            if node in ref_ancestor_depth:
                lca_depth = ref_ancestor_depth[node]
                break
            node = parent_of.get(node)
        distances[s.id] = depth[s.id] + depth[ref_id] - 2.0 * lca_depth
    return distances


# --- main entry point --------------------------------------------------------


def compute_dominance(
    config: ModelConfigModel,
    *,
    reference: Optional[dict] = None,
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
) -> list[SectionDominance]:
    """Compute per-section dominance scores for every section of every cell in ``config``.

    ``reference`` optionally pins the reference site as ``{"cell_id": ..., "section_id": ...}``
    (``cell_id`` may be omitted). When not given, each cell uses its own soma (a section
    with ``category == 'soma'``), else its tree root. Electrotonic attenuation is computed
    within each cell — cross-cell electrical coupling (via synapses) is not modeled.

    Scores are normalized across the whole model, so ``global_score`` and
    ``reference_score`` each sum to 1 over the returned list (unless the model is empty).
    """
    alpha, beta, gamma = weights

    # Pass 1 — per-section physical factors.
    rows: list[dict] = []
    for cell in config.cells:
        sections = cell.topology.sections
        elec_len: dict[str, float] = {}

        for section in sections:
            geom = _section_geometry(section)
            ra = _section_ra(section, config)
            cm = _section_cm(section, config)  # µF/cm²
            comp = _compartment_for_section(section, cell)
            total_g_density, passive_g_density = _conductance_densities(comp)  # S/cm²

            capacitance = cm * 1e-6 * geom.area  # farad (µF/cm² · 1e-6 · cm²)
            conductance_load = total_g_density * geom.area  # siemens

            # Axial conductance of this section's upstream (parent) edge; a property of
            # the child cable's geometry (root has no upstream edge → 0).
            edge_axial = 0.0
            if section.parent is not None and geom.length > 0 and ra > 0 and geom.diam > 0:
                cross_area = math.pi * (geom.diam / 2.0) ** 2  # cm²
                resistance = ra * geom.length / cross_area  # ohm
                edge_axial = 1.0 / resistance if resistance > 0 else 0.0

            rm = (1.0 / passive_g_density) if passive_g_density > 0 else DEFAULT_RM_OHM_CM2
            elec_len[section.id] = _elec_length(geom, ra, rm)

            rows.append(
                {
                    "cell_id": cell.id,
                    "section": section,
                    "area": geom.area,
                    "capacitance": capacitance,
                    "edge_axial": edge_axial,
                    "conductance_load": conductance_load,
                }
            )

        # Total axial coupling incident on each section = its own upstream edge plus the
        # edges of its children. This credits a soma (the root) for the coupling to its
        # children rather than leaving it at zero, and reflects how much axial current can
        # flow in/out of the section overall.
        cell_rows = [r for r in rows if r["cell_id"] == cell.id]
        children_edge_sum: dict[str, float] = {}
        for r in cell_rows:
            parent_id = r["section"].parent.parent if r["section"].parent else None
            if parent_id is not None:
                children_edge_sum[parent_id] = children_edge_sum.get(parent_id, 0.0) + r["edge_axial"]
        for r in cell_rows:
            r["axial"] = r["edge_axial"] + children_edge_sum.get(r["section"].id, 0.0)

        # Electrotonic distance + transfer weight, per cell.
        ref_id = _reference_section(cell, reference)
        distances = _electrotonic_distances(cell, elec_len, ref_id)
        for row in rows:
            if row["cell_id"] != cell.id:
                continue
            dist = distances.get(row["section"].id, 0.0)
            row["electrotonic_distance"] = dist
            row["transfer_weight"] = math.exp(-dist)
            row["is_reference"] = row["section"].id == ref_id

    if not rows:
        return []

    # Pass 2 — normalize each factor to a fraction, then compose the scores.
    def _fraction(key: str) -> dict[int, float]:
        total = sum(r[key] for r in rows)
        if total <= 0:
            return {i: 0.0 for i in range(len(rows))}
        return {i: rows[i][key] / total for i in range(len(rows))}

    g_frac = _fraction("conductance_load")
    c_frac = _fraction("capacitance")
    a_frac = _fraction("axial")

    raw_global = [
        alpha * g_frac[i] + beta * c_frac[i] + gamma * a_frac[i] for i in range(len(rows))
    ]
    raw_reference = [raw_global[i] * rows[i]["transfer_weight"] for i in range(len(rows))]

    global_total = sum(raw_global)
    reference_total = sum(raw_reference)

    results: list[SectionDominance] = []
    for i, row in enumerate(rows):
        section: SectionModel = row["section"]
        results.append(
            SectionDominance(
                cell_id=row["cell_id"],
                section_id=section.id,
                category=section.category,
                global_score=(raw_global[i] / global_total) if global_total > 0 else 0.0,
                reference_score=(raw_reference[i] / reference_total) if reference_total > 0 else 0.0,
                raw_global=raw_global[i],
                raw_reference=raw_reference[i],
                area=row["area"],
                capacitance=row["capacitance"],
                axial_conductance=row["axial"],
                conductance_load=row["conductance_load"],
                electrotonic_distance=row["electrotonic_distance"],
                transfer_weight=row["transfer_weight"],
                is_reference=row["is_reference"],
            )
        )
    return results
