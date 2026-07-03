import warnings
from typing import Dict, Union
from .cell import CellInputModel
from .biophysics import IonInputModel, MechanismGlobalParamInputModel
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Literal, Union, Optional
from kanne_server import quantities as pq
import uuid
from core import enums


class SynapseInputModel(BaseModel):
    """Synaptic stimulus parameters. Quantities persist as {canonical, given, unit}."""

    id: str = Field(description="The unique identifier of the synapse within the model.")
    kind: enums.SynapseKind = Field(default=enums.SynapseKind.EXP2SYN, description="The kind of synapse model to use.")
    e: pq.ElectricPotential = Field(description="Reversal potential.")
    tau2: pq.Duration = Field(description="Decay time constant.")
    tau1: pq.Duration = Field(description="Rise time constant.")
    delay: pq.Duration = Field(default=100_000_000_000, description="Delay before the synapse activates.")  # 100 ms
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


class ModelConfigInputModel(BaseModel):
    """Configuration for a model."""

    cells: List[CellInputModel] = Field(default_factory=list, description="The list of cells in the model.")
    net_stimulators: List[NetStimulatorInputModel] = Field(default_factory=list, description="The list of net stimulators in the model.")
    net_connections: List[NetConnectionInputModel] = Field(default_factory=list, description="The list of net connections in the model.")
    net_synapses: List[SynapseInputModel] = Field(default_factory=list, description="The list of net synapses in the model.")
    ions: List[IonInputModel] = Field(default_factory=list, description="Model-wide default ion settings (reversal potentials / concentrations). A compartment's own ions override these by ion name.")
    mechanism_globals: List[MechanismGlobalParamInputModel] = Field(default_factory=list, description="GLOBAL mechanism parameters (NEURON GLOBAL variables, e.g. q10_hh), shared across every instance of the mechanism.")
    ra: Optional[pq.Resistivity] = Field(default=None, description="Model-wide default axial resistivity (NEURON Ra). A section's own ra overrides this; unset falls back to NEURON's built-in 35.4 Ω·cm.")
    cm: Optional[pq.SpecificCapacitance] = Field(default=None, description="Model-wide default specific membrane capacitance (NEURON cm). A section's own cm overrides this; unset falls back to NEURON's built-in 1 µF/cm².")
    v_init: pq.ElectricPotential = Field(default=-67_000_000_000_000, description="Initial membrane potential.")  # -67 mV
    temperature: pq.Temperature = Field(default=309_150_000_000, description="Simulation bath temperature.")  # 36 °C
    label: Optional[str] = Field(default=None, description="An optional label for the model configuration.")

    @model_validator(mode="after")
    def check_cells(self) -> "ModelConfigInputModel":
        self._check_unique_ions(self.ions, "the model-wide ion defaults")
        if self.ra is not None and self.ra <= 0:
            raise ValueError("The model-wide default ra must be > 0.")
        if self.cm is not None and self.cm <= 0:
            raise ValueError("The model-wide default cm must be > 0.")

        for cell in self.cells:
            self._check_topology(cell)
            self._check_biophysics(cell)

        if self.net_synapses:
            for synapse in self.net_synapses:
                cell: CellInputModel | None = next((cell for cell in self.cells if cell.id == synapse.cell), None)
                if cell is None:
                    raise ValueError(f"Cell {synapse.cell} not found in the model configuration.")

                location = next((loc for loc in cell.topology.sections if loc.id == synapse.location), None)
                if location is None:
                    raise ValueError(f"Location {synapse.location} not found in cell {cell.id}.")

        if self.net_connections:
            for connection in self.net_connections:
                synapse: SynapseInputModel | None = next((syn for syn in self.net_synapses if syn.id == connection.synapse), None)
                if synapse is None:
                    raise ValueError(f"Synapse {connection.synapse} not found in the model configuration.")

                net_stimulator: NetStimulatorInputModel | None = next((stim for stim in self.net_stimulators if stim.id == connection.net_stimulator), None)
                if net_stimulator is None:
                    raise ValueError(f"Net stimulator {connection.net_stimulator} not found in the model configuration.")

        return self

    @staticmethod
    def _check_topology(cell: CellInputModel) -> None:
        """Validate that a cell's sections form a single, acyclic parent tree."""
        sections = cell.topology.sections
        section_ids = {s.id for s in sections}
        if len(section_ids) != len(sections):
            raise ValueError(f"Cell {cell.id} has duplicate section ids.")

        roots = [s for s in sections if s.parent is None]
        if sections and len(roots) != 1:
            raise ValueError(f"Cell {cell.id} must have exactly one root section (found {len(roots)}).")

        for section in sections:
            if section.nseg < 1:
                raise ValueError(f"Section {section.id} in cell {cell.id} must have nseg >= 1.")
            if section.nseg % 2 == 0:
                warnings.warn(
                    f"Section {section.id} in cell {cell.id} has an even nseg ({section.nseg}); "
                    "NEURON convention prefers an odd nseg so the section has a true midpoint node.",
                    stacklevel=2,
                )
            if section.d_lambda is not None and section.d_lambda <= 0:
                raise ValueError(f"Section {section.id} in cell {cell.id} must have d_lambda > 0.")

            # Geometry: a section needs either stylized length or pt3d coords.
            coords = section.coords or []
            if section.length is None and not coords:
                raise ValueError(
                    f"Section {section.id} in cell {cell.id} needs geometry: set length or provide coords."
                )
            if section.length is not None and section.length <= 0:
                raise ValueError(f"Section {section.id} in cell {cell.id} must have length > 0.")
            if coords and len(coords) < 2:
                raise ValueError(
                    f"Section {section.id} in cell {cell.id} needs at least two coords to define a cable."
                )
            if section.diam <= 0:
                raise ValueError(f"Section {section.id} in cell {cell.id} must have diam > 0.")
            if section.ra is not None and section.ra <= 0:
                raise ValueError(f"Section {section.id} in cell {cell.id} must have ra > 0.")
            if section.cm is not None and section.cm <= 0:
                raise ValueError(f"Section {section.id} in cell {cell.id} must have cm > 0.")

            if section.parent is None:
                continue
            if section.parent.parent not in section_ids:
                raise ValueError(f"Section {section.id} in cell {cell.id} references unknown parent section {section.parent.parent}.")
            if not 0.0 <= section.parent.parent_location <= 1.0:
                raise ValueError(f"Section {section.id} in cell {cell.id} has parent_location outside [0, 1].")
            if section.parent.child_end not in (0.0, 1.0):
                raise ValueError(f"Section {section.id} in cell {cell.id} has child_end that is not 0 or 1.")

        # Cycle detection: walking parents from any section must reach a root.
        parent_of = {s.id: (s.parent.parent if s.parent else None) for s in sections}
        for start in section_ids:
            seen = set()
            node = start
            while node is not None:
                if node in seen:
                    raise ValueError(f"Cell {cell.id} has a cycle in its section tree at {node}.")
                seen.add(node)
                node = parent_of.get(node)

    @staticmethod
    def _check_biophysics(cell: CellInputModel) -> None:
        """Validate compartment-to-section (by category) and mechanism references."""
        if cell.biophysics is None:
            return
        for comp in cell.biophysics.compartments:
            for param in comp.section_params:
                if param.mechanism not in comp.mechanisms:
                    raise ValueError(f"Section parameter {param.param} in compartment {comp.id} references mechanism {param.mechanism}, which is not among the compartment's mechanisms.")
            ModelConfigInputModel._check_unique_ions(comp.ions, f"compartment {comp.id}")

    @staticmethod
    def _check_unique_ions(ions: List[IonInputModel], where: str) -> None:
        """Ensure ion settings are unambiguous — no ion species appears twice."""
        seen: set[str] = set()
        for ion in ions:
            if ion.ion in seen:
                raise ValueError(f"Ion {ion.ion!r} is set more than once in {where}.")
            seen.add(ion.ion)
