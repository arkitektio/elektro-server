from kante.types import Info
from datalayer.datalayer import get_current_datalayer
import strawberry
import kante
from typing import Any
from pydantic import BaseModel, Field
from core import types, models, scalars, enums
from core.guards import enforce_delete
from kanne import scalars as quantities
from core.base_models.input.graphql.biophysics import BiophysicsInput
import datetime


class AnalogSignalChannelInputModel(BaseModel):
    name: str
    index: int
    unit: str | None = None
    description: str | None = None
    color: list[int] | None = None
    trace: Any


@kante.pydantic_input(AnalogSignalChannelInputModel)
class AnalogSignalChannelInput:
    name: str
    index: int
    unit: str | None = None
    description: str | None = None
    color: list[int] | None = None
    trace: scalars.TraceLike


class AnalogSignalInputModel(BaseModel):
    time_trace: Any
    name: str | None = None
    description: str | None = None
    sampling_rate: int
    t_start: int
    unit: str | None = None
    channels: list[AnalogSignalChannelInputModel]


@kante.pydantic_input(AnalogSignalInputModel)
class AnalogSignalInput:
    time_trace: scalars.TraceLike
    name: str | None = None
    description: str | None = None
    sampling_rate: quantities.Frequency
    t_start: quantities.Duration
    unit: str | None = None
    channels: list[AnalogSignalChannelInput]


class IrregularlySampledSignalInputModel(BaseModel):
    times: Any
    trace: Any
    name: str | None = None
    unit: str | None = None
    description: str | None = None


@kante.pydantic_input(IrregularlySampledSignalInputModel)
class IrregularlySampledSignalInput:
    times: scalars.TraceLike
    trace: scalars.TraceLike
    name: str | None = None
    unit: str | None = None
    description: str | None = None


class SpikeTrainInputModel(BaseModel):
    times: Any
    t_start: int
    t_stop: int
    waveforms: Any = None
    name: str | None = None
    description: str | None = None
    left_sweep: int | None = None


@kante.pydantic_input(SpikeTrainInputModel)
class SpikeTrainInput:
    times: scalars.TraceLike
    t_start: quantities.Duration
    t_stop: quantities.Duration
    waveforms: scalars.TraceLike | None = None
    name: str | None = None
    description: str | None = None
    left_sweep: quantities.Duration | None = None


class BlockSegmentInputModel(BaseModel):
    name: str | None = None
    description: str | None = None
    analog_signals: list[AnalogSignalInputModel] = Field(default_factory=list)
    irregularly_sampled_signals: list[IrregularlySampledSignalInputModel] = Field(default_factory=list)
    spike_trains: list[SpikeTrainInputModel] = Field(default_factory=list)


@kante.pydantic_input(BlockSegmentInputModel)
class BlockSegmentInput:
    name: str | None = None
    description: str | None = None
    analog_signals: list[AnalogSignalInput] = strawberry.field(default_factory=list)
    irregularly_sampled_signals: list[IrregularlySampledSignalInput] = strawberry.field(default_factory=list)
    spike_trains: list[SpikeTrainInput] = strawberry.field(default_factory=list)


class CreateBlockInputModel(BaseModel):
    file: str | None = None
    name: str
    recording_time: datetime.datetime | None = None
    segments: list[BlockSegmentInputModel] = Field(default_factory=list)


@kante.pydantic_input(CreateBlockInputModel)
class CreateBlockInput:
    file: strawberry.ID | None = None
    name: str
    recording_time: datetime.datetime | None = None
    segments: list[BlockSegmentInput] = strawberry.field(default_factory=list)


def create_block(
    info: Info,
    input: CreateBlockInput,
) -> types.Block:
    parsed = input.to_pydantic()
    datalayer = get_current_datalayer()

    block = models.Block.objects.create(
        dataset=models.Dataset.objects.get_or_create(
            organization=info.context.request.organization,
            creator=info.context.request.user,
            membership=info.context.request.membership,
            name="Default Dataset",
        )[0],
        name=parsed.name,
        recording_time=parsed.recording_time or datetime.datetime.now(),
        origin=models.File.objects.get(id=parsed.file) if parsed.file else None,
        organization=info.context.request.organization,
        creator=info.context.request.user,
    )

    for segment in parsed.segments:
        segment_model = models.BlockSegment.objects.create(
            session=block,
        )

        for analog_signal in segment.analog_signals:
            ttrace = models.ZarrStore.objects.get(id=analog_signal.time_trace)
            ttrace.fill_info(datalayer)

            ttrace = models.Trace.objects.create(
                creator=info.context.request.user,
                organization=info.context.request.organization,
                name=parsed.name,
                store=ttrace,
            )

            analog_signal_model = models.AnalogSignal.objects.create(
                recording_segment=segment_model,
                sampling_rate=analog_signal.sampling_rate,
                t_start=analog_signal.t_start,
                time_trace=ttrace,
                name=analog_signal.name,
                unit=analog_signal.unit,
                description=analog_signal.description,
            )

            for channel in analog_signal.channels:
                trace = models.ZarrStore.objects.get(id=channel.trace)
                trace.fill_info(datalayer)

                trace = models.Trace.objects.create(
                    creator=info.context.request.user,
                    organization=info.context.request.organization,
                    name=parsed.name,
                    store=trace,
                )

                models.AnalogSignalChannel.objects.create(
                    signal=analog_signal_model,
                    trace=trace,
                    name=channel.name,
                    unit=channel.unit,
                    index=channel.index,
                    description=channel.description,
                    color=channel.color,
                )

        for irregularly_sampled_signal in segment.irregularly_sampled_signals:
            time_trace = models.ZarrStore.objects.get(id=irregularly_sampled_signal.times)
            time_trace.fill_info(datalayer)

            time_trace = models.Trace.objects.create(
                creator=info.context.request.user,
                organization=info.context.request.organization,
                name=parsed.name,
                store=time_trace,
            )
            trace = models.ZarrStore.objects.get(id=irregularly_sampled_signal.trace)
            trace.fill_info(datalayer)

            trace = models.Trace.objects.create(
                creator=info.context.request.user,
                organization=info.context.request.organization,
                name=parsed.name,
                store=trace,
            )

            models.IrregularlySampledSignal.objects.create(
                recording_segment=segment_model,
                time_trace=time_trace,
                trace=trace,
                name=irregularly_sampled_signal.name,
                unit=irregularly_sampled_signal.unit,
                description=irregularly_sampled_signal.description,
            )

        for spike_train in segment.spike_trains:
            time_trace = models.ZarrStore.objects.get(id=spike_train.times)
            time_trace.fill_info(datalayer)

            time_trace = models.Trace.objects.create(
                creator=info.context.request.user,
                organization=info.context.request.organization,
                name=parsed.name,
                store=time_trace,
            )
            models.SpikeTrain.objects.create(
                recording_segment=segment_model,
                time_trace=time_trace,
                t_start=spike_train.t_start,
                t_stop=spike_train.t_stop,
                waveforms=models.Trace.objects.get(id=spike_train.waveforms) if spike_train.waveforms else None,
                name=spike_train.name,
                description=spike_train.description,
                left_sweep=spike_train.left_sweep,
            )

    return block


class DeleteBlockInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteBlockInputModel)
class DeleteBlockInput:
    id: strawberry.ID


def delete_block(
    info: Info,
    input: DeleteBlockInput,
) -> strawberry.ID:
    parsed = input.to_pydantic()
    try:
        block = models.Block.objects.get(id=parsed.id)
        enforce_delete(info, block)
        block.delete()
        return parsed.id
    except models.Block.DoesNotExist:
        raise Exception("Block does not exist")
