from typing import Any, Optional
from rekuest_core import enums
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self


class BindsInputModel(BaseModel):
    implementations: Optional[list[str]]
    clients: Optional[list[str]]
    desired_instances: int = 1
    minimum_instances: int = 1


class EffectDependencyInputModel(BaseModel):
    key: str
    condition: str
    value: str


class EffectInputModel(BaseModel):
    function: str
    dependencies: list[str] | None = []
    message: str | None = None
    kind: enums.EffectKind
    fade: bool = True
    hook: str | None = None
    ward: str | None = None


class ChoiceInputModel(BaseModel):
    value: str
    label: str
    image: str | None = None
    description: str | None = None


class ValidatorInputModel(BaseModel):
    function: str
    dependencies: list[str] | None = []
    label: str | None = None
    error_message: str | None = None


class StateAccessorInputModel(BaseModel):
    option_key: enums.OptionKey
    sub_path: str | None = None


class AssignWidgetInputModel(BaseModel):
    kind: enums.AssignWidgetKind
    query: str | None = None
    choices: list[ChoiceInputModel] | None = None
    state_choices: str | None = None
    follow_value: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    placeholder: str | None = None
    hook: str | None = None
    ward: str | None = None
    fallback: Optional["AssignWidgetInputModel"] = None
    filters: list["ArgPortInputModel"] | None = None
    dependencies: list[str] | None = []
    dependency: str | None = None
    target_dependency: str | None = None
    target_action: str | None = None
    target_port: str | None = None
    state_path: str | None = None
    state_accessors: list[StateAccessorInputModel] | None = None


class ReturnWidgetInputModel(BaseModel):
    kind: enums.ReturnWidgetKind
    query: str | None = None
    choices: list[ChoiceInputModel] | None = None
    min: int | None = None
    max: int | None = None
    step: int | None = None
    placeholder: str | None = None
    hook: str | None = None
    ward: str | None = None


class RequiresInputModel(BaseModel):
    key: str
    operator: enums.RequiresOperator
    value: Any


class ProvidesInputModel(BaseModel):
    key: str
    operator: enums.ProvidesOperator
    value: Any


class DescriptorSchemaInputModel(BaseModel):
    key: str
    description: str | None = None


class OptimisticInputModel(BaseModel):
    state: str
    path: str
    accessor: str | None = None


class PortInputModel(BaseModel):
    validators: list[ValidatorInputModel] | None = None
    key: str
    label: str | None = None
    kind: enums.PortKind
    description: str | None = None
    identifier: str | None = None
    nullable: bool = False
    effects: list[EffectInputModel] | None = None
    default: Any | None = None
    children: list["PortInputModel"] | None = None
    choices: list[ChoiceInputModel] | None = None

    @model_validator(mode="after")
    def check_children_for_port(cls, self) -> Self:
        if self.kind == enums.PortKind.LIST and (self.children is None or len(self.children) != 1):
            raise ValueError("Port of kind LIST must have exactly on children")
        return self


class ArgPortInputModel(PortInputModel):
    default: Any | None = None
    widget: Optional["AssignWidgetInputModel"] = None
    requires: list[RequiresInputModel] | None = None

    @model_validator(mode="after")
    def check_children_for_port(cls, self) -> Self:
        if self.kind == enums.PortKind.LIST and (self.children is None or len(self.children) != 1):
            raise ValueError("Port of kind LIST must have exactly on children")
        return self


class ReturnPortInputModel(PortInputModel):
    widget: Optional["ReturnWidgetInputModel"] = None
    provides: list[ProvidesInputModel] | None = None

    @model_validator(mode="after")
    def check_children_for_port(cls, self) -> Self:
        if self.kind == enums.PortKind.LIST and (self.children is None or len(self.children) != 1):
            raise ValueError("Port of kind LIST must have exactly on children")
        return self


class PortGroupInputModel(BaseModel):
    key: str
    title: str | None
    description: str | None
    effects: list[EffectInputModel] | None
    ports: list[str]


class PortMatchInputModel(BaseModel):
    at: int | None = None
    key: str | None = None
    kind: enums.PortKind | None = None
    identifier: str | None = None
    nullable: bool | None = None
    children: Optional[list["PortMatchInputModel"]] = None


class ActionDependencyInputModel(BaseModel):
    key: str
    version: str | None = None
    description: str | None = None
    action_key: str | None = None
    app: str | None = None
    arg_matches: list[PortMatchInputModel] | None = None
    return_matches: list[PortMatchInputModel] | None = None
    protocols: list[str] | None = None
    force_arg_length: int | None = None
    force_return_length: int | None = None
    optional: bool = False
    allow_inactive: bool = True


class StateDependencyInputModel(BaseModel):
    key: str
    version: str | None = None
    description: str | None = None
    state_key: str | None = None
    app: str | None = None
    port_matches: list[PortMatchInputModel] | None = None
    optional: bool = False
    allow_inactive: bool = True


class AgentDependencyInputModel(BaseModel):
    key: str
    app: str | None = None
    version: str | None = None

    description: str | None = None
    optional: bool = False

    # Filters for selecting which instances of the agent are valid for this dependency
    action_demands: list[ActionDependencyInputModel] | None = None
    state_demands: list[StateDependencyInputModel] | None = None
    auto_resolvable: bool = False

    min_viable_instances: int | None = None
    max_viable_instances: int | None = None
    prefered_instances: int | None = None
    assign_policy: enums.AssignPolicy = enums.AssignPolicy.BALANCED


class DefinitionInputModel(BaseModel):
    """A definition for a implementation"""

    key: str
    version: str = "1"
    description: str = "No description provided"
    collections: list[str] = Field(default_factory=list)
    package: str | None = None
    name: str
    stateful: bool = False
    port_groups: list[PortGroupInputModel] = Field(default_factory=list)
    args: list[ArgPortInputModel] = Field(default_factory=list)
    returns: list[ReturnPortInputModel] = Field(default_factory=list)
    kind: enums.ActionKind
    tests: ActionDependencyInputModel | None = Field(default=None)
    is_test_for: list["str"] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    is_dev: bool = False
    logo: str | None = None

    @model_validator(mode="after")
    def check_dependencies(cls, self) -> Self:
        """Ensure that all dependencies in ports are valid."""
        all_arg_keys = [port.key for port in self.args]
        all_return_keys = [port.key for port in self.returns]

        for arg in self.args:
            for validator in arg.validators or []:
                if validator.dependencies:
                    for dep in validator.dependencies:
                        if dep not in all_arg_keys and dep not in all_return_keys:
                            raise ValueError(f"Validator {validator.label} in port {arg.key} has invalid dependency: {dep}")

            for effect in arg.effects or []:
                if effect.dependencies:
                    for dep in effect.dependencies:
                        if dep not in all_arg_keys and dep not in all_return_keys:
                            raise ValueError(f"Effect {effect.function} in port {arg.key} has invalid dependency: {dep}")

        return self


class DependencyInputModel(BaseModel):
    action: str
    hash: str
    reference: str | None
    binds: BindsInputModel | None
    optional: bool = False
    viable_instances: int | None


class ImplementationInputModel(BaseModel):
    definition: DefinitionInputModel
    dependencies: list[AgentDependencyInputModel] = Field(default_factory=list)
    interface: str
    params: dict[str, Any] | None = None
    instance_id: str | None = None
    dynamic: bool = False
    logo: str | None = None
    locks: list[str] | None = None
    extension: str | None = None


class StateDefinitionInputModel(BaseModel):
    ports: list[ReturnPortInputModel]
    name: str


class StateImplementationInputModel(BaseModel):
    interface: str
    definition: StateDefinitionInputModel


class LockDefinitionInputModel(BaseModel):
    key: str
    description: str | None = None


class LockImplementationInputModel(BaseModel):
    key: str
    definition: LockDefinitionInputModel


class InterfaceInputModel(BaseModel):
    key: str
    description: str | None = None
    default_widget: Optional[AssignWidgetInputModel] = None
    default_return_widget: Optional[ReturnWidgetInputModel] = None


class StructureInputModel(BaseModel):
    key: str
    description: str | None = None
    implements: list[str] = None
    descriptors: list[str] = None
    default_widget: Optional[AssignWidgetInputModel] = None
    default_return_widget: Optional[ReturnWidgetInputModel] = None
    qet_query: str | None = None
    describe_query: str | None = None


class StructurePackageInputModel(BaseModel):
    key: str
    version: str = "0.1.0"
    description: str | None = None
    interfaces: list[InterfaceInputModel] | None = None
    structures: list[StructureInputModel] | None = None
    descriptors: list[DescriptorSchemaInputModel] | None = None


AssignWidgetInputModel.model_rebuild()
