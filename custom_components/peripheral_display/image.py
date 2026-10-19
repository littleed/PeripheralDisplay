"""The rendered artwork, exposed as an image entity (SVG)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PeripheralDisplayConfigEntry
from .const import CONF_ASPECT_RATIO
from .entity import PeripheralDisplayEntity
from .language import parse_aspect


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PeripheralDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the artwork entity and its services."""
    async_add_entities([PeripheralDisplayImage(hass, entry)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "set_signal",
        {
            vol.Required("signal"): cv.string,
            vol.Required("value"): vol.Any(bool, int, float, str),
            vol.Optional("duration"): cv.positive_time_period,
        },
        "async_set_signal",
    )
    platform.async_register_entity_service(
        "clear_signal", {vol.Optional("signal"): cv.string}, "async_clear_signal"
    )


class PeripheralDisplayImage(PeripheralDisplayEntity, ImageEntity):
    """The scene rendered for the current signal values."""

    _attr_name = None
    _attr_content_type = "image/svg+xml"

    def __init__(self, hass: HomeAssistant, entry: PeripheralDisplayConfigEntry) -> None:
        """Initialise the image."""
        PeripheralDisplayEntity.__init__(self, entry, "display")
        ImageEntity.__init__(self, hass)
        # Validated by the config flow; entries from before it existed have none.
        self._aspect = parse_aspect(entry.options.get(CONF_ASPECT_RATIO))
        self._attr_extra_state_attributes = {"scene": self.runtime.scene.id}
        self._update()

    def _update(self) -> None:
        self._svg = self.runtime.scene.render(self.runtime.values, self._aspect).encode()
        self._attr_image_last_updated = dt_util.utcnow()

    async def async_image(self) -> bytes:
        """Return the SVG document."""
        return self._svg

    def _check(self, signal: str) -> None:
        if signal not in self.runtime.scene.signals:
            raise ServiceValidationError(
                f"Scene '{self.runtime.scene.id}' has no signal '{signal}'; "
                f"choose from {', '.join(self.runtime.scene.signals)}"
            )

    async def async_set_signal(
        self, signal: str, value: Any, duration: timedelta | None = None
    ) -> None:
        """Force a signal from an automation or script."""
        self._check(signal)
        self.runtime.async_set_override(signal, value, duration)

    async def async_clear_signal(self, signal: str | None = None) -> None:
        """Return signals to their bindings and clear held or latched triggers."""
        if signal:
            self._check(signal)
        self.runtime.async_clear(signal)
