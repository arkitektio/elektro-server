from typing import Dict, Union
from .cell import CellModel
from pydantic import BaseModel, Field
from typing import List, Dict, Literal, Union, Optional
import uuid


class SynapseBaseModel(BaseModel):
    """Synaptic stimulus parameters."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Name of the synapse
    cell: str
    location: str
    position: float = 0.5      # Between 0 and 1


class Exp2SynModel(SynapseBaseModel):
    """Synaptic stimulus parameters."""
    kind: Literal["Exp2Syn"] = "Exp2Syn"
    e: float 
    tau2: float 
    tau1: float
    delay: float = 100.0       # ms


class NetConnectionModel(BaseModel):
    """Base class for net connection parameters."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Name of the net connection
    weight: float | None = None
    threshold: float | None = None 
    delay: float | None = None
    
    
class SynapticConnectionModel(NetConnectionModel):
    net_stimulator: str
    synapse: str
    
class NetStimulatorModel(BaseModel):
    """Base class for net stimulation parameters."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Name of the net stimulator
    start: float = 100.0       # Start time (ms)
    number: int = 1            # Number of spikes
    interval: float | None = None



class ModelConfigModel(BaseModel):
    cells: List[CellModel] = Field(default_factory=list)
    net_stimulators: List[NetStimulatorModel] = Field(default_factory=list)
    net_connections: List[Union[SynapticConnectionModel]] = Field(default_factory=list)
    net_synapses: List[Union[Exp2SynModel]] = Field(default_factory=list)
    v_init: float = -67.0
    celsius: float = 36.0
    label: Optional[str] = None
    
    
    
    
