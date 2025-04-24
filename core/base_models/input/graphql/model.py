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
    start: float = 100.0       # Start time (ms)
    number: int = 1            # Number of spikes
    interval: float | None = None

@pydantic.input(NetConnectionInputModel)
class NetConnectionInput:
    """Base class for net stimulation parameters."""
    kind: ConnectionKind
    id: strawberry.ID
    start: float = 100.0       # Start time (ms)
    number: int = 1            # Number of spikes
    interval: float | None = None


@pydantic.input(ModelConfigInputModel)
class ModelConfigInput:
    cells: List[CellInput] 
    net_stimulators: List[NetStimulatorInput]  | None = strawberry.field(default=None)
    net_connections: List[NetConnectionInput] | None = strawberry.field(default=None)
    net_synapses: List[NetSynapseInput] | None = strawberry.field(default=None)
    v_init: float 
    celsius: float 
    label: str | None = None
    
    
    
    




