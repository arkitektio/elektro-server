import uuid
from typing import Annotated, Optional, List, Dict, Set
from strawberry.experimental import pydantic
import strawberry
from kante.types import Info
import re
from kanne_server import scalars as quantities
from ..topology import TopologyModel, CoordModel, ConnectionModel, SectionModel

@pydantic.type(CoordModel, description="Represents a 3D coordinate (in space) of a point along a section.")
class Coord:
    x: quantities.Length = strawberry.field(description="The x coordinate of the point.")
    y: quantities.Length = strawberry.field(description="The y coordinate of the point.")
    z: quantities.Length = strawberry.field(description="The z coordinate of the point.")
    diam: Optional[quantities.Length] = strawberry.field(default=None, description="The diameter of the section at this point (NEURON pt3d). Falls back to the section diameter when omitted.")

@pydantic.type(ConnectionModel, description="Represents a connection of a section to its (single) parent section, defining the morphology tree.")
class Connection:
    parent: str = strawberry.field(description="The ID of the parent section this section connects to.")
    parent_location: float = strawberry.field(default=1.0, description="The position along the parent section where this section attaches, between 0 and 1.")
    child_end: float = strawberry.field(default=0.0, description="Which end of this section attaches to the parent: 0 (default) or 1.")

@pydantic.type(SectionModel, description="Represents a section of a cell's morphology, the basic structural unit of the topology.")
class Section:
    id: str = strawberry.field(description="The unique identifier of the section within the cell.")
    category: Optional[str] = strawberry.field(default=None, description="The category of the section (e.g. 'soma', 'axon', 'dend'). Biophysics compartments are matched to sections by this category.")
    nseg: int = strawberry.field(default=1, description="The number of segments the section is discretized into (used when d_lambda is not set). NEURON convention prefers an odd count so the section has a true midpoint node.")
    d_lambda: Optional[float] = strawberry.field(default=None, description="If set, nseg is computed from NEURON's d_lambda rule (target fraction of the AC length constant at 100 Hz per segment; 0.1 is typical) and overrides the fixed nseg.")
    diam: quantities.Length = strawberry.field(default=1_000_000, description="The diameter of the section (stylized geometry). Overridden by per-point coord diameters when coords are supplied.")
    length: Optional[quantities.Length] = strawberry.field(default=None, description="Length of the section (stylized geometry). Required if coords is not provided; ignored when coords are supplied.")
    ra: Optional[quantities.Resistivity] = strawberry.field(default=None, description="Axial resistivity (NEURON Ra). Unset inherits the model-wide default, then NEURON's built-in 35.4 Ω·cm.")
    cm: Optional[quantities.SpecificCapacitance] = strawberry.field(default=None, description="Specific membrane capacitance (NEURON cm). Unset inherits the model-wide default, then NEURON's built-in 1 µF/cm².")
    coords: List[Coord] | None = strawberry.field(default=None, description="The 3D coordinates (NEURON pt3d) describing the section's geometry. Required if length is not provided; when supplied they take precedence over length/diam. At least two points are needed to define a cable.")
    parent: Optional[Connection] = strawberry.field(default=None, description="The connection to this section's parent section. None for the root section of the cell.")

    @strawberry.field(
        description=(
            "Where this section was recorded: the datasets with a recording site on it, grouped by the clock they are timed onto -- one session per run. "
            "Read from the model's recording sites, in the viewer's organization; untimed datasets come last, under a null clock. Empty when the section was not read from a stored model"
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
        recorded = sites.recorded_dataset_ids(model_id, cell=self._cell_id, location=self.id, sole_cell=self._sole_cell)
        return await sync_to_async(sessions_of)(info, models.ArrayDataset.objects.filter(pk__in=recorded))

    @strawberry.field(description="This section's id from outside its model, 'model:cell:section' (each part percent-encoded): what the `section` query takes. `id` is only unique within its cell. Null when the section was not read from a stored model")
    def compound_id(self) -> strawberry.ID | None:
        from core.logic import sites

        if self._neuron_model_id is None or self._cell_id is None:
            return None
        return strawberry.ID(sites.compound_id(self._neuron_model_id, self._cell_id, self.id))

    @strawberry.field(description="The neuron model this section is part of. Null when the section was not read from a stored model")
    async def model(self, info: Info) -> Annotated["NeuronModel", strawberry.lazy("core.types")] | None:
        from asgiref.sync import sync_to_async

        from core import models, scoping

        if self._neuron_model_id is None:
            return None
        return await sync_to_async(scoping.get_for_org)(models.NeuronModel, info, id=self._neuron_model_id)

    @strawberry.field(description="The cell this section belongs to. Null when the section was not read from a stored model")
    async def cell(self, info: Info) -> Annotated["Cell", strawberry.lazy("core.base_models.type.graphql.cell")] | None:
        from asgiref.sync import sync_to_async

        from core import models, scoping
        from core.logic import sites

        if self._neuron_model_id is None or self._cell_id is None:
            return None

        def _cell():  # noqa: ANN202 - a stamped CellModel
            return sites.cell_of(scoping.get_for_org(models.NeuronModel, info, id=self._neuron_model_id), self._cell_id)

        return await sync_to_async(_cell)()


@pydantic.type(TopologyModel, description="Represents the topology of a cell, which defines its structure as a set of connected sections.")
class Topology:
    sections: List[Section] = strawberry.field(description="The list of sections that make up the cell's morphology.")