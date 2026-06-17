from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class CoordInputModel(BaseModel):
    """A 3D coordinate (in space) of a point along a section. Stored in picometers."""
    x: int = Field(description="The x coordinate of the point.")  # picometers
    y: int = Field(description="The y coordinate of the point.")  # picometers
    z: int = Field(description="The z coordinate of the point.")  # picometers

class ConnectionInputModel(BaseModel):
    """A connection of a section to its parent section, defining the morphology tree."""
    parent: str = Field(description="The ID of the parent section this section connects to.")
    location: float = Field(default=1.0, description="The position along the parent section where this section attaches, between 0 and 1.")  # Between 0 and 1

class SectionInputModel(BaseModel):
    """A section of a cell's morphology, the basic structural unit of the topology."""
    id: str = Field(description="The unique identifier of the section within the cell.")
    category: Optional[str] = Field(default=None, description="An optional category for the section (e.g. 'soma', 'axon', 'dend').")
    nseg: int = Field(default=1, description="The number of segments the section is discretized into.")
    diam: int = Field(default=1_000_000, description="The diameter of the section.")  # picometers (1 um)
    length: Optional[int] = Field(default=None, description="Length of the section in picometers. Required if coords is not provided.")
    coords: List[CoordInputModel] | None = Field(default=None, description="The 3D coordinates describing the section's geometry. Required if length is not provided.")
    connections: List[ConnectionInputModel] = Field(default_factory=list, description="The connections of this section to its parent section(s).")



class TopologyInputModel(BaseModel):
    """The topology of a cell, which defines its structure as a set of connected sections."""
    sections: List[SectionInputModel] = Field(description="The list of sections that make up the cell's morphology.")

    
    
            
    
        
        
    
    
    




