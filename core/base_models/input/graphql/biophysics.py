import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from ..biophysics import SectionParamMapInputModel, GlobalParamMapInputModel, CompartmentInputModel, BiophysicsInputModel


@pydantic.input(SectionParamMapInputModel, description="Input for a section parameter mapping of a biophysics model. (this will be set on the mechanisms of the compartments of the model)")
class SectionParamMapInput:
    param: str = strawberry.field(description="The name of the parameter to set.")
    mechanism: str = strawberry.field(description="The governing mechanism")
    value: float = strawberry.field(description="The value of the parameter")
    description: Optional[str] = strawberry.field(default=None, description="Description of the parameter")


@pydantic.input(GlobalParamMapInputModel, description="Input for a global parameter mapping of a biophysics model. (this will be set on non-mechanistic parameters (i.e PAS) of the model)")
class GlobalParamMapInput:
    param: str = strawberry.field(description="The name of the parameter to set.")
    value: float = strawberry.field(description="The value of the parameter")
    description: Optional[str] = strawberry.field(default=None, description="Description of the parameter")


@pydantic.input(CompartmentInputModel, description="Input for a compartment in a biophysics model.")
class CompartmentInput:
    id: str = strawberry.field(default_factory=lambda: str(uuid.uuid4()), description="The unique identifier of the compartment within the model.")
    mechanisms: list[str] = strawberry.field(default_factory=set, description="The set of mechanisms active in this compartment.")
    section_params: List[SectionParamMapInput] | None = strawberry.field(default_factory=list, description="The mechanism-specific parameters applied to the sections of this compartment.")
    global_params: List[GlobalParamMapInput] | None = strawberry.field(default_factory=list, description="The non-mechanistic (global) parameters applied to this compartment.")


@pydantic.input(BiophysicsInputModel, description="Input for a biophysics model, which consists of compartments, each with their own mechanisms and parameters.")
class BiophysicsInput:
    compartments: List[CompartmentInput] = strawberry.field(default_factory=list, description="The list of compartments in the biophysics model.")
