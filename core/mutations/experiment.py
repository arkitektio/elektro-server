from kante.types import Info
import strawberry
import kante
from pydantic import BaseModel
from core import types, models, scalars, enums
from kanne import scalars as quantities
from core.base_models.input.graphql.biophysics import BiophysicsInput


class StimulusViewInputModel(BaseModel):
    stimulus: str
    offset: int | None = None
    duration: int | None = None
    label: str | None = None


@kante.pydantic_input(StimulusViewInputModel)
class StimulusViewInput:
    stimulus: strawberry.ID
    offset: quantities.Duration | None = None
    duration: quantities.Duration | None = None
    label: str | None = None


class RecordingViewInputModel(BaseModel):
    recording: str
    offset: int | None = None
    duration: int | None = None
    label: str | None = None


@kante.pydantic_input(RecordingViewInputModel)
class RecordingViewInput:
    recording: strawberry.ID
    offset: quantities.Duration | None = None
    duration: quantities.Duration | None = None
    label: str | None = None


class CreateExperimentInputModel(BaseModel):
    name: str
    time_trace: str | None = None
    stimulus_views: list[StimulusViewInputModel]
    recording_views: list[RecordingViewInputModel]
    description: str | None = None


@kante.pydantic_input(CreateExperimentInputModel)
class CreateExperimentInput:
    name: str
    time_trace: strawberry.ID | None = None
    stimulus_views: list[StimulusViewInput]
    recording_views: list[RecordingViewInput]
    description: str | None = None


def create_experiment(
    info: Info,
    input: CreateExperimentInput,
) -> types.Experiment:
    parsed = input.to_pydantic()
    exp = models.Experiment.objects.create(
        name=parsed.name,
        creator=info.context.request.user,
        description=parsed.description,
        time_trace=models.Trace.objects.get(id=parsed.time_trace),
    )

    for view in parsed.stimulus_views:
        stimulus = models.Stimulus.objects.get(id=view.stimulus)

        models.ExperimentStimulusView.objects.create(
            experiment=exp,
            stimulus=stimulus,
            organization=info.context.request.organization,
            offset=view.offset,
            label=view.label,
            duration=view.duration,
        )

    for view in parsed.recording_views:
        recording = models.Recording.objects.get(id=view.recording)

        models.ExperimentRecordingView.objects.create(
            experiment=exp,
            recording=recording,
            organization=info.context.request.organization,
            offset=view.offset,
            label=view.label,
            duration=view.duration,
        )

    return exp
