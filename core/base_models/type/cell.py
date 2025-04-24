from .biophysics import BiophysicsModel
from .topology import TopologyModel
from pydantic import Field, BaseModel
import uuid


class CellModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    biophysics: BiophysicsModel
    topology: TopologyModel
        
    



