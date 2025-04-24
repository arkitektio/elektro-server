import strawberry_django
from core import models
from typing import List, Optional
from strawberry import ID
import strawberry

@strawberry_django.input(models.Trace)
class TraceInput:
    origins: Optional[List[ID]]
    dataset: Optional[ID]
    creator: ID


@strawberry_django.input(models.Dataset)
class DatasetInput:
    name: str
    description: str


@strawberry.input()
class AssociateInput:
    selfs: List[strawberry.ID]
    other: strawberry.ID

@strawberry.input()
class DesociateInput:
    selfs: List[strawberry.ID]
    other: strawberry.ID


@strawberry.input()
class CellInput:
    id: strawberry.ID
    


@strawberry.input()
class ModelInput:
    cells: List[strawberry.ID]