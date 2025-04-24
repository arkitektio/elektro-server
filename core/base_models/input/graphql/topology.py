import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from ..topology import TopologyInputModel, CoordInputModel, ConnectionInputModel, SectionInputModel

@pydantic.input(CoordInputModel)
class CoordInput:
    x: float
    y: float
    z: float

@pydantic.input(ConnectionInputModel)
class ConnectionInput:
    parent: str
    location: float = 1.0

@pydantic.input(SectionInputModel)
class SectionInput:
    id: str
    category: Optional[str]
    nseg: int = 1
    diam: float = 1.0
    length: Optional[float] = strawberry.field(default=None, description="Length of the section. Required if coords is not provided.")
    coords: List[CoordInput] | None = strawberry.field(default=None)
    connections: List[ConnectionInput] | None = strawberry.field(default_factory=list)
    
    
@pydantic.input(TopologyInputModel)
class TopologyInput:
    sections: List[SectionInput]