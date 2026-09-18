"""The axis input of a sparse dataset: a name, what its positions are, and -- here -- a type.

Split from :mod:`core.inputs.identification` when the identification union became shared with
the table path. What is left here is the part that is genuinely a sparse matrix's own.

**elektro: an axis may be TIME.** In mikro both axes of a sparse matrix enumerate, so the input
has no ``type`` and INDEX is supplied. A spike raster is a sparse matrix too -- units x samples,
one nonzero per spike -- and its sample axis has a metric: it is placed on a clock by a sampling
law, exactly as an analog signal's is. So ``type`` exists here, defaults to INDEX (a mikro
client that never sends it is unaffected), and admits exactly INDEX and TIME, with at most one
TIME axis. A TIME axis is identified by nothing -- its positions are samples, and the sampling
law is what says when they were -- so its ``identifiedBy`` must be empty.
"""

from pydantic import BaseModel, ConfigDict, Field

import strawberry

import kante

from core import enums
from core.inputs.identification import IdentificationInput, IdentificationSpec

_AXIS_NAME_DESCRIPTION = (
    "The axis' name, free-form and unique within this dataset -- `unit`, `t`, `bin`, `gene`, `neuron`. It is the name a colouring names a position along, and the name the "
    "server reports back in `indexableAxes`"
)


class SparseAxisInputModel(BaseModel):
    """One axis of a sparse dataset: its name, its type, and what it is."""

    model_config = ConfigDict(extra="forbid")

    name: str
    # elektro: see the module docstring. INDEX by default, so mikro's wire shape still parses.
    type: enums.AxisType = enums.AxisType.INDEX
    identified_by: list[IdentificationSpec] = Field(default_factory=list)
    long_name: str | None = None
    description: str | None = None


@kante.pydantic_input(
    SparseAxisInputModel,
    description=(
        "One axis of a sparse matrix, and what its positions **are**. An INDEX axis (the default) enumerates, and says what through `identifiedBy` -- a list because fan-in is "
        "real, and not empty: an INDEX axis nothing identifies is one no source could ever key. A TIME axis (at most one; elektro's own) is a spike raster's sample axis: it is "
        "identified by nothing, because a sampling law onto a clock is what says when its samples were (`createSamplingLaw`)"
    ),
)
class SparseAxisInput:
    """One axis of a sparse dataset."""

    name: str = strawberry.field(description=_AXIS_NAME_DESCRIPTION)
    type: enums.AxisType = strawberry.field(
        default=enums.AxisType.INDEX,
        description="INDEX (an enumeration: units, genes, bins) or TIME (a sample axis, placed by a sampling law). Nothing else: a sparse matrix has no spatial or channel axes",
    )
    identified_by: list[IdentificationInput] = strawberry.field(
        default_factory=list,
        description="What this INDEX axis' positions are: sources whose contents are the ids, or the table whose rows they are. At least one for an INDEX axis; none for a TIME axis. More than one is fan-in, which writes an edge per source",
    )
    long_name: str | None = strawberry.field(default=None, description="A human-readable name for the axis")
    description: str | None = strawberry.field(default=None, description="What this axis enumerates, for a reader of the schema")
