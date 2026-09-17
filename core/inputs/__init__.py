from typing import List
import strawberry
import kante
from pydantic import BaseModel


class AssociateInputModel(BaseModel):
    selfs: List[str]
    other: str


@kante.pydantic_input(AssociateInputModel)
class AssociateInput:
    selfs: List[strawberry.ID]
    other: strawberry.ID


class DesociateInputModel(BaseModel):
    selfs: List[str]
    other: str


@kante.pydantic_input(DesociateInputModel)
class DesociateInput:
    selfs: List[strawberry.ID]
    other: strawberry.ID
