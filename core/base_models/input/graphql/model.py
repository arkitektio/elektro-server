from typing import List, Literal
from strawberry.experimental import pydantic
import strawberry
from .cell import CellInput
from .biophysics import IonInput, MechanismGlobalParamInput
from kanne import scalars as quantities
from ..model import ModelConfigInputModel, NetConnectionInputModel, NetStimulatorInputModel, SynapseInputModel
from core.enums import SynapseKind, ConnectionKind


@pydantic.input(NetStimulatorInputModel, description="Input for a net stimulator in the model. This specifies the parameters of stimulators that drive synaptic connections.")
class NetStimulatorInput:
    """Net stimulation parameters."""

    id: strawberry.ID = strawberry.field(description="The unique identifier of the stimulator within the model.")
    start: quantities.Duration = strawberry.field(default=100_000_000_000, description="Start time of the first spike.")
    number: int = strawberry.field(default=1, description="Number of spikes to emit.")
    interval: quantities.Duration | None = strawberry.field(default=None, description="Interval between spikes.")


@pydantic.input(SynapseInputModel, description="Input for an exponential synapse, a synaptic stimulus with an exponential rise and decay. This specifies the parameters of synapses in the model.")
class NetSynapseInput:
    """Synaptic stimulus parameters."""

    kind: SynapseKind = strawberry.field(description="The kind of synapse model to use.")
    id: strawberry.ID = strawberry.field(description="The unique identifier of the synapse within the model.")
    e: quantities.ElectricPotential = strawberry.field(description="Reversal potential.")
    tau2: quantities.Duration = strawberry.field(description="Decay time constant.")
    tau1: quantities.Duration = strawberry.field(description="Rise time constant.")
    cell: strawberry.ID = strawberry.field(description="The ID of the cell this synapse is located on.")
    location: strawberry.ID = strawberry.field(description="The location on the cell where the synapse is located. This can be a section name, a segment number, or a more complex specification depending on the model.")
    position: float = strawberry.field(default=0.5, description="The position along the section where the synapse is located, specified as a value between 0 and 1. This is only relevant if the location is specified as a section name.")


@pydantic.input(NetConnectionInputModel, description="Input for a synaptic connection between two cells in the model. Each connection has a pre-synaptic cell (the net stimulator) and a post-synaptic cell (the synapse).")
class NetConnectionInput:
    """Net connection parameters."""

    kind: ConnectionKind = strawberry.field(description="The kind of connection to create.")
    synapse: strawberry.ID = strawberry.field(description="The ID of the synapse that is the post-synaptic cell in this connection.")
    net_stimulator: strawberry.ID = strawberry.field(description="The ID of the net stimulator that is the pre-synaptic cell in this connection.")
    id: strawberry.ID = strawberry.field(description="The unique identifier of the connection within the model.")
    weight: quantities.ElectricalConductance | None = strawberry.field(default=None, description="The weight (conductance) of the connection.")
    threshold: quantities.ElectricPotential | None = strawberry.field(default=None, description="The threshold for the connection.")
    delay: quantities.Duration | None = strawberry.field(default=None, description="The delay for the connection.")


@pydantic.input(ModelConfigInputModel, description="Input for the configuration of a model.")
class ModelConfigInput:
    cells: List[CellInput] = strawberry.field(description="The list of cells in the model.")
    net_stimulators: List[NetStimulatorInput] | None = strawberry.field(default_factory=list, description="The list of net stimulators in the model.")
    net_connections: List[NetConnectionInput] | None = strawberry.field(default_factory=list, description="The list of net connections in the model.")
    net_synapses: List[NetSynapseInput] | None = strawberry.field(default_factory=list, description="The list of net synapses in the model.")
    ions: List[IonInput] | None = strawberry.field(default_factory=list, description="Model-wide default ion settings (reversal potentials / concentrations). A compartment's own ions override these by ion name.")
    mechanism_globals: List[MechanismGlobalParamInput] | None = strawberry.field(default_factory=list, description="GLOBAL mechanism parameters (NEURON GLOBAL variables, e.g. q10_hh), shared across every instance of the mechanism.")
    ra: quantities.Resistivity | None = strawberry.field(default=None, description="Model-wide default axial resistivity (NEURON Ra). A section's own ra overrides this; unset falls back to NEURON's built-in 35.4 Ω·cm.")
    cm: quantities.SpecificCapacitance | None = strawberry.field(default=None, description="Model-wide default specific membrane capacitance (NEURON cm). A section's own cm overrides this; unset falls back to NEURON's built-in 1 µF/cm².")
    v_init: quantities.ElectricPotential = strawberry.field(description="Initial membrane potential.")
    temperature: quantities.Temperature = strawberry.field(description="Simulation bath temperature.")
    label: str | None = strawberry.field(default=None, description="An optional label for the model configuration.")
