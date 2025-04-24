from .biophysics import BiophysicsInputModel
from .topology import TopologyInputModel
from pydantic import Field
from .base import BaseConfig
import uuid


class CellInputModel(BaseConfig):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    biophysics: BiophysicsInputModel
    topology: TopologyInputModel
        
    



