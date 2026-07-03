import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from kanne_server import scalars as quantities
from ..topology import TopologyInputModel, CoordInputModel, ConnectionInputModel, SectionInputModel

@pydantic.input(CoordInputModel, description="Input for a 3D coordinate (in space) of a point along a section.")
class CoordInput:
    x: quantities.Length = strawberry.field(description="The x coordinate of the point.")
    y: quantities.Length = strawberry.field(description="The y coordinate of the point.")
    z: quantities.Length = strawberry.field(description="The z coordinate of the point.")
    diam: Optional[quantities.Length] = strawberry.field(default=None, description="The diameter of the section at this point (NEURON pt3d). Falls back to the section diameter when omitted.")

@pydantic.input(ConnectionInputModel, description="Input for a connection of a section to its (single) parent section, defining the morphology tree.")
class ConnectionInput:
    parent: str = strawberry.field(description="The ID of the parent section this section connects to.")
    parent_location: float = strawberry.field(default=1.0, description="The position along the parent section where this section attaches, between 0 and 1.")
    child_end: float = strawberry.field(default=0.0, description="Which end of this section attaches to the parent: 0 (default) or 1.")

@pydantic.input(SectionInputModel, description="Input for a section of a cell's morphology, the basic structural unit of the topology.")
class SectionInput:
    id: str = strawberry.field(description="The unique identifier of the section within the cell.")
    category: Optional[str] = strawberry.field(default=None, description="An optional category for the section (e.g. 'soma', 'axon', 'dend'). Biophysics compartments are matched to sections by this category.")
    nseg: int = strawberry.field(default=1, description="The number of segments the section is discretized into (used when d_lambda is not set). NEURON convention prefers an odd count so the section has a true midpoint node.")
    d_lambda: Optional[float] = strawberry.field(default=None, description="If set, nseg is computed from NEURON's d_lambda rule (target fraction of the AC length constant at 100 Hz per segment; 0.1 is typical) and overrides the fixed nseg.")
    diam: quantities.Length = strawberry.field(default=1_000_000, description="The diameter of the section (stylized geometry). Overridden by per-point coord diameters when coords are supplied.")
    length: Optional[quantities.Length] = strawberry.field(default=None, description="Length of the section (stylized geometry). Required if coords is not provided; ignored when coords are supplied.")
    ra: Optional[quantities.Resistivity] = strawberry.field(default=None, description="Axial resistivity (NEURON Ra). Unset inherits the model-wide default, then NEURON's built-in 35.4 Ω·cm.")
    cm: Optional[quantities.SpecificCapacitance] = strawberry.field(default=None, description="Specific membrane capacitance (NEURON cm). Unset inherits the model-wide default, then NEURON's built-in 1 µF/cm².")
    coords: List[CoordInput] | None = strawberry.field(default=None, description="The 3D coordinates (NEURON pt3d) describing the section's geometry. Required if length is not provided; when supplied they take precedence over length/diam. At least two points are needed to define a cable.")
    parent: Optional[ConnectionInput] = strawberry.field(default=None, description="The connection to this section's parent section. None for the root section of the cell.")


@pydantic.input(TopologyInputModel, description="Input for the topology of a cell, which defines its structure as a set of connected sections.")
class TopologyInput:
    sections: List[SectionInput] = strawberry.field(description="The list of sections that make up the cell's morphology.")