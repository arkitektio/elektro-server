from .biophysics import BiophysicsInputModel
from .topology import TopologyInputModel
from pydantic import Field
from .base import BaseConfig
import uuid


class CellInputModel(BaseConfig):
    """A cell model, which consists of a biophysics model and a topology. You can think of the biophysics model as the 'properties' of the cell, and the topology as the 'structure' of the cell."""
    id: str = Field(description="The unique identifier of the cell within the model.")
    biophysics: BiophysicsInputModel = Field(description="The biophysics model of the cell, which defines the properties of the cell such as its compartments, mechanisms, and parameters.")
    topology: TopologyInputModel = Field(description="The topology of the cell, which defines the structure of the cell such as its morphology and connectivity.")
