from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class CoordInputModel(BaseModel):
    x: int  # picometers
    y: int  # picometers
    z: int  # picometers

class ConnectionInputModel(BaseModel):
    parent: str
    location: float = 1.0  # Between 0 and 1

class SectionInputModel(BaseModel):
    id: str
    category: Optional[str] = None
    nseg: int = 1
    diam: int = 1_000_000  # picometers (1 um)
    length: Optional[int] = Field(default=None, description="Length of the section in picometers. Required if coords is not provided.")
    coords: List[CoordInputModel] | None = Field(default=None)
    connections: List[ConnectionInputModel] = Field(default_factory=list)
    
    

class TopologyInputModel(BaseModel):
    sections: List[SectionInputModel]

    
    
            
    
        
        
    
    
    




