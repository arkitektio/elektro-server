
import strawberry
from strawberry.experimental import pydantic

from ..cell import CellInputModel
from .biophysics import BiophysicsInput
from .topology import TopologyInput


@pydantic.input(CellInputModel, description="Input for a cell model, which consists of a biophysics model and a topology. You can think of the biophysics model as the 'properties' of the cell, and the topology as the 'structure' of the cell.")
class CellInput:
    id: str = strawberry.field(description="The unique identifier of the cell within the model.")
    biophysics: BiophysicsInput = strawberry.field(description="The biophysics model of the cell, which defines the properties of the cell such as its compartments, mechanisms, and parameters.")
    topology: TopologyInput = strawberry.field(description="The topology of the cell, which defines the structure of the cell such as its morphology and connectivity.")
        
    



