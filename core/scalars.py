"""Custom GraphQL scalars for the core app.

The NewTypes are used in annotations; the GraphQL definitions in
:data:`SCALAR_MAP` are merged into the schema's ``StrawberryConfig.scalar_map``
in ``elektro_server/schema.py``.
"""

from typing import NewType

import strawberry
from strawberry.types.scalar import ScalarDefinition

TraceLike = NewType("TraceLike", str)
RGBAColor = NewType("RGBAColor", list)
UntypedPlateChild = NewType("UntypedPlateChild", object)
FileLike = NewType("FileLike", str)
StructureString = NewType("StructureString", str)
ParquetLike = NewType("ParquetLike", str)
Matrix = NewType("Matrix", object)
MikroStore = NewType("MikroStore", str)
Milliseconds = NewType("Milliseconds", float)
Micrometers = NewType("Micrometers", float)
Microliters = NewType("Microliters", float)
Micrograms = NewType("Micrograms", float)
FourByFourMatrix = NewType("FourByFourMatrix", object)
FiveDVector = NewType("FiveDVector", list)
FourDVector = NewType("FourDVector", list)
ThreeDVector = NewType("ThreeDVector", list)
TwoDVector = NewType("TwoDVector", list)
UntypedRender = NewType("UntypedRender", object)
Metric = NewType("Metric", object)
MetricMap = NewType("MetricMap", object)
Any = NewType("Any", object)


def _identity(v: object) -> object:
    """Pass-through serialization: the scalar carries its JSON value unchanged."""
    return v


SCALAR_MAP: dict[object, ScalarDefinition] = {
    TraceLike: strawberry.scalar(
        name="TraceLike",
        description="The `ArrayLike` scalar type represents a reference to a store "
        "previously created by the user n a datalayer",
        serialize=_identity,
        parse_value=_identity,
    ),
    RGBAColor: strawberry.scalar(
        name="RGBAColor",
        description="The Color scalar type represents a color as a list of 4 values RGBA",
        serialize=_identity,
        parse_value=_identity,
    ),
    UntypedPlateChild: strawberry.scalar(
        name="UntypedPlateChild",
        description="The `UntypedPlateChild` scalar type represents a plate child",
        serialize=_identity,
        parse_value=_identity,
    ),
    FileLike: strawberry.scalar(
        name="FileLike",
        description="The `FileLike` scalar type represents a reference to a big file"
        " storage previously created by the user n a datalayer",
        serialize=_identity,
        parse_value=_identity,
    ),
    StructureString: strawberry.scalar(
        name="StructureString",
        description="The `StructureString` scalar type represents a reference to a strucutre outside of this service"
        " previously created by the user n a datalayer",
        serialize=_identity,
        parse_value=_identity,
    ),
    ParquetLike: strawberry.scalar(
        name="ParquetLike",
        description="The `ParquetLike` scalar type represents a reference to a parquet"
        " objected stored previously created by the user on a datalayer",
        serialize=_identity,
        parse_value=_identity,
    ),
    Matrix: strawberry.scalar(
        name="Matrix",
        description="The `Matrix` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    MikroStore: strawberry.scalar(
        name="MikroStore",
        description="The `MikroStore` scalar type represents a matrix values "
        "as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    Milliseconds: strawberry.scalar(
        name="Milliseconds",
        description="The `Matrix` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    Micrometers: strawberry.scalar(
        name="Micrometers",
        description="The `Micrometers` scalar type represents a matrix values"
        "as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    Microliters: strawberry.scalar(
        name="Microliters",
        description="The `Microliters` scalar type represnts a volume of liquid"
        "as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    Micrograms: strawberry.scalar(
        name="Micrograms",
        description="The `Micrograms` scalar type represents a mass of a substance",
        serialize=_identity,
        parse_value=_identity,
    ),
    FourByFourMatrix: strawberry.scalar(
        name="FourByFourMatrix",
        description="The `FourByFourMatrix` scalar type represents a matrix"
        " values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    FiveDVector: strawberry.scalar(
        name="FiveDVector",
        description="The `Vector` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    FourDVector: strawberry.scalar(
        name="FourDVector",
        description="The `Vector` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    ThreeDVector: strawberry.scalar(
        name="ThreeDVector",
        description="The `Vector` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    TwoDVector: strawberry.scalar(
        name="TwoDVector",
        description="The `Vector` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    UntypedRender: strawberry.scalar(
        name="UntypedRender",
        description="The `UntypedRender` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    Metric: strawberry.scalar(
        name="Metric",
        description="The `Metric` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    MetricMap: strawberry.scalar(
        name="MetricMap",
        description="The `MetricMap` scalar type represents a matrix values as specified by",
        serialize=_identity,
        parse_value=_identity,
    ),
    Any: strawberry.scalar(
        name="Any",
        description="The `Any` scalar any type",
        serialize=_identity,
        parse_value=_identity,
    ),
}
