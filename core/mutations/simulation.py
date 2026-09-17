"""Creating a simulation: one run of a neuron model, its recordings and stimuli, and the clock it ran on.

**The interpretation layer**, like :mod:`core.mutations.block`. A run holds no data: its
recordings and stimuli *name* array datasets that already exist, and ``createSimulation``
writes what it means for them to be one run -- a clock, a site row per dataset, and **one
timing edge per dataset**, all onto that one clock. That they line up is a fact about those
edges; nothing shares a sample grid (every dataset owns its own, as in mikro).

What is checked is that they *can* line up: every dataset has a TIME axis and the same
number of samples along it, because one run recorded them all on one sample index.
"""

import strawberry
from django.db import transaction
from kante.types import Info
from pydantic import BaseModel, model_validator

import kante
from kanne_server import scalars as quantities

from core import enums, models, types
from core.creation import CreationContext
from core.guards import enforce_delete
from core.logic import clocks
from core.logic import spaces as spaces_logic
from core.scoping import get_for_org


class RecordingInputModel(BaseModel):
    dataset: str
    kind: enums.RecordingKind
    cell: str | None = None
    location: str | None = None
    position: float | None = None
    label: str | None = None


@kante.pydantic_input(RecordingInputModel, description="What was recorded from the model at one site")
class RecordingInput:
    """A recording of a simulation."""

    dataset: strawberry.ID = strawberry.field(description="The recorded samples: an existing array dataset with a TIME axis, one value per sample of the run. What its values measure is its own `valueUnit`")
    kind: enums.RecordingKind
    cell: strawberry.ID | None = strawberry.field(default=None, description="The id of the cell, as the model config names it")
    location: strawberry.ID | None = strawberry.field(default=None, description="The id of the section, as the model config names it")
    position: float | None = strawberry.field(default=None, description="The normalized position along the section, 0 to 1")
    label: str | None = None


class StimulusInputModel(BaseModel):
    dataset: str
    kind: enums.StimulusKind
    cell: str | None = None
    location: str | None = None
    position: float | None = None
    label: str | None = None


@kante.pydantic_input(StimulusInputModel, description="What was injected into the model at one site")
class StimulusInput:
    """A stimulus of a simulation."""

    dataset: strawberry.ID = strawberry.field(description="The injected samples: an existing array dataset with a TIME axis, one value per sample of the run. What its values measure is its own `valueUnit`")
    kind: enums.StimulusKind
    cell: strawberry.ID | None = strawberry.field(default=None, description="The id of the cell, as the model config names it")
    location: strawberry.ID | None = strawberry.field(default=None, description="The id of the section, as the model config names it")
    position: float | None = strawberry.field(default=None, description="The normalized position along the section, 0 to 1")
    label: str | None = None


class SamplingInputModel(BaseModel):
    rate: int
    t_start: int = 0


@kante.pydantic_input(SamplingInputModel, description="A fixed recording interval: the run recorded one sample every 1/rate, starting at tStart")
class SamplingInput:
    """The sampling law of a run that recorded at a fixed interval."""

    rate: quantities.Frequency = strawberry.field(description="The rate samples were RECORDED at, e.g. '40 kHz'. Not the integrator's `dt`: a run can record more coarsely than it integrates")
    t_start: quantities.Duration = strawberry.field(default=0, description="When sample 0 was recorded, on the simulation's clock. Defaults to 0")


class CreateSimulationInputModel(BaseModel):
    name: str
    description: str | None = None
    model: str
    recordings: list[RecordingInputModel]
    stimuli: list[StimulusInputModel]
    time_dataset: str | None = None
    sampling: SamplingInputModel | None = None
    time_unit: str = "millisecond"
    duration: int
    dt: int | None = None

    @model_validator(mode="after")
    def _one_way_of_timing(self) -> "CreateSimulationInputModel":
        if (self.time_dataset is None) == (self.sampling is None):
            raise ValueError(
                "A run's samples are timed in exactly one way: pass `sampling` when it recorded at a fixed interval, or `timeDataset` when it did not (a variable time step). "
                "Both would be two statements of one fact, free to disagree; neither leaves the recordings with no time at all."
            )
        return self


@kante.pydantic_input(CreateSimulationInputModel, description="One run of a neuron model: what was injected, what was recorded, and how its samples are timed. It names array datasets that already exist; it creates no data")
class CreateSimulationInput:
    """Input for creating a simulation."""

    name: str
    description: str | None = None
    model: strawberry.ID = strawberry.field(description="The neuron model that was run")
    recordings: list[RecordingInput]
    stimuli: list[StimulusInput]
    time_dataset: strawberry.ID | None = strawberry.field(
        default=None,
        description=(
            "(variable time step) The instant each sample was recorded at: an existing one-dimensional array dataset, one value per sample, whose dataset-wide `valueUnit` is `timeUnit`. "
            "Written as a time lookup per recording and stimulus -- a FIELD edge whose map is the values of this array -- so it must live alone in its coordinate system. Exactly one of `timeDataset` and `sampling`"
        ),
    )
    sampling: SamplingInput | None = strawberry.field(default=None, description="(fixed interval) The sampling law of the run. Written as one edge per recording and stimulus, all onto the run's clock. Exactly one of `timeDataset` and `sampling`")
    time_unit: quantities.Unit = strawberry.field(default="millisecond", description="The unit the simulation's clock counts in, and so the unit the values of `timeDataset` must be in. Defaults to 'millisecond', NEURON's unit of time")
    duration: quantities.Duration = strawberry.field(description="How long the model was run for (NEURON's tstop)")
    dt: quantities.Duration | None = strawberry.field(default=None, description="The integration time step (NEURON's dt). An integrator parameter, not the sampling period")


def create_simulation(
    info: Info,
    input: CreateSimulationInput,
) -> types.Simulation:
    """Create a simulation, its clock, a site row per dataset, and the edge that times each one."""
    parsed = input.to_pydantic()
    model = get_for_org(models.NeuronModel, info, id=parsed.model)
    ctx = CreationContext.from_info(info)

    sites = [(models.Recording, site) for site in parsed.recordings] + [(models.Stimulus, site) for site in parsed.stimuli]
    if not sites:
        raise ValueError("A simulation with no recordings and no stimuli has no samples, and so nothing to put on its clock.")

    # Everything is resolved and checked before anything is written.
    resolved = []
    for site_model, site in sites:
        dataset = get_for_org(models.ArrayDataset, info, id=site.dataset)
        sample_axis = clocks.time_axis(clocks.grid_of(dataset))
        if sample_axis is None:
            raise ValueError(f"Dataset '{dataset.name}' has no TIME axis, so it has no samples for the run's clock to time. A recording or a stimulus is a function of the run's sample index, and that axis is typed TIME.")
        resolved.append((site_model, site, dataset, sample_axis.name))

    counts = {dataset.name: clocks.sample_count(dataset, axis) for _, _, dataset, axis in resolved}
    if len(set(counts.values())) > 1:
        raise ValueError(f"One run records every site on one sample index, so its datasets have the same number of samples, but these differ: {counts}.")

    times = get_for_org(models.ArrayDataset, info, id=parsed.time_dataset) if parsed.time_dataset else None
    if times is not None:
        _, _, first, first_axis = resolved[0]
        clocks.assert_times_match(parsed.name, first, first_axis, times)

    timed = clocks.TimedOnce()
    with transaction.atomic():
        clock = clocks.create_clock(name=f"{parsed.name}/clock", unit=parsed.time_unit, ctx=ctx)
        simulation = models.Simulation.objects.create(
            model=model,
            name=parsed.name,
            description=parsed.description,
            duration=parsed.duration,
            dt=parsed.dt,
            clock=clock,
            creator=ctx.user,
        )

        for site_model, site, dataset, sample_axis in resolved:
            timed.claim(dataset, clock, parsed.name)
            site_model.objects.create(dataset=dataset, simulation=simulation, kind=site.kind, cell=site.cell, location=site.location, position=site.position, label=site.label)
            if parsed.sampling is not None:
                clocks.write_sampling_law(grid=clocks.grid_of(dataset), clock=clock, sampling_rate=parsed.sampling.rate, t_start=parsed.sampling.t_start, name=f"{dataset.name}: sampling law", ctx=ctx)
            else:
                clocks.write_time_lookup(grid=clocks.grid_of(dataset), clock=clock, times=times, input_axis=sample_axis, name=f"{dataset.name}: sample times", ctx=ctx)

    return simulation


class DeleteSimulationInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteSimulationInputModel, description="Input for deleting a simulation by ID")
class DeleteSimulationInput:
    """Input for deleting a simulation by ID."""

    id: strawberry.ID = strawberry.field(description="The ID of the simulation to delete")


def delete_simulation(info: Info, input: DeleteSimulationInput) -> strawberry.ID:
    """Delete a run: the interpretation, and nothing it interprets.

    The recordings and stimuli go with the run -- and with them every experiment view of
    them -- while the datasets they named stay, times dataset included: ``createSimulation``
    made none of them. What goes is the run's clock, once nothing is laid out on it, which
    takes every timing edge onto it and every offset edge out of it into an experiment's
    world along. The worlds themselves are never touched.
    """
    parsed = input.to_pydantic()
    simulation = get_for_org(models.Simulation, info, id=parsed.id)
    enforce_delete(info, simulation)

    with transaction.atomic():
        clock_id = simulation.clock_id
        simulation.delete()
        spaces_logic.sweep_empty_systems({clock_id})

    return parsed.id
