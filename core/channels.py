from kante.channel import build_channel
from pydantic import BaseModel


class ArrayDatasetSignal(BaseModel):
    """One change to an array dataset: exactly one of the three is set."""

    create: int | None = None
    update: int | None = None
    delete: int | None = None


class FileSignal(BaseModel):
    """A model representing a file signal."""

    create: int | None = None
    update: int | None = None
    delete: int | None = None


array_dataset_channel = build_channel(ArrayDatasetSignal)

file_channel = build_channel(FileSignal)
