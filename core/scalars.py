from typing import NewType

import strawberry

TraceLike = strawberry.scalar(
    NewType("TraceLike", str),
    description="The `ArrayLike` scalar type represents a reference to a store "
    "previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

RGBAColor = strawberry.scalar(
    NewType("RGBAColor", list),
    description="The Color scalar type represents a color as a list of 4 values RGBA",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

UntypedPlateChild = strawberry.scalar(
    NewType("UntypedPlateChild", object),
    description="The `UntypedPlateChild` scalar type represents a plate child",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


FileLike = strawberry.scalar(
    NewType("FileLike", str),
    description="The `FileLike` scalar type represents a reference to a big file"
    " storage previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


StructureString = strawberry.scalar(
    NewType("StructureString", str),
    description="The `StructureString` scalar type represents a reference to a strucutre outside of this service"
    " previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

ParquetLike = strawberry.scalar(
    NewType("ParquetLike", str),
    description="The `ParquetLike` scalar type represents a reference to a parquet"
    " objected stored previously created by the user on a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


Matrix = strawberry.scalar(
    NewType("Matrix", object),
    description="The `Matrix` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

MikroStore = strawberry.scalar(
    NewType("MikroStore", str),
    description="The `MikroStore` scalar type represents a matrix values "
    "as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

Milliseconds = strawberry.scalar(
    NewType("Milliseconds", float),
    description="The `Matrix` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

Micrometers = strawberry.scalar(
    NewType("Micrometers", float),
    description="The `Micrometers` scalar type represents a matrix values"
    "as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

Microliters = strawberry.scalar(
    NewType("Microliters", float),
    description="The `Microliters` scalar type represnts a volume of liquid"
    "as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

Micrograms = strawberry.scalar(
    NewType("Micrograms", float),
    description="The `Micrograms` scalar type represents a mass of a substance",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)



FourByFourMatrix = strawberry.scalar(
    NewType("FourByFourMatrix", object),
    description="The `FourByFourMatrix` scalar type represents a matrix"
    " values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

FiveDVector = strawberry.scalar(
    NewType("FiveDVector", list),
    description="The `Vector` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


FourDVector = strawberry.scalar(
    NewType("FourDVector", list),
    description="The `Vector` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

ThreeDVector = strawberry.scalar(
    NewType("ThreeDVector", list),
    description="The `Vector` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

TwoDVector = strawberry.scalar(
    NewType("TwoDVector", list),
    description="The `Vector` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


UntypedRender = strawberry.scalar(
    NewType("UntypedRender", object),
    description="The `UntypedRender` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


Metric = strawberry.scalar(
    NewType("Metric", object),
    description="The `Metric` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

MetricMap = strawberry.scalar(
    NewType("MetricMap", object),
    description="The `MetricMap` scalar type represents a matrix values as specified by",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


Any = strawberry.scalar(
    NewType("Any", object),
    description="The `Any` scalar any type",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

