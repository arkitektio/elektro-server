import uuid
from typing import Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
import re
from core import scalars
from core.enums import DistributionKind
from ..biophysics import DistributionInputModel, SectionParamMapInputModel, GlobalParamMapInputModel, CompartmentInputModel, BiophysicsInputModel


@pydantic.input(DistributionInputModel, description="Input for how a section parameter is distributed along a section (NEURON range variable). Supply the fields matching the chosen kind: 'uniform' -> value; 'linear' -> proximal_value & distal_value; 'expression' -> expression.")
class DistributionInput:
    kind: DistributionKind = strawberry.field(default=DistributionKind.UNIFORM, description="The kind of spatial distribution.")
    value: Optional[float] = strawberry.field(default=None, description="The uniform value applied to every segment (required for 'uniform').")
    proximal_value: Optional[float] = strawberry.field(default=None, description="The value at path distance 0 (required for 'linear').")
    distal_value: Optional[float] = strawberry.field(default=None, description="The value at the most distal segment (required for 'linear').")
    expression: Optional[str] = strawberry.field(default=None, description="An expression in `x` (normalized position) and `d` (path distance) (required for 'expression').")


@pydantic.input(SectionParamMapInputModel, description="Input for a section parameter mapping of a biophysics model. (this will be set on the mechanisms of the compartments of the model)")
class SectionParamMapInput:
    param: str = strawberry.field(description="The name of the parameter to set.")
    mechanism: str = strawberry.field(description="The governing mechanism")
    distribution: DistributionInput = strawberry.field(description="How the parameter is distributed along the section (uniform by default).")
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
    color: Optional[scalars.RGBAColor] = strawberry.field(default=None, description="An optional RGBA color (list of 4 values) used to render this compartment in the UI.")


@pydantic.input(BiophysicsInputModel, description="Input for a biophysics model, which consists of compartments, each with their own mechanisms and parameters.")
class BiophysicsInput:
    compartments: List[CompartmentInput] = strawberry.field(default_factory=list, description="The list of compartments in the biophysics model.")
