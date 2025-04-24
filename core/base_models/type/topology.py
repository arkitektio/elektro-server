from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class CoordModel(BaseModel):
    x: float
    y: float
    z: float

class ConnectionModel(BaseModel):
    parent: str
    location: float = 1.0

class SectionModel(BaseModel):
    id: str
    category: Optional[str]
    nseg: int = 1
    diam: float = 1.0
    length: Optional[float] = Field(default=None, description="Length of the section. Required if coords is not provided.")
    coords: List[CoordModel] | None = Field(default=None)
    connections: List[ConnectionModel] = Field(default_factory=list)
    
    

class TopologyModel(BaseModel):
    sections: List[SectionModel]

    
    
            
    
        
        
    
    
    




