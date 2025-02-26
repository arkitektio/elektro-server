import strawberry_django
from core import models
from typing import List, Optional
from strawberry import ID
import strawberry

@strawberry_django.input(models.Image)
class ImageInput:
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
