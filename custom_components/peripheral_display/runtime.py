"""Turns Home Assistant states and events into scene signal values."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    TrackTemplate,
    TrackTemplateResult,
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_template_result,
    async_track_time_interval,
)
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util

from .language import Scene, Signal

_LOGGER = logging.getLogger(__name__)
_INVALID = (STATE_UNAVAILABLE, STATE_UNKNOWN)
DEFAULT_MOMENTARY_HOLD = 30.0
DEFAULT_CALENDAR_DAYS = 7
CALENDAR_REFRESH = timedelta(minutes=15)
_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _read(binding: dict[str, Any], state: State | None) -> Any:
    """Return the watched value (state or attribute) of an entity, or None."""
    if state is None or state.state in _INVALID:
        return None
    if attribute := binding.get("attribute"):
        return state.attributes.get(attribute)
    return state.state


def _matches(binding: dict[str, Any], state: State | None) -> bool:
    """Whether an entity is in one of the binding's ``match`` states."""
    match = [m.lower() for m in binding.get("match", ["on"])]
    if state is not None and state.state in _INVALID:
        return state.state in match
    value = _read(binding, state)
    return value is not None and str(value).lower() in match


def _is_timestamp(entity_id: str, state: State | None) -> bool:
    """Event entities and timestamp sensors (e.g. Ring's "Last ding")."""
    return entity_id.startswith("event.") or (
        state is not None and state.attributes.get("device_class") == "timestamp"
    )


def _momentary(binding: dict[str, Any], entity_id: str, state: State | None) -> bool:
    """Timestamp entities (and ``@changed``) trigger on every new state."""
    return _is_timestamp(entity_id, state) or "@changed" in binding.get("match", [])


def _fired_at(entity_id: str, state: State | None) -> datetime | None:
    """The time a timestamp entity says it last fired."""
    if not _is_timestamp(entity_id, state) or state.state in _INVALID:
        return None
    when = dt_util.parse_datetime(state.state)
    return dt_util.as_utc(when) if when else None


def _map_option(binding: dict[str, Any], value: str) -> str | None:
    """The option whose keyword matches; the longest keyword wins ties."""
    value = value.lower()
    contains = binding.get("compare", "exact") == "contains"
    best: tuple[int, int, str] | None = None
    for index, (option, patterns) in enumerate(binding["map"].items()):
        for pattern in patterns:
            pattern = pattern.lower()
            if (pattern in value) if contains else (pattern == value):
                candidate = (len(pattern), -index, option)
                best = max(best, candidate) if best else candidate
    return best[2] if best else None


def _event_date(event: dict[str, Any]) -> date | None:
    """The local date an event (from calendar.get_events) starts."""
    start = str(event.get("start", ""))
    if when := dt_util.parse_datetime(start):
        return dt_util.as_local(when).date() if when.tzinfo else when.date()
    try:
        return date.fromisoformat(start[:10])
    except ValueError:
        return None


def _due_items(
    binding: dict[str, Any], events: dict[str, list[dict[str, Any]] | None], today: date
) -> list[dict[str, str]]:
    """Items with a matching calendar event from today for ``days`` days."""
    end = today + timedelta(days=binding.get("days", DEFAULT_CALENDAR_DAYS))
    due = []
    for index, item in enumerate(binding["items"]):
        keywords = [k.lower() for k in item["match"]]
        dates = [
            max(day, today)  # an event that began earlier is still on today
            for event in events.get(item["calendar"]) or []
            if (day := _event_date(event)) is not None
            and day < end
            and (
                not keywords
                or any(k in str(event.get("summary", "")).lower() for k in keywords)
            )
        ]
        if dates:
            day = min(dates)
            due.append((day, index, item))
    return [
        {
            "name": item["name"],
            "color": item["color"],
            "day": _WEEKDAYS[day.weekday()],
            "date": day.isoformat(),
        }
        for day, _, item in sorted(due, key=lambda d: d[:2])
    ]


class DisplayRuntime:
    """Live signal values for one configured display."""

    def __init__(
        self, hass: HomeAssistant, scene: Scene, bindings: dict[str, dict[str, Any]]
    ) -> None:
        """Initialise with a scene and the active (bound) bindings."""
        self.hass = hass
        self.scene = scene
        self.bindings = bindings
        self.values: dict[str, Any] = scene.defaults()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._overrides: dict[str, tuple[Any, datetime | None]] = {}
        self._last_active: dict[tuple[str, str], datetime] = {}
        self._events: dict[str, tuple[datetime, str]] = {}
        self._templates: dict[str, Any] = {}
        # Events from today onwards, per calendar entity.
        self._calendar_events: dict[str, list[dict[str, Any]] | None] = {}
        self._calendar_days: dict[str, int] = {}
        self._cleared: dict[str, datetime] = {}
        self._timer: CALLBACK_TYPE | None = None
        self._next_expiry: datetime | None = None

    @callback
    def async_start(self) -> None:
        """Subscribe to everything the bindings watch, then compute values."""
        watched: set[str] = set()
        for name, binding in self.bindings.items():
            source = binding["source"]
            if source == "state":
                watched.update(binding["entities"])
            elif source in ("numeric", "map"):
                watched.add(binding["entity"])
            elif source == "calendar":
                days = binding.get("days", DEFAULT_CALENDAR_DAYS)
                for item in binding["items"]:
                    calendar = item["calendar"]
                    self._calendar_days[calendar] = max(
                        days, self._calendar_days.get(calendar, 0)
                    )
            elif source == "event":
                self._unsubs.append(
                    self.hass.bus.async_listen(
                        binding["event_type"],
                        callback(lambda event, name=name: self._on_event(name, event)),
                    )
                )
            elif source == "template":
                info = async_track_template_result(
                    self.hass,
                    [TrackTemplate(Template(binding["template"], self.hass), None)],
                    callback(
                        lambda _e, updates, name=name: self._on_template(name, updates)
                    ),
                )
                info.async_refresh()
                self._unsubs.append(info.async_remove)
        if self._calendar_days:
            watched.update(self._calendar_days)
            for calendar in self._calendar_days:
                self._refresh_calendar(calendar)
            self._unsubs.append(
                async_track_time_interval(
                    self.hass,
                    callback(lambda _now: [self._refresh_calendar(c) for c in self._calendar_days]),
                    CALENDAR_REFRESH,
                )
            )
        if watched:
            self._unsubs.append(
                async_track_state_change_event(self.hass, list(watched), self._on_state)
            )
        self._recompute()

    @callback
    def async_stop(self) -> None:
        """Remove all subscriptions."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._timer:
            self._timer()
            self._timer = None

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call ``listener`` whenever signal values change."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_set_override(
        self, name: str, value: Any, duration: timedelta | None
    ) -> None:
        """Force a signal to a value, optionally for a limited time."""
        until = dt_util.utcnow() + duration if duration else None
        self._overrides[name] = (self.scene.signals[name].coerce(value), until)
        self._recompute()

    @callback
    def async_clear(self, name: str | None) -> None:
        """Drop overrides, holds and latched events for one or all signals."""
        names = [name] if name else list(self.scene.signals)
        for sig in names:
            self._overrides.pop(sig, None)
            self._events.pop(sig, None)
            self._cleared[sig] = dt_util.utcnow()
            for key in [k for k in self._last_active if k[0] == sig]:
                del self._last_active[key]
        self._recompute()

    # -- inputs ---------------------------------------------------------------

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        now = dt_util.utcnow()
        if entity_id in self._calendar_days:
            self._refresh_calendar(entity_id)
        for name, binding in self.bindings.items():
            if binding["source"] != "state" or entity_id not in binding["entities"]:
                continue
            if _momentary(binding, entity_id, new):
                if (
                    old is not None
                    and new is not None
                    and old.state not in _INVALID
                    and new.state not in _INVALID
                    and old.state != new.state
                ):
                    self._last_active[(name, entity_id)] = now
            elif _matches(binding, old) and not _matches(binding, new):
                # Starts the hold period from the moment it stopped matching.
                self._last_active[(name, entity_id)] = now
        self._recompute()

    @callback
    def _on_event(self, name: str, event: Event) -> None:
        binding = self.bindings[name]
        data = event.data
        if any(data.get(k) != v for k, v in binding.get("data", {}).items()):
            return
        fields = binding.get("fields") or list(data)
        haystack = " ".join(
            str(data[f]) for f in fields if isinstance(data.get(f), str)
        ).lower()
        keywords = binding["keywords"]
        hit = next(
            (k for k in keywords if k == "*" or k.lower() in haystack), None
        )
        if hit is None:
            return
        text = data.get(binding.get("text_field", ""))
        text = text if isinstance(text, str) and text else hit
        self._events[name] = (dt_util.utcnow(), text)
        self._recompute()

    @callback
    def _on_template(self, name: str, updates: list[TrackTemplateResult]) -> None:
        result = updates.pop().result
        self._templates[name] = None if isinstance(result, Exception) else result
        self._recompute()

    @callback
    def _refresh_calendar(self, entity_id: str) -> None:
        self.hass.async_create_task(
            self._async_refresh_calendar(entity_id), eager_start=True
        )

    async def _async_refresh_calendar(self, entity_id: str) -> None:
        """Fetch a calendar's events from the start of today."""
        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": entity_id,
                    "start_date_time": dt_util.start_of_local_day(),
                    "duration": {"days": self._calendar_days[entity_id] + 1},
                },
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            # The calendar may not be loaded yet; its first state change retries.
            _LOGGER.debug("Could not read %s: %s", entity_id, err)
            events = None
        else:
            events = (response or {}).get(entity_id, {}).get("events", [])
        self._calendar_events[entity_id] = events
        self._recompute()

    @callback
    def _on_timer(self, _now: datetime) -> None:
        self._timer = None
        self._recompute()

    # -- evaluation -----------------------------------------------------------

    def _expires(self, when: datetime) -> None:
        if self._next_expiry is None or when < self._next_expiry:
            self._next_expiry = when

    def _held(self, last: datetime | None, hold: float, now: datetime) -> bool:
        if last is None or not hold:
            return False
        until = last + timedelta(seconds=hold)
        if until <= now:
            return False
        self._expires(until)
        return True

    def _compute(self, sig: Signal, binding: dict[str, Any], now: datetime) -> Any:
        """Return the raw value of a bound signal (None means default)."""
        source = binding["source"]
        if source == "state":
            active = []
            for entity_id in binding["entities"]:
                state = self.hass.states.get(entity_id)
                momentary = _momentary(binding, entity_id, state)
                hold = binding.get("hold") or (DEFAULT_MOMENTARY_HOLD if momentary else 0)
                # Triggered when HA saw the change or when the entity says it
                # fired, whichever is later, and not before a clear_signal.
                cleared = self._cleared.get(sig.name)
                triggers = [
                    t
                    for t in (
                        self._last_active.get((sig.name, entity_id)),
                        _fired_at(entity_id, state),
                    )
                    if t and (cleared is None or t > cleared)
                ]
                on = (not momentary and _matches(binding, state)) or self._held(
                    max(triggers, default=None), hold, now
                )
                if on:
                    active.append(
                        state.name if state is not None else entity_id
                    )
            count, total = len(active), len(binding["entities"])
            result = count == total if binding.get("mode") == "all" else count > 0
            if binding.get("invert"):
                result, count = not result, total - count
            if sig.type == "level":
                return count / total
            if sig.type == "text":
                return (", ".join(active) or sig.label) if result else ""
            return result
        if source == "numeric":
            value = _read(binding, self.hass.states.get(binding["entity"]))
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if sig.type == "text":
                return value
            low, high = binding.get("min", 0.0), binding.get("max", 100.0)
            level = (number - low) / (high - low) if high != low else float(number > low)
            level = min(1.0, max(0.0, level))
            return 1 - level if binding.get("invert") else level
        if source == "calendar":
            return _due_items(binding, self._calendar_events, dt_util.now().date())
        if source == "map":
            value = _read(binding, self.hass.states.get(binding["entity"]))
            return None if value is None else _map_option(binding, str(value))
        if source == "event":
            latched = self._events.get(sig.name)
            if latched is None:
                return None
            when, text = latched
            if hold := binding.get("hold", 0):
                until = when + timedelta(seconds=hold)
                if until <= now:
                    return None
                self._expires(until)
            return text if sig.type == "text" else True
        if source == "template":
            return self._templates.get(sig.name)
        return None

    @callback
    def _recompute(self) -> None:
        now = dt_util.utcnow()
        self._next_expiry = None
        values: dict[str, Any] = {}
        for name, sig in self.scene.signals.items():
            override = self._overrides.get(name)
            if override and (override[1] is None or override[1] > now):
                if override[1]:
                    self._expires(override[1])
                values[name] = override[0]
                continue
            self._overrides.pop(name, None)
            raw = self._compute(sig, self.bindings[name], now) if name in self.bindings else None
            values[name] = sig.default if raw is None else sig.coerce(raw)

        if self._timer:
            self._timer()
            self._timer = None
        if self._next_expiry:
            self._timer = async_track_point_in_utc_time(
                self.hass, self._on_timer, self._next_expiry + timedelta(milliseconds=50)
            )

        if values != self.values:
            self.values = values
            for listener in list(self._listeners):
                listener()
