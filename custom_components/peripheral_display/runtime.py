"""Turns Home Assistant states and events into scene signal values."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
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
from homeassistant.helpers.event import (
    TrackTemplate,
    TrackTemplateResult,
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_template_result,
)
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util

from .language import Scene, Signal

_INVALID = (STATE_UNAVAILABLE, STATE_UNKNOWN)
DEFAULT_MOMENTARY_HOLD = 30.0


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


def _momentary(binding: dict[str, Any], entity_id: str) -> bool:
    """Event entities (and ``@changed``) trigger on every new state."""
    return entity_id.startswith("event.") or "@changed" in binding.get("match", [])


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
            for key in [k for k in self._last_active if k[0] == sig]:
                del self._last_active[key]
        self._recompute()

    # -- inputs ---------------------------------------------------------------

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        now = dt_util.utcnow()
        for name, binding in self.bindings.items():
            if binding["source"] != "state" or entity_id not in binding["entities"]:
                continue
            if _momentary(binding, entity_id):
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
    def _on_timer(self, _now: datetime) -> None:
        self._timer = None
        self._recompute()

    # -- evaluation -----------------------------------------------------------

    def _expires(self, when: datetime) -> None:
        if self._next_expiry is None or when < self._next_expiry:
            self._next_expiry = when

    def _held(self, key: tuple[str, str], hold: float, now: datetime) -> bool:
        last = self._last_active.get(key)
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
                momentary = _momentary(binding, entity_id)
                hold = binding.get("hold") or (DEFAULT_MOMENTARY_HOLD if momentary else 0)
                on = (not momentary and _matches(binding, state)) or self._held(
                    (sig.name, entity_id), hold, now
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
        if source == "map":
            if binding["entity"].startswith("calendar.") and "attribute" not in binding:
                # A calendar's state is on/off; its next event is in 'message'.
                binding = {**binding, "attribute": "message"}
            value = _read(binding, self.hass.states.get(binding["entity"]))
            if value is None:
                return None
            value = str(value).lower()
            contains = binding.get("compare", "exact") == "contains"
            for option, patterns in binding["map"].items():
                for pattern in patterns:
                    pattern = pattern.lower()
                    if (pattern in value) if contains else (pattern == value):
                        return option
            return None
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
