"""Creating and deleting a lens. Vendored from mikro's ``core/mutations/lens.py``; a lens selects over a dataset.

There is no ``updateLens``: a lens is immutable, because the edge placing it is derived from
its slices at creation and a second write would be a second chance for the two to disagree.
"""

import strawberry
from kante.types import Info
from pydantic import BaseModel, Field

import kante
from core import guards, models, types
from core.base_models import slices as slice_models
from core.creation import CreationContext
from core.logic import coordinate_system as coordinate_system_logic
from core.logic import spaces as spaces_logic
from core.scoping import get_for_org


@kante.pydantic_input(slice_models.SliceInputModel, description="A slice along one named axis, with python's half-open `start:stop:step` semantics. Indices are SAMPLE indices along that axis of the dataset, never physical units")
class SliceInput:
    """One per-axis slice of a lens."""

    axis: str = strawberry.field(description="The name of the axis to slice, e.g. 't' or 'c'. Must be an axis of the dataset")
    start: int | None = strawberry.field(default=None, description="The first index selected. Omit to start at the beginning")
    stop: int | None = strawberry.field(default=None, description="One past the last index selected. Omit to run to the end")
    step: int | None = strawberry.field(default=None, description="The stride. Omit for every sample; a lens with a stride also rescales, which its edge records")


class CreateLensInputModel(BaseModel):
    dataset: str
    slices: list[slice_models.SliceInputModel] | None = None


@kante.pydantic_input(CreateLensInputModel, description="Input for creating a lens: a selection over a dataset")
class CreateLensInput:
    """Input for creating a lens over a dataset."""

    dataset: strawberry.ID = strawberry.field(description="The ID of the dataset to select over. It must have a coordinate system, i.e. it was created with axes")
    slices: list[SliceInput] | None = strawberry.field(
        default=None,
        description="Optional slices selecting a window of the dataset, one per axis to restrict. Omit (or pass an empty list) for a lens that selects everything; a sliced lens gets its own coordinate system and the edge recording the shift",
    )


def create_lens(info: Info, input: CreateLensInput) -> types.Lens:
    """Create a lens, its coordinate system, and the edge placing it back in its dataset.

    The lens' shape and axes are not written: they follow from the dataset and the
    slices, and a second copy could only drift from the first.
    """
    model = input.to_pydantic()
    dataset = get_for_org(models.ArrayDataset, info, id=model.dataset)
    ctx = CreationContext.from_info(info)
    return coordinate_system_logic.create_lens(dataset, model.slices or [], ctx)


class DeleteLensInputModel(BaseModel):
    id: str = Field(description="The ID of the lens to delete")


@kante.pydantic_input(DeleteLensInputModel, description="Input for deleting a lens by ID")
class DeleteLensInput:
    """Input for deleting a lens by ID."""

    id: strawberry.ID = strawberry.field(description="The ID of the lens to delete")


def delete_lens(info: Info, input: DeleteLensInput) -> strawberry.ID:
    """Delete a lens, and the coordinate system it owned if it was sliced.

    The lens goes first: its FK to the system is PROTECT. A sliced lens' system is its own
    -- nothing else can live there -- so it goes with it, and the derived edge cascades from
    the system. An unsliced lens shares its dataset's sample grid, which is the dataset's and stays.
    """
    model = input.to_pydantic()
    lens = get_for_org(models.Lens, info, id=model.id)
    guards.enforce_delete(info, lens)

    system_id = lens.coordinate_system_id
    lens.delete()
    # Swept only if nothing lives there any more: an unsliced lens' system is its dataset's grid, which stays.
    spaces_logic.sweep_empty_systems([system_id])
    return strawberry.ID(model.id)
