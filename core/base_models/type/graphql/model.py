from typing import List, Literal
from .biophysics import Biophysics
from .topology import Topology
from strawberry.experimental import pydantic
import strawberry
from .cell import Cell
from ..model import Exp2SynModel, SynapticConnectionModel, SynapseBaseModel, NetConnectionModel, NetStimulatorModel, ModelConfigModel


@pydantic.interface(SynapseBaseModel)
class NetSynapse:
    """Synaptic stimulus parameters."""
    id: strawberry.ID  
    cell: str
    location: str
    position: float = 0.5      # Between 0 and 1

@pydantic.type(Exp2SynModel)
class Exp2Synapse(NetSynapse):
    """Synaptic stimulus parameters."""
    e: float 
    tau2: float 
    tau1: float
    delay: float = 100.0       # ms

@pydantic.interface(NetConnectionModel)
class NetConnection:
    """Base class for net connection parameters."""
    id: strawberry.ID 
    weight: float | None = None
    threshold: float | None = None 
    delay: float | None = None
    
@pydantic.type(SynapticConnectionModel)
class SynapticConnection(NetConnection):
    net_stimulator: strawberry.ID
    synapse: strawberry.ID

@pydantic.type(NetStimulatorModel)
class NetStimulator:
    """Base class for net stimulation parameters."""
    id: strawberry.ID
    start: float = 100.0       # Start time (ms)
    number: int = 1            # Number of spikes
    interval: float | None = None



@pydantic.type(ModelConfigModel)
class ModelConfig:
    cells: List[Cell] 
    net_stimulators: List[NetStimulator]  | None
    net_connections: List[NetConnection] | None
    net_synapses: List[NetSynapse] | None
    v_init: float 
    celsius: float 
    label: str | None = None
    
    
    
    




