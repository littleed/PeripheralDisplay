"""A sensor listing which signals are active, with every value as attributes."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PeripheralDisplayConfigEntry
from .entity import PeripheralDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PeripheralDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the signals sensor."""
    async_add_entities([SignalsSensor(entry)])


class SignalsSensor(PeripheralDisplayEntity, SensorEntity):
    """Active signals, e.g. ``Weather: rain, Night, Lights``."""

    _attr_translation_key = "signals"

    def __init__(self, entry: PeripheralDisplayConfigEntry) -> None:
        """Initialise the sensor."""
        super().__init__(entry, "signals")
        self._update()

    def _update(self) -> None:
        values = self.runtime.values
        active = self.runtime.scene.describe(values)
        self._attr_native_value = (", ".join(active) or "None")[:255]
        self._attr_extra_state_attributes = dict(values)
