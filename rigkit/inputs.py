"""GraphQL input types for a recorded rig state, mirrored off the pydantic models."""

import strawberry
from strawberry.experimental import pydantic

from kanne_server import scalars as kanne_scalars
from rigkit import models

ClampMode = strawberry.enum(models.ClampMode, description="Which quantity the amplifier controlled: the potential (voltage clamp), the current (current clamp), or nothing at all (I=0)")


@pydantic.input(models.SettingModel, description="One named device setting with exactly one value slot filled: a quantity when the setting carries a unit, else a number, text or flag. A setting holding two values is two settings")
class SettingInput:
    name: str = strawberry.field(description="The setting's name on the device, e.g. 'lowpass', 'gain', 'bridge-balance'")
    quantity: kanne_scalars.GenericQuantity | None = strawberry.field(default=None, description="The value as a unit-carrying quantity, e.g. '10 kHz', '2 pF'")
    number: float | None = strawberry.field(default=None, description="The value as a bare number, for a unitless setting such as a gain")
    text: str | None = strawberry.field(default=None, description="The value as text, e.g. a named filter 'Bessel'")
    flag: bool | None = strawberry.field(default=None, description="The value as a flag, e.g. whole-cell compensation enabled")


@pydantic.input(models.DeviceStateModel, description="One hardware device's recorded state: its identity in the setup plus its settings at this coordinate")
class DeviceStateInput:
    label: str = strawberry.field(description="The device's identity in the setup, e.g. 'multiclamp-700b-1'")
    kind: str | None = strawberry.field(default=None, description="A free-form device kind, e.g. 'amplifier', 'digitizer', 'probe'")
    settings: list[SettingInput] = strawberry.field(default_factory=list, description="The device's named settings, one value slot each")


@pydantic.input(
    models.RigStateModel,
    description="The recorded rig state: the hardware truth at the moment of acquisition. The common facts (clamp mode, holding level, access and membrane measurements, temperature) are first-class and quantity-typed; everything else is per-device named settings",
)
class RigStateInput:
    mode: ClampMode | None = strawberry.field(default=None, description="Which quantity was clamped. It decides which holding level may be stated")
    holding_potential: kanne_scalars.ElectricPotential | None = strawberry.field(default=None, description="(VOLTAGE_CLAMP) The potential the cell was held at, e.g. '-70 mV'")
    holding_current: kanne_scalars.ElectricCurrent | None = strawberry.field(default=None, description="(CURRENT_CLAMP) The current the cell was held at, e.g. '-50 pA'")
    series_resistance: kanne_scalars.ElectricalResistance | None = strawberry.field(default=None, description="The series (access) resistance the amplifier measured, e.g. '12 Mohm'")
    membrane_capacitance: kanne_scalars.Capacitance | None = strawberry.field(default=None, description="The whole-cell membrane capacitance, e.g. '25 pF'")
    temperature: kanne_scalars.Temperature | None = strawberry.field(default=None, description="The bath temperature, e.g. '32 degC'")
    devices: list[DeviceStateInput] = strawberry.field(default_factory=list, description="The recorded per-device states")
