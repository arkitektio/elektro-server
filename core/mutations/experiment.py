from kante.types import Info
from core.datalayer import get_current_datalayer
import strawberry
from core import types, models, scalars, enums
from core.base_models.input.graphql.biophysics import BiophysicsInput



@strawberry.input()
class StimulusViewInput:
    stimulus: strawberry.ID
    offset: float | None = None
    duration: float | None = None
    label: str | None = None
  
  
@strawberry.input()
class RecordingViewInput:
    recording: strawberry.ID 
    offset: float | None = None
    duration: float | None = None
    label: str | None = None
      
    

@strawberry.input()
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


   
    
    exp = models.Experiment.objects.create(
        name=input.name,
        creator=info.context.request.user,
        description=input.description,
        time_trace=models.Trace.objects.get(id=input.time_trace),
        
    )
    
    
    for view in input.stimulus_views:
        
        stimulus = models.Stimulus.objects.get(id=view.stimulus)
        
        models.ExperimentStimulusView.objects.create(
            experiment=exp,
            stimulus=stimulus,
            offset=view.offset,
            label=view.label,
            duration=view.duration,
        )
        
    for view in input.recording_views:
        
        recording = models.Recording.objects.get(id=view.recording)
        
        models.ExperimentRecordingView.objects.create(
            experiment=exp,
            recording=recording,
            offset=view.offset,
            label=view.label,
            duration=view.duration,
        )
           
    return exp


