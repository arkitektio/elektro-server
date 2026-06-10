from typing import NewType
from datalayer import models
import strawberry


MediaLike = strawberry.scalar(
    NewType("MediaLike", str),
    description="A type representing a media store reference, which can be either a string ID or a more complex object.",
    serialize=lambda v: v,  # Implement your serialization logic here
    parse_value=lambda v: v,  # Implement your parsing logic here
)


ArrayLike = strawberry.scalar(
    NewType("ArrayLike", list),
    description="A type representing an array-like structure, which can be a list or any iterable.",
    serialize=lambda v: v,  # Implement your serialization logic here
    parse_value=lambda v: v,  # Implement your parsing logic here
)


BigFileLike = strawberry.scalar(
    NewType("BigFileLike", str),
    description="A type representing a big file store reference, which can be either a string ID or a more complex object.",
    serialize=lambda v: v,  # Implement your serialization logic here
    parse_value=lambda v: v,  # Implement your parsing logic here
)

scalar_map = {MediaLike: MediaLike, ArrayLike: ArrayLike}
