from typing import NewType
import strawberry

Identifier = strawberry.scalar(
    NewType("Identifier", str),
    description="The `ArrayLike` scalar type represents a reference to a store "
    "previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

AnyDefault = strawberry.scalar(
    NewType("AnyDefault", object),
    description="The `ArrayLike` scalar type represents a reference to a store "
    "previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

Arg = strawberry.scalar(
    NewType("Arg", object),
    description="The `Arg` scalar type represents a an Argument in a Action assignment",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

SearchQuery = strawberry.scalar(
    NewType("SearchQuery", str),
    description="The `ArrayLike` scalar type represents a reference to a store "
    "previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

InstanceID = strawberry.scalar(
    NewType("InstanceId", str),
    description="The `ArrayLike` scalar type represents a reference to a store "
    "previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

ActionHash = strawberry.scalar(
    NewType("ActionHash", str),
    description="The `ArrayLike` scalar type represents a reference to a store "
    "previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

ValidatorFunction = strawberry.scalar(
    NewType("ValidatorFunction", object),
    description="""
    The `Validator` scalar represents a javascript function that should execute on the client side (inside a shadow realm)
      to validate a value (or a set of values) before it is sent to the server.  The function has two parameters (value, otherValues) and should return a string if the value is invalid and undefined if the value is valid.
        The otherValues parameter is an object with the other values in the form {fieldName: value}.""",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)
