

from kante.types import Info
from core.datalayer import get_current_datalayer
import strawberry
from core import types, models, scalars, enums
from core.base_models.input.graphql.biophysics import BiophysicsInput
import datetime



@strawberry.input()
class AnalogSignalChannelInput:
    name: str
    index: int
    unit: str | None = None
    description: str | None = None
    color: list[int] | None = None
    trace: scalars.TraceLike




@strawberry.input()
class AnalogSignalInput:
    time_trace: scalars.TraceLike
    name: str | None = None
    description: str | None = None
    sampling_rate: float
    t_start: float
    unit: str | None = None
    channels: list[AnalogSignalChannelInput]


@strawberry.input()
class IrregularlySampledSignalInput:
    times: scalars.TraceLike
    trace: scalars.TraceLike
    name: str | None = None
    unit: str | None = None
    description: str | None = None

@strawberry.input()
class SpikeTrainInput:
    times: scalars.TraceLike
    t_start: float
    t_stop: float
    waveforms: scalars.TraceLike | None = None
    name: str | None = None
    description: str | None = None
    left_sweep: float | None = None



@strawberry.input()
class BlockSegmentInput:
    name: str | None = None
    description: str | None = None
    analog_signals: list[AnalogSignalInput] = strawberry.field(default_factory=list)
    irregularly_sampled_signals: list[IrregularlySampledSignalInput] = strawberry.field(default_factory=list)
    spike_trains: list[SpikeTrainInput] = strawberry.field(default_factory=list)
    


@strawberry.input()
class CreateBlockInput:
    file: strawberry.ID | None = None
    name: str
    recording_time: datetime.datetime | None = None
    segments: list[BlockSegmentInput] = strawberry.field(default_factory=list)


def create_block(
    info: Info,
    input: CreateBlockInput,
) -> types.Block:
    
    datalayer = get_current_datalayer()


    
    block = models.Block.objects.create(
        dataset=models.Dataset.objects.get_or_create(
            organization=info.context.request.organization,
            creator=info.context.request.user,
            membership=info.context.request.membership,
            name="Default Dataset",
            )[0],
        name=input.name,
        recording_time=input.recording_time or datetime.datetime.now(),
        origin=models.File.objects.get(id=input.file) if input.file else None,
        organization=info.context.request.organization,
        creator=info.context.request.user,
    )


    for segment in input.segments:
        segment_model = models.BlockSegment.objects.create(
            session=block,
        )

        for analog_signal in segment.analog_signals:
            
            
            ttrace = models.ZarrStore.objects.get(id=analog_signal.time_trace)
            ttrace.fill_info(datalayer)
            
            
            ttrace = models.Trace.objects.create(
                creator=info.context.request.user,
                organization=info.context.request.organization,
                name=input.name,
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
                    name=input.name,
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
                name=input.name,
                store=time_trace,
            )
            trace = models.ZarrStore.objects.get(id=irregularly_sampled_signal.trace)
            trace.fill_info(datalayer)
            
            trace = models.Trace.objects.create(
                creator=info.context.request.user,
                organization=info.context.request.organization,
                name=input.name,
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
                name=input.name,
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

@strawberry.input
class DeleteBlockInput:
    id: strawberry.ID

def delete_block(
    info: Info,
    input: DeleteBlockInput,
) -> strawberry.ID:
    datalayer = get_current_datalayer()
    try:
        block = models.Block.objects.get(id=input.id)
        if block.dataset.organization != info.context.request.organization:
            raise Exception("Block does not belong to your organization")
        block.delete()
        return input.id
    except models.Block.DoesNotExist:
        raise Exception("Block does not exist")