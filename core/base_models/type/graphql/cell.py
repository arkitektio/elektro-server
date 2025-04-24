from .biophysics import Biophysics
from .topology import Topology
from strawberry.experimental import pydantic

from ..cell import CellModel


@pydantic.type(CellModel)
class Cell:
    id: str 
    biophysics: Biophysics
    topology: Topology
        
    



