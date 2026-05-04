import datetime
from typing import Annotated, Optional
import strawberry
import strawberry_django
from pydantic import BaseModel
from strawberry import LazyType
from strawberry.experimental import pydantic

from rekuest_core.objects import models
from rekuest_core import enums, scalars


class ChoiceModel(BaseModel):
    label: str
    value: str
    image: str | None
    description: str | None


@pydantic.type(models.ChoiceModel)
class Choice:
    label: str
    value: str
    image: str | None
    description: str | None


@pydantic.interface(models.AssignWidgetModel)
class AssignWidget:
    kind: enums.AssignWidgetKind
    follow_value: str | None


@pydantic.type(models.ProxyWidgetModel)
class ProxyWidget(AssignWidget):
    target_port: str = strawberry.field(description="The port key of the port that we are going to target with a proxy widget. This is used for proxy widgets")
    target_action: str = strawberry.field(description="The action dependency name that we are going to target with a proxy widget. This is used for proxy widgets")
    target_dependency: str | None = strawberry.field(description="The dependency that we are going to target with a proxy widget. This is used for proxy widgets")


@pydantic.type(models.SliderAssignWidgetModel)
class SliderAssignWidget(AssignWidget):
    min: float | None
    max: float | None
    step: float | None


@pydantic.type(models.ChoiceAssignWidgetModel)
class ChoiceAssignWidget(AssignWidget):
    choices: strawberry.auto


@pydantic.type(models.CustomAssignWidgetModel)
class CustomAssignWidget(AssignWidget):
    hook: str
    ward: str


@pydantic.type(models.StateAccessorModel)
class StateAccessor:
    option_key: enums.OptionKey
    sub_path: str | None = None


@pydantic.type(models.StateChoiceAssignWidgetModel)
class StateChoiceAssignWidget(AssignWidget):
    state_path: str
    dependency: str | None
    state_accessors: list[StateAccessor] | None


@pydantic.type(models.StringWidgetModel)
class StringAssignWidget(AssignWidget):
    placeholder: str
    as_paragraph: bool


@pydantic.interface(models.ReturnWidgetModel)
class ReturnWidget:
    kind: enums.ReturnWidgetKind


@pydantic.type(models.CustomReturnWidgetModel)
class CustomReturnWidget(ReturnWidget):
    hook: str
    ward: str


@pydantic.type(models.ChoiceReturnWidgetModel)
class ChoiceReturnWidget(ReturnWidget):
    choices: strawberry.auto


@pydantic.interface(models.EffectModel)
class Effect:
    kind: enums.EffectKind
    function: scalars.ValidatorFunction
    dependencies: list[str]


@pydantic.type(models.MessageEffectModel)
class MessageEffect(Effect):
    message: str


@pydantic.type(models.CustomEffectModel)
class CustomEffect(Effect):
    ward: str
    hook: str


@pydantic.type(models.HideEffectModel)
class HideEffect(Effect):
    fade: bool = True


@pydantic.type(models.PortMatchModel)
class PortMatch:
    at: int | None = strawberry.field(
        default=None,
        description="The index of the port to match. ",
    )
    key: str | None = strawberry.field(
        default=None,
        description="The key of the port to match.",
    )
    kind: enums.PortKind | None = strawberry.field(
        default=None,
        description="The kind of the port to match. ",
    )
    identifier: str | None = strawberry.field(
        default=None,
        description="The identifier of the port to match. ",
    )
    nullable: bool | None = strawberry.field(
        default=None,
        description="Whether the port is nullable. ",
    )
    children: list[Annotated["PortMatch", strawberry.lazy(__name__)]] | None = strawberry.field(
        default=None,
        description="Child ports to match. ",
    )


@pydantic.type(models.PortGroupModel)
class PortGroup:
    key: str
    title: str | None
    description: str | None
    effects: list[Effect] | None
    ports: list[str]


@pydantic.type(models.ValidatorModel)
class Validator:
    function: scalars.ValidatorFunction
    dependencies: list[str] | None
    label: str | None
    error_message: str | None = None


@pydantic.type(models.RequiresModel)
class Requires:
    key: str = strawberry.field(description="The key of the descriptor. This is used to uniquely identify the descriptor")
    value: scalars.Arg = strawberry.field(description="The value of the descriptor. This can be any JSON serializable value")
    operator: enums.RequiresOperator = strawberry.field(description="The operator to use for matching the descriptor. This is used when searching for actions based on their descriptors. The operator can be EQUALS, NOT_EQUALS, EXISTS, NOT_EXISTS, GREATER_THAN, LESS_THAN, INCLUDES, NOT_INCLUDES")


@pydantic.type(models.ProvidesModel)
class Provides:
    key: str = strawberry.field(description="The key of the descriptor. This is used to uniquely identify the descriptor")
    value: scalars.Arg = strawberry.field(description="The value of the descriptor. This can be any JSON serializable value")
    operator: enums.ProvidesOperator = strawberry.field(description="The operator to use for matching the descriptor. This is used when searching for actions based on their descriptors. The operator can be EQUALS, NOT_EQUALS, EXISTS, NOT_EXISTS, GREATER_THAN, LESS_THAN, INCLUDES, NOT_INCLUDES")


@pydantic.type(models.ArgPortModel)
class ArgPort:
    identifier: scalars.Identifier | None = strawberry.field(
        default=None,
        description="The identifier of the port. Identifier are used to give meaning to structure ports",
    )
    default: scalars.AnyDefault | None
    kind: enums.PortKind
    key: str
    nullable: bool
    label: str | None
    description: str | None
    effects: list[Effect] | None = None
    children: list[Annotated["ArgPort", strawberry.lazy(__name__)]] | None = None
    choices: list[Choice] | None = None
    widget: AssignWidget | None = None
    validators: list[Validator] | None = None
    requires: list[Requires] | None = None


@pydantic.type(models.ReturnPortModel)
class ReturnPort:
    identifier: scalars.Identifier | None = strawberry.field(
        default=None,
        description="The identifier of the port. Identifier are used to give meaning to structure ports",
    )
    default: scalars.AnyDefault | None
    kind: enums.PortKind
    key: str
    nullable: bool
    label: str | None
    description: str | None
    effects: list[Effect] | None = None
    children: list[Annotated["ReturnPort", strawberry.lazy(__name__)]] | None = None
    choices: list[Choice] | None = None
    widget: ReturnWidget | None = None
    provides: list[Provides] | None = None


@pydantic.type(models.SearchAssignWidgetModel)
class SearchAssignWidget(AssignWidget):
    query: str
    ward: str
    filters: list[ArgPort] | None = None
    dependencies: list[str] | None = None


# TODO: Should be saved and made accessible
@pydantic.type(models.OptimisticModel)
class Optimistic:
    """An optimistic is used to optimistically set state values when the action is assigned. This is used to provide a better user experience by optimistically setting state values when the action is assigned, instead of waiting for the action to be executed and the state to be updated. This will only ever happen on the frontend."""

    state: str
    path: str
    accessor: str | None = None


@pydantic.type(models.DefinitionModel)
class Definition:
    hash: scalars.ActionHash
    name: str
    stateful: bool
    kind: enums.ActionKind
    description: str | None
    port_groups: list[PortGroup]
    collections: list[str]
    scope: enums.ActionScope
    is_test_for: list[str]
    tests: list[str]
    protocols: list[str]
    defined_at: datetime.datetime
    is_dev: bool

    @strawberry_django.field()
    def args(self) -> list[ArgPort]:
        return [models.ArgPortModel(**i) for i in self.args]

    @strawberry_django.field()
    def returns(self) -> list[ReturnPort]:
        return [models.ReturnPortModel(**i) for i in self.returns]
