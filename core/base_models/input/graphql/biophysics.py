import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from ..biophysics import SectionParamMapInputModel, GlobalParamMapInputModel, CompartmentInputModel, BiophysicsInputModel

@pydantic.input(SectionParamMapInputModel)
class SectionParamMapInput:
    param: str
    mechanism: str = strawberry.field(description="The governing mechanism")
    value: float = strawberry.field(description="The value of the parameter")
    description: Optional[str] = strawberry.field(None, description="Description of the parameter")
    
    
@pydantic.input(GlobalParamMapInputModel)
class GlobalParamMapInput:
    param: str
    value: float
    description: Optional[str] = None

@pydantic.input(CompartmentInputModel)
class CompartmentInput:
    id: str = strawberry.field(default_factory=lambda: str(uuid.uuid4()))
    mechanisms: list[str]  = strawberry.field(default_factory=set)
    section_params: List[SectionParamMapInput] | None = strawberry.field(default_factory=list)
    global_params: List[GlobalParamMapInput] | None  = strawberry.field(default_factory=list)
    
        

@pydantic.input(BiophysicsInputModel)
class BiophysicsInput:
    compartments: List[CompartmentInput] = strawberry.field(default_factory=list)

    
        

