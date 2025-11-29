from .biophysics import BiophysicsInputModel
from .topology import TopologyInputModel
from pydantic import Field
from .base import BaseConfig
import uuid


class CellInputModel(BaseConfig):
    id: str
    biophysics: BiophysicsInputModel
    topology: TopologyInputModel
