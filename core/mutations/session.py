"""Timing several datasets onto one clock at once: a session, recorded or simulated.

What was ``createSimulation``, minus the run. A run is its clock: which traces made up one run
is the graph -- the datasets timed onto one clock -- and what was run is the ``simulation``
spoke on each output, said at ``createArrayDataset``. What is left is not simulation-specific
at all: write one timing edge per dataset onto a clock -- a new one, or an existing one, for a
second batch -- checking first that the datasets *can* line up: every one has a TIME axis and the same number of samples along it, because one session
recorded them all on one sample index. A wet recording session is built the same way.

It is sugar over ``createCoordinateSystem`` and one ``createSamplingLaw`` (or FIELD
``createTransformation``) per dataset, and writes nothing those could not.
"""

import strawberry
from django.db import transaction
from kante.types import Info
from pydantic import BaseModel, Field, model_validator

import kante
from kanne_server import scalars as quantities

from core import types
from core import models
from core.creation import CreationContext
from core.logic import clocks
from core.scoping import get_for_org


class SamplingInputModel(BaseModel):
    rate: int
    t_start: int = 0


@kante.pydantic_input(SamplingInputModel, description="A fixed recording interval: one sample every 1/rate, starting at tStart")
class SamplingInput:
    """The sampling law of a session that recorded at a fixed interval."""

    rate: quantities.Frequency = strawberry.field(description="The rate samples were RECORDED at, e.g. '40 kHz'. For a simulation, not the integrator's `dt`: a run can record more coarsely than it integrates")
    t_start: quantities.Duration = strawberry.field(default=0, description="When sample 0 was recorded, on the session's clock. Defaults to 0")


class CreateSessionInputModel(BaseModel):
    name: str | None = None
    clock: str | None = None
    datasets: list[str] = Field(min_length=1)
    time_dataset: str | None = None
    sampling: SamplingInputModel | None = None
    time_unit: str = "second"

    @model_validator(mode="after")
    def _one_way_of_timing(self) -> "CreateSessionInputModel":
        if (self.name is None) == (self.clock is None):
            raise ValueError("Name the new clock (`name`), or give an existing one to time onto (`clock`). Exactly one of the two.")
        if (self.time_dataset is None) == (self.sampling is None):
            raise ValueError(
                "A session's samples are timed in exactly one way: pass `sampling` when it recorded at a fixed interval, or `timeDataset` when it did not (a variable time step). "
                "Both would be two statements of one fact, free to disagree; neither leaves the datasets with no time at all."
            )
        return self


@kante.pydantic_input(
    CreateSessionInputModel,
    description=(
        "Array datasets recorded together, timed onto one clock: one sampling law (or one time lookup) per dataset, onto a new clock or an existing one. A recording session, or one "
        "run of a neuron model -- a run is its clock, and the outputs timed onto one clock must agree on what was run (their `simulation` anchors)"
    ),
)
class CreateSessionInput:
    """Input for creating a session."""

    name: str | None = strawberry.field(default=None, description="Mint a new clock for the session, named '<name>/clock'. Exactly one of `name` and `clock`")
    clock: strawberry.ID | None = strawberry.field(default=None, description="Time onto this existing clock instead -- a second batch of a session or run. Exactly one of `name` and `clock`")
    datasets: list[strawberry.ID] = strawberry.field(description="The array datasets recorded in the session. Each needs a TIME axis, and all the same number of samples")
    time_dataset: strawberry.ID | None = strawberry.field(
        default=None,
        description=(
            "(variable time step) The instant each sample was recorded at: an existing one-dimensional array dataset, one value per sample, whose dataset-wide `valueUnit` is `timeUnit`. "
            "Written as a time lookup per dataset -- a FIELD edge whose map is the values of this array -- so it must live alone in its coordinate system. Exactly one of `timeDataset` and `sampling`"
        ),
    )
    sampling: SamplingInput | None = strawberry.field(default=None, description="(fixed interval) The sampling law, written as one edge per dataset onto the new clock. Exactly one of `timeDataset` and `sampling`")
    time_unit: quantities.Unit = strawberry.field(default="second", description="The unit a new clock counts in, and so the unit the values of `timeDataset` must be in. NEURON counts in 'millisecond'. Ignored with `clock`, which has its unit")


def create_session(info: Info, input: CreateSessionInput) -> types.CoordinateSystem:
    """Mint a clock (or take one), and the edge that times each named dataset on it."""
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)
    existing = get_for_org(models.CoordinateSystem, info, id=parsed.clock) if parsed.clock else None
    if existing is not None and clocks.time_axis(existing) is None:
        raise ValueError(f"'{existing.name}' has no TIME axis, so it is not a clock anything can be timed onto.")
    label = parsed.name or existing.name

    # Everything is resolved and checked before anything is written.
    resolved = []
    for identifier in dict.fromkeys(parsed.datasets):
        dataset = get_for_org(models.ArrayDataset, info, id=identifier)
        sample_axis = clocks.time_axis(clocks.grid_of(dataset))
        if sample_axis is None:
            raise ValueError(f"Dataset '{dataset.name}' has no TIME axis, so it has no samples for the session's clock to time. A recording or a stimulus is a function of the sample index, and that axis is typed TIME.")
        resolved.append((dataset, sample_axis.name))

    counts = {dataset.name: clocks.sample_count(dataset, axis) for dataset, axis in resolved}
    if len(set(counts.values())) > 1:
        raise ValueError(f"One session records every dataset on one sample index, so its datasets have the same number of samples, but these differ: {counts}.")

    times = get_for_org(models.ArrayDataset, info, id=parsed.time_dataset) if parsed.time_dataset else None
    if times is not None:
        first, first_axis = resolved[0]
        clocks.assert_times_match(label, first, first_axis, times)

    timed = clocks.TimedOnce()
    with transaction.atomic():
        clock = existing or clocks.create_clock(name=f"{parsed.name}/clock", unit=parsed.time_unit, ctx=ctx)
        for dataset, sample_axis in resolved:
            timed.claim(dataset, clock, label)
            if parsed.sampling is not None:
                clocks.write_sampling_law(grid=clocks.grid_of(dataset), clock=clock, sampling_rate=parsed.sampling.rate, t_start=parsed.sampling.t_start, name=f"{dataset.name}: sampling law", ctx=ctx)
            else:
                clocks.write_time_lookup(grid=clocks.grid_of(dataset), clock=clock, times=times, input_axis=sample_axis, name=f"{dataset.name}: sample times", ctx=ctx)

    return clock
