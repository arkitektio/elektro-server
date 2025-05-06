from kante.channel import build_channel
from pydantic import BaseModel


class TraceSignal(BaseModel):
    """A model representing a base signal."""
    create: int | None = None
    update: int | None = None
    delete: int | None = None
    
    
class RoiSignal(BaseModel):
    """A model representing a ROI signal."""
    create: int | None = None
    update: int | None = None
    delete: int | None = None
    
    
class FileSignal(BaseModel):
    """A model representing a file signal."""
    create: int | None = None
    update: int | None = None
    delete: int | None = None



trace_channel = build_channel(
    TraceSignal
)

roi_channel = build_channel(
    RoiSignal
)

file_channel = build_channel(
    FileSignal
)