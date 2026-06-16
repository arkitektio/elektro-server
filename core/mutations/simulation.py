from kante.types import Info
from datalayer.datalayer import get_current_datalayer
import strawberry
import kante
from typing import Any
from pydantic import BaseModel
from core import types, models, scalars, enums
from core.base_models.input.graphql.biophysics import BiophysicsInput
from datalayer.scalars import ArrayLike


class RecordingInputModel(BaseModel):
    trace: Any
    kind: enums.RecordingKind
    cell: str | None = None
    location: str | None = None
    position: float | None = None


@kante.pydantic_input(RecordingInputModel)
class RecordingInput:
    trace: ArrayLike
    kind: enums.RecordingKind
    cell: strawberry.ID | None = None
    location: strawberry.ID | None = None
    position: float | None = None


class StimulusInputModel(BaseModel):
    trace: Any
    kind: enums.StimulusKind
    cell: str | None = None
    location: str | None = None
    position: float | None = None


@kante.pydantic_input(StimulusInputModel)
class StimulusInput:
    trace: ArrayLike
    kind: enums.StimulusKind
    cell: strawberry.ID | None = None
    location: strawberry.ID | None = None
    position: float | None = None


class CreateSimulationInputModel(BaseModel):
    name: str
    model: str
    recordings: list[RecordingInputModel]
    stimuli: list[StimulusInputModel]
    time_trace: Any = None
    duration: float
    dt: float | None = None


@kante.pydantic_input(CreateSimulationInputModel)
class CreateSimulationInput:
    name: str
    model: strawberry.ID
    recordings: list[RecordingInput]
    stimuli: list[StimulusInput]
    time_trace: ArrayLike | None = None
    duration: scalars.Milliseconds
    dt: scalars.Milliseconds | None = None


def create_simulation(
    info: Info,
    input: CreateSimulationInput,
) -> types.Simulation:
    parsed = input.to_pydantic()
    model = models.NeuronModel.objects.get(
        id=parsed.model,
    )

    datalayer = get_current_datalayer()

    time_store = models.ZarrStore.objects.get(id=parsed.time_trace)
    time_store.fill_info(datalayer)

    time_trace = models.Trace.objects.create(
        creator=info.context.request.user,
        organization=info.context.request.organization,
        name=parsed.name,
        store=time_store,
    )

    sims = models.Simulation.objects.create(
        model=model,
        duration=parsed.duration,
        name=parsed.name,
        time_trace=time_trace,
        dt=parsed.dt or 1.0,
    )

    for recording in parsed.recordings:
        store = models.ZarrStore.objects.get(id=recording.trace)
        store.fill_info(datalayer)

        trace = models.Trace.objects.create(
            creator=info.context.request.user,
            organization=info.context.request.organization,
            name=parsed.name,
            store=store,
        )

        recording = models.Recording.objects.create(trace=trace, kind=recording.kind, cell=recording.cell, location=recording.location, position=recording.position, simulation=sims)

    for stimulus in parsed.stimuli:
        store = models.ZarrStore.objects.get(id=stimulus.trace)
        store.fill_info(datalayer)

        trace = models.Trace.objects.create(
            creator=info.context.request.user,
            organization=info.context.request.organization,
            name=parsed.name,
            store=store,
        )

        stim = models.Stimulus.objects.create(trace=trace, kind=stimulus.kind, cell=stimulus.cell, location=stimulus.location, position=stimulus.position, simulation=sims)

    return sims
