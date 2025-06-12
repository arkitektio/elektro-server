from typing import List, Literal
from strawberry.experimental import pydantic
import strawberry
from .cell import CellInput
from ..model import ModelConfigInputModel, NetConnectionInputModel, NetStimulatorInputModel, SynapseInputModel
from core.enums import SynapseKind, ConnectionKind


@pydantic.input(NetStimulatorInputModel)
class NetStimulatorInput:
    """Base class for net stimulation parameters."""
    id: strawberry.ID
    start: float = 100.0       # Start time (ms)
    number: int = 1            # Number of spikes
    interval: float | None = None

@pydantic.input(SynapseInputModel)
class NetSynapseInput:
    """Base class for net stimulation parameters."""
    kind: SynapseKind
    id: strawberry.ID
    e: float 
    tau2: float 
    tau1: float
    cell: strawberry.ID
    location: strawberry.ID
    position: float = 0.5      # Between 0 and 1

@pydantic.input(NetConnectionInputModel)
class NetConnectionInput:
    """Base class for net stimulation parameters."""
    kind: ConnectionKind
    synapse: strawberry.ID
    net_stimulator: strawberry.ID
    id: strawberry.ID
    weight: float | None = None
    threshold: float | None = None
    delay: float | None = None


@pydantic.input(ModelConfigInputModel)
class ModelConfigInput:
    cells: List[CellInput] 
    net_stimulators: List[NetStimulatorInput]  | None = strawberry.field(default_factory=list)
    net_connections: List[NetConnectionInput] | None = strawberry.field(default_factory=list)
    net_synapses: List[NetSynapseInput] | None = strawberry.field(default_factory=list)
    v_init: float 
    celsius: float 
    label: str | None = None
    
    
    
    




