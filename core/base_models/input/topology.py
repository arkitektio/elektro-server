from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class CoordInputModel(BaseModel):
    x: float
    y: float
    z: float

class ConnectionInputModel(BaseModel):
    parent: str
    location: float = 1.0

class SectionInputModel(BaseModel):
    id: str
    category: Optional[str]
    nseg: int = 1
    diam: float = 1.0
    length: Optional[float] = Field(default=None, description="Length of the section. Required if coords is not provided.")
    coords: List[CoordInputModel] | None = Field(default=None)
    connections: List[ConnectionInputModel] = Field(default_factory=list)
    
    

class TopologyInputModel(BaseModel):
    sections: List[SectionInputModel]

    
    
            
    
        
        
    
    
    




