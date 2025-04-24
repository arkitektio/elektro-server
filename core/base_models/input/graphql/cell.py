
from strawberry.experimental import pydantic

from ..cell import CellInputModel
from .biophysics import BiophysicsInput
from .topology import TopologyInput


@pydantic.input(CellInputModel)
class CellInput:
    id: str 
    biophysics: BiophysicsInput
    topology: TopologyInput
        
    



