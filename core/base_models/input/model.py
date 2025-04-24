from typing import Dict, Union
from .cell import CellInputModel
from pydantic import BaseModel, Field
from typing import List, Dict, Literal, Union, Optional
import uuid
from core import enums



class SynapseInputModel(BaseModel):
    """Synaptic stimulus parameters."""
    kind: enums.SynapseKind = Field(default=enums.SynapseKind.EXP2SYN)
    e: float 
    tau2: float 
    tau1: float
    delay: float = 100.0
    cell: str
    location: str
    position: float = 0.5      # Be# ms


class NetConnectionInputModel(BaseModel):
    """Base class for net connection parameters."""
    kind: enums.ConnectionKind = Field(default=enums.ConnectionKind.SYNAPSE)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Name of the net connection
    weight: float | None = None
    threshold: float | None = None 
    delay: float | None = None
    net_stimulator: Optional[str] = None
    synapse: Optional[str] = None
    
   
class NetStimulatorInputModel(BaseModel):
    """Base class for net stimulation parameters."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Name of the net stimulator
    start: float = 100.0       # Start time (ms)
    number: int = 1            # Number of spikes
    interval: float | None = None
    net_stimulator: str
    synapse: str



class ModelConfigInputModel(BaseModel):
    cells: List[CellInputModel] = Field(default_factory=list)
    net_stimulators: List[NetStimulatorInputModel] = Field(default_factory=list)
    net_connections: List[NetStimulatorInputModel] = Field(default_factory=list)
    net_synapses: List[SynapseInputModel] = Field(default_factory=list)
    v_init: float = -67.0
    celsius: float = 36.0
    label: Optional[str] = None
    
    
    
    
    
    
    
