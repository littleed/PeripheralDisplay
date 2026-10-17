"""Peripheral Display: a generative artwork driven by your home's state."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import (
    BUILTIN_SCENES_DIR,
    CONF_OVERRIDES,
    CONF_SCENE,
    CONF_SELECTIONS,
    USER_SCENES_DIR,
)
from .language import Scene, SceneError, load_scenes, resolve_binding, selection_fits
from .runtime import DisplayRuntime

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.IMAGE, Platform.SENSOR]

type PeripheralDisplayConfigEntry = ConfigEntry[DisplayRuntime]


async def async_get_scenes(hass: HomeAssistant) -> dict[str, Scene]:
    """Load built-in scenes plus any in <config>/peripheral_display/scenes."""
    scenes, errors = await hass.async_add_executor_job(
        load_scenes, BUILTIN_SCENES_DIR, Path(hass.config.path(USER_SCENES_DIR))
    )
    for error in errors:
        _LOGGER.warning("Skipping invalid scene %s", error)
    return scenes


def build_bindings(scene: Scene, options: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolve every bound signal of a scene; raises SceneError when invalid."""
    selections = options.get(CONF_SELECTIONS, {})
    overrides = options.get(CONF_OVERRIDES, {})
    bindings = {}
    for name, signal in scene.signals.items():
        selection = selections.get(name)
        if selection not in (None, "", []) and not selection_fits(signal, selection):
            _LOGGER.warning(
                "Ignoring the saved choice for %s (%r), which does not suit scene %s;"
                " choose it again under Configure",
                name, selection, scene.id,
            )
        binding = resolve_binding(signal, selection, overrides.get(name))
        if binding:
            bindings[name] = binding
    unknown = set(overrides) - set(scene.signals)
    if unknown:
        raise SceneError(f"{scene.id} has no signals named {sorted(unknown)}")
    return bindings


async def async_setup_entry(
    hass: HomeAssistant, entry: PeripheralDisplayConfigEntry
) -> bool:
    """Set up a display from a config entry."""
    scene = (await async_get_scenes(hass)).get(entry.options[CONF_SCENE])
    if scene is None:
        raise ConfigEntryError(f"Scene '{entry.options[CONF_SCENE]}' was not found")
    try:
        bindings = build_bindings(scene, entry.options)
    except SceneError as err:
        raise ConfigEntryError(str(err)) from err

    runtime = DisplayRuntime(hass, scene, bindings)
    runtime.async_start()
    entry.async_on_unload(runtime.async_stop)
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: PeripheralDisplayConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
