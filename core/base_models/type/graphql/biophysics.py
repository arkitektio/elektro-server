import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from core.enums import DistributionKind
from ..biophysics import DistributionModel, SectionParamMapModel, GlobalParamMapModel, CompartmentModel, BiophysicsModel

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
    
    
@pydantic.type(GlobalParamMapModel, description="Represents a global parameter mapping for a biophysics model. (this will be set on non-mechanistic parameters  (i.e PAS ) of the model)")
class GlobalParamMap:
    param: str
    value: float
    description: Optional[str] = strawberry.field(default=None, description="Description of the parameter")

@pydantic.type(CompartmentModel, description="Represents a compartment in a biophysics model.")
class Compartment:
    id: str = strawberry.field(default_factory=lambda: str(uuid.uuid4()))
    mechanisms: list[str]  = strawberry.field(default_factory=set)
    section_params: List[SectionParamMap]
    global_params: List[GlobalParamMap] 
    
        

@pydantic.type(BiophysicsModel, description="Represents a biophysics model, which consists of compartments, each with their own mechanisms and parameters.")
class Biophysics:
    compartments: List[Compartment] = strawberry.field(default_factory=list, description="The list of compartments in the biophysics model.")

    
        

