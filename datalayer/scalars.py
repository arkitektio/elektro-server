"""Custom GraphQL scalars for the datalayer app.

The NewTypes are used in annotations; the GraphQL definitions in
:data:`SCALAR_MAP` are merged into the schema's ``StrawberryConfig.scalar_map``
in ``elektro_server/schema.py``.
"""

from typing import NewType

import strawberry
from strawberry.types.scalar import ScalarDefinition

MediaLike = NewType("MediaLike", str)
ArrayLike = NewType("ArrayLike", list)
BigFileLike = NewType("BigFileLike", str)


def _identity(v: object) -> object:
    """Pass-through serialization: the scalar carries its JSON value unchanged."""
    return v


SCALAR_MAP: dict[object, ScalarDefinition] = {
    MediaLike: strawberry.scalar(
        name="MediaLike",
        description="A type representing a media store reference, which can be either a string ID or a more complex object.",
        serialize=_identity,
        parse_value=_identity,
    ),
    ArrayLike: strawberry.scalar(
        name="ArrayLike",
        description="A type representing an array-like structure, which can be a list or any iterable.",
        serialize=_identity,
        parse_value=_identity,
    ),
    BigFileLike: strawberry.scalar(
        name="BigFileLike",
        description="A type representing a big file store reference, which can be either a string ID or a more complex object.",
        serialize=_identity,
        parse_value=_identity,
    ),
}
