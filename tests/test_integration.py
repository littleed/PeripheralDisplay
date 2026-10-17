"""Peripheral Display running inside Home Assistant."""

from datetime import date, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    setup_test_component_platform,
)

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.peripheral_display.const import DOMAIN

IMAGE = "image.living_room_art"
# A bin as the frontend's list editor submits it.
BIN = {"name": "Recycling", "calendar": "calendar.bins", "match": ["Blue-lidded"], "color": [44, 107, 208]}
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
        "weather", "night", "motion", "doorbell", "side_door", "lights",
        "heating", "cinema", "bins", "offline", "season", "alert",
    }
    assert fields["night"].description == {"suggested_value": ["sun.sun"]}
    # The holiday rule is shown so it can be edited.
    assert "d.month == 12" in fields["season"].description["suggested_value"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "night": ["sun.sun"],
            "motion": ["binary_sensor.garden"],
            "alert": ["octopus"],
            "bins": [BIN],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        "scene": "test_cottage",
        "selections": {
            "night": ["sun.sun"],
            "motion": ["binary_sensor.garden"],
            "alert": ["octopus"],
            "bins": [BIN],
        },
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
    hass.states.async_set("binary_sensor.ping", "on")
    await _setup(
        hass,
        {
            "weather": "weather.home",
            "lights": ["light.kitchen", "light.hall"],
            "heating": ["climate.house"],
            "cinema": ["media_player.cinema"],
            "offline": ["binary_sensor.ping"],
        },
    )
    values = _signals(hass)
    assert values["weather"] == "storm"
    assert values["lights"] == 0.5
    assert values["heating"] == 0.0
    assert values["cinema"] is False
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


async def test_doorbell_from_ring_last_ding_timestamp(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Ring reports rings as a timestamp sensor that updates after a delay."""
    ring = "sensor.front_door_last_ding"
    attrs = {"device_class": "timestamp", "friendly_name": "Front Door Last ding"}
    hass.states.async_set(ring, (dt_util.utcnow() - timedelta(hours=3)).isoformat(), attrs)
    entry = await _setup(hass, {"doorbell": [ring]})
    # An old ring present at start-up does not count.
    assert _signals(hass)["doorbell"] is False

    # Ring's poll reports a ring from 40 s ago; the hold runs from when HA saw it.
    hass.states.async_set(ring, (dt_util.utcnow() - timedelta(seconds=40)).isoformat(), attrs)
    await hass.async_block_till_done()
    assert _signals(hass)["doorbell"] is True
    await _advance(hass, freezer, 50)
    assert _signals(hass)["doorbell"] is True
    await _advance(hass, freezer, 15)
    assert _signals(hass)["doorbell"] is False

    # clear_signal dismisses a ring even though its timestamp is recent.
    hass.states.async_set(ring, dt_util.utcnow().isoformat(), attrs)
    await hass.async_block_till_done()
    assert _signals(hass)["doorbell"] is True
    await hass.services.async_call(
        DOMAIN, "clear_signal", {"entity_id": IMAGE, "signal": "doorbell"}, blocking=True
    )
    assert _signals(hass)["doorbell"] is False

    # A malformed time (e.g. set through the REST API) is not fatal: the change
    # still counts as activity and the display keeps updating.
    await _advance(hass, freezer, 1)
    hass.states.async_set(ring, "2026-13-45T10:00:00", attrs)
    await hass.async_block_till_done()
    assert _signals(hass)["doorbell"] is True
    await _advance(hass, freezer, 61)
    assert _signals(hass)["doorbell"] is False
    assert not [r for r in caplog.records if r.levelname == "ERROR"]

    # A ring during a restart still shows afterwards, from its timestamp.
    await _advance(hass, freezer, 5)
    hass.states.async_set(ring, (dt_util.utcnow() - timedelta(seconds=10)).isoformat(), attrs)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _signals(hass)["doorbell"] is True


async def test_doorbell_event_entity_missing_at_startup(hass: HomeAssistant) -> None:
    """Issue #1: a chosen event entity may not exist yet when HA starts."""
    entry = await _setup(hass, {"doorbell": ["event.front_door_ding"]})
    assert entry.state is ConfigEntryState.LOADED
    assert _signals(hass)["doorbell"] is False

    # Ring loads later; its first state is not a ring, the next one is.
    hass.states.async_set("event.front_door_ding", "2026-10-14T08:00:00+00:00")
    await hass.async_block_till_done()
    assert _signals(hass)["doorbell"] is False
    hass.states.async_set("event.front_door_ding", dt_util.utcnow().isoformat())
    await hass.async_block_till_done()
    assert _signals(hass)["doorbell"] is True


class BinCalendar(CalendarEntity):
    """A calendar whose events can be changed by the test."""

    _attr_name = "Bins"

    def __init__(self) -> None:
        """Start empty."""
        self.items: list[CalendarEvent] = []

    @property
    def event(self) -> CalendarEvent | None:
        """The next event."""
        return min(self.items, key=lambda e: e.start_datetime_local, default=None)

    async def async_get_events(self, hass, start_date, end_date) -> list[CalendarEvent]:
        """Events overlapping the window."""
        return [
            e
            for e in self.items
            if e.start_datetime_local < end_date and e.end_datetime_local > start_date
        ]


def _all_day(day: str, summary: str) -> CalendarEvent:
    start = date.fromisoformat(day)
    return CalendarEvent(start=start, end=start + timedelta(days=1), summary=summary)


async def test_bins_from_calendars(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_client_no_auth
) -> None:
    freezer.move_to("2026-10-14 12:00:00+00:00")  # a Wednesday
    council, garden = BinCalendar(), BinCalendar()
    council.items = [
        _all_day("2026-10-15", "Dentist"),
        _all_day("2026-10-16", "Blue-lidded Recycling Bin"),
        _all_day("2026-10-16", "Glass, Metals, Plastics and Cartons"),
        _all_day("2026-10-23", "General Waste"),
    ]
    garden._attr_name = "Garden bin"
    garden.items = [_all_day("2026-10-20", "Collection")]
    setup_test_component_platform(hass, "calendar", [council, garden])
    assert await async_setup_component(hass, "calendar", {"calendar": {"platform": "test"}})
    await hass.async_block_till_done()

    bins = [
        {"name": "Recycling", "calendar": "calendar.bins", "match": ["blue-lidded"], "color": [44, 107, 208]},
        {"name": "General", "calendar": "calendar.bins", "match": ["General Waste"], "color": [43, 43, 46]},
        # Its own calendar, so any event counts.
        {"name": "Food & Garden", "calendar": "calendar.garden_bin", "color": [122, 78, 45]},
        {"name": "Glass & Plastics", "calendar": "calendar.bins", "match": ["glass"], "color": [62, 142, 58]},
    ]
    await _setup(hass, {"bins": bins})
    # Two bins on Friday plus the garden bin next Tuesday; General (23rd) is
    # beyond today + 6 days. Ordered by date, then by the list above.
    assert [(b["name"], b["day"], b["color"]) for b in _signals(hass)["bins"]] == [
        ("Recycling", "FRI", "#2c6bd0"),
        ("Glass & Plastics", "FRI", "#3e8e3a"),
        ("Food & Garden", "TUE", "#7a4e2d"),
    ]
    # Fetched like the dashboard card does, via the image's token URL.
    client = await hass_client_no_auth()
    picture = hass.states.get(IMAGE).attributes["entity_picture"]
    svg = await (await client.get(picture)).text()
    assert svg.count('class="tag">FRI<') == 2 and svg.count('class="tag">TUE<') == 1

    # On collection day, today's bins still show, next week's do not.
    await _advance(hass, freezer, 2 * 24 * 3600)  # Friday 16th
    assert [b["name"] for b in _signals(hass)["bins"]] == [
        "Recycling", "Glass & Plastics", "Food & Garden",
    ]
    # Saturday: the 23rd is now within the week.
    await _advance(hass, freezer, 24 * 3600)
    assert [(b["name"], b["day"]) for b in _signals(hass)["bins"]] == [
        ("Food & Garden", "TUE"),
        ("General", "FRI"),
    ]


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


@pytest.mark.parametrize(
    ("when", "season"),
    [
        ("2026-10-23 23:59:00", "none"),
        ("2026-10-24 00:01:00", "halloween"),
        ("2026-10-31 20:00:00", "halloween"),
        ("2026-11-07 23:59:00", "halloween"),
        ("2026-11-08 00:01:00", "none"),
        ("2026-12-01 00:01:00", "christmas"),
        ("2026-12-31 23:59:00", "christmas"),
        ("2027-01-01 00:01:00", "none"),
    ],
)
async def test_season_follows_the_date(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: str, season: str
) -> None:
    freezer.move_to(dt_util.as_utc(dt_util.parse_datetime(when).replace(tzinfo=dt_util.get_default_time_zone())))
    await _setup(hass, {})
    assert _signals(hass)["season"] == season


async def test_season_changes_while_running(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    tz = dt_util.get_default_time_zone()
    freezer.move_to(dt_util.as_utc(dt_util.parse_datetime("2026-11-30 23:58:00").replace(tzinfo=tz)))
    await _setup(hass, {})
    assert _signals(hass)["season"] == "none"
    await _advance(hass, freezer, 180)
    assert _signals(hass)["season"] == "christmas"


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
        result["flow_id"], {"overrides": {"bins": {"source": "state", "entities": ["sensor.x"]}}}
    )
    assert result["errors"] == {"base": "invalid_binding"}

    hass.states.async_set("input_boolean.bedtime", "on")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "overrides": {
                "heating": {"source": "numeric", "entity": "sensor.boiler_power", "max": 24000},
                "night": {
                    "source": "template",
                    "template": "{{ is_state('input_boolean.bedtime', 'on') }}",
                },
            }
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert _signals(hass)["heating"] == 0.25
    assert _signals(hass)["night"] is True
    hass.states.async_set("input_boolean.bedtime", "off")
    await hass.async_block_till_done()
    assert _signals(hass)["night"] is False
