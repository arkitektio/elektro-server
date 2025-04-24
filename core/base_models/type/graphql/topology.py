import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from ..topology import TopologyModel, CoordModel, ConnectionModel, SectionModel

@pydantic.type(CoordModel)
class Coord:
    x: float
    y: float
    z: float

@pydantic.type(ConnectionModel)
class Connection:
    parent: str
    location: float = 1.0

@pydantic.type(SectionModel)
class Section:
    id: str
    category: str
    nseg: int = 1
    diam: float = 1.0
    length: Optional[float] = strawberry.field(default=None, description="Length of the section. Required if coords is not provided.")
    coords: List[Coord] | None = strawberry.field(default=None)
    connections: List[Connection] = strawberry.field(default_factory=list)
    
    
@pydantic.type(TopologyModel)
class Topology:
    sections: List[Section]