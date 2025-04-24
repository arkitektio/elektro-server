import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from ..biophysics import SectionParamMapModel, GlobalParamMapModel, CompartmentModel, BiophysicsModel

@pydantic.type(SectionParamMapModel)
class SectionParamMap:
    param: str
    mechanism: str = strawberry.field(description="The governing mechanism")
    value: float = strawberry.field(description="The value of the parameter")
    description: Optional[str] = strawberry.field(None, description="Description of the parameter")
    
    
@pydantic.type(GlobalParamMapModel)
class GlobalParamMap:
    param: str
    value: float
    description: Optional[str] = None

@pydantic.type(CompartmentModel)
class Compartment:
    id: str = strawberry.field(default_factory=lambda: str(uuid.uuid4()))
    mechanisms: list[str]  = strawberry.field(default_factory=set)
    section_params: List[SectionParamMap]
    global_params: List[GlobalParamMap] 
    
        

@pydantic.type(BiophysicsModel)
class Biophysics:
    compartments: List[Compartment] = strawberry.field(default_factory=list)

    
        

