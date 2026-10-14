"""Shared base for Peripheral Display entities."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from . import PeripheralDisplayConfigEntry
from .const import DOMAIN


class PeripheralDisplayEntity(Entity):
    """An entity that updates whenever the display's signals change."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: PeripheralDisplayConfigEntry, key: str) -> None:
        """Initialise from the config entry's runtime."""
        self.runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Peripheral Display",
            model=self.runtime.scene.name,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Follow signal changes."""
        self.async_on_remove(self.runtime.async_add_listener(self._handle_change))
        self._update()

    def _update(self) -> None:
        """Refresh cached values from the runtime."""

    @callback
    def _handle_change(self) -> None:
        self._update()
        self.async_write_ha_state()
