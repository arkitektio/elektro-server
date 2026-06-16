from typing import Dict, Union
from .cell import CellModel
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Literal, Union, Optional
import uuid


class SynapseBaseModel(BaseModel):
    """Synaptic stimulus parameters."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Name of the synapse
    cell: str
    location: str
    position: float = 0.5      # Between 0 and 1


class Exp2SynModel(SynapseBaseModel):
    """Synaptic stimulus parameters. Quantity fields are stored as nano-base ints."""
    kind: Literal["exp2syn"] = "exp2syn"
    e: int          # femtovolts
    tau2: int       # picoseconds
    tau1: int       # picoseconds
    delay: int = 100_000_000_000   # picoseconds (100 ms)


class NetConnectionModel(BaseModel):
    """Base class for net connection parameters. Quantities stored as nano-base ints."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Name of the net connection
    weight: int | None = None      # femtosiemens
    threshold: int | None = None   # femtovolts
    delay: int | None = None       # picoseconds


class SynapticConnectionModel(NetConnectionModel):
    net_stimulator: str
    synapse: str

class NetStimulatorModel(BaseModel):
    """Base class for net stimulation parameters. Quantities stored as nano-base ints."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Name of the net stimulator
    start: int = 100_000_000_000   # picoseconds (100 ms)
    number: int = 1            # Number of spikes
    interval: int | None = None    # picoseconds



class ModelConfigModel(BaseModel):
    cells: List[CellModel] = Field(default_factory=list)
    net_stimulators: List[NetStimulatorModel] | None = Field(default_factory=list)
    net_connections: List[Union[SynapticConnectionModel]] | None= Field(default_factory=list)
    net_synapses: List[Union[Exp2SynModel]] | None = Field(default_factory=list)
    v_init: int = -67_000_000_000_000   # femtovolts (-67 mV)
    celsius: float = 36.0
    label: Optional[str] = None
    
    
    
    
    
    
    
    
