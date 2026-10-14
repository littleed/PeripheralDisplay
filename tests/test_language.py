"""Scene language: validation, evaluation and rendering."""

from copy import deepcopy
import itertools
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from custom_components.peripheral_display.language import (
    SceneError,
    load_scene_file,
    parse_scene,
    resolve_binding,
)

TEST_SCENE = (
    Path(__file__).parents[1]
    / "custom_components/peripheral_display/scenes/test_cottage.yaml"
)

BASE = {
    "schema": "peripheral-display/scene@1",
    "id": "mini",
    "name": "Mini",
    "signals": {
        "weather": {"type": "enum", "options": ["clear", "rain"]},
        "lights": {"type": "level"},
        "alert": {"type": "text"},
    },
    "vars": {"sky": [{"when": {"signal": "weather", "is": "rain"}, "value": "grey"}, {"value": "blue"}]},
    "layers": [
        {"id": "sky", "svg": '<rect fill="{{ sky }}"/>'},
        {"id": "lamp", "when": {"signal": "lights", "above": 0.5}, "svg": "<circle/>"},
        {"id": "banner", "when": "alert", "svg": "<text>{{ alert|truncate:10 }}</text>"},
    ],
}


def _layers(svg: str) -> set[str]:
    root = ET.fromstring(svg)
    return {g.get("id") for g in root if g.get("id", "").startswith("layer-")}


def test_test_scene_renders_valid_svg_for_every_combination() -> None:
    """Every layer of the shipped scene produces well-formed SVG together."""
    scene = load_scene_file(TEST_SCENE)
    weathers = scene.signals["weather"].options
    bins = scene.signals["bin"].options
    seen: set[str] = set()
    for weather, night, bin_, on in itertools.product(weathers, (False, True), bins, (False, True)):
        values = {
            "weather": weather,
            "night": night,
            "bin": bin_,
            "motion": on,
            "doorbell": on,
            "lights": 1.0 if on else 0.0,
            "heating": 1.0 if on else 0.0,
            "cinema": on,
            "offline": on,
            "alert": "Fish & chips <tonight>" if on else "",
        }
        seen |= _layers(scene.render(values))
    # Every layer is reachable by some combination of the signals.
    assert seen == {f"layer-{layer.id}" for layer in scene.layers}


def test_conditions_vars_and_text() -> None:
    scene = parse_scene(BASE)
    calm = scene.render({})
    assert _layers(calm) == {"layer-sky"}
    assert 'fill="blue"' in calm

    busy = scene.render({"weather": "rain", "lights": 0.51, "alert": "A & B <c> long headline"})
    assert _layers(busy) == {"layer-sky", "layer-lamp", "layer-banner"}
    assert 'fill="grey"' in busy
    # Text is escaped and truncated to 10 characters including the ellipsis.
    assert "<text>A &amp; B &lt;c&gt;…</text>" in busy
    # 'above' is strict.
    assert "layer-lamp" not in _layers(scene.render({"lights": 0.5}))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["layers"][1].update(when="lamps"), "unknown signal 'lamps'"),
        (lambda d: d["layers"][1].update(when={"signal": "weather", "is": "snow"}), "'snow' is not an option"),
        (lambda d: d["layers"][1].update(when={"signal": "alert", "above": 1}), "need a level signal"),
        (lambda d: d["layers"][0].update(svg="{{ skye }}"), "unknown placeholder 'skye'"),
        (lambda d: d["layers"].append({"id": "sky", "svg": ""}), "duplicate id 'sky'"),
        (
            lambda d: d["signals"]["weather"].update(bind={"source": "map", "map": {"snow": ["snowy"]}}),
            "map keys must be options",
        ),
        (lambda d: d["signals"]["weather"].update(bind={"source": "state"}), "cannot drive a enum signal"),
    ],
)
def test_validation_errors(mutate, message: str) -> None:
    doc = deepcopy(BASE)
    mutate(doc)
    with pytest.raises(SceneError, match=message):
        parse_scene(doc)


def test_resolve_binding() -> None:
    scene = load_scene_file(TEST_SCENE)
    motion = scene.signals["motion"]
    # Unbound until the user picks entities.
    assert resolve_binding(motion) is None
    bound = resolve_binding(motion, ["binary_sensor.hall"], {"hold": 5})
    assert bound["entities"] == ["binary_sensor.hall"]
    assert bound["hold"] == 5 and bound["source"] == "state"
    # An override with another source replaces the scene default entirely.
    templated = resolve_binding(motion, ["binary_sensor.hall"], {"source": "template", "template": "{{ true }}"})
    assert templated == {"source": "template", "template": "{{ true }}"}
    with pytest.raises(SceneError):
        resolve_binding(scene.signals["bin"], None, {"source": "state", "entities": ["sensor.x"]})
