"""Putting samples on a clock, and a clock on another: the two timing edges, as mutations.

elektro's own, and deliberately thin. Both edges can be written with mikro's
``createTransformation`` -- a sampling law is a ``BY_DIMENSION`` over the sample axis with a 1x2
``affine``, an offset one with a ``translation`` -- and nothing here writes anything that call
could not. What these add is the arithmetic a client should not have to do: a rate and a start
arrive as kanne quantities ("30 kHz", "2 s"), and the edge wants float64 numbers in the *clock's*
unit, a period rather than a rate. :mod:`core.logic.clocks` is the one writer, shared with
``createSession``.

They are what replaced ``createBlock``. A recording session is built CS-first:

1. ``createCoordinateSystem`` -- the session clock, one TIME axis, ``epoch`` = when it started;
2. ``createArrayDataset`` / ``createSparseDataset`` / ``createTableDataset`` -- the data;
3. ``createSamplingLaw`` per signal and raster; a FIELD ``createTransformation`` for an
   irregularly sampled one; ``createClockOffset`` for a segment's clock onto the session's;
4. ``createExperimentFromCoordinateSystem`` over the session clock.
"""

import strawberry
from django.db import transaction
from kante.types import Info
from pydantic import BaseModel

import kante
from kanne_server import scalars as quantities

from core import enums, models, types
from core.creation import CreationContext
from core.logic import clocks
from core.scoping import get_for_org


class CreateSamplingLawInputModel(BaseModel):
    source: str
    clock: str
    sampling_rate: int
    t_start: int = 0
    validity: enums.PlacementValidity | None = None
    name: str | None = None


@kante.pydantic_input(
    CreateSamplingLawInputModel,
    description=(
        "State `t = sample / samplingRate + tStart` as one edge from a sample grid onto a clock: how a regularly sampled signal -- or a spike raster's sample axis -- is timed. "
        "One BY_DIMENSION edge over the grid's TIME axis, in the clock's unit; the same edge `createTransformation` would write, with the arithmetic done for you"
    ),
)
class CreateSamplingLawInput:
    """Input for a sampling law."""

    source: strawberry.ID = strawberry.field(description="The coordinate system whose samples are timed: an array dataset's sample grid, or a sparse dataset's (unit, t) space. It needs one TIME axis")
    clock: strawberry.ID = strawberry.field(description="The clock the samples are timed on: a coordinate system with one TIME axis carrying a time unit -- a session's, a segment's, a run's")
    sampling_rate: quantities.Frequency = strawberry.field(description="The rate the samples were taken at, e.g. '30 kHz'")
    t_start: quantities.Duration = strawberry.field(default=0, description="When sample 0 was taken, on the clock. Defaults to 0")
    validity: enums.PlacementValidity | None = strawberry.field(default=None, description="How far the law may be trusted. INFERRED by default: it was read from acquisition metadata")
    name: str | None = None


def create_sampling_law(info: Info, input: CreateSamplingLawInput) -> types.Transformation:
    """Time a grid's samples on a clock with one sampling-law edge."""
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)
    grid = get_for_org(models.CoordinateSystem, info, id=parsed.source)
    clock = get_for_org(models.CoordinateSystem, info, id=parsed.clock)
    _assert_clock(clock)
    with transaction.atomic():
        clocks.TimedOnce().claim_grid(grid, clock, grid.name)
        return clocks.write_sampling_law(
            grid=grid,
            clock=clock,
            sampling_rate=parsed.sampling_rate,
            t_start=parsed.t_start,
            name=parsed.name or f"{grid.name}: sampling law",
            validity=parsed.validity,
            ctx=ctx,
        )


class CreateClockOffsetInputModel(BaseModel):
    clock: str
    onto: str
    offset: int | None = None
    drift_ppm: float = 0.0
    validity: enums.PlacementValidity | None = None
    name: str | None = None


@kante.pydantic_input(
    CreateClockOffsetInputModel,
    description=(
        "State where one clock's zero sits on another, and how fast it ticks against it: a segment within its session, a session or a run within an experiment's "
        "world, a probe's clock against a DAQ's. One edge, shared by everything timed on `clock` -- which is why an offset is stated here once and never per layer. "
        "A bare offset when the two clocks count in one unit and do not drift, a one-axis affine otherwise"
    ),
)
class CreateClockOffsetInput:
    """Input for a clock offset."""

    clock: strawberry.ID = strawberry.field(description="The clock being placed")
    onto: strawberry.ID = strawberry.field(description="The clock (or world) it is placed on")
    offset: quantities.Duration | None = strawberry.field(
        default=None,
        description=(
            "How far into `onto` the zero of `clock` is, e.g. '50 ms'. Omit it when both clocks are anchored to a wall-clock `epoch`: the offset is then their epochs' "
            "difference -- the nominal sync -- and a later `updateTransformation` refines it"
        ),
    )
    drift_ppm: float = strawberry.field(
        default=0.0,
        description="How much faster `clock` ticks than `onto`, in parts per million (a crystal's drift, e.g. 12.5). Written as the factor of the one edge, never as a second edge",
    )
    validity: enums.PlacementValidity | None = strawberry.field(default=None, description="How far the offset may be trusted. MANUAL by default: someone decided it")
    name: str | None = None


def create_clock_offset(info: Info, input: CreateClockOffsetInput) -> types.Transformation:
    """Place one clock on another with one offset edge, refusing a rival."""
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)
    clock = get_for_org(models.CoordinateSystem, info, id=parsed.clock)
    onto = get_for_org(models.CoordinateSystem, info, id=parsed.onto)
    _assert_clock(clock)
    _assert_clock(onto)
    if clock.pk == onto.pk:
        raise ValueError(f"'{clock.name}' cannot be placed on itself: its zero is its zero.")
    offset = parsed.offset if parsed.offset is not None else clocks.nominal_offset(clock, onto)
    if offset is None:
        raise ValueError(
            f"State the `offset`: '{clock.name}' and '{onto.name}' are not both anchored to a wall-clock epoch, so nothing says where one's zero sits on the other."
        )
    existing = clocks.offset_of(clock, onto)
    if existing is not None or models.Transformation.objects.filter(input=clock, output=onto, parent__isnull=True).exists():
        raise ValueError(
            f"'{clock.name}' already sits on '{onto.name}'{f' ({existing} ps in)' if existing is not None else ''}. That edge is shared by everything timed on it; "
            "refine it with `updateTransformation` rather than stating a second one, which would be a rival the path search picks between."
        )
    with transaction.atomic():
        return clocks.write_offset(
            source=clock,
            target=onto,
            offset=offset,
            drift_ppm=parsed.drift_ppm,
            name=parsed.name or f"{clock.name} -> {onto.name}",
            validity=parsed.validity or enums.PlacementValidity.MANUAL,
            ctx=ctx,
        )


def _assert_clock(system: "models.CoordinateSystem") -> None:
    """A clock has a TIME axis in a time unit: a sample grid's unitless TIME axis is not one."""
    axis = clocks.time_axis(system)
    if axis is None or not axis.unit:
        raise ValueError(
            f"'{system.name}' is not a clock: a clock has one TIME axis carrying a time unit, so an instant on it means something. "
            "A sample grid's TIME axis has no unit -- time it on a clock instead. Create one with `createCoordinateSystem(axes: [{name: \"t\", type: TIME, unit: \"second\"}])`."
        )
