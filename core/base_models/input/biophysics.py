import uuid
from typing import Optional, List, Dict, Set
from pydantic import BaseModel, Field
import re
from .base import BaseConfig

class SectionParamMapInputModel(BaseConfig):
    param: str
    mechanism: str = Field(description="The governing mechanism")
    value: float = Field(description="The value of the parameter")
    description: Optional[str] = Field(description="Description of the parameter")
    
   
    
class GlobalParamMapInputModel(BaseModel):
    param: str
    value: float
    description: Optional[str] = None

class CompartmentInputModel(BaseConfig):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mechanisms: Set[str] = Field(default_factory=set)
    section_params: List[SectionParamMapInputModel] = Field(default_factory=dict)
    global_params: List[GlobalParamMapInputModel] = Field(default_factory=dict)
    
  
    
    def section_param_for_key(self, name):
        """Get the compartment for a given key."""
        return next((comp for comp in self.section_params if comp.param == name), None)
    
    def global_param_for_key(self, name):
        """Get the compartment for a given key."""
        return next((comp for comp in self.section_params if comp.param == name), None)
        
    


class BiophysicsInputModel(BaseConfig):
    compartments: List[CompartmentInputModel] = Field(default_factory=list)

    
    def add_compartment(self, compartment: CompartmentInputModel):
        assert self.compartment_for_key(compartment.id) is None, f"Compartment with id {compartment.id} already exists."
        self.compartments.append(compartment)
        
    
    def compartment_for_key(self, name) -> CompartmentInputModel :
        """Get the compartment for a given key."""
        return next((comp for comp in self.compartments if comp.id == name), None)
        

