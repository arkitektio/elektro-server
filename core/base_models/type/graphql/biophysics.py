import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from core import scalars
from core.enums import DistributionKind, IonStyle
from kanne import scalars as quantities
from ..biophysics import DistributionModel, SectionParamMapModel, MechanismGlobalParamModel, IonModel, CompartmentModel, BiophysicsModel

@pydantic.type(DistributionModel, description="Represents how a section parameter is distributed along a section (NEURON range variable).")
class Distribution:
    kind: DistributionKind = strawberry.field(default=DistributionKind.UNIFORM, description="The kind of spatial distribution.")
    value: Optional[float] = strawberry.field(default=None, description="The uniform value applied to every segment (required for 'uniform').")
    proximal_value: Optional[float] = strawberry.field(default=None, description="The value at path distance 0 (required for 'linear').")
    distal_value: Optional[float] = strawberry.field(default=None, description="The value at the most distal segment (required for 'linear').")
    expression: Optional[str] = strawberry.field(default=None, description="An expression in `x` (normalized position) and `d` (path distance) (required for 'expression').")

@pydantic.type(SectionParamMapModel, description="Represents a section parameter mapping for a biophysics model. (this will be set on the mechanisms of the compartments of the model)")
class SectionParamMap:
    param: str
    mechanism: str = strawberry.field(description="The governing mechanism")
    distribution: Distribution = strawberry.field(description="How the parameter is distributed along the section (uniform by default).")
    description: Optional[str] = strawberry.field(default=None, description="Description of the parameter")
    
    
@pydantic.type(MechanismGlobalParamModel, description="Represents a GLOBAL mechanism parameter (NEURON GLOBAL variable, e.g. q10_hh) — shared across every instance of the mechanism, set once at the model level.")
class MechanismGlobalParam:
    mechanism: str = strawberry.field(description="The mechanism that owns this GLOBAL parameter (e.g. 'hh').")
    param: str
    value: float
    description: Optional[str] = strawberry.field(default=None, description="Description of the parameter")

@pydantic.type(IonModel, description="Represents an ion species' intrinsic properties on a compartment (NEURON per-section ion settings, e.g. ena/nai/nao).")
class Ion:
    ion: str = strawberry.field(description="The ion species name as NEURON knows it (e.g. 'na', 'k', 'ca'). Custom ions declared by mechanisms are allowed.")
    style: IonStyle = strawberry.field(default=IonStyle.FIXED_REVERSAL, description="How the reversal potential and concentrations are treated (NEURON ion_style): a fixed reversal parameter, computed from fixed concentrations via Nernst, or with concentrations as states advanced by an accumulation mechanism.")
    reversal_potential: Optional[quantities.ElectricPotential] = strawberry.field(default=None, description="The reversal potential for this ion (NEURON e<ion>, e.g. ena). Unset leaves NEURON's default.")
    internal_concentration: Optional[quantities.Concentration] = strawberry.field(default=None, description="The intracellular concentration for this ion (NEURON <ion>i, e.g. nai).")
    external_concentration: Optional[quantities.Concentration] = strawberry.field(default=None, description="The extracellular concentration for this ion (NEURON <ion>o, e.g. nao).")

@pydantic.type(CompartmentModel, description="Represents a compartment in a biophysics model.")
class Compartment:
    id: str = strawberry.field(default_factory=lambda: str(uuid.uuid4()))
    mechanisms: list[str]  = strawberry.field(default_factory=set)
    section_params: List[SectionParamMap]
    ions: List[Ion] = strawberry.field(default_factory=list, description="Ion species settings (reversal potentials and concentrations) applied to this compartment.")
    color: Optional[scalars.RGBAColor] = strawberry.field(default=None, description="An optional RGBA color (list of 4 values) used to render this compartment in the UI.")
    
        

@pydantic.type(BiophysicsModel, description="Represents a biophysics model, which consists of compartments, each with their own mechanisms and parameters.")
class Biophysics:
    compartments: List[Compartment] = strawberry.field(default_factory=list, description="The list of compartments in the biophysics model.")

    
        

