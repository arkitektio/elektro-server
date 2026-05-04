from typing import Annotated, List, Optional
from strawberry.experimental import pydantic
from strawberry import LazyType
from rekuest_core.inputs import models
import strawberry
from rekuest_core import enums, scalars


@pydantic.input(
    models.EffectInputModel,
    description="""
                 An effect is a way to modify a port based on a condition. For example,
    you could have an effect that sets a port to null if another port is null.

    Or, you could have an effect that hides the port if another port meets a condition.
    E.g when the user selects a certain option in a dropdown, another port is hidden.


    """,
)
class EffectInput:
    kind: enums.EffectKind = strawberry.field(description="The kind of the effect. Can be either message, hide or custom")
    dependencies: list[str] | None = strawberry.field(
        default_factory=list,
        description="The dependencies of the effect. Use the .. syntax to traverse the tree of ports. For example, if you have a port with the key 'foo' and you want to reference a port with the key 'bar' that is a child of 'foo', you would use 'foo..bar'",
    )
    function: scalars.ValidatorFunction = strawberry.field(description="The function to run to determine if the effect should be applied")
    message: str | None = strawberry.field(
        default=None,
        description="The message to display when the effect is applied (if it is a message effect)",
    )
    hook: str | None = strawberry.field(
        default=None,
        description="The hook to run when the effect is applied (if it is a custom effect)",
    )
    ward: str | None = strawberry.field(
        default=None,
        description="The ward to run when the effect is applied (if it is a custom effect)",
    )
    fade: bool | None = strawberry.field(
        default=True,
        description="Whether to fade out the port when the effect is applied (if it is a hide effect)",
    )


@pydantic.input(
    models.ChoiceInputModel,
    description="""
A choice is a value that can be selected in a dropdown.

It is composed of a value, a label, and a description. The value is the
value that is returned when the choice is selected. The label is the
text that is displayed in the dropdown. The description is the text
that is displayed when the user hovers over the choice.

    """,
)
class ChoiceInput:
    value: scalars.AnyDefault = strawberry.field(description="The value of the choice. This is the value that is returned when the choice is selected")
    label: str = strawberry.field(description="The label of the choice. This is the text that is displayed in the UI")
    image: str | None = strawberry.field(
        default=None,
        description="The image of the choice. This is the image that is displayed in the UI (must be a URL)",
    )
    description: str | None = strawberry.field(
        default=None,
        description="The description of the choice. This is the text that is displayed in the UI when the user hovers over the choice",
    )


@pydantic.input(models.StateAccessorInputModel)
class StateAccessorInput:
    option_key: enums.OptionKey = strawberry.field(description="The part of the state accessor to use as the value for the assign widget (e.g. the key, the description, the logo, etc.)")
    sub_path: str | None = strawberry.field(
        default=None,
        description="The sub path to access a specific part of the state value. Always traverse from top to bottom level. i.e state.x for state.x and state.x.y for state.x.y. You can also use an arrow function to specify a dynamic path based on the other arguments, e.g. (args) => state[args.foo]",
    )


@pydantic.input(models.AssignWidgetInputModel)
class AssignWidgetInput:
    """An Assign Widget is a UI element that is used to assign a value to a port.

    It gets displayed if we intend to assign to a action, and represents the Widget
    that gets displayed in the UI. For example, a dropdown, a text input, a slider,
    etc.

    This input type composes elements of all the different kinds of assign widgets.
    Please refere to each subtype for more information.



    """

    kind: enums.AssignWidgetKind = strawberry.field(description="The kind of the assign widget. Can be either dropdown, text, slider, checkbox, radio or custom")
    query: scalars.SearchQuery | None = strawberry.field(
        default=None,
        description="The query to run when searching for choices. This is used for dropdowns and text inputs",
    )
    choices: list[ChoiceInput] | None = strawberry.field(
        default=None,
        description="The choices to display in the dropdown. This is used for dropdowns and text inputs",
    )
    min: float | None = strawberry.field(
        default=None,
        description="The minimum value of the slider (if a slider). . This is used for sliders and text inputs",
    )
    max: float | None = strawberry.field(
        default=None,
        description="The maximum value of the slider (if a slider). This is used for sliders and text inputs",
    )
    step: float | None = strawberry.field(
        default=None,
        description="The step value of the slider (if a slider). This is used for sliders and text inputs",
    )
    placeholder: str | None = strawberry.field(
        default=None,
        description="The placeholder of the input if . This is used for text inputs and dropdowns",
    )
    as_paragraph: bool | None = strawberry.field(
        default=None,
        description="Whether to display the input as a paragraph or not. This is used for text inputs and dropdowns",
    )
    hook: str | None = strawberry.field(
        default=None,
        description="The hook to run when the input is changed. This is used for custom assign widgets",
    )
    ward: str | None = strawberry.field(
        default=None,
        description="The ward that is respoinsbiel for handling queriny the choices",
    )
    fallback: Optional[Annotated["AssignWidgetInput", strawberry.lazy(__name__)]] = strawberry.field(
        default=None,
        description="The fallback assign widget to use if the current one fails. This is used for custom assign widgets",
    )
    filters: Optional[List[Annotated["ArgPortInput", strawberry.lazy(__name__)]]] = strawberry.field(
        default_factory=list,
        description="The filters to apply to a search widget. This is used for custom assign widgets",
    )
    dependencies: list[str] | None = strawberry.field(
        default_factory=list,
        description="The dependencies of the assign widget, which will be pased to the search or the hook widget. Use the .. syntax to traverse the tree of ports. For example, if you have a port with the key 'foo' and you want to reference a port with the key 'bar' that is a child of 'foo', you would use 'foo..bar'",
    )
    dependency: str | None = strawberry.field(default=None, description="The dependency that we are going to use to fullfill the state choices. If none is provided its the own state that will be queried")
    state_path: str | None = strawberry.field(
        default=None,
        description="The path to the state value that we are going to use to fullfill the state choices. Always traverse from top to bottom level. i.e state.x for state.x and state.x.y for state.x.y. You can also use an arrow function to specify a dynamic path based on the other arguments, e.g. (args) => state[args.foo]",
    )
    target_dependency: str | None = strawberry.field(default=None, description="The dependency that we are going to target with a proxy widget. This is used for proxy widgets")
    target_action: str | None = strawberry.field(default=None, description="The action that we are going to target with a proxy widget. This is used for proxy widgets")
    target_port: str | None = strawberry.field(default=None, description="The port that we are going to target with a proxy widget. This is used for proxy widgets")

    state_accessors: Optional[List[Annotated["StateAccessorInput", strawberry.lazy(__name__)]]] = strawberry.field(
        default=None,
        description="State accessors are used to specify how to access the state values that we are going to use to fullfill the state choices. This is used when the state value that we want to use is not the same as the one of the port, e.g. when we want to use a specific key of a state object, or when we want to use a dynamic key based on the other arguments. The option_key field is used to specify which part of the state accessor we want to use as the value for the assign widget (e.g. the key, the description, the logo, etc.)",
    )


@pydantic.input(
    models.ReturnWidgetInputModel,
    description="""A Return Widget is a UI element that is used to display the value of a port.

    Return Widgets get displayed both if we show the return values of an assignment,
    but also when we inspect the given arguments of a previous run task. Their primary
    usecase is to adequately display the value of a port, in a user readable way.

    Return Widgets are often overwriten by the underlying UI framework (e.g. Orkestrator)
    to provide a better user experience. For example, a return widget that displays a
    date could be overwriten to display a calendar widget.

    Return Widgets provide more a way to customize this overwriten behavior.

    """,
)
class ReturnWidgetInput:
    kind: enums.ReturnWidgetKind = strawberry.field(description="The kind of the return widget. Can be either dropdown, text, slider, checkbox, radio or custom")
    query: scalars.SearchQuery | None = strawberry.field(
        default=None,
        description="The query to run when searching for choices. This is used for dropdowns and text inputs",
    )
    choices: list[ChoiceInput] | None = strawberry.field(
        default=None,
        description="The choices to display in the dropdown. This is used for dropdowns and text inputs",
    )
    min: int | None = None
    max: int | None = None
    step: int | None = None
    placeholder: str | None = None
    hook: str | None = None
    ward: str | None = None


@pydantic.input(
    models.ValidatorInputModel,
    description=""" 
A validating function for a port. Can specify a function that will run when validating values of the port.
If outside dependencies are needed they need to be specified in the dependencies field. With the .. syntax
when transversing the tree of ports. 

""",
)
class ValidatorInput:
    function: scalars.ValidatorFunction = strawberry.field(description="The function to run when validating the port")
    dependencies: list[str] | None = strawberry.field(
        default_factory=list,
        description="The dependencies of the function. Use the .. syntax to traverse the tree of ports. For example, if you have a port with the key 'foo' and you want to reference a port with the key 'bar' that is a child of 'foo', you would use 'foo..bar'",
    )
    label: str | None = None
    error_message: str | None = strawberry.field(description="The error message to display when the validation fails")


@pydantic.input(
    models.OptimisticInputModel,
    description=""" An optimistic is used to optimistically set state values when the action is assigned. This is used to provide a better user experience by optimistically setting state values when the action is assigned, instead of waiting for the action to be executed and the state to be updated. This will only ever happen on the frontend.

""",
)
class OptimisticInput:
    state: str = strawberry.field(description="The state to optimistically set when the action is is assigned")
    path: str = strawberry.field(
        description="The path to the state.value to optimistically set the value, always traverse from top to bottom level. i.e state.x for state.x and state.x.y for state.x.y. YOu can also use an arrow function to specify a dynamic path based on the other arguments, e.g. (args) => state[args.foo]",
    )
    accessor: str | None = strawberry.field(default=None, description="The accessor to get the value to optimistically set. This is used when the value to optimistically set is not the same as the value of the port")


@pydantic.input(models.RequiresInputModel)
class RequiresInput:
    key: str = strawberry.field(description="The key of the requirement. This is used to uniquely identify the requirement")
    operator: enums.RequiresOperator = strawberry.field(description="The operator for the requirement")
    value: scalars.Arg = strawberry.field(description="The value of the requirement. This can be any JSON serializable value")


@pydantic.input(models.ProvidesInputModel)
class ProvidesInput:
    key: str = strawberry.field(description="The key of the provision. This is used to uniquely identify the provision")
    operator: enums.ProvidesOperator = strawberry.field(description="The operator for the provision")
    value: scalars.Arg = strawberry.field(description="The value of the provision. This can be any JSON serializable value")


@pydantic.input(
    models.ArgPortInputModel,
    description="""Port

    A Port is a single input or output of a action. It is composed of a key and a kind
    which are used to uniquely identify the port.

    If the Port is a structure, we need to define a identifier and scope,
    Identifiers uniquely identify a specific type of model for the scopes (e.g
    all the ports that have the identifier "@mikro/image" are of the same type, and
    are hence compatible with each other). Scopes are used to define in which context
    the identifier is valid (e.g. a port with the identifier "@mikro/image" and the
    scope "local", can only be wired to other ports that have the same identifier and
    are running in the same app). Global ports are ports that have the scope "global",
    and can be wired to any other port that has the same identifier, as there exists a
    mechanism to resolve and retrieve the object for each app. Please check the rekuest
    documentation for more information on how this works.


    """,
)
class ArgPortInput:
    validators: list[ValidatorInput] | None = strawberry.field(default_factory=list, description="The validators for the port")
    key: str = strawberry.field(description="The key of the port")
    label: str | None = strawberry.field(
        default=None,
        description="The label of the port. This is the text that is displayed in the UI",
    )
    kind: enums.PortKind = strawberry.field(description="The kind of the port. This is the type of the port. Can be either int, string, structure, list, bool, dict, float, date, union or model")
    description: str | None = strawberry.field(
        default=None,
        description="The description of the port. This is the text that is displayed in the UI when the user hovers over the port",
    )
    identifier: str | None = strawberry.field(
        default=None,
        description="The identifier of a structure port. This is used to uniquely identify a specific type of structure.",
    )
    nullable: bool = strawberry.field(
        default=False,
        description="Whether the port is nullable or not. If the port is nullable, it can be set to null. If the port is not nullable, it cannot be set to null",
    )
    effects: list[EffectInput] | None = strawberry.field(default_factory=list, description="The effects of the port")
    choices: list[ChoiceInput] | None = strawberry.field(
        default_factory=list,
        description="The options for the port. This is used for dropdowns and text inputs",
    )
    default: scalars.AnyDefault | None = None
    children: list[Annotated["ArgPortInput", strawberry.lazy(__name__)]] | None = strawberry.field(default_factory=list)
    widget: Optional["AssignWidgetInput"] = None
    requires: list[RequiresInput] | None = strawberry.field(
        default_factory=list, description="The descriptors for the port. Descriptors are key-value pairs that can be used to add additional metadata to a port. When using rekuest's action search, you can filter actions based on their port descriptors"
    )


@pydantic.input(
    models.ReturnPortInputModel,
    description="""Port

    A Port is a single input or output of a action. It is composed of a key and a kind
    which are used to uniquely identify the port.

    If the Port is a structure, we need to define a identifier and scope,
    Identifiers uniquely identify a specific type of model for the scopes (e.g
    all the ports that have the identifier "@mikro/image" are of the same type, and
    are hence compatible with each other). Scopes are used to define in which context
    the identifier is valid (e.g. a port with the identifier "@mikro/image" and the
    scope "local", can only be wired to other ports that have the same identifier and
    are running in the same app). Global ports are ports that have the scope "global",
    and can be wired to any other port that has the same identifier, as there exists a
    mechanism to resolve and retrieve the object for each app. Please check the rekuest
    documentation for more information on how this works.


    """,
)
class ReturnPortInput:
    validators: list[ValidatorInput] | None = strawberry.field(default_factory=list, description="The validators for the port")
    key: str = strawberry.field(description="The key of the port")
    label: str | None = strawberry.field(
        default=None,
        description="The label of the port. This is the text that is displayed in the UI",
    )
    kind: enums.PortKind = strawberry.field(description="The kind of the port. This is the type of the port. Can be either int, string, structure, list, bool, dict, float, date, union or model")
    description: str | None = strawberry.field(
        default=None,
        description="The description of the port. This is the text that is displayed in the UI when the user hovers over the port",
    )
    identifier: str | None = strawberry.field(
        default=None,
        description="The identifier of a structure port. This is used to uniquely identify a specific type of structure.",
    )
    nullable: bool = strawberry.field(
        default=False,
        description="Whether the port is nullable or not. If the port is nullable, it can return null",
    )
    effects: list[EffectInput] | None = strawberry.field(default_factory=list, description="The effects of the port")
    choices: list[ChoiceInput] | None = strawberry.field(
        default_factory=list,
        description="The options for the port. This is used for dropdowns and text inputs",
    )
    default: scalars.AnyDefault | None = None
    children: list[Annotated["ReturnPortInput", strawberry.lazy(__name__)]] | None = strawberry.field(default_factory=list)
    widget: Optional["ReturnWidgetInput"] = None
    provides: list[ProvidesInput] | None = strawberry.field(
        default_factory=list, description="The provisions for the port. Provisions are key-value pairs that can be used to add additional metadata to a port. When using rekuest's action search, you can filter actions based on their port provisions"
    )


@strawberry.input(
    description="A Port Group is a group of ports that are related to each other. It is used to group ports together in the UI and provide a better user experience.",
)
class PortGroupInput:
    key: str = strawberry.field(description="The key of the port group. This is used to uniquely identify the port group")
    title: str | None
    description: str | None
    effects: list[EffectInput] | None = strawberry.field(default_factory=list)
    ports: list[str] | None = strawberry.field(default_factory=list)


@pydantic.input(
    models.PortMatchInputModel,
    description="""A dependency for a implementation. By defining dependencies, you can
    create a dependency graph for your implementations and actions""",
)
class PortMatchInput:
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
    object: scalars.Arg | None = strawberry.field(
        default=None,
        description="The object of the port to match. This is used for adanved pattern matching based on the exact object descriptors of the object. i.e { x: 1, y: 2} ",
    )
    nullable: bool | None = strawberry.field(
        default=None,
        description="Whether the port is nullable. ",
    )
    children: Optional[list[Annotated["PortMatchInput", strawberry.lazy(__name__)]]] = strawberry.field(
        default=None,
        description="The matches for the children of the port to match. ",
    )


@pydantic.input(
    models.ActionDependencyInputModel,
    description="""A dependency for a implementation. By defining dependencies, you can
    create a dependency graph for your implementations and actions""",
)
class ActionDependencyInput:
    key: str = strawberry.field(
        description="The key of the action. This is used to identify the dependency in the system.",
    )
    app: str | None = strawberry.field(
        default=None,
        description="Which app this dependency corresponds to (i.e. do you want to use a stardist agent for that or imagej agents needs to be a world unique classsifier (reverse domain notation) that identifies the type of agent you want to use, and then we can have multiple agents of the same type running in the system, e.g. startdist could be the app for all agents that correpsond to a startdist instance)",
    )
    allow_inactive: bool | None = strawberry.field(default=None, description="Allow inactive nodes, defaults to true")
    name: str | None = strawberry.field(
        default=None,
        description="The name of the action. This is used to identify the action in the system.",
    )
    action_key: str | None = strawberry.field(
        default=None,
        description="The key of the state this dependency corresponds to. (i.e frame:acquireimage)",
    )
    description: str | None = strawberry.field(
        default=None,
        description="The description of the action. This can described the action and its purpose.",
    )
    arg_matches: list[PortMatchInput] | None = strawberry.field(
        default=None,
        description="The demands for the action args, this can be additionaly specified so that when we loosen the matching criteria for an action in a resolver, we can still make sure to match the right action based on the demands for the args. This is used to identify the demand in the system.",
    )
    return_matches: list[PortMatchInput] | None = strawberry.field(
        default=None,
        description="The demands for the action args, this can be additionaly specified so that when we loosen the matching criteria for an action in a resolver, we can still make sure to match the right action based on the demands for the args. This is used to identify the demand in the system.",
    )
    protocols: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="The protocols that the action is implementing or relying on. This is used to identify the demand in the system, and can be used to match actions that are implementing the same protocol together.",
    )
    force_arg_length: int | None = strawberry.field(
        default=None,
        description="Require that the action has a specific number of args. When loosing the matching criteria for an action in a resolver, we can still make sure to match the right action based on the demands for the args. This is used to identify the demand in the system.",
    )
    force_return_length: int | None = strawberry.field(
        default=None,
        description="Require that the action has a specific number of returns. This is used to identify the demand in the system.",
    )
    optional: bool = strawberry.field(default=False, description="Whether the dependency is optional or not. If the dependency is optional, the agent doesn't have to provide it to be potentially callable")


@pydantic.input(
    models.StateDependencyInputModel,
    description="""A dependency for a implementation. By defining dependencies, you can
    create a dependency graph for your implementations and actions""",
)
class StateDependencyInput:
    key: str = strawberry.field(
        description="The key of the state. This is used to identify the dependency in the system.",
    )
    app: str | None = strawberry.field(
        default=None,
        description="Which app this dependency corresponds to (i.e. do you want to use a stardist agent for that or imagej agents needs to be a world unique classsifier (reverse domain notation) that identifies the type of agent you want to use, and then we can have multiple agents of the same type running in the system, e.g. startdist could be the app for all agents that correpsond to a startdist instance)",
    )
    state_key: str | None = strawberry.field(
        default=None,
        description="The key of the state this dependency corresponds to. (i.e frame:count)",
    )
    allow_inactive: bool | None = strawberry.field(default=None, description="Allow inactive nodes, defaults to true")
    name: str | None = strawberry.field(
        default=None,
        description="The name of the state. This is used to identify the action in the system.",
    )
    description: str | None = strawberry.field(
        default=None,
        description="The description of the action. This can described the action and its purpose.",
    )
    port_matches: list[PortMatchInput] | None = strawberry.field(
        default=None,
        description="The demands for the action args, this can be additionaly specified so that when we loosen the matching criteria for an action in a resolver, we can still make sure to match the right action based on the demands for the args. This is used to identify the demand in the system.",
    )
    protocols: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="The protocols that the action is implementing or relying on. This is used to identify the demand in the system, and can be used to match actions that are implementing the same protocol together.",
    )
    optional: bool = strawberry.field(default=False, description="Whether the dependency is optional or not. If the dependency is optional, the agent doesn't have to provide it to be potentially callable")


@pydantic.input(
    models.AgentDependencyInputModel,
    description="""A dependency for a implementation. By defining dependencies, you can
    create a dependency graph for your implementations and actions""",
)
class AgentDependencyInput:
    key: str = strawberry.field(
        description="The key of this dependency, when assigning you can reference this key to specify which agent_dependency you are assigning to. ",
    )
    app: str | None = strawberry.field(
        default=None,
        description="Which app this dependency corresponds to (i.e. do you want to use a stardist agent for that or imagej agents needs to be a world unique classsifier (reverse domain notation) that identifies the type of agent you want to use, and then we can have multiple agents of the same type running in the system, e.g. startdist could be the app for all agents that correpsond to a startdist instance)",
    )
    version: str | None = strawberry.field(
        default=None,
        description="The version of the app this dependency corresponds to.",
    )
    auto_resolvable: bool = strawberry.field(
        default=False,
        description="Whether this dependency is auto resolvable or not. If so we will try to automatically resolve it based on the demands specified in the dependency and the capabilities of the available agents in the system. This is used to identify the demand in the system. Attention if any of the dependencies of this agent dependency is not auto resolvable, this dependency will also not be auto resolvable",
    )
    name: str | None = strawberry.field(
        default=None,
        description="The name of the agent. This is used to identify the agent in the system.",
    )
    description: str | None = strawberry.field(
        default=None,
        description="A description of the dependency, why it is needed and what it is used for. This can be used to provide more context to users when assigning dependencies.",
    )
    optional: bool = strawberry.field(default=False, description="Whether the dependency is optional or not. If the dependency is optional, users can choose to not provide it")
    action_demands: list[ActionDependencyInput] | None = strawberry.field(
        default=None,
        description="The action demands of the agent. This is used to identify the demand in the system.",
    )
    state_demands: list[StateDependencyInput] | None = strawberry.field(
        default=None,
        description="The state demands of the agent. This is used to identify the demand in the system.",
    )
    min_viable_instances: int | None = strawberry.field(
        default=None,
        description="The minimum amount of viable instances for the agent. This is used to identify the demand in the system.",
    )
    max_viable_instances: int | None = strawberry.field(
        default=None,
        description="The maximum amount of viable instances for the agent. This is used to identify the demand in the system.",
    )
    mutually_exclusive_keys: list[str] | None = strawberry.field(
        default=None,
        description="A list of keys of other agent dependencies that are mutually exclusive with this one. This means two agent dependencies with mutually exclusive keys cannot be assigned to the same implementing agent. This is used to identify the demand in the system.",
    )
    prefered_instances: int | None = strawberry.field(
        default=None,
        description="The prefered amount of instances for the agent. This is used to identify the demand in the system.",
    )


@strawberry.input(
    description="""A definition

    Definitions are the building implementation for Actions and provide the
    information needed to create a action. They are primarly composed of a name,
    a description, and a list of ports.

    Definitions provide a protocol of input and output, and do not contain
    any information about the actual implementation of the action ( this is handled
    by a implementation that implements a action).

    """,
)
class DefinitionInput:
    description: str | None = strawberry.field(
        default=None,
        description="The description of the definition. This is the text that is displayed in the UI",
    )
    collections: list[str] = strawberry.field(
        default_factory=list,
        description="The collections of the definition. This is used to group definitions together in the UI",
    )
    key: str = strawberry.field(description="The key of the definition. This is used to uniquely identify the definition")
    package: str | None = strawberry.field(
        default=None,
        description="The package of the function. Will default to the currents agent's app if not specified. This is used to group definitions together in the UI and provide a better user experience",
    )
    version: str = strawberry.field(description="The version of the definition. This is used to differentiate if the underyling algorithm has changed, i.e we would expect different results for the same input")
    name: str = strawberry.field(description="The name of the actions. This is used to uniquely identify the definition")
    stateful: bool = strawberry.field(
        default=False,
        description="Whether the definition is stateful or not. If the definition is stateful, it can be used to create a stateful action. If the definition is not stateful, it cannot be used to create a stateful action",
    )
    port_groups: list[PortGroupInput] = strawberry.field(
        default_factory=list,
        description="The port groups of the definition. This is used to group ports together in the UI",
    )
    args: list[ArgPortInput] = strawberry.field(
        default_factory=list,
        description="The args of the definition. This is the input ports of the definition",
    )
    returns: list[ReturnPortInput] = strawberry.field(
        default_factory=list,
        description="The returns of the definition. This is the output ports of the definition",
    )
    tests: ActionDependencyInput | None = strawberry.field(default=None)
    kind: enums.ActionKind = strawberry.field(description="The kind of the definition. This is the type of the definition. Can be either a function or a generator")
    is_test_for: list["str"] = strawberry.field(
        default_factory=list,
        description="The tests for the definition. This is used to group definitions together in the UI",
    )

    interfaces: list[str] = strawberry.field(
        default_factory=list,
        description="""The interfaces of the definition. This is used to group definitions together in the UI""",
    )
    is_dev: bool = strawberry.field(
        default=False,
        description="Whether the definition is a dev definition or not. If the definition is a dev definition, it can be used to create a dev action. If the definition is not a dev definition, it cannot be used to create a dev action",
    )
    logo: str | None = strawberry.field(
        default=None,
        description="The logo of the definition. This is used to display the logo in the UI",
    )


@pydantic.input(
    models.ImplementationInputModel,
    description="""A implementation is a blueprint for a action. It is composed of a definition, a list of dependencies, and a list of params.""",
)
class ImplementationInput:
    definition: DefinitionInput = strawberry.field(
        description="The definition of the implementation. This is used to uniquely identify the implementation",
    )
    interface: str | None = strawberry.field(
        default=None,
        description="The interface of the implementation. This is used to group implementations together in the UI",
    )
    params: scalars.AnyDefault | None = strawberry.field(
        default=None,
        description="The params of the implementation. This is used to pass parameters to the implementation",
    )
    dynamic: bool = strawberry.field(
        default=False,
        description="Whether the implementation is dynamic or not. If the implementation is dynamic, it can be used to create a dynamic action. If the implementation is not dynamic, it cannot be used to create a dynamic action",
    )
    logo: str | None = strawberry.field(
        default=None,
        description="The logo of the implementation. This is used to display the logo in the UI",
    )
    locks: list[str] | None = strawberry.field(
        default=None,
        description="The locks of the implementation. This is used to specify which resources the implementation needs to run",
    )
    optimistics: list[OptimisticInput] | None = strawberry.field(
        default=None,
        description="The optimistics of the definition. This is used to optimistically set state values when the action is assigned. This is used to provide a better user experience by optimistically setting state",
    )
    extension: str | None = strawberry.field(
        default=None,
        description="The extension of the implementation. This is used to group implementations together in the UI and provide a better user experience",
    )
    dependencies: list[AgentDependencyInput] = strawberry.field(default_factory=list)


@pydantic.input(
    models.StateDefinitionInputModel,
    description="""A state schema is a blueprint for a state. It is composed of a definition, a list of dependencies, and a list of params.""",
)
class StateDefinitionInput:
    name: str = strawberry.field(description="The name of the state schema. This is used to uniquely identify the state schema")
    ports: list[ReturnPortInput] = strawberry.field(default_factory=list, description="The ports of the state schema. This is used to define the structure of the state")


@pydantic.input(
    models.StateImplementationInputModel,
    description="""A state implementation is a blueprint for a state. It is composed of a definition, a list of dependencies, and a list of params.""",
)
class StateImplementationInput:
    interface: str = strawberry.field(description="The key of the state implementation. This is used to uniquely identify the state implementation")
    definition: StateDefinitionInput = strawberry.field(description="The schema of the state implementation. This is used to define the structure of the state")


@pydantic.input(
    models.LockDefinitionInputModel,
    description="Which locks does the agent provide in general",
)
class LockDefinitionInput:
    key: str
    description: str | None = strawberry.field(default=None, description="Describe the structure a bit")


@pydantic.input(
    models.LockImplementationInputModel,
    description="Which locks does the agent provide in general",
)
class LockImplementationInput:
    key: str
    definition: LockDefinitionInput


@pydantic.input(
    models.StructureInputModel,
    description="Which structures does the agent act upon in general",
)
class StructureInput:
    key: str
    description: str | None = strawberry.field(default=None, description="Describe the structure a bit")
    default_assign_widget: Optional["AssignWidgetInput"] = strawberry.field(default=None, description="Describe the structure a bit")
    default_return_widget: Optional["ReturnWidgetInput"] = strawberry.field(default=None, description="Describe the structure a bit")


@pydantic.input(
    models.InterfaceInputModel,
    description="Which interfaces does the agent declare",
)
class InterfaceInput:
    key: str
    description: str | None = strawberry.field(default=None, description="Describe the structure a bit")
    default_assign_widget: Optional["AssignWidgetInput"] = strawberry.field(default=None, description="Describe the structure a bit")
    default_return_widget: Optional["ReturnWidgetInput"] = strawberry.field(default=None, description="Describe the structure a bit")


@pydantic.input(models.DescriptorSchemaInputModel, description="A descriptor model")
class DescriptorSchemaInput:
    key: str = strawberry.field(description="The key of the descriptor. This is used to uniquely identify the descriptor")
    description: str | None = strawberry.field(default=None, description="Describe the descriptor a bit")


@pydantic.input(
    models.StructurePackageInputModel,
    description="A structure schema model",
)
class StructurePackageInput:
    key: str
    description: str | None = strawberry.field(default=None, description="Describe the schema")
    descriptors: list[DescriptorSchemaInput] | None = strawberry.field(default=None, description="The listed descriptors")
    interfaces: list[InterfaceInput] | None = strawberry.field(default=None, description="The listed interfaces")
    structures: list[StructureInput] | None = strawberry.field(default=None, description="The listed structures")
