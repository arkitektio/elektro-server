from typing import Annotated, List

import strawberry
from kante.types import Info
from .biophysics import Biophysics
from .topology import Topology
from strawberry.experimental import pydantic

from ..cell import CellModel


@pydantic.type(CellModel, description="Represents a cell model, which consists of a biophysics model and a topology. You can think of the biophysics model as the 'properties' of the cell, and the topology as the 'structure' of the cell.")
class Cell:
    id: str  = strawberry.field(description="The unique identifier of the cell within the model.")
    biophysics: Biophysics = strawberry.field(description="The biophysics model of the cell, which defines the properties of the cell such as its compartments, mechanisms, and parameters.")
    topology: Topology = strawberry.field(description="The topology of the cell, which defines the structure of the cell such as its morphology and connectivity.")

    @strawberry.field(
        description=(
            "Where this cell was recorded: the datasets with a recording site on it, grouped by the clock they are timed onto -- one session per run. "
            "Read from the model's recording sites, in the viewer's organization; untimed datasets come last, under a null clock. Empty when the cell was not read from a stored model"
        )
    )
    async def sessions(self, info: Info) -> List[Annotated["NeuronModelSession", strawberry.lazy("core.types")]]:
        # A plain strawberry resolver, not a strawberry_django one: nothing runs it off the
        # event loop for us, and it reads the ORM.
        from asgiref.sync import sync_to_async

        from core import models
        from core.logic import sites
        from core.types import sessions_of

        model_id = self._neuron_model_id
        if model_id is None:
            return []
        recorded = sites.recorded_dataset_ids(model_id, cell=self.id, sole_cell=self._sole_cell)
        return await sync_to_async(sessions_of)(info, models.ArrayDataset.objects.filter(pk__in=recorded))

    @strawberry.field(description="This cell's id from outside its model, 'model:cell' (each part percent-encoded): what the `cell` query takes. `id` is only unique within the model. Null when the cell was not read from a stored model")
    def compound_id(self) -> strawberry.ID | None:
        from core.logic import sites

        return None if self._neuron_model_id is None else strawberry.ID(sites.compound_id(self._neuron_model_id, self.id))

    @strawberry.field(description="The neuron model this cell is part of. Null when the cell was not read from a stored model")
    async def model(self, info: Info) -> Annotated["NeuronModel", strawberry.lazy("core.types")] | None:
        from asgiref.sync import sync_to_async

        from core import models, scoping

        if self._neuron_model_id is None:
            return None
        return await sync_to_async(scoping.get_for_org)(models.NeuronModel, info, id=self._neuron_model_id)
        
    



