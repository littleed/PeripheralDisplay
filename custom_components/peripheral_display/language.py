"""The Peripheral Display scene language.

A scene is a YAML document that declares:

* ``signals``: the named, typed data states the artwork reacts to, each with a
  default binding that says where the value usually comes from in Home
  Assistant;
* ``vars``: values (colours, opacities, ...) derived from signals;
* ``defs``/``style``/``layers``: SVG fragments, where each layer may carry a
  ``when`` condition and any fragment may use ``{{ placeholders }}``.

This module has no Home Assistant dependency so scenes can be validated and
rendered anywhere. See docs/scene-language.md for the full reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Any
from xml.sax.saxutils import escape

import voluptuous as vol
import yaml

SCHEMA_ID = "peripheral-display/scene@1"
SIGNAL_TYPES = ("boolean", "level", "enum", "text")
SOURCES = ("state", "numeric", "map", "event", "template", "manual")
FILTERS = ("upper", "lower", "truncate")

_NAME = r"[a-z][a-z0-9_]*"
_NAME_RE = re.compile(rf"^{_NAME}$")
_PLACEHOLDER_RE = re.compile(
    rf"\{{\{{\s*({_NAME})\s*(?:\|\s*([a-z]+)(?::(\d+))?\s*)?\}}\}}"
)
_TRUE_STRINGS = {"on", "true", "yes", "1", "home", "open", "detected", "playing"}


class SceneError(ValueError):
    """Raised when a scene document is invalid."""


def _name(value: Any) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise vol.Invalid(f"'{value}' must be lower_snake_case")
    return value


BINDING_SCHEMA = vol.Schema(
    {
        vol.Required("source"): vol.In(SOURCES),
        # UI hint: entity domains offered by the config flow picker.
        vol.Optional("domains"): [str],
        vol.Optional("entities"): vol.All(vol.Coerce(list), [str]),
        vol.Optional("entity"): str,
        vol.Optional("attribute"): str,
        vol.Optional("match"): vol.All(vol.Coerce(list), [vol.Coerce(str)]),
        vol.Optional("mode"): vol.In(("any", "all")),
        vol.Optional("hold"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("invert"): bool,
        vol.Optional("min"): vol.Coerce(float),
        vol.Optional("max"): vol.Coerce(float),
        vol.Optional("map"): {str: vol.All(vol.Coerce(list), [vol.Coerce(str)])},
        vol.Optional("compare"): vol.In(("exact", "contains")),
        vol.Optional("event_type"): str,
        vol.Optional("data"): dict,
        vol.Optional("keywords"): vol.All(vol.Coerce(list), [vol.Coerce(str)]),
        vol.Optional("fields"): vol.All(vol.Coerce(list), [str]),
        vol.Optional("text_field"): str,
        vol.Optional("template"): str,
    }
)

_SIGNAL_SCHEMA = vol.Schema(
    {
        vol.Required("type"): vol.In(SIGNAL_TYPES),
        vol.Optional("label"): str,
        vol.Optional("description", default=""): str,
        vol.Optional("options"): vol.All([vol.Coerce(str)], vol.Length(min=1)),
        vol.Optional("default"): vol.Any(bool, int, float, str),
        vol.Optional("bind", default={"source": "manual"}): BINDING_SCHEMA,
    }
)

_LAYER_SCHEMA = vol.Schema(
    {
        vol.Required("id"): _name,
        vol.Optional("when"): object,
        vol.Required("svg"): str,
    }
)

_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required("schema"): SCHEMA_ID,
        vol.Required("id"): _name,
        vol.Required("name"): str,
        vol.Optional("description", default=""): str,
        vol.Optional("author", default=""): str,
        vol.Optional("canvas", default={}): {
            vol.Optional("width", default=1600): vol.All(int, vol.Range(min=1)),
            vol.Optional("height", default=900): vol.All(int, vol.Range(min=1)),
        },
        vol.Required("signals"): vol.All({_name: _SIGNAL_SCHEMA}, vol.Length(min=1)),
        vol.Optional("vars", default={}): {_name: object},
        vol.Optional("defs", default=""): str,
        vol.Optional("style", default=""): str,
        vol.Required("layers"): vol.All([_LAYER_SCHEMA], vol.Length(min=1)),
    }
)


@dataclass(frozen=True)
class Signal:
    """A typed data state the artwork reacts to."""

    name: str
    type: str
    label: str
    description: str
    options: tuple[str, ...]
    default: Any
    bind: dict[str, Any]

    def coerce(self, raw: Any) -> Any:
        """Convert a raw value (state string, number, bool) to this signal's type."""
        if self.type == "boolean":
            if isinstance(raw, str):
                return raw.strip().lower() in _TRUE_STRINGS
            return bool(raw)
        if self.type == "level":
            if isinstance(raw, str) and raw.strip().lower() in _TRUE_STRINGS | {
                "off",
                "false",
                "no",
            }:
                raw = raw.strip().lower() in _TRUE_STRINGS
            try:
                return min(1.0, max(0.0, float(raw)))
            except (TypeError, ValueError):
                return self.default
        if self.type == "enum":
            value = str(raw).strip().lower() if raw is not None else ""
            return value if value in self.options else self.default
        return "" if raw is None else str(raw).strip()

    def truthy(self, value: Any) -> bool:
        """Truthiness used by bare conditions such as ``when: motion``."""
        if self.type == "enum":
            return value not in ("", "none")
        if self.type == "level":
            return value > 0
        return bool(value)


@dataclass(frozen=True)
class Layer:
    """An SVG fragment, optionally shown only when a condition holds."""

    id: str
    when: Any
    svg: str


@dataclass(frozen=True)
class Scene:
    """A validated scene preset."""

    id: str
    name: str
    description: str
    author: str
    width: int
    height: int
    signals: dict[str, Signal]
    vars: dict[str, Any]
    defs: str
    style: str
    layers: tuple[Layer, ...] = field(default_factory=tuple)

    def defaults(self) -> dict[str, Any]:
        """Return every signal at its default value."""
        return {name: sig.default for name, sig in self.signals.items()}

    def evaluate(self, condition: Any, values: dict[str, Any]) -> bool:
        """Evaluate a (validated) condition against signal values."""
        if condition is None:
            return True
        if isinstance(condition, str):
            negate = condition.startswith("!")
            name = condition.lstrip("!")
            return self.signals[name].truthy(values[name]) != negate
        if "all" in condition:
            return all(self.evaluate(c, values) for c in condition["all"])
        if "any" in condition:
            return any(self.evaluate(c, values) for c in condition["any"])
        if "not" in condition:
            return not self.evaluate(condition["not"], values)
        sig = self.signals[condition["signal"]]
        value = values[sig.name]
        if "is" in condition:
            return value == sig.coerce(condition["is"])
        if "in" in condition:
            return value in [sig.coerce(v) for v in condition["in"]]
        if "above" in condition or "below" in condition:
            number = float(value)
            return number > condition.get("above", float("-inf")) and number < (
                condition.get("below", float("inf"))
            )
        return sig.truthy(value)

    def resolve_vars(self, values: dict[str, Any]) -> dict[str, Any]:
        """Compute every var for the given signal values."""
        resolved: dict[str, Any] = {}
        for name, spec in self.vars.items():
            if isinstance(spec, list):
                resolved[name] = next(
                    (
                        rule["value"]
                        for rule in spec
                        if self.evaluate(rule.get("when"), values)
                    ),
                    "",
                )
            elif isinstance(spec, dict):
                low, high = spec["range"]
                level = float(values[spec["signal"]])
                resolved[name] = round(low + (high - low) * level, 3)
            else:
                resolved[name] = spec
        return resolved

    def describe(self, values: dict[str, Any]) -> list[str]:
        """Human-readable active signals, e.g. ``["Weather: rain", "Lights"]``."""
        return [
            f"{sig.label}: {values[sig.name]}" if sig.type == "enum" else sig.label
            for sig in self.signals.values()
            if sig.truthy(values[sig.name])
        ]

    def render(self, values: dict[str, Any]) -> str:
        """Render the scene to an SVG document."""
        values = {**self.defaults(), **values}
        context = {**values, **self.resolve_vars(values)}

        def fill(text: str) -> str:
            def replace(match: re.Match[str]) -> str:
                value = context[match.group(1)]
                if isinstance(value, bool):
                    value = "on" if value else "off"
                value = str(value)
                if match.group(2) == "upper":
                    value = value.upper()
                elif match.group(2) == "lower":
                    value = value.lower()
                elif match.group(2) == "truncate":
                    limit = int(match.group(3) or 40)
                    if len(value) > limit:
                        value = value[: limit - 1].rstrip() + "…"
                return escape(value, {'"': "&quot;"})

            return _PLACEHOLDER_RE.sub(replace, text)

        title = escape(f"{self.name}: {', '.join(self.describe(values)) or 'calm'}")
        body = "".join(
            f'<g id="layer-{layer.id}">{fill(layer.svg)}</g>\n'
            for layer in self.layers
            if self.evaluate(layer.when, values)
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" role="img">\n'
            f"<title>{title}</title>\n"
            f"<style><![CDATA[{fill(self.style)}]]></style>\n"
            f"<defs>{fill(self.defs)}</defs>\n"
            f"{body}</svg>\n"
        )


def _check_condition(cond: Any, signals: dict[str, Signal], path: str) -> Any:
    """Validate a condition and return it unchanged."""
    if cond is None:
        return None
    if isinstance(cond, str):
        if cond.lstrip("!") not in signals:
            raise SceneError(f"{path}: unknown signal '{cond.lstrip('!')}'")
        return cond
    if not isinstance(cond, dict):
        raise SceneError(f"{path}: a condition must be a signal name or a mapping")
    for key in ("all", "any"):
        if key in cond:
            if set(cond) != {key} or not isinstance(cond[key], list):
                raise SceneError(f"{path}: '{key}' takes a list and nothing else")
            for i, sub in enumerate(cond[key]):
                _check_condition(sub, signals, f"{path}.{key}[{i}]")
            return cond
    if "not" in cond:
        if set(cond) != {"not"}:
            raise SceneError(f"{path}: 'not' takes a single condition")
        _check_condition(cond["not"], signals, f"{path}.not")
        return cond
    name = cond.get("signal")
    if name not in signals:
        raise SceneError(f"{path}: unknown signal '{name}'")
    sig = signals[name]
    tests = set(cond) - {"signal"}
    if not tests <= {"is", "in", "above", "below"}:
        raise SceneError(f"{path}: unknown keys {sorted(tests - {'is', 'in', 'above', 'below'})}")
    if "is" in tests and len(tests) > 1 or "in" in tests and len(tests) > 1:
        raise SceneError(f"{path}: use one of 'is', 'in' or 'above'/'below'")
    if "in" in cond and not isinstance(cond["in"], list):
        raise SceneError(f"{path}: 'in' takes a list")
    if sig.type == "enum":
        for value in cond.get("in", []) + ([cond["is"]] if "is" in cond else []):
            if str(value).lower() not in sig.options:
                raise SceneError(
                    f"{path}: '{value}' is not an option of '{name}' {list(sig.options)}"
                )
    if tests & {"above", "below"}:
        if sig.type != "level":
            raise SceneError(f"{path}: 'above'/'below' need a level signal")
        for key in tests & {"above", "below"}:
            if not isinstance(cond[key], (int, float)):
                raise SceneError(f"{path}: '{key}' must be a number")
    return cond


def parse_scene(data: Any) -> Scene:
    """Validate a scene document (already parsed from YAML)."""
    try:
        doc = _SCENE_SCHEMA(data)
    except vol.Invalid as err:
        raise SceneError(f"invalid scene: {vol.humanize.humanize_error(data, err)}") from err

    signals: dict[str, Signal] = {}
    for name, spec in doc["signals"].items():
        options = tuple(o.lower() for o in spec.get("options", ()))
        if spec["type"] == "enum" and not options:
            raise SceneError(f"signals.{name}: enum signals need 'options'")
        if spec["type"] != "enum" and options:
            raise SceneError(f"signals.{name}: only enum signals take 'options'")
        base = Signal(
            name=name,
            type=spec["type"],
            label=spec.get("label", name.replace("_", " ").capitalize()),
            description=spec["description"],
            options=options,
            default=options[0] if options else {"boolean": False, "level": 0.0, "text": ""}.get(spec["type"]),
            bind=spec["bind"],
        )
        if "default" in spec:
            default = base.coerce(spec["default"])
            if spec["type"] == "enum" and str(spec["default"]).lower() not in options:
                raise SceneError(f"signals.{name}: default must be one of {list(options)}")
            base = replace(base, default=default)
        try:
            resolve_binding(base)
        except SceneError as err:
            raise SceneError(f"signals.{name}.bind: {err}") from err
        signals[name] = base

    for name, spec in doc["vars"].items():
        path = f"vars.{name}"
        if name in signals:
            raise SceneError(f"{path}: name clashes with a signal")
        if isinstance(spec, list):
            for i, rule in enumerate(spec):
                if not isinstance(rule, dict) or "value" not in rule or set(rule) - {"when", "value"}:
                    raise SceneError(f"{path}[{i}]: rules are {{when: ..., value: ...}}")
                _check_condition(rule.get("when"), signals, f"{path}[{i}].when")
        elif isinstance(spec, dict):
            sig = signals.get(spec.get("signal"))
            rng = spec.get("range")
            if (
                set(spec) != {"signal", "range"}
                or sig is None
                or sig.type not in ("level", "boolean")
                or not (isinstance(rng, list) and len(rng) == 2)
                or not all(isinstance(n, (int, float)) for n in rng)
            ):
                raise SceneError(f"{path}: use {{signal: <level signal>, range: [low, high]}}")
        elif not isinstance(spec, (str, int, float)):
            raise SceneError(f"{path}: must be a literal, a rule list or a range")

    layers = []
    seen: set[str] = set()
    for i, raw in enumerate(doc["layers"]):
        if raw["id"] in seen:
            raise SceneError(f"layers[{i}]: duplicate id '{raw['id']}'")
        seen.add(raw["id"])
        layers.append(
            Layer(raw["id"], _check_condition(raw.get("when"), signals, f"layers[{i}].when"), raw["svg"])
        )

    known = set(signals) | set(doc["vars"])
    for where, text in [("defs", doc["defs"]), ("style", doc["style"])] + [
        (f"layer '{layer.id}'", layer.svg) for layer in layers
    ]:
        for match in _PLACEHOLDER_RE.finditer(text):
            if match.group(1) not in known:
                raise SceneError(f"{where}: unknown placeholder '{match.group(1)}'")
            if match.group(2) and match.group(2) not in FILTERS:
                raise SceneError(f"{where}: unknown filter '{match.group(2)}'")

    return Scene(
        id=doc["id"],
        name=doc["name"],
        description=doc["description"],
        author=doc["author"],
        width=doc["canvas"]["width"],
        height=doc["canvas"]["height"],
        signals=signals,
        vars=doc["vars"],
        defs=doc["defs"],
        style=doc["style"],
        layers=tuple(layers),
    )


# The one input the config flow asks for per source; scenes provide the rest.
SOURCE_TYPES = {
    "state": ("boolean", "level", "text"),
    "numeric": ("boolean", "level", "text"),
    "map": ("enum",),
    "event": ("boolean", "level", "text"),
    "template": SIGNAL_TYPES,
    "manual": SIGNAL_TYPES,
}
SELECTION_KEYS = {
    "state": "entities",
    "numeric": "entity",
    "map": "entity",
    "event": "keywords",
    "template": "template",
}


def resolve_binding(
    signal: Signal, selection: Any = None, override: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Combine a scene's default binding, a UI selection and a YAML override.

    Returns the validated binding when it has the inputs it needs, or None
    when the signal is unbound (and so stays at its default value).
    """
    binding = dict(signal.bind)
    key = SELECTION_KEYS.get(binding["source"])
    if key and selection not in (None, "", []):
        binding[key] = selection
    if override:
        same_source = override.get("source", binding["source"]) == binding["source"]
        binding = {**binding, **override} if same_source else dict(override)
    try:
        binding = BINDING_SCHEMA(binding)
    except vol.Invalid as err:
        raise SceneError(f"{signal.name}: {err}") from err
    source = binding["source"]
    if signal.type not in SOURCE_TYPES[source]:
        raise SceneError(
            f"{signal.name}: the '{source}' source cannot drive a {signal.type} signal"
        )
    if source == "map" and not set(binding.get("map", {})) <= set(signal.options):
        raise SceneError(f"{signal.name}: map keys must be options {list(signal.options)}")
    required = {
        "state": ("entities",),
        "numeric": ("entity",),
        "map": ("entity", "map"),
        "event": ("event_type", "keywords"),
        "template": ("template",),
    }.get(source)
    if not required or not all(binding.get(k) for k in required):
        return None
    return binding


def load_scene_file(path: Path) -> Scene:
    """Load and validate a scene from a YAML file."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise SceneError(f"{path.name}: {err}") from err
    try:
        return parse_scene(data)
    except SceneError as err:
        raise SceneError(f"{path.name}: {err}") from err


def load_scenes(*directories: Path) -> tuple[dict[str, Scene], list[str]]:
    """Load every ``*.yaml`` scene; later directories override earlier ids."""
    scenes: dict[str, Scene] = {}
    errors: list[str] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            try:
                scene = load_scene_file(path)
            except SceneError as err:
                errors.append(str(err))
            else:
                scenes[scene.id] = scene
    return scenes, errors
