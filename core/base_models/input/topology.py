from pydantic import BaseModel, Field

from kanne_server import quantities as pq


class CoordInputModel(BaseModel):
    """A 3D coordinate (in space) of a point along a section. Persists as {canonical, given, unit}."""

    x: pq.Length = Field(description="The x coordinate of the point.")
    y: pq.Length = Field(description="The y coordinate of the point.")
    z: pq.Length = Field(description="The z coordinate of the point.")
    diam: pq.Length | None = Field(
        default=None,
        description="The diameter of the section at this point (NEURON pt3d). Falls back to the section diameter when omitted.",
    )


class ConnectionInputModel(BaseModel):
    """A connection of a section to its (single) parent section, defining the morphology tree.

    Maps to NEURON ``child.connect(parent(parent_location), child_end)``.
    """

    parent: str = Field(
        description="The ID of the parent section this section connects to."
    )
    parent_location: float = Field(
        default=1.0,
        description="The position along the parent section where this section attaches, between 0 and 1.",
    )
    child_end: float = Field(
        default=0.0,
        description="Which end of this section attaches to the parent: 0 (default) or 1.",
    )


class SectionInputModel(BaseModel):
    """A section of a cell's morphology, the basic structural unit of the topology."""

    id: str = Field(description="The unique identifier of the section within the cell.")
    category: str | None = Field(
        default=None,
        description="An optional category for the section (e.g. 'soma', 'axon', 'dend'). Biophysics compartments are matched to sections by this category.",
    )
    nseg: int = Field(
        default=1,
        description="The number of segments the section is discretized into (used when d_lambda is not set). NEURON convention prefers an odd count so the section has a true midpoint node.",
    )
    d_lambda: float | None = Field(
        default=None,
        description="If set, nseg is computed from NEURON's d_lambda rule (target fraction of the AC length constant at 100 Hz per segment; 0.1 is typical) and overrides the fixed nseg.",
    )
    diam: pq.Length = Field(
        default=1_000_000,
        description="The diameter of the section (stylized geometry). Overridden by per-point coord diameters when coords are supplied.",
    )  # 1 µm
    length: pq.Length | None = Field(
        default=None,
        description="Length of the section (stylized geometry). Required if coords is not provided; ignored when coords are supplied.",
    )
    ra: pq.Resistivity | None = Field(
        default=None,
        description="Axial resistivity (NEURON Ra). Unset inherits the model-wide default, then NEURON's built-in 35.4 Ω·cm.",
    )
    cm: pq.SpecificCapacitance | None = Field(
        default=None,
        description="Specific membrane capacitance (NEURON cm). Unset inherits the model-wide default, then NEURON's built-in 1 µF/cm².",
    )
    coords: list[CoordInputModel] | None = Field(
        default=None,
        description="The 3D coordinates (NEURON pt3d) describing the section's geometry. Required if length is not provided; when supplied they take precedence over length/diam. At least two points are needed to define a cable.",
    )
    parent: ConnectionInputModel | None = Field(
        default=None,
        description="The connection to this section's parent section. None for the root section of the cell.",
    )


class TopologyInputModel(BaseModel):
    """The topology of a cell, which defines its structure as a set of connected sections."""

    sections: list[SectionInputModel] = Field(
        description="The list of sections that make up the cell's morphology."
    )
