import strawberry
from .biophysics import Biophysics
from .topology import Topology
from strawberry.experimental import pydantic

from ..cell import CellModel


@pydantic.type(CellModel, description="Represents a cell model, which consists of a biophysics model and a topology. You can think of the biophysics model as the 'properties' of the cell, and the topology as the 'structure' of the cell.")
class Cell:
    id: str  = strawberry.field(description="The unique identifier of the cell within the model.")
    biophysics: Biophysics = strawberry.field(description="The biophysics model of the cell, which defines the properties of the cell such as its compartments, mechanisms, and parameters.")
    topology: Topology = strawberry.field(description="The topology of the cell, which defines the structure of the cell such as its morphology and connectivity.")
        
    



