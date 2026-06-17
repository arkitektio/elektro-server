import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from kanne import scalars as quantities
from ..topology import TopologyInputModel, CoordInputModel, ConnectionInputModel, SectionInputModel

@pydantic.input(CoordInputModel, description="Input for a 3D coordinate (in space) of a point along a section.")
class CoordInput:
    x: quantities.Length = strawberry.field(description="The x coordinate of the point.")
    y: quantities.Length = strawberry.field(description="The y coordinate of the point.")
    z: quantities.Length = strawberry.field(description="The z coordinate of the point.")

@pydantic.input(ConnectionInputModel, description="Input for a connection of a section to its parent section, defining the morphology tree.")
class ConnectionInput:
    parent: str = strawberry.field(description="The ID of the parent section this section connects to.")
    location: float = strawberry.field(default=1.0, description="The position along the parent section where this section attaches, between 0 and 1.")

@pydantic.input(SectionInputModel, description="Input for a section of a cell's morphology, the basic structural unit of the topology.")
class SectionInput:
    id: str = strawberry.field(description="The unique identifier of the section within the cell.")
    category: Optional[str] = strawberry.field(default=None, description="An optional category for the section (e.g. 'soma', 'axon', 'dend').")
    nseg: int = strawberry.field(default=1, description="The number of segments the section is discretized into.")
    diam: quantities.Length = strawberry.field(default=1_000_000, description="The diameter of the section.")
    length: Optional[quantities.Length] = strawberry.field(default=None, description="Length of the section. Required if coords is not provided.")
    coords: List[CoordInput] | None = strawberry.field(default=None, description="The 3D coordinates describing the section's geometry. Required if length is not provided.")
    connections: List[ConnectionInput] | None = strawberry.field(default_factory=list, description="The connections of this section to its parent section(s).")


@pydantic.input(TopologyInputModel, description="Input for the topology of a cell, which defines its structure as a set of connected sections.")
class TopologyInput:
    sections: List[SectionInput] = strawberry.field(description="The list of sections that make up the cell's morphology.")