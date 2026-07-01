import uuid
from typing import Optional, List, Dict, Set
from pydantic import BaseModel, Field, model_validator
import re
from .base import BaseConfig
from core import enums


class DistributionInputModel(BaseConfig):
    """How a section parameter is distributed along a section (NEURON range variable).

    - ``uniform``: a single ``value`` applied to every segment (default).
    - ``linear``: linear interpolation from ``proximal_value`` (path distance 0,
      i.e. the soma) to ``distal_value`` (the most distal segment).
    - ``expression``: ``expression`` evaluated per segment as a function of the
      normalized position ``x`` (0-1 along the section) and the path distance
      ``d`` from the soma.
    """
    kind: enums.DistributionKind = Field(default=enums.DistributionKind.UNIFORM, description="The kind of spatial distribution.")
    value: Optional[float] = Field(default=None, description="The uniform value applied to every segment (required for 'uniform').")
    proximal_value: Optional[float] = Field(default=None, description="The value at path distance 0 (required for 'linear').")
    distal_value: Optional[float] = Field(default=None, description="The value at the most distal segment (required for 'linear').")
    expression: Optional[str] = Field(default=None, description="An expression in `x` (normalized position) and `d` (path distance) (required for 'expression').")

    @model_validator(mode="after")
    def check_kind(self) -> "DistributionInputModel":
        if self.kind == enums.DistributionKind.UNIFORM and self.value is None:
            raise ValueError("A 'uniform' distribution requires a value.")
        if self.kind == enums.DistributionKind.LINEAR and (self.proximal_value is None or self.distal_value is None):
            raise ValueError("A 'linear' distribution requires both proximal_value and distal_value.")
        if self.kind == enums.DistributionKind.EXPRESSION and self.expression is None:
            raise ValueError("An 'expression' distribution requires an expression.")
        return self


class SectionParamMapInputModel(BaseConfig):
    """A section parameter mapping for a biophysics model. (this will be set on the mechanisms of the compartments of the model)"""
    param: str = Field(description="The name of the parameter to set.")
    mechanism: str = Field(description="The governing mechanism")
    distribution: DistributionInputModel = Field(description="How the parameter is distributed along the section (uniform by default).")
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
    section_params: List[SectionParamMapInputModel] = Field(default_factory=list, description="The mechanism-specific parameters applied to the sections of this compartment.")
    global_params: List[GlobalParamMapInputModel] = Field(default_factory=list, description="The non-mechanistic (global) parameters applied to this compartment.")

    def section_param_for_key(self, name):
        """Get the section parameter for a given param name."""
        return next((param for param in self.section_params if param.param == name), None)

    def global_param_for_key(self, name):
        """Get the global parameter for a given param name."""
        return next((param for param in self.global_params if param.param == name), None)


class BiophysicsInputModel(BaseConfig):
    compartments: List[CompartmentInputModel] = Field(default_factory=list)

    def add_compartment(self, compartment: CompartmentInputModel):
        assert self.compartment_for_key(compartment.id) is None, f"Compartment with id {compartment.id} already exists."
        self.compartments.append(compartment)

    def compartment_for_key(self, name) -> CompartmentInputModel:
        """Get the compartment for a given key."""
        return next((comp for comp in self.compartments if comp.id == name), None)
