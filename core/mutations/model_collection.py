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
class CreateModelCollectionInput:
    name: str 
    models: list[strawberry.ID]
    description: str | None = None
    

def create_model_collection(
    info: Info,
    input: CreateModelCollectionInput,
) -> types.ModelCollection:

   
    
    exp = models.ModelCollection.objects.create(
        name=input.name,
        creator=info.context.request.user,
        description=input.description,
        
    )
    
    exp.models.set(
        models.NeuronModel.objects.filter(id__in=input.models)
    )
        
           
    return exp


