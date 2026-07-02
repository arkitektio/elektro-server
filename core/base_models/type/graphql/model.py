from typing import List, Literal
from .biophysics import Biophysics, Ion, MechanismGlobalParam
from .topology import Topology
from strawberry.experimental import pydantic
import strawberry
from .cell import Cell
from kanne import scalars as quantities
from ..model import Exp2SynModel, SynapticConnectionModel, SynapseBaseModel, NetConnectionModel, NetStimulatorModel, ModelConfigModel


@pydantic.interface(SynapseBaseModel, description="Base class for synaptic stimulus parameters.")
class NetSynapse:
    """Synaptic stimulus parameters."""
    id: strawberry.ID  = strawberry.field(description="The unique identifier of the synapse within the model.")
    cell: str = strawberry.field(description="The ID of the cell this synapse is located on.")
    location: str = strawberry.field(description="The location on the cell where the synapse is located. This can be a section name, a segment number, or a more complex specification depending on the model.")
    position: float   = strawberry.field(default= 0.5, description="The position along the section where the synapse is located, specified as a value between 0 and 1. This is only relevant if the location is specified as a section name.")

@pydantic.type(Exp2SynModel, description="Represents an exponential synapse model, which is a type of synaptic stimulus that has an exponential rise and decay. This will be used to specify the parameters of synapses in the model.")
class Exp2Synapse(NetSynapse):
    """Synaptic stimulus parameters."""
    e: quantities.ElectricPotential = strawberry.field(description="Reversal potential")
    tau2: quantities.Duration = strawberry.field(description="Decay time constant")
    tau1: quantities.Duration = strawberry.field(description="Rise time constant")
    delay: quantities.Duration | None  = strawberry.field(default=None, description="Delay before the synapse starts to activate")

@pydantic.interface(NetConnectionModel, description="Base class for net connection parameters.")
class NetConnection:
    """Base class for net connection parameters."""
    id: strawberry.ID  = strawberry.field(description="The unique identifier of the connection within the model.")
    weight: quantities.ElectricalConductance | None = strawberry.field(default=None, description="The weight (conductance) of the connection.")
    threshold: quantities.ElectricPotential | None = strawberry.field(default=None, description="The threshold for the connection.")
    delay: quantities.Duration | None = strawberry.field(default=None, description="The delay for the connection.")

@pydantic.type(SynapticConnectionModel, description="Represents a synaptic connection between two cells in the model. This will be used to specify the connections between cells in the model, where each connection has a pre-synaptic cell (the net stimulator) and a post-synaptic cell (the synapse).")
class SynapticConnection(NetConnection):
    net_stimulator: strawberry.ID = strawberry.field(description="The ID of the net stimulator that is the pre-synaptic cell in this connection.")
    synapse: strawberry.ID = strawberry.field(description="The ID of the synapse that is the post-synaptic cell in this connection.")

@pydantic.type(NetStimulatorModel, description="Represents a net stimulator in the model. This will be used to specify the parameters of stimulators in the model.")
class NetStimulator:
    """Base class for net stimulation parameters."""
    id: strawberry.ID = strawberry.field(description="The unique identifier of the stimulator within the model.")
    start: quantities.Duration = strawberry.field(default=100_000_000_000, description="Start time")
    number: int = strawberry.field(default=1, description="Number of spikes")
    interval: quantities.Duration | None = strawberry.field(default=None, description="Interval between spikes")



@pydantic.type(ModelConfigModel, description="Represents the configuration for the model.")
class ModelConfig:
    cells: List[Cell] = strawberry.field(default_factory=list, description="The list of cells in the model.")
    net_stimulators: List[NetStimulator]  | None = strawberry.field(default=None, description="The list of net stimulators in the model.")
    net_connections: List[NetConnection] | None = strawberry.field(default=None, description="The list of net connections in the model.")
    net_synapses: List[NetSynapse] | None = strawberry.field(default=None, description="The list of net synapses in the model.")
    ions: List[Ion] = strawberry.field(default_factory=list, description="Model-wide default ion settings (reversal potentials / concentrations). A compartment's own ions override these by ion name.")
    mechanism_globals: List[MechanismGlobalParam] = strawberry.field(default_factory=list, description="GLOBAL mechanism parameters (NEURON GLOBAL variables, e.g. q10_hh), shared across every instance of the mechanism.")
    ra: quantities.Resistivity | None = strawberry.field(default=None, description="Model-wide default axial resistivity (NEURON Ra). A section's own ra overrides this; unset falls back to NEURON's built-in 35.4 Ω·cm.")
    cm: quantities.SpecificCapacitance | None = strawberry.field(default=None, description="Model-wide default specific membrane capacitance (NEURON cm). A section's own cm overrides this; unset falls back to NEURON's built-in 1 µF/cm².")
    v_init: quantities.ElectricPotential = strawberry.field(description="Initial membrane potential")
    temperature: quantities.Temperature = strawberry.field(description="Simulation bath temperature")
    label: str | None = strawberry.field(description="An optional label for the model configuration.")
    
    
    
    




