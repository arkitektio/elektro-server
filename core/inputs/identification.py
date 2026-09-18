"""The one question an axis of positions has to answer: what *are* these positions?

An axis is a list of positions and nothing else. To mean anything it has to say what they
are. mikro knows four answers; here there are two (elektro has no mesh or network
collections) -- a dataset whose values are the ids, or a table whose rows the positions are. This module is that answer, shared by the two places
an axis is declared: a sparse matrix's axes, which have nothing *but* this to say, and a
table's INDEX coordinate columns.

**It lives on the axis, which is the whole point.** For a table it used to be split across two
sibling lists -- ``keyedBy`` and the columns' ``references`` -- of which only the second named
an axis at all; the first was matched to its axis by subtraction inside ``write_key_edges``,
which is correct and invisible. Carried on the axis the pairing is the input's own shape, so
"identified exactly once" stops being a check the mutation performs.

**It is a list, because fan-in is real.** One axis may be identified by two masks -- a nucleus
mask and a cell mask keying the same object id -- and ``write_key_edges`` has always written an
edge per entry and refused only *duplicate sources*. The singular form sparse shipped with was
under-modelling, not a guarantee.

One kind authors a FIELD edge and one does not, and that difference is real rather than an
implementation detail: a mask is a thing whose *contents* identify an object, which is a claim
about space and therefore an edge; a table is already in record-land, where the relation is a
foreign key. ``TABLE`` is valid on an **INDEX** axis only, in either place -- for a table it is
item 7's product-space case, where an axis's values are already ids and naming the table it
enumerates is what the enumeration is *of*. (elektro: a sparse dataset may also have one TIME
axis -- a spike raster's samples -- which is identified by nothing: a sampling law places it.)

Flat-discriminated in the wire shape, following ``core.input_unions`` exactly as
``DerivedFromInput`` does, because GraphQL has no input unions.
"""

from typing import Annotated, ClassVar, Literal

import strawberry
from pydantic import BaseModel, ConfigDict, Field

import kante

from core import enums
from core.input_unions import parse_union_member, prose_errors, union_memberships

_NAME_DESCRIPTION = (
    "What to call the edge this authors, in a graph a person has to read. Defaults to `<source> -> <dataset>`. Only meaningful for the kinds that author one"
)

_AXIS_NAME_DESCRIPTION = (
    "The axis' name, free-form and unique within this dataset -- `bin`, `gene`, `metabolite`, `neuron`. It is the name a colouring names a position along, and the name the "
    "server reports back in `indexableAxes`"
)


class IdentificationInputBase(BaseModel):
    """The fields every identification carries, whichever kind of thing it names."""

    model_config = ConfigDict(extra="forbid")

    kind: enums.IdentificationKind
    name: str | None = None
    validity: enums.PlacementValidity | None = None

    #: The member's own id field, so a reader needs no per-member branch. A ClassVar, so pydantic
    #: treats it as neither a field nor a private attribute.
    SOURCE_FIELD: ClassVar[str] = "source"

    #: Whether this kind authors a FIELD edge. The one behavioural difference between the members,
    #: stated once here rather than branched on at every call site.
    AUTHORS_EDGE: ClassVar[bool] = True

    #: Where a NO-edge identification is written: on the column's `references` FK ("table").
    #: None for the kinds that author an edge instead. Stated here for `AUTHORS_EDGE`'s
    #: reason -- `split_identifications` routes on it rather than growing a kind branch.
    REFERENCE_TARGET: ClassVar[str | None] = None

    @property
    def source_id(self) -> str:
        """The id of whichever source this member names."""
        return getattr(self, type(self).SOURCE_FIELD)


class DatasetIdentifiesInputModel(IdentificationInputBase):
    """Identified by a label mask, through its intrinsic pixel grid."""

    kind: Literal[enums.IdentificationKind.DATASET] = enums.IdentificationKind.DATASET
    dataset: str
    SOURCE_FIELD: ClassVar[str] = "dataset"


class TableIdentifiesInputModel(IdentificationInputBase):
    """Identified by a table whose rows this axis' positions are.

    Authors no edge. That is not an omission: an edge is a claim about how one space maps into
    another, and this claim is a foreign key -- *the values along this axis identify rows of that
    table*. It is also what lets a FIELD edge land on the same dataset at all, since an axis
    identified this way is one the edge is not expected to supply.
    """

    kind: Literal[enums.IdentificationKind.TABLE] = enums.IdentificationKind.TABLE
    table: str
    SOURCE_FIELD: ClassVar[str] = "table"
    AUTHORS_EDGE: ClassVar[bool] = False
    REFERENCE_TARGET: ClassVar[str | None] = "table"


#: Every identification kind, keyed by discriminator value.
IDENTIFICATION_MEMBERS: dict[str, type[BaseModel]] = {
    enums.IdentificationKind.DATASET.value: DatasetIdentifiesInputModel,
    enums.IdentificationKind.TABLE.value: TableIdentifiesInputModel,
}

#: The union the pydantic side carries, so the mutation never sees the flat wire shape.
IdentificationSpec = Annotated[
    DatasetIdentifiesInputModel | TableIdentifiesInputModel,
    Field(discriminator="kind"),
]

#: The wire fields carrying a source id, one per member.
_SOURCE_FIELDS = ("dataset", "table")


@prose_errors
@strawberry.input(
    description=(
        "What a column's values or an axis' positions **are**, as a discriminated union: `kind` selects which sort of thing is being named, and only that member's id field is "
        "read -- any other is rejected. Carried by a sparse dataset's axes and by a table's columns alike -- the one spelling of every 'values here identify things there' claim. "
        "`DATASET` authors a FIELD edge from the source into this data, which is also what makes it reachable from a layer over that source (INDEX axes only -- the edge "
        "produces an axis); `TABLE` authors no edge and states a foreign key instead, on an INDEX axis or a plain data column"
    ),
)
class IdentificationInput:
    """How one column or axis is identified, discriminated by `kind`.

    Deliberately not pydantic-backed: the wire type is flat because GraphQL has no input unions,
    and ``to_pydantic`` is where that flatness is corrected into the strict member.
    """

    kind: enums.IdentificationKind = strawberry.field(description="Which sort of thing identifies this column or axis. It fixes which id field below is read; any other is rejected")
    dataset: strawberry.ID | None = strawberry.field(
        default=None,
        description="(DATASET) The label dataset whose pixel values are the positions along this axis. Its own pixel grid is both the edge's input and its field, which is what a label mask is",
    )
    table: strawberry.ID | None = strawberry.field(
        default=None,
        description=(
            "(TABLE) The table whose rows this column's values are -- an INDEX axis' enumeration, or a plain data column's foreign key (an `instance_id` referencing a table of "
            "tracks: the edge of the join graph `colorBys` walks). Must be keyed by exactly one INDEX coordinate column, which is where a value is looked up -- the contract "
            "`Column.references` records. A matrix with 19 059 features costs one picker entry because of this, not 19 059"
        ),
    )
    name: str | None = strawberry.field(default=None, description=_NAME_DESCRIPTION)
    validity: enums.PlacementValidity | None = strawberry.field(default=None, description="How far the edge this authors may be trusted. Only meaningful for the kinds that author one")

    def to_pydantic(self) -> BaseModel:
        """Match the flat wire fields to the member model `kind` selects, strictly."""
        supplied = {name: getattr(self, name) for name in ("kind", "name", "validity", *_SOURCE_FIELDS)}
        data = {name: value for name, value in supplied.items() if value is not None}
        return parse_union_member(IDENTIFICATION_MEMBERS, data, noun="identification")


def _identification_member(model: type, key: "enums.IdentificationKind", description: str):  # noqa: ANN202 - a decorator factory
    """Publish one member input of the IdentificationInput union."""
    return kante.pydantic_input(
        model,
        directives=union_memberships("IdentificationInput", key=key.value),
        description=f"{description}. Published for codegen; the wire type is the flat IdentificationInput",
    )


@_identification_member(DatasetIdentifiesInputModel, enums.IdentificationKind.DATASET, "The fields a DATASET identification reads")
class DatasetIdentifiesInput:
    """The DATASET member of the identification union."""

    kind: enums.IdentificationKind = strawberry.field(description="The discriminator: which member of IdentificationInput this is")
    dataset: strawberry.ID = strawberry.field(description="The label dataset whose pixel values are the positions along this axis")
    name: str | None = strawberry.field(default=None, description=_NAME_DESCRIPTION)
    validity: enums.PlacementValidity | None = strawberry.field(default=None, description="How far the edge this authors may be trusted")


@_identification_member(TableIdentifiesInputModel, enums.IdentificationKind.TABLE, "The fields a TABLE identification reads")
class TableIdentifiesInput:
    """The TABLE member of the identification union."""

    kind: enums.IdentificationKind = strawberry.field(description="The discriminator: which member of IdentificationInput this is")
    table: strawberry.ID = strawberry.field(description="The table whose rows this axis' positions are, keyed by its single INDEX coordinate column")


#: The member inputs published to the SDL, for the schema's ``types=[...]``. Dropping one erases
#: it from the SDL silently, and the union then advertises a member nobody can construct.
identification_union_types: list[type] = [
    DatasetIdentifiesInput,
    TableIdentifiesInput,
]
