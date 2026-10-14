"""Config and options flows for Peripheral Display."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    ObjectSelector,
    ObjectSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TemplateSelector,
    TextSelector,
    TextSelectorConfig,
)

from . import PeripheralDisplayConfigEntry, async_get_scenes, build_bindings
from .const import CONF_OVERRIDES, CONF_SCENE, CONF_SELECTIONS, DOMAIN
from .language import SELECTION_KEYS, Scene, SceneError


def _scene_selector(scenes: dict[str, Scene]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=s.id, label=s.name) for s in scenes.values()]
        )
    )


# One row per item (e.g. per bin) of a calendar-driven items signal.
_CALENDAR_ITEMS_SELECTOR = ObjectSelector(
    ObjectSelectorConfig(
        multiple=True,
        label_field="name",
        # Sub-field selectors must be given as configs: HA re-validates them.
        fields={
            "name": {"label": "Name", "required": True, "selector": {"text": {}}},
            "calendar": {
                "label": "Calendar",
                "required": True,
                "selector": {"entity": {"domain": "calendar"}},
            },
            "match": {
                "label": "Event title contains (empty: any event)",
                "selector": {"text": {"multiple": True}},
            },
            "color": {"label": "Colour", "selector": {"color_rgb": {}}},
        },
    )
)


def _signals_schema(
    hass: HomeAssistant, scene: Scene, selections: dict[str, Any]
) -> vol.Schema:
    """One field per signal, asking only for what its scene binding lacks."""
    fields: dict[Any, Any] = {}
    for name, signal in scene.signals.items():
        bind = signal.bind
        key = SELECTION_KEYS.get(bind["source"])
        if key is None:
            continue
        suggested = selections.get(name)
        if suggested is None and key == "entities":
            suggested = [e for e in bind.get("entities", []) if hass.states.get(e)]
        if key in ("entities", "entity"):
            selector: Any = EntitySelector(
                EntitySelectorConfig(
                    domain=bind.get("domains") or None, multiple=key == "entities"
                )
            )
        elif key == "keywords":
            selector = TextSelector(TextSelectorConfig(multiple=True))
        elif key == "items":
            selector = _CALENDAR_ITEMS_SELECTOR
        else:
            selector = TemplateSelector()
        fields[vol.Optional(name, description={"suggested_value": suggested})] = selector
    return vol.Schema(fields)


def _signals_help(scene: Scene) -> str:
    return "\n".join(
        f"- **{s.label}** (`{s.name}`, {s.type}): {s.description}"
        for s in scene.signals.values()
    )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in user_input.items() if v not in (None, "", [])}


class PeripheralDisplayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a display: name it, pick a scene, bind its signals."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._scenes: dict[str, Scene] = {}
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the display and choose a scene preset."""
        self._scenes = await async_get_scenes(self.hass)
        if not self._scenes:
            return self.async_abort(reason="no_scenes")
        if user_input is not None:
            self._data = user_input
            return await self.async_step_signals()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Peripheral Display"): str,
                    vol.Required(
                        CONF_SCENE, default=next(iter(self._scenes))
                    ): _scene_selector(self._scenes),
                }
            ),
        )

    async def async_step_signals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Bind the scene's signals to entities, keywords or templates."""
        scene = self._scenes[self._data[CONF_SCENE]]
        errors: dict[str, str] = {}
        placeholders = {"scene": scene.name, "signals": _signals_help(scene), "error": ""}
        if user_input is not None:
            options = {
                CONF_SCENE: scene.id,
                CONF_SELECTIONS: _clean(user_input),
                CONF_OVERRIDES: {},
            }
            try:
                build_bindings(scene, options)
            except SceneError as err:
                errors["base"] = "invalid_binding"
                placeholders["error"] = str(err)
            else:
                return self.async_create_entry(
                    title=self._data[CONF_NAME], data={}, options=options
                )
        return self.async_show_form(
            step_id="signals",
            data_schema=_signals_schema(self.hass, scene, user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: PeripheralDisplayConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return PeripheralDisplayOptionsFlow()


class PeripheralDisplayOptionsFlow(OptionsFlow):
    """Change scene, re-bind signals, or edit advanced bindings as YAML."""

    def __init__(self) -> None:
        """Initialise the flow."""
        self._scenes: dict[str, Scene] = {}
        self._scene_id = ""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose what to change."""
        return self.async_show_menu(step_id="init", menu_options=["scene", "advanced"])

    async def async_step_scene(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the scene preset."""
        self._scenes = await async_get_scenes(self.hass)
        if user_input is not None:
            self._scene_id = user_input[CONF_SCENE]
            return await self.async_step_signals()
        current = self.config_entry.options[CONF_SCENE]
        return self.async_show_form(
            step_id="scene",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCENE,
                        default=current if current in self._scenes else next(iter(self._scenes)),
                    ): _scene_selector(self._scenes)
                }
            ),
        )

    async def async_step_signals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Bind the scene's signals (selections carry over between scenes)."""
        scene = self._scenes[self._scene_id]
        errors: dict[str, str] = {}
        placeholders = {"scene": scene.name, "signals": _signals_help(scene), "error": ""}
        selections = self.config_entry.options.get(CONF_SELECTIONS, {})
        if user_input is not None:
            options = {
                **self.config_entry.options,
                CONF_SCENE: scene.id,
                CONF_SELECTIONS: _clean(user_input),
            }
            # Overrides for signals the new scene lacks would be invalid.
            options[CONF_OVERRIDES] = {
                k: v for k, v in options.get(CONF_OVERRIDES, {}).items() if k in scene.signals
            }
            try:
                build_bindings(scene, options)
            except SceneError as err:
                errors["base"] = "invalid_binding"
                placeholders["error"] = str(err)
            else:
                return self.async_create_entry(data=options)
            selections = user_input
        return self.async_show_form(
            step_id="signals",
            data_schema=_signals_schema(self.hass, scene, selections),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit full bindings as YAML, keyed by signal name."""
        options = self.config_entry.options
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        overrides = options.get(CONF_OVERRIDES, {})
        if user_input is not None:
            overrides = user_input.get(CONF_OVERRIDES) or {}
            new_options = {**options, CONF_OVERRIDES: overrides}
            scene = (await async_get_scenes(self.hass)).get(options[CONF_SCENE])
            try:
                if not isinstance(overrides, dict) or not all(
                    isinstance(v, dict) for v in overrides.values()
                ):
                    raise SceneError("expected a mapping of signal name to binding")
                if scene is None:
                    raise SceneError(f"scene '{options[CONF_SCENE]}' was not found")
                build_bindings(scene, new_options)
            except SceneError as err:
                errors["base"] = "invalid_binding"
                placeholders["error"] = str(err)
            else:
                return self.async_create_entry(data=new_options)
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_OVERRIDES, description={"suggested_value": overrides}
                    ): ObjectSelector()
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
