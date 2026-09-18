"""Pydantic models of a recorded rig state.

One model family serves input and output alike: a state is a *snapshot*, so nothing is
generated server-side and the structure a client sends is exactly the structure every
reader gets back.

The shape is deliberately two-layered, as mikro's ``optikit`` is. The facts nearly every
intracellular recording has -- which quantity was clamped and at what level, what the
amplifier measured of the access and the membrane, the bath temperature -- are first-class
and quantity-typed, so a client can ask "what was the series resistance" without knowing
whose amplifier recorded it. What is left is honest heterogeneity: hardware exposes
arbitrary named settings, so devices carry a list of :class:`SettingModel`, each holding
exactly one value slot (a quantity when the setting has a unit, a number/text/flag when it
does not). That keeps the state composable without inventing a hardware ontology a real rig
would immediately outgrow -- an extracellular probe, a digitizer and a perfusion pump are
all just devices with settings.

Anchored like any spoke: at ``{}`` it is the state the whole dataset was recorded under, at
``{"c": 1}`` the state of the headstage behind channel 1, at ``{"sweep": 12}`` the state
during one sweep -- which is how a series resistance that drifted is recorded without a
second mechanism.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from kanne_server import quantities


class ClampMode(str, Enum):
    """Which quantity the amplifier controlled, and therefore which one was measured."""

    VOLTAGE_CLAMP = "VOLTAGE_CLAMP"
    CURRENT_CLAMP = "CURRENT_CLAMP"
    ZERO_CURRENT = "ZERO_CURRENT"


class SettingModel(BaseModel):
    """One named device setting, with exactly one value slot filled.

    A quantity when the setting carries a unit ('10 kHz', '2 pF'), a bare number, a text, or
    a flag when it does not. One slot, enforced: a setting holding two values is two settings.
    """

    name: str
    quantity: quantities.GenericQuantity | None = None
    number: float | None = None
    text: str | None = None
    flag: bool | None = None

    @model_validator(mode="after")
    def _one_value_slot(self) -> "SettingModel":
        filled = [slot for slot in (self.quantity, self.number, self.text, self.flag) if slot is not None]
        if len(filled) > 1:
            raise ValueError(f"Setting {self.name!r} fills more than one value slot; a setting holds exactly one value, so record two settings instead.")
        return self


class DeviceStateModel(BaseModel):
    """One hardware device's recorded state: identity plus its settings."""

    label: str = Field(description="The device's identity in the setup, e.g. 'multiclamp-700b-1'")
    kind: str | None = Field(None, description="A free-form device kind, e.g. 'amplifier', 'digitizer', 'probe'")
    settings: list[SettingModel] = Field(default_factory=list)


class RigStateModel(BaseModel):
    """The recorded rig state pinned to a coordinate anchor."""

    mode: ClampMode | None = None
    holding_potential: quantities.ElectricPotential | None = None
    holding_current: quantities.ElectricCurrent | None = None
    series_resistance: quantities.ElectricalResistance | None = None
    membrane_capacitance: quantities.Capacitance | None = None
    temperature: quantities.Temperature | None = None
    devices: list[DeviceStateModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _holding_level_matches_mode(self) -> "RigStateModel":
        # The holding level is the level of whatever was *clamped*. Stating the other one is
        # not extra information, it is a contradiction of `mode`.
        if self.mode == ClampMode.VOLTAGE_CLAMP and self.holding_current is not None:
            raise ValueError("A voltage clamp holds a potential, so `holdingCurrent` contradicts `mode: VOLTAGE_CLAMP`. State `holdingPotential`, or record the mode as CURRENT_CLAMP.")
        if self.mode == ClampMode.CURRENT_CLAMP and self.holding_potential is not None:
            raise ValueError("A current clamp holds a current, so `holdingPotential` contradicts `mode: CURRENT_CLAMP`. State `holdingCurrent`, or record the mode as VOLTAGE_CLAMP.")
        if self.mode == ClampMode.ZERO_CURRENT and (self.holding_current is not None or self.holding_potential is not None):
            raise ValueError("`mode: ZERO_CURRENT` (I=0) holds nothing, so it takes neither `holdingCurrent` nor `holdingPotential`.")
        return self
