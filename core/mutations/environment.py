from kante.types import Info
from core.datalayer import get_current_datalayer
import strawberry
from core import types, models, scalars, enums
from core.base_models.input.graphql.biophysics import BiophysicsInput


@strawberry.input()
class RecordingInput:
    trace: scalars.TraceLike
    kind: enums.RecordingKind
    cell: strawberry.ID | None
    location: strawberry.ID | None
    position: float | None


@strawberry.input()
class StimulusInput:
    trace: scalars.TraceLike
    kind: enums.StimulusKind
    cell: strawberry.ID | None
    location: strawberry.ID | None
    position: float | None


@strawberry.input()
class CreateEnvironmentInput:
    hash: str
    name: str


def create_simulation(
    info: Info,
    input: CreateSimulationInput,
) -> types.Simulation:
    model = models.NeuronModel.objects.get(
        id=input.model,
    )

    datalayer = get_current_datalayer()

    time_store = models.ZarrStore.objects.get(id=input.time_trace)
    time_store.fill_info(datalayer)

    time_trace = models.Trace.objects.create(
        creator=info.context.request.user,
        organization=info.context.request.organization,
        name=input.name,
        store=time_store,
    )

    sims = models.Simulation.objects.create(
        model=model,
        duration=input.duration,
        name=input.name,
        time_trace=time_trace,
        dt=input.dt or 1.0,
    )

    for recording in input.recordings:
        store = models.ZarrStore.objects.get(id=recording.trace)
        store.fill_info(datalayer)

        trace = models.Trace.objects.create(
            creator=info.context.request.user,
            organization=info.context.request.organization,
            name=input.name,
            store=store,
        )

        recording = models.Recording.objects.create(trace=trace, kind=recording.kind, cell=recording.cell, location=recording.location, position=recording.position, simulation=sims)

    for stimulus in input.stimuli:
        store = models.ZarrStore.objects.get(id=stimulus.trace)
        store.fill_info(datalayer)

        trace = models.Trace.objects.create(
            creator=info.context.request.user,
            organization=info.context.request.organization,
            name=input.name,
            store=store,
        )

        stim = models.Stimulus.objects.create(trace=trace, kind=stimulus.kind, cell=stimulus.cell, location=stimulus.location, position=stimulus.position, simulation=sims)

    return sims
