"""The slice a lens makes along one axis. mikro keeps this in ``core/base_models.py``; here ``core.base_models`` is already a package."""

from pydantic import BaseModel, Field


class SliceModel(BaseModel):
    """One per-axis slice, with python's half-open ``start:stop:step`` semantics."""

    axis: str = Field(..., description="The name of the axis the slice acts on, e.g. 't' or 'c'")
    start: int | None = Field(default=None, description="The starting index of the slice, or None to start from the beginning")
    stop: int | None = Field(default=None, description="The stopping index of the slice, or None to go to the end")
    step: int | None = Field(default=None, description="The step size of the slice, or None to use the default step")


class SliceInputModel(BaseModel):
    """The input twin of :class:`SliceModel`."""

    axis: str
    start: int | None = None
    stop: int | None = None
    step: int | None = None
