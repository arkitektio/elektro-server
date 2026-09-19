from .biophysics import BiophysicsModel
from .topology import TopologyModel
from pydantic import Field, BaseModel, PrivateAttr
import uuid


class CellModel(BaseModel):
    """A cell model, which consists of a biophysics model and a topology. You can think of the biophysics model as the 'properties' of the cell, and the topology as the 'structure' of the cell."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="The unique identifier of the cell within the model.")
    biophysics: BiophysicsModel = Field(description="The biophysics model of the cell, which defines the properties of the cell such as its compartments, mechanisms, and parameters.")
    topology: TopologyModel = Field(description="The topology of the cell, which defines the structure of the cell such as its morphology and connectivity.")
    # Where this cell was read from, stamped by `core.logic.sites.config_of` when a stored
    # model's config is served. Private: never serialized, never in the schema, never written
    # back into `json_model` -- it is the resolver's context, not the cell's.
    _neuron_model_id: int | None = PrivateAttr(default=None)
    _sole_cell: bool = PrivateAttr(default=False)
        
    



