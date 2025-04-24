from kante.types import Info
from core.datalayer import get_current_datalayer
import strawberry
from core import types, models, scalars, enums
from core.base_models.input.graphql.biophysics import BiophysicsInput



@strawberry.input()
class ViewInput:
    stimulus: strawberry.ID | None = None
    recording: strawberry.ID | None = None
    offset: float | None = None
    duration: float | None = None
    label: str | None = None
    
    

@strawberry.input()
class CreateExperimentInput:
    name: str 
    views: list[ViewInput]
    description: str | None = None
    

def create_experiment(
    info: Info,
    input: CreateExperimentInput,
) -> types.Experiment:

   
    
    exp = models.Experiment.objects.create(
        name=input.name,
        creator=info.context.request.user,
        description=input.description,
        
    )
    
    
    for view in input.views:
        
        recording = None
        stimulus = None
        
        if view.stimulus:
            stimulus = models.Stimulus.objects.get(id=view.stimulus)
        elif view.recording:
            recording = models.Recording.objects.get(id=view.recording)
        else:
            raise ValueError("Either stimulus or recording must be provided")
        
        if stimulus and recording:
            raise ValueError("Both stimulus and recording cannot be provided")
        
        models.ExperimentView.objects.create(
            experiment=exp,
            stimulus=stimulus,
            recording=recording,
            offset=view.offset,
            label=view.label,
            duration=view.duration,
        )
           
    return exp


