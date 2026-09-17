"""Creating and deleting a block: a recording session, in Neo's data model.

**The interpretation layer.** A block holds no data. Its signals *name* array datasets that
already exist (``createArrayDataset``), exactly as a layer of a mikro scene names a lens, and
``createBlock`` writes only what it means for those arrays to be a session: a clock, and an
edge putting each dataset's samples onto it (:mod:`core.logic.clocks`). A client says what
Neo says -- this signal was sampled at 30 kHz starting 2 s in; those are the instants that
one was sampled at -- and the quantities arrive as pint strings, are lowered once, and are
stored nowhere else; ``samplingRate``, ``tStart`` and ``timeDataset`` are read back off the
edges.

What a dataset *is* -- its axes, the unit of its values, what its channels are called -- was
said when it was created and is not repeated here: there is no ``axes``, ``unit`` or
``channels`` on a signal. What is checked here is that the dataset can bear the
interpretation: an analog signal needs a TIME axis for a sampling law to act on, a spike
train is one INDEX axis whose values are instants on this block's clock.

Everything is written in one transaction, in dependency order: the session clock, then per
segment its clock and the offset relating it to the session's, then per signal its row and
its timing edge. A refusal anywhere -- spike times in the wrong unit, a dataset named twice
against one clock -- leaves nothing behind. And because a block made no data, deleting it
deletes none: the datasets stay, and only the clocks left empty go.
"""

import datetime
from enum import Enum

import strawberry
from django.db import transaction
from django.utils import timezone
from kante.types import Info
from pydantic import BaseModel, Field

import kante
from kanne_server import scalars as quantities

from core import enums, models, types
from core.creation import CreationContext
from core.guards import enforce_delete
from core.logic import clocks
from core.logic import folder as folder_logic
from core.logic import spaces as spaces_logic
from core.scoping import get_for_org


class AnalogSignalInputModel(BaseModel):
    dataset: str
    name: str | None = None
    description: str | None = None
    sampling_rate: int
    t_start: int = 0
    validity: enums.PlacementValidity | None = None
    color: str | None = None


@kante.pydantic_input(AnalogSignalInputModel, description="A regularly sampled signal: the array dataset holding all its channels, and the sampling law that times it")
class AnalogSignalInput:
    """A regularly sampled signal of a segment."""

    dataset: strawberry.ID = strawberry.field(description="The samples: an existing array dataset holding ONE array for the whole signal, shaped (t) or (t, c). It must have a TIME axis -- that is the axis the sampling law acts on")
    name: str | None = strawberry.field(default=None, description="The name of the signal. Defaults to the dataset's")
    description: str | None = None
    sampling_rate: quantities.Frequency = strawberry.field(description="The sampling rate, e.g. '30 kHz'. Written as the sampling law -- one edge from the dataset's sample grid onto the segment's clock -- and stored nowhere else")
    t_start: quantities.Duration = strawberry.field(default=0, description="When sample 0 was taken, on the segment's clock, e.g. '2 s'. Part of the same edge. Defaults to 0")
    validity: enums.PlacementValidity | None = strawberry.field(
        default=None, description="How much the sampling law is actually known. Defaults to INFERRED: numbers read from acquisition metadata are as right as the metadata is"
    )
    color: str | None = strawberry.field(default=None, description="The color of the signal, as a HEX string")


class IrregularlySampledSignalInputModel(BaseModel):
    dataset: str
    times_dataset: str
    name: str | None = None
    description: str | None = None


@kante.pydantic_input(IrregularlySampledSignalInputModel, description="A signal sampled at arbitrary instants: a dataset of samples, and a dataset of the instants they were taken at")
class IrregularlySampledSignalInput:
    """An irregularly sampled signal of a segment."""

    dataset: strawberry.ID = strawberry.field(description="The samples: an existing array dataset. Its sample axis is TIME even though sampling is irregular")
    times_dataset: strawberry.ID = strawberry.field(
        description=(
            "The instants the samples were taken at: an existing one-dimensional array dataset with one value per sample, on the segment's clock. Written as a time lookup -- a FIELD edge whose map "
            "is the values of this array -- so it must live alone in its coordinate system, and its dataset-wide `valueUnit` must be the block's `timeUnit`: a lookup states no numbers, so it has nothing to convert with"
        )
    )
    name: str | None = strawberry.field(default=None, description="The name of the signal. Defaults to the dataset's")
    description: str | None = None


class SpikeTrainInputModel(BaseModel):
    dataset: str
    waveforms_dataset: str | None = None
    t_start: int
    t_stop: int
    name: str | None = None
    description: str | None = None


@kante.pydantic_input(SpikeTrainInputModel, description="The spike times of one unit, and the window it was observed over")
class SpikeTrainInput:
    """A spike train of a segment."""

    dataset: strawberry.ID = strawberry.field(
        description=(
            "The spike times: an existing array dataset with exactly one axis, typed INDEX (spike number has no metric), one value per spike, on the segment's clock. The array's values ARE the times, "
            "so the time lookup's field is this dataset itself, and its dataset-wide `valueUnit` must be the block's `timeUnit`"
        )
    )
    waveforms_dataset: strawberry.ID | None = strawberry.field(default=None, description="The spike waveforms: an existing array dataset, typically (spike: INDEX, c: CHANNEL, t: TIME)")
    t_start: quantities.Duration = strawberry.field(description="The start of the window the unit was observed over. Stated, not derived: spike times cannot say how long nothing happened")
    t_stop: quantities.Duration = strawberry.field(description="The end of the window the unit was observed over")
    name: str | None = strawberry.field(default=None, description="The name of the spike train. Defaults to the dataset's")
    description: str | None = None


@strawberry.enum(description="Which clock a segment's signals are timed against")
class SegmentTimebase(str, Enum):
    """Which clock a segment's signals are timed against."""

    SESSION = "SESSION"
    OWN = "OWN"


enums._describe(
    SegmentTimebase,
    SESSION="The signals' start times are already relative to the start of the session, so the segment shares the session's clock. No second clock is made",
    OWN="The signals' start times are relative to the start of the segment. The segment gets its own clock, related to the session's by `startTime` when that is known, and honestly unrelated when it is not",
)


class BlockSegmentInputModel(BaseModel):
    name: str | None = None
    description: str | None = None
    timebase: SegmentTimebase = SegmentTimebase.OWN
    start_time: int | None = None
    analog_signals: list[AnalogSignalInputModel] = Field(default_factory=list)
    irregularly_sampled_signals: list[IrregularlySampledSignalInputModel] = Field(default_factory=list)
    spike_trains: list[SpikeTrainInputModel] = Field(default_factory=list)


@kante.pydantic_input(BlockSegmentInputModel, description="One contiguous stretch of a session -- a trial, a sweep, a protocol step -- and the signals recorded in it")
class BlockSegmentInput:
    """A segment of a block."""

    name: str | None = None
    description: str | None = None
    timebase: SegmentTimebase = strawberry.field(default=SegmentTimebase.OWN, description="Which clock this segment's signals are timed against")
    start_time: quantities.Duration | None = strawberry.field(
        default=None, description="(OWN) Where this segment starts on the session clock. Written as one offset edge between the two clocks. Omit it and the segment's clock is unrelated to the session's"
    )
    analog_signals: list[AnalogSignalInput] = strawberry.field(default_factory=list)
    irregularly_sampled_signals: list[IrregularlySampledSignalInput] = strawberry.field(default_factory=list)
    spike_trains: list[SpikeTrainInput] = strawberry.field(default_factory=list)


class CreateBlockInputModel(BaseModel):
    name: str
    description: str | None = None
    folder: str | None = None
    file: str | None = None
    recording_time: datetime.datetime | None = None
    time_unit: str = "second"
    segments: list[BlockSegmentInputModel] = Field(default_factory=list)


@kante.pydantic_input(CreateBlockInputModel, description="A recording session: its clock, its segments, and the signals in them. It names array datasets that already exist and says how they are timed; it creates no data")
class CreateBlockInput:
    """Input for creating a block."""

    name: str
    description: str | None = None
    folder: strawberry.ID | None = strawberry.field(default=None, description="The folder to file the block in. Organisational only. Defaults to the user's default folder")
    file: strawberry.ID | None = strawberry.field(default=None, description="The file this block was read from, if any")
    recording_time: datetime.datetime | None = strawberry.field(default=None, description="When the recording started. Stored as the `epoch` of the session clock. Omit it and the clock is unanchored: time in the session is still well defined, just not tied to a wall clock")
    time_unit: quantities.Unit = strawberry.field(default="second", description="The unit the session's clocks count in, and so the unit spike times and sample times must be in. Defaults to 'second'")
    segments: list[BlockSegmentInput] = strawberry.field(default_factory=list)


def create_block(
    info: Info,
    input: CreateBlockInput,
) -> types.Block:
    """Create a block, its clocks, its signal rows, and every edge that times a dataset on them."""
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)

    recording_time = parsed.recording_time
    if recording_time is not None and timezone.is_naive(recording_time):
        recording_time = timezone.make_aware(recording_time)

    folder = folder_logic.resolve_folder(info, ctx, parsed.folder)
    origin = get_for_org(models.File, info, id=parsed.file) if parsed.file else None
    timed = clocks.TimedOnce()

    with transaction.atomic():
        session_clock = clocks.create_clock(name=f"{parsed.name}/clock", unit=parsed.time_unit, epoch=recording_time, ctx=ctx)
        block = models.Block.objects.create(
            folder=folder,
            name=parsed.name,
            description=parsed.description,
            origin=origin,
            organization=ctx.organization,
            creator=ctx.user,
            clock=session_clock,
        )

        for index, segment in enumerate(parsed.segments):
            label = segment.name or f"segment {index}"

            if segment.timebase == SegmentTimebase.SESSION:
                if segment.start_time is not None:
                    raise ValueError(f"Segment '{label}' shares the session clock, so it has no start of its own to state: drop `startTime`, or give it `timebase: OWN`.")
                segment_clock = session_clock
            else:
                segment_clock = clocks.create_clock(name=f"{parsed.name}/{label}/clock", unit=parsed.time_unit, ctx=ctx)
                if segment.start_time is not None:
                    clocks.write_offset(
                        source=segment_clock, target=session_clock, offset=segment.start_time, name=f"{label} -> session", validity=enums.PlacementValidity.INFERRED, ctx=ctx
                    )

            segment_row = models.BlockSegment.objects.create(block=block, index=index, name=segment.name, description=segment.description, clock=segment_clock)

            for signal in segment.analog_signals:
                dataset = get_for_org(models.ArrayDataset, info, id=signal.dataset)
                name = signal.name or dataset.name
                timed.claim(dataset, segment_clock, name)
                models.AnalogSignal.objects.create(segment=segment_row, dataset=dataset, name=name, description=signal.description, color=signal.color or "#000000")
                clocks.write_sampling_law(
                    grid=clocks.grid_of(dataset), clock=segment_clock, sampling_rate=signal.sampling_rate, t_start=signal.t_start, validity=signal.validity, name=f"{name}: sampling law", ctx=ctx
                )

            for signal in segment.irregularly_sampled_signals:
                dataset = get_for_org(models.ArrayDataset, info, id=signal.dataset)
                times = get_for_org(models.ArrayDataset, info, id=signal.times_dataset)
                name = signal.name or dataset.name
                timed.claim(dataset, segment_clock, name)
                sample_axis = clocks.time_axis(clocks.grid_of(dataset))
                if sample_axis is None:
                    raise ValueError(f"'{name}' has no TIME axis, so there is no axis for its sample times to time. The sample axis of a signal is typed TIME even when sampling is irregular.")
                clocks.assert_times_match(name, dataset, sample_axis.name, times)
                models.IrregularlySampledSignal.objects.create(segment=segment_row, dataset=dataset, name=name, description=signal.description)
                clocks.write_time_lookup(grid=clocks.grid_of(dataset), clock=segment_clock, times=times, input_axis=sample_axis.name, name=f"{name}: sample times", ctx=ctx)

            for train in segment.spike_trains:
                spikes = get_for_org(models.ArrayDataset, info, id=train.dataset)
                waveforms = get_for_org(models.ArrayDataset, info, id=train.waveforms_dataset) if train.waveforms_dataset else None
                name = train.name or spikes.name
                if train.t_stop < train.t_start:
                    raise ValueError(f"'{name}' was observed from tStart to tStop, so tStop cannot come first.")
                timed.claim(spikes, segment_clock, name)
                spike_axis = _spike_axis(name, spikes)
                models.SpikeTrain.objects.create(segment=segment_row, dataset=spikes, waveforms=waveforms, t_start=train.t_start, t_stop=train.t_stop, name=name, description=train.description)
                clocks.write_time_lookup(grid=clocks.grid_of(spikes), clock=segment_clock, times=spikes, input_axis=spike_axis, name=f"{name}: spike times", ctx=ctx)

    return block


def _spike_axis(name: str, spikes: "models.ArrayDataset") -> str:
    """The one axis of a spike-times dataset. Its name is read, not assumed; its type is not negotiable."""
    clocks.grid_of(spikes)
    axes = spikes.axes
    if len(axes) != 1 or axes[0].type != enums.AxisTypeChoices.INDEX.value:
        described = ", ".join(f"{axis.name}: {axis.type}" for axis in axes) or "none"
        raise ValueError(
            f"'{name}' names dataset '{spikes.name}' as its spike times, whose axes are ({described}). Spike times are one value per spike along exactly one axis, typed INDEX: "
            "spike number has no metric -- the distance between spike 3 and spike 4 means nothing -- which is why a spike train reaches time through a lookup and not a sampling law."
        )
    return axes[0].name


class DeleteBlockInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteBlockInputModel, description="Input for deleting a block by ID")
class DeleteBlockInput:
    """Input for deleting a block by ID."""

    id: strawberry.ID = strawberry.field(description="The ID of the block to delete")


def delete_block(
    info: Info,
    input: DeleteBlockInput,
) -> strawberry.ID:
    """Delete a block: the interpretation, and nothing it interprets.

    The signals go with the block and the datasets they named stay -- ``createBlock`` made
    none of them, exactly as deleting a mikro scene deletes no image. What does go is what
    exists only because of the block: its clocks, once nothing is laid out on them, and with
    them every edge that timed a dataset against them. Order matters: a block's FK to its
    clock is RESTRICT, so the block goes first.
    """
    parsed = input.to_pydantic()
    block = get_for_org(models.Block, info, id=parsed.id)
    enforce_delete(info, block)

    with transaction.atomic():
        clock_ids = {block.clock_id, *block.segments.values_list("clock_id", flat=True)} - {None}
        block.delete()
        spaces_logic.sweep_empty_systems(clock_ids)

    return parsed.id
