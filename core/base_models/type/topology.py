from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class CoordModel(BaseModel):
    x: int  # picometers
    y: int  # picometers
    z: int  # picometers

class ConnectionModel(BaseModel):
    parent: str
    location: float = 1.0  # Between 0 and 1

class SectionModel(BaseModel):
    id: str
    category: Optional[str]
    nseg: int = 1
    diam: int = 1_000_000  # picometers (1 um)
    length: Optional[int] = Field(default=None, description="Length of the section in picometers. Required if coords is not provided.")
    coords: List[CoordModel] | None = Field(default=None)
    connections: List[ConnectionModel] = Field(default_factory=list)
    
    

class TopologyModel(BaseModel):
    sections: List[SectionModel]

    
    
            
    
        
        
    
    
    




