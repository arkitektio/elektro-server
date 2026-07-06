import uuid
from typing import Optional, List, Set
from pydantic import BaseModel, Field
from core import enums
from kanne_server import quantities as pq


class DistributionModel(BaseModel):
    """How a section parameter is distributed along a section (NEURON range variable).

    - ``uniform``: a single ``value`` applied to every segment (default).
    - ``linear``: linear interpolation from ``proximal_value`` (path distance 0,
      i.e. the soma) to ``distal_value`` (the most distal segment).
    - ``expression``: ``expression`` evaluated per segment as a function of the
      normalized position ``x`` (0-1 along the section) and the path distance
      ``d`` from the soma.
    """
    kind: enums.DistributionKind = Field(default=enums.DistributionKind.UNIFORM, description="The kind of spatial distribution.")
    value: Optional[pq.GenericQuantity] = Field(default=None, description="The uniform value applied to every segment (required for 'uniform'). A unit-bearing quantity, e.g. '0.12 S/cm2'.")
    proximal_value: Optional[pq.GenericQuantity] = Field(default=None, description="The value at path distance 0 (required for 'linear'). A unit-bearing quantity.")
    distal_value: Optional[pq.GenericQuantity] = Field(default=None, description="The value at the most distal segment (required for 'linear'). A unit-bearing quantity.")
    expression: Optional[str] = Field(default=None, description="An expression in `x` (normalized position) and `d` (path distance) (required for 'expression').")


class SectionParamMapModel(BaseModel):
    """A section parameter mapping for a biophysics model. (this will be set on the mechanisms of the compartments of the model)"""
    param: str = Field(description="The name of the parameter to set.")
    mechanism: str = Field(description="The governing mechanism")
    distribution: DistributionModel = Field(description="How the parameter is distributed along the section (uniform by default).")
    description: Optional[str] = Field(default=None, description="Description of the parameter")




class MechanismGlobalParamModel(BaseModel):
    """A GLOBAL mechanism parameter (NEURON GLOBAL variable, e.g. ``q10_hh``).

    Unlike a section parameter (a per-segment RANGE variable), a GLOBAL is shared
    across every instance of the mechanism in the simulation, so it is set once at
    the model level rather than per compartment.
    """
    mechanism: str = Field(description="The mechanism that owns this GLOBAL parameter (e.g. 'hh').")
    param: str = Field(description="The name of the GLOBAL parameter to set (e.g. 'q10').")
    value: pq.GenericQuantity = Field(description="The value of the parameter, as a unit-bearing quantity (e.g. '2 dimensionless', '10 mV').")
    description: Optional[str] = Field(default=None, description="Description of the parameter")


class IonModel(BaseModel):
    """An ion species' intrinsic properties on a compartment (NEURON per-section ion settings).

    Maps to NEURON's per-ion range variables: for ion ``na`` these are the
    reversal potential ``ena`` and the internal/external concentrations
    ``nai``/``nao``. Leave a field unset to keep NEURON's default (or let an
    accumulation mechanism compute it, e.g. Nernst).
    """
    ion: str = Field(description="The ion species name as NEURON knows it (e.g. 'na', 'k', 'ca'). Custom ions declared by mechanisms are allowed.")
    style: enums.IonStyle = Field(default=enums.IonStyle.FIXED_REVERSAL, description="How the reversal potential and concentrations are treated (NEURON ion_style): a fixed reversal parameter, computed from fixed concentrations via Nernst, or with concentrations as states advanced by an accumulation mechanism.")
    reversal_potential: Optional[pq.ElectricPotential] = Field(default=None, description="The reversal potential for this ion (NEURON e<ion>, e.g. ena). Unset leaves NEURON's default.")
    internal_concentration: Optional[pq.Concentration] = Field(default=None, description="The intracellular concentration for this ion (NEURON <ion>i, e.g. nai).")
    external_concentration: Optional[pq.Concentration] = Field(default=None, description="The extracellular concentration for this ion (NEURON <ion>o, e.g. nao).")


class CompartmentModel(BaseModel):
    """A compartment in a biophysics model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="The unique identifier of the compartment within the model.")
    mechanisms: Set[str] = Field(default_factory=set, description="The set of mechanisms active in this compartment.")
    section_params: List[SectionParamMapModel] = Field(default_factory=list, description="The mechanism-specific parameters applied to the sections of this compartment.")
    ions: List[IonModel] = Field(default_factory=list, description="Ion species settings (reversal potentials and concentrations) applied to this compartment.")
    color: Optional[List[int]] = Field(default=None, description="An optional RGBA color (list of 4 values) used to render this compartment in the UI.")


    def section_param_for_key(self, name: str) -> SectionParamMapModel | None:
        """Get the section parameter for a given param name."""
        return next((param for param in self.section_params if param.param == name), None)

    


class BiophysicsModel(BaseModel):
    """A biophysics model for a neuron, consisting of compartments with mechanisms and parameters."""
    compartments: List[CompartmentModel] = Field(default_factory=list)

    
    def add_compartment(self, compartment: CompartmentModel) -> None:
        """Add a compartment to the biophysics model."""
        assert self.compartment_for_key(compartment.id) is None, f"Compartment with id {compartment.id} already exists."
        self.compartments.append(compartment)
        
    
    def compartment_for_key(self, name: str) -> CompartmentModel | None:
        """Get the compartment for a given key."""
        return next((comp for comp in self.compartments if comp.id == name), None)
        

