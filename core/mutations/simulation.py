"""Creating a simulation: one run of a neuron model, and the clock it ran on.

**The interpretation layer**, and the thinnest part of it. A run holds no data and no rows per
dataset: what was recorded where, and what was injected where, are ``RecordingSite`` and
``StimulusSite`` spokes on the datasets' own anchors, said when the data was created. What
``createSimulation`` writes is what only a run can say -- the model, the integrator's ``dt`` and
``duration``, a clock -- and, for the datasets it is handed, **one timing edge per dataset**
onto that clock. That they line up is a fact about those edges; nothing shares a sample grid.

CS-first: with no ``datasets`` it only mints the run's clock, and the datasets are timed
against it later, one ``createSamplingLaw`` (or FIELD ``createTransformation``) at a time --
exactly as a recording session is built. Which datasets belong to a run is read back from the
graph (``Simulation.datasets``), never stored.

What is checked is that the named datasets *can* line up: every one has a TIME axis and the
same number of samples along it, because one run recorded them all on one sample index -- and
that every site they carry is part of the model that was run.
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
    datasets: list[str] = []
    time_dataset: str | None = None
    sampling: SamplingInputModel | None = None
    time_unit: str = "millisecond"
    duration: int
    dt: int | None = None

    @model_validator(mode="after")
    def _one_way_of_timing(self) -> "CreateSimulationInputModel":
        if not self.datasets:
            if self.time_dataset is not None or self.sampling is not None:
                raise ValueError("`sampling` and `timeDataset` say how the run's `datasets` are timed, but no datasets were named. Name them, or leave both out and time them later with `createSamplingLaw`.")
            return self
        if (self.time_dataset is None) == (self.sampling is None):
            raise ValueError(
                "A run's samples are timed in exactly one way: pass `sampling` when it recorded at a fixed interval, or `timeDataset` when it did not (a variable time step). "
                "Both would be two statements of one fact, free to disagree; neither leaves the datasets with no time at all."
            )
        return self


@kante.pydantic_input(
    CreateSimulationInputModel,
    description=(
        "One run of a neuron model: the model, the integrator's parameters, and a clock. Optionally, the array datasets it produced and how their samples are timed on that clock. "
        "What was recorded or injected where is not stated here: it is a `recordingSite` / `stimulusSite` on each dataset's anchors, said at `createArrayDataset`"
    ),
)
class CreateSimulationInput:
    """Input for creating a simulation."""

    name: str
    description: str | None = None
    model: strawberry.ID = strawberry.field(description="The neuron model that was run")
    datasets: list[strawberry.ID] = strawberry.field(
        default_factory=list,
        description="The array datasets the run produced -- recordings and stimuli alike -- to time on its clock now. Each needs a TIME axis, and all the same number of samples. Leave empty to only mint the clock",
    )
    time_dataset: strawberry.ID | None = strawberry.field(
        default=None,
        description=(
            "(variable time step) The instant each sample was recorded at: an existing one-dimensional array dataset, one value per sample, whose dataset-wide `valueUnit` is `timeUnit`. "
            "Written as a time lookup per dataset -- a FIELD edge whose map is the values of this array -- so it must live alone in its coordinate system. Exactly one of `timeDataset` and `sampling` when `datasets` is given"
        ),
    )
    sampling: SamplingInput | None = strawberry.field(default=None, description="(fixed interval) The sampling law of the run. Written as one edge per dataset, all onto the run's clock. Exactly one of `timeDataset` and `sampling` when `datasets` is given")
    time_unit: quantities.Unit = strawberry.field(default="millisecond", description="The unit the simulation's clock counts in, and so the unit the values of `timeDataset` must be in. Defaults to 'millisecond', NEURON's unit of time")
    duration: quantities.Duration = strawberry.field(description="How long the model was run for (NEURON's tstop)")
    dt: quantities.Duration | None = strawberry.field(default=None, description="The integration time step (NEURON's dt). An integrator parameter, not the sampling period")


def create_simulation(
    info: Info,
    input: CreateSimulationInput,
) -> types.Simulation:
    """Create a simulation, its clock, and the edge that times each named dataset on it."""
    parsed = input.to_pydantic()
    model = get_for_org(models.NeuronModel, info, id=parsed.model)
    ctx = CreationContext.from_info(info)

    # Everything is resolved and checked before anything is written.
    resolved = []
    for identifier in dict.fromkeys(parsed.datasets):
        dataset = get_for_org(models.ArrayDataset, info, id=identifier)
        sample_axis = clocks.time_axis(clocks.grid_of(dataset))
        if sample_axis is None:
            raise ValueError(f"Dataset '{dataset.name}' has no TIME axis, so it has no samples for the run's clock to time. A recording or a stimulus is a function of the run's sample index, and that axis is typed TIME.")
        foreign = sorted(
            {name for spoke in (models.RecordingSite, models.StimulusSite) for name in spoke.objects.filter(anchor__dataset=dataset).exclude(model=model).values_list("model__name", flat=True)}
        )
        if foreign:
            raise ValueError(f"Dataset '{dataset.name}' carries sites on model {foreign}, but this is a run of model '{model.name}'. A site is part of the model it names, and a run records and injects at sites of the model it ran.")
        resolved.append((dataset, sample_axis.name))

    counts = {dataset.name: clocks.sample_count(dataset, axis) for dataset, axis in resolved}
    if len(set(counts.values())) > 1:
        raise ValueError(f"One run records every site on one sample index, so its datasets have the same number of samples, but these differ: {counts}.")

    times = get_for_org(models.ArrayDataset, info, id=parsed.time_dataset) if parsed.time_dataset else None
    if times is not None:
        first, first_axis = resolved[0]
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

        for dataset, sample_axis in resolved:
            timed.claim(dataset, clock, parsed.name)
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

    The datasets it timed stay, times dataset and site spokes included: ``createSimulation``
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
