"""Peripheral Display running inside Home Assistant."""

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError

from custom_components.peripheral_display.const import DOMAIN

IMAGE = "image.living_room_art"
SIGNALS = "sensor.living_room_art_active_signals"


async def _setup(
    hass: HomeAssistant, selections: dict[str, Any], overrides: dict[str, Any] | None = None
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room art",
        options={"scene": "test_cottage", "selections": selections, "overrides": overrides or {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _signals(hass: HomeAssistant) -> dict[str, Any]:
    return dict(hass.states.get(SIGNALS).attributes)


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_config_flow_creates_display(hass: HomeAssistant) -> None:
    hass.states.async_set("sun.sun", "below_horizon")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Living room art", "scene": "test_cottage"}
    )
    assert result["step_id"] == "signals"
    # The scene asks for one input per bound signal; night is pre-filled.
    fields = {str(k): k for k in result["data_schema"].schema}
    assert set(fields) == {
        "weather", "night", "motion", "doorbell", "lights",
        "heating", "cinema", "bin", "offline", "alert",
    }
    assert fields["night"].description == {"suggested_value": ["sun.sun"]}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"night": ["sun.sun"], "motion": ["binary_sensor.garden"], "alert": ["octopus"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        "scene": "test_cottage",
        "selections": {"night": ["sun.sun"], "motion": ["binary_sensor.garden"], "alert": ["octopus"]},
        "overrides": {},
    }
    await hass.async_block_till_done()
    assert _signals(hass)["night"] is True
    assert hass.states.get(IMAGE) is not None


async def test_signals_follow_home_state(hass: HomeAssistant, hass_client) -> None:
    hass.states.async_set("weather.home", "lightning-rainy")
    hass.states.async_set("light.kitchen", "on")
    hass.states.async_set("light.hall", "off")
    hass.states.async_set("climate.house", "heat", {"hvac_action": "idle"})
    hass.states.async_set("media_player.cinema", "paused")
    hass.states.async_set("calendar.bins", "off", {"message": "Garden waste collection"})
    hass.states.async_set("binary_sensor.ping", "on")
    await _setup(
        hass,
        {
            "weather": "weather.home",
            "lights": ["light.kitchen", "light.hall"],
            "heating": ["climate.house"],
            "cinema": ["media_player.cinema"],
            "bin": "calendar.bins",
            "offline": ["binary_sensor.ping"],
        },
    )
    values = _signals(hass)
    assert values["weather"] == "storm"
    assert values["lights"] == 0.5
    assert values["heating"] == 0.0
    assert values["cinema"] is False
    # Calendars are read from their next event's message.
    assert values["bin"] == "garden"
    assert values["offline"] is False

    hass.states.async_set("climate.house", "heat", {"hvac_action": "heating"})
    hass.states.async_set("media_player.cinema", "playing")
    hass.states.async_set("binary_sensor.ping", "unavailable")
    hass.states.async_set("weather.home", "something-new")
    await hass.async_block_till_done()
    values = _signals(hass)
    assert values["heating"] == 1.0
    assert values["cinema"] is True
    assert values["offline"] is True
    # Unmapped conditions fall back to the signal default.
    assert values["weather"] == "clear"
    assert hass.states.get(SIGNALS).state.startswith("Weather: clear, Lights, Heating, Cinema")

    client = await hass_client()
    response = await client.get(f"/api/image_proxy/{IMAGE}")
    assert response.status == 200
    assert response.content_type == "image/svg+xml"
    svg = await response.text()
    for layer in ("layer-sun", "layer-light_left", "layer-smoke_heavy", "layer-cinema", "layer-offline"):
        assert layer in svg
    assert "layer-light_right" in svg  # 0.5 > 0.34
    assert "layer-light_gable" not in svg


async def test_motion_holds_after_clearing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("binary_sensor.garden", "off")
    hass.states.async_set("binary_sensor.drive", "off")
    await _setup(hass, {"motion": ["binary_sensor.garden", "binary_sensor.drive"]})
    assert _signals(hass)["motion"] is False

    hass.states.async_set("binary_sensor.drive", "on")
    await hass.async_block_till_done()
    assert _signals(hass)["motion"] is True
    await _advance(hass, freezer, 300)
    assert _signals(hass)["motion"] is True  # still detecting

    hass.states.async_set("binary_sensor.drive", "off")
    await hass.async_block_till_done()
    await _advance(hass, freezer, 115)
    assert _signals(hass)["motion"] is True  # within the 120 s hold
    await _advance(hass, freezer, 10)
    assert _signals(hass)["motion"] is False


async def test_doorbell_event_entity_is_momentary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("event.front_door", "2026-10-14T08:00:00+00:00")
    await _setup(hass, {"doorbell": ["event.front_door"]})
    # An existing last-press timestamp is not a new ring.
    assert _signals(hass)["doorbell"] is False

    hass.states.async_set("event.front_door", "2026-10-14T09:00:00+00:00")
    await hass.async_block_till_done()
    assert _signals(hass)["doorbell"] is True
    await _advance(hass, freezer, 61)
    assert _signals(hass)["doorbell"] is False


async def test_alert_matches_feed_keywords(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await _setup(hass, {"alert": ["Octopus", "peripheral display"]})
    hass.bus.async_fire("feedreader", {"title": "Weather update", "summary": "Rain later"})
    await hass.async_block_till_done()
    assert _signals(hass)["alert"] == ""

    hass.bus.async_fire(
        "feedreader",
        {"title": "Giant cephalopod spotted", "summary": "An OCTOPUS was seen", "link": "https://x"},
    )
    await hass.async_block_till_done()
    assert _signals(hass)["alert"] == "Giant cephalopod spotted"

    await _advance(hass, freezer, 6 * 3600 - 60)
    assert _signals(hass)["alert"] == "Giant cephalopod spotted"
    await hass.services.async_call(
        DOMAIN, "clear_signal", {"entity_id": IMAGE, "signal": "alert"}, blocking=True
    )
    assert _signals(hass)["alert"] == ""


async def test_set_signal_from_automation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("weather.home", "sunny")
    await _setup(hass, {"weather": "weather.home"})
    await hass.services.async_call(
        DOMAIN,
        "set_signal",
        {"entity_id": IMAGE, "signal": "weather", "value": "snow", "duration": {"seconds": 30}},
        blocking=True,
    )
    assert _signals(hass)["weather"] == "snow"
    await _advance(hass, freezer, 31)
    assert _signals(hass)["weather"] == "clear"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_signal", {"entity_id": IMAGE, "signal": "rainbow", "value": "on"}, blocking=True
        )


async def test_advanced_options_rebind_signal(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.boiler_power", "6000")
    entry = await _setup(hass, {})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"overrides": {"bin": {"source": "state", "entities": ["sensor.x"]}}}
    )
    assert result["errors"] == {"base": "invalid_binding"}

    hass.states.async_set("input_select.bin_week", "Blue week")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "overrides": {
                "heating": {"source": "numeric", "entity": "sensor.boiler_power", "max": 24000},
                "bin": {
                    "source": "template",
                    "template": "{{ 'recycling' if is_state('input_select.bin_week', 'Blue week') else 'general' }}",
                },
            }
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert _signals(hass)["heating"] == 0.25
    assert _signals(hass)["bin"] == "recycling"
    hass.states.async_set("input_select.bin_week", "Black week")
    await hass.async_block_till_done()
    assert _signals(hass)["bin"] == "general"
