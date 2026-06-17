import uuid
from typing import Optional, List, Dict, Set
from pydantic import BaseModel, Field
import re
from .base import BaseConfig


class SectionParamMapInputModel(BaseConfig):
    """A section parameter mapping for a biophysics model. (this will be set on the mechanisms of the compartments of the model)"""
    param: str = Field(description="The name of the parameter to set.")
    mechanism: str = Field(description="The governing mechanism")
    value: float = Field(description="The value of the parameter")
    description: Optional[str] = Field(default=None, description="Description of the parameter")


class GlobalParamMapInputModel(BaseModel):
    """A global parameter mapping for a biophysics model. (this will be set on non-mechanistic parameters (i.e PAS) of the model)"""
    param: str = Field(description="The name of the parameter to set.")
    value: float = Field(description="The value of the parameter")
    description: Optional[str] = Field(default=None, description="Description of the parameter")


class CompartmentInputModel(BaseConfig):
    """A compartment in a biophysics model."""
    id: str = Field(description="The unique identifier of the compartment within the model.")
    mechanisms: Set[str] = Field(default_factory=set, description="The set of mechanisms active in this compartment.")
    section_params: List[SectionParamMapInputModel] = Field(default_factory=dict, description="The mechanism-specific parameters applied to the sections of this compartment.")
    global_params: List[GlobalParamMapInputModel] = Field(default_factory=dict, description="The non-mechanistic (global) parameters applied to this compartment.")

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

    def compartment_for_key(self, name) -> CompartmentInputModel:
        """Get the compartment for a given key."""
        return next((comp for comp in self.compartments if comp.id == name), None)
