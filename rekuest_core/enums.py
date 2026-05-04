import strawberry
from enum import Enum


@strawberry.enum(description="The kind of action.")
class ActionKind(str, Enum):
    FUNCTION = "FUNCTION"
    GENERATOR = "GENERATOR"


@strawberry.enum(description="The kind of port.")
class PortKind(str, Enum):
    INT = "INT"
    STRING = "STRING"
    STRUCTURE = "STRUCTURE"
    LIST = "LIST"
    BOOL = "BOOL"
    DICT = "DICT"
    FLOAT = "FLOAT"
    DATE = "DATE"
    UNION = "UNION"
    ENUM = "ENUM"
    MODEL = "MODEL"
    MEMORY_STRUCTURE = "MEMORY_STRUCTURE"
    INTERFACE = "INTERFACE"


@strawberry.enum(description="The kind of assign widget.")
class AssignWidgetKind(str, Enum):
    SEARCH = "SEARCH"
    CHOICE = "CHOICE"
    SLIDER = "SLIDER"
    CUSTOM = "CUSTOM"
    STRING = "STRING"
    STATE_CHOICE = "STATE_CHOICE"
    PROXY = "PROXY"


@strawberry.enum(description="The kind of return widget.")
class ReturnWidgetKind(str, Enum):
    CHOICE = "CHOICE"
    CUSTOM = "CUSTOM"
    PROXY = "PROXY"


@strawberry.enum(description="The kind of effect.")
class EffectKind(str, Enum):
    MESSAGE = "MESSAGE"
    HIDE = "HIDE"
    CUSTOM = "CUSTOM"


@strawberry.enum(description="The kind of action scope.")
class ActionScope(str, Enum):
    GLOBAL = "GLOBAL"
    LOCAL = "LOCAL"
    BRIDGE_GLOBAL_TO_LOCAL = "BRIDGE_GLOBAL_TO_LOCAL"
    BRIDGE_LOCAL_TO_GLOBAL = "BRIDGE_LOCAL_TO_GLOBAL"


@strawberry.enum(description="The operator for matching descriptors.")
class RequiresOperator(str, Enum):
    MATCHES = "MATCHES"
    EXISTS = "EXISTS"
    LTE = "LTE"
    GTE = "GTE"
    EQUALS = "EQUALS"
    CONTAINS = "CONTAINS"
    NOT_EQUALS = "NOT_EQUALS"
    IN = "IN"
    NOT_IN = "NOT_IN"


@strawberry.enum(description="The operator for matching descriptors.")
class ProvidesOperator(str, Enum):
    MATCHES = "MATCHES"
    EXISTS = "EXISTS"
    LTE = "LTE"
    GTE = "GTE"
    EQUALS = "EQUALS"
    CONTAINS = "CONTAINS"
    NOT_EQUALS = "NOT_EQUALS"
    IN = "IN"
    NOT_IN = "NOT_IN"


@strawberry.enum
class AssignPolicy(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    BALANCED = "BALANCED"
    ROUND_ROBIN = "ROUND_ROBIN"
    LEAST_BUSY = "LEAST_BUSY"
    FASTEST_RESPONSE = "FASTEST_RESPONSE"


@strawberry.enum
class OptionKey(str, Enum):
    LABEL = "LABEL"
    DESCRIPTION = "DESCRIPTION"
    LOGO = "LOGO"
    VALUE = "VALUE"
