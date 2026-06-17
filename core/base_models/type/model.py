from typing import Dict, Union
from .cell import CellModel
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Literal, Union, Optional
import uuid


class SynapseBaseModel(BaseModel):
    """Base class for synaptic stimulus parameters."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="The unique identifier of the synapse within the model.")
    cell: str = Field(description="The ID of the cell this synapse is located on.")
    location: str = Field(description="The location on the cell where the synapse is located. This can be a section name, a segment number, or a more complex specification depending on the model.")
    position: float = Field(default=0.5, description="The position along the section where the synapse is located, specified as a value between 0 and 1. This is only relevant if the location is specified as a section name.")


class Exp2SynModel(SynapseBaseModel):
    """Exponential synapse, a synaptic stimulus with an exponential rise and decay. Quantity fields are stored as nano-base ints."""
    kind: Literal["exp2syn"] = "exp2syn"
    e: int = Field(description="Reversal potential.")          # femtovolts
    tau2: int = Field(description="Decay time constant.")      # picoseconds
    tau1: int = Field(description="Rise time constant.")       # picoseconds
    delay: int = Field(default=100_000_000_000, description="Delay before the synapse activates.")   # picoseconds (100 ms)


class NetConnectionModel(BaseModel):
    """Base class for net connection parameters. Quantities stored as nano-base ints."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="The unique identifier of the connection within the model.")
    weight: int | None = Field(default=None, description="The weight (conductance) of the connection.")      # femtosiemens
    threshold: int | None = Field(default=None, description="The threshold for the connection.")   # femtovolts
    delay: int | None = Field(default=None, description="The delay for the connection.")       # picoseconds


class SynapticConnectionModel(NetConnectionModel):
    """Synaptic connection between two cells, linking a pre-synaptic net stimulator to a post-synaptic synapse."""
    net_stimulator: str = Field(description="The ID of the net stimulator that is the pre-synaptic cell in this connection.")
    synapse: str = Field(description="The ID of the synapse that is the post-synaptic cell in this connection.")

class NetStimulatorModel(BaseModel):
    """Base class for net stimulation parameters. Quantities stored as nano-base ints."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="The unique identifier of the stimulator within the model.")
    start: int = Field(default=100_000_000_000, description="Start time of the first spike.")   # picoseconds (100 ms)
    number: int = Field(default=1, description="Number of spikes to emit.")            # Number of spikes
    interval: int | None = Field(default=None, description="Interval between spikes.")    # picoseconds



class ModelConfigModel(BaseModel):
    """Configuration for a model."""
    cells: List[CellModel] = Field(default_factory=list, description="The list of cells in the model.")
    net_stimulators: List[NetStimulatorModel] | None = Field(default_factory=list, description="The list of net stimulators in the model.")
    net_connections: List[Union[SynapticConnectionModel]] | None= Field(default_factory=list, description="The list of net connections in the model.")
    net_synapses: List[Union[Exp2SynModel]] | None = Field(default_factory=list, description="The list of net synapses in the model.")
    v_init: int = Field(default=-67_000_000_000_000, description="Initial membrane potential.")   # femtovolts (-67 mV)
    temperature: int = Field(default=309_150_000_000, description="Simulation bath temperature.")   # nanokelvin (36 °C)
    label: Optional[str] = Field(default=None, description="An optional label for the model configuration.")
    
    
    
    
    
    
    
    
