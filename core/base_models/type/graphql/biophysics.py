import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from ..biophysics import SectionParamMapModel, GlobalParamMapModel, CompartmentModel, BiophysicsModel

@pydantic.type(SectionParamMapModel, description="Represents a section parameter mapping for a biophysics model. (this will be set on the mechanisms of the compartments of the model)")
class SectionParamMap:
    param: str
    mechanism: str = strawberry.field(description="The governing mechanism")
    value: float = strawberry.field(description="The value of the parameter")
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

    
        

