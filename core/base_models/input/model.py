from typing import Dict, Union
from .cell import CellInputModel
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Literal, Union, Optional
from kanne import quantities as pq
import uuid
from core import enums


class SynapseInputModel(BaseModel):
    """Synaptic stimulus parameters. Quantities persist as {canonical, given, unit}."""

    kind: enums.SynapseKind = Field(default=enums.SynapseKind.EXP2SYN, description="The kind of synapse model to use.")
    e: pq.ElectricPotential = Field(description="Reversal potential.")
    tau2: pq.Duration = Field(description="Decay time constant.")
    tau1: pq.Duration = Field(description="Rise time constant.")
    delay: pq.Duration = Field(default=100_000_000_000, description="Delay before the synapse activates.")   # 100 ms
    cell: str = Field(description="The ID of the cell this synapse is located on.")
    location: str = Field(description="The location on the cell where the synapse is located. This can be a section name, a segment number, or a more complex specification depending on the model.")
    position: float = Field(default=0.5, description="The position along the section where the synapse is located, specified as a value between 0 and 1. This is only relevant if the location is specified as a section name.")


class NetConnectionInputModel(BaseModel):
    """Net connection parameters. Quantities stored as nano-base ints."""

    kind: enums.ConnectionKind = Field(default=enums.ConnectionKind.SYNAPSE, description="The kind of connection to create.")
    id: str = Field(description="The unique identifier of the connection within the model.")
    weight: pq.ElectricalConductance | None = Field(default=None, description="The weight (conductance) of the connection.")
    threshold: pq.ElectricPotential | None = Field(default=None, description="The threshold for the connection.")
    delay: pq.Duration | None = Field(default=None, description="The delay for the connection.")
    net_stimulator: Optional[str] = Field(default=None, description="The ID of the net stimulator that is the pre-synaptic cell in this connection.")
    synapse: Optional[str] = Field(default=None, description="The ID of the synapse that is the post-synaptic cell in this connection.")


class NetStimulatorInputModel(BaseModel):
    """Net stimulation parameters. Quantities stored as nano-base ints."""

    id: str = Field(description="The unique identifier of the stimulator within the model.")
    start: pq.Duration = Field(default=100_000_000_000, description="Start time of the first spike.")  # 100 ms
    number: int = Field(default=1, description="Number of spikes to emit.")  # Number of spikes
    interval: pq.Duration | None = Field(default=None, description="Interval between spikes.")
    net_stimulator: str
    synapse: str


class ModelConfigInputModel(BaseModel):
    """Configuration for a model."""
    cells: List[CellInputModel] = Field(default_factory=list, description="The list of cells in the model.")
    net_stimulators: List[NetStimulatorInputModel] = Field(default_factory=list, description="The list of net stimulators in the model.")
    net_connections: List[NetConnectionInputModel] = Field(default_factory=list, description="The list of net connections in the model.")
    net_synapses: List[SynapseInputModel] = Field(default_factory=list, description="The list of net synapses in the model.")
    v_init: pq.ElectricPotential = Field(default=-67_000_000_000_000, description="Initial membrane potential.")   # -67 mV
    temperature: pq.Temperature = Field(default=309_150_000_000, description="Simulation bath temperature.")   # 36 °C
    label: Optional[str] = Field(default=None, description="An optional label for the model configuration.")

    @model_validator(mode="after")
    def check_cells(cls, self: "ModelConfigInputModel") -> "ModelConfigInputModel":
        if self.net_synapses:
            for synapse in self.net_synapses:
                cell: CellInputModel | None = next((cell for cell in self.cells if cell.id == synapse.cell), None)
                if cell is None:
                    raise ValueError(f"Cell {synapse.cell} not found in the model configuration.")

                location = next((loc for loc in cell.topology.sections if loc.id == synapse.location), None)
                if location is None:
                    raise ValueError(f"Location {synapse.location} not found in cell {cell.id}.")

        if self.net_stimulators:
            for connection in self.net_connections:
                synapse: NetConnectionInputModel | None = next((syn for syn in self.net_synapses if syn.id == connection.synapse), None)
                if synapse is None:
                    raise ValueError(f"Synapse {connection.synapse} not found in the model configuration.")

                net_stimulator: NetStimulatorInputModel | None = next((stim for stim in self.net_stimulators if stim.id == connection.net_stimulator), None)
                if net_stimulator is None:
                    raise ValueError(f"Net stimulator {connection.net_stimulator} not found in the model configuration.")

        return self
