"""GraphQL output types for a recorded rig state, mirrored off the same pydantic models."""

import strawberry
from strawberry.experimental import pydantic

from kanne_server import scalars as kanne_scalars
from rigkit import models
from rigkit.inputs import ClampMode


@pydantic.type(models.SettingModel, description="One named device setting, exactly one value slot filled")
class Setting:
    name: str = strawberry.field(description="The setting's name on the device")
    quantity: kanne_scalars.GenericQuantity | None = strawberry.field(default=None, description="The value as a unit-carrying quantity, when the setting has one")
    number: float | None = strawberry.field(default=None, description="The value as a bare number")
    text: str | None = strawberry.field(default=None, description="The value as text")
    flag: bool | None = strawberry.field(default=None, description="The value as a flag")


@pydantic.type(models.DeviceStateModel, description="One hardware device's recorded state")
class DeviceState:
    label: str = strawberry.field(description="The device's identity in the setup")
    kind: str | None = strawberry.field(default=None, description="A free-form device kind")
    settings: list[Setting] = strawberry.field(default_factory=list, description="The device's named settings")


@pydantic.type(models.RigStateModel, description="The recorded rig state: the hardware truth at the moment of acquisition")
class RigStateGraph:
    mode: ClampMode | None = strawberry.field(default=None, description="Which quantity was clamped")
    holding_potential: kanne_scalars.ElectricPotential | None = strawberry.field(default=None, description="The potential the cell was held at, under voltage clamp")
    holding_current: kanne_scalars.ElectricCurrent | None = strawberry.field(default=None, description="The current the cell was held at, under current clamp")
    series_resistance: kanne_scalars.ElectricalResistance | None = strawberry.field(default=None, description="The series (access) resistance the amplifier measured")
    membrane_capacitance: kanne_scalars.Capacitance | None = strawberry.field(default=None, description="The whole-cell membrane capacitance")
    temperature: kanne_scalars.Temperature | None = strawberry.field(default=None, description="The bath temperature")
    devices: list[DeviceState] = strawberry.field(default_factory=list, description="The recorded per-device states")
