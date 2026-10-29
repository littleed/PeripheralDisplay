"""Scene language: validation, evaluation and rendering."""

from copy import deepcopy
import itertools
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from custom_components.peripheral_display.language import (
    SceneError,
    load_scene_file,
    load_scenes,
    parse_aspect,
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


@pytest.mark.parametrize(
    "path", sorted(TEST_SCENE.parent.glob("*.yaml")), ids=lambda path: path.stem
)
def test_shipped_scenes_render_valid_svg_for_every_combination(path: Path) -> None:
    """Every layer of each shipped scene produces well-formed SVG together."""
    scene = load_scene_file(path)
    bins = [{"name": "Glass & <plastics>", "color": "#3e8e3a", "day": "FRI", "date": "2026-10-16"}] * 3
    active = {"boolean": True, "level": 1.0, "text": "Fish & chips <tonight>", "items": bins}
    idle = {"boolean": False, "level": 0.0, "text": "", "items": []}
    enums = [sig for sig in scene.signals.values() if sig.type == "enum"]
    seen: set[str] = set()
    for options, night, on in itertools.product(
        itertools.product(*(sig.options for sig in enums)), (False, True), (False, True)
    ):
        values = {
            sig.name: (active if on else idle)[sig.type]
            for sig in scene.signals.values()
            if sig.type != "enum"
        }
        values |= {sig.name: option for sig, option in zip(enums, options, strict=True)}
        values["night"] = night
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
        (lambda d: d["layers"][0].update(svg="{{ item.color }}"), "unknown placeholder 'item.color'"),
        (lambda d: d["layers"][0].update(repeat={"signal": "lights"}), "not an items signal"),
        (lambda d: d["layers"][0].update(svg="{{ sky|upper|shout }}"), "unknown filter 'shout'"),
    ],
)
def test_validation_errors(mutate, message: str) -> None:
    doc = deepcopy(BASE)
    mutate(doc)
    with pytest.raises(SceneError, match=message):
        parse_scene(doc)


def test_repeat_layers() -> None:
    doc = deepcopy(BASE)
    doc["signals"]["bins"] = {"type": "items"}
    doc["layers"].append(
        {
            "id": "bins",
            "when": "bins",
            "repeat": {"signal": "bins", "step": [10, 2], "max": 2},
            "svg": '<rect fill="{{ item.color }}"><title>{{ index }} {{ item.day }} {{ item.name|upper|truncate:6 }}</title></rect>',
        }
    )
    scene = parse_scene(doc)
    assert "layer-bins" not in _layers(scene.render({}))
    root = ET.fromstring(
        scene.render(
            {
                "bins": [
                    {"name": "Recycling", "color": "#2c6bd0", "day": "FRI"},
                    {"name": "Food", "day": "TUE"},
                    {"name": "General", "color": "#000000", "day": "FRI"},
                ]
            }
        )
    )
    copies = root.find("{http://www.w3.org/2000/svg}g[@id='layer-bins']")
    # Capped at max, each copy shifted by one more step, colour defaulted.
    assert [g.get("transform") for g in copies] == ["translate(0 0)", "translate(10 2)"]
    rects = [g[0] for g in copies]
    assert [r.get("fill") for r in rects] == ["#2c6bd0", "#3b4047"]
    assert [r[0].text for r in rects] == ["0 FRI RECYC…", "1 TUE FOOD"]


@pytest.mark.parametrize("season", ["none", "christmas", "halloween"])
@pytest.mark.parametrize("colors", [[], ["#000000"], ["#2c6bd0"], ["#2c6bd0", "#3e8e3a"], ["#2c6bd0", "#3e8e3a", "#7a4e2d"]])
def test_poster_bin_colours_and_empty_railway(season, colors) -> None:
    """The poster caps colours at two and never smokes without a train."""
    scene = load_scene_file(TEST_SCENE.with_name("film_poster.yaml"))
    bins = [
        {"name": f"Collection {i}", "color": color, "day": "FRI", "date": "2026-10-30"}
        for i, color in enumerate(colors)
    ]
    svg = scene.render({"bins": bins, "season": season, "heating": 1})
    layers = _layers(svg)
    assert ("layer-bins" in layers) == bool(colors)
    assert ("layer-smoke" in layers) == bool(colors)
    assert ("layer-smoke_heavy" in layers) == bool(colors)
    assert ("layer-empty_railway" in layers) == (not colors)
    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    train = root.find("svg:g[@id='layer-bins']", ns)
    if colors:
        assert [node.get("flood-color") for node in train.findall(".//svg:feFlood", ns)] == colors[:2]
        assert not train.findall(".//svg:text", ns)
        assert "layer-smoke" not in _layers(scene.render({"bins": bins, "season": season}))
    visible_text = " ".join(node.text or "" for node in root.findall(".//svg:text", ns))
    assert "Collection" not in visible_text and "FRI" not in visible_text


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
        resolve_binding(scene.signals["bins"], None, {"source": "state", "entities": ["sensor.x"]})

    bins = scene.signals["bins"]
    assert resolve_binding(bins) is None
    bound = resolve_binding(
        bins, [{"name": "Recycling", "calendar": "calendar.bins", "color": [44, 107, 208]}]
    )
    assert bound["items"] == [
        {"name": "Recycling", "calendar": "calendar.bins", "match": [], "color": "#2c6bd0"}
    ]
    with pytest.raises(SceneError):
        resolve_binding(bins, [{"name": "Recycling", "calendar": "sensor.bins"}])

    # Saved choices made for another kind of input are ignored, not coerced
    # (e.g. one entity id into a list of its characters).
    assert resolve_binding(motion, "binary_sensor.hall") is None
    assert resolve_binding(scene.signals["alert"], "octopus") is None
    assert resolve_binding(scene.signals["weather"], ["weather.home"]) is None
    assert resolve_binding(bins, ["calendar.bins"]) is None


def test_load_scenes_skips_unreadable_files(tmp_path: Path) -> None:
    """One bad file in the user's scenes folder must not hide the others."""
    (tmp_path / "a_binary.yaml").write_bytes(b"\xff\xfe\x00 not text")
    (tmp_path / "b_empty.yaml").write_text("")
    (tmp_path / "c_cottage.yaml").write_text(TEST_SCENE.read_text())
    scenes, errors = load_scenes(tmp_path)
    assert list(scenes) == ["test_cottage"]
    assert [e.split(":")[0] for e in errors] == ["a_binary.yaml", "b_empty.yaml"]


@pytest.mark.parametrize(
    ("aspect", "view_box"),
    [
        (None, (0, 0, 1600, 900)),
        ("16:9", (0, 0, 1600, 900)),
        # Taller screens show more above and below; wider ones more to the sides.
        ("16:10", (0, -50, 1600, 1000)),
        ("1280x800", (0, -50, 1600, 1000)),
        ("4:3", (0, -150, 1600, 1200)),
        ("21:9", (-250, 0, 2100, 900)),
        ("2", (-100, 0, 1800, 900)),
    ],
)
def test_view_box_fits_the_screen_around_the_canvas(aspect, view_box) -> None:
    assert load_scene_file(TEST_SCENE).view_box(parse_aspect(aspect)) == view_box


@pytest.mark.parametrize("text", ["4 by 3", "16:0", "0:9", "5:1", "wide"])
def test_parse_aspect_rejects_nonsense(text: str) -> None:
    with pytest.raises(SceneError):
        parse_aspect(text)


def test_view_placeholders_reach_every_edge() -> None:
    doc = deepcopy(BASE)
    doc["layers"].append(
        {
            "id": "backdrop",
            "svg": '<rect x="{{ view.x }}" y="{{ view.y }}" width="{{ view.width }}"'
            ' height="{{ view.height }}"/><path d="M0,0 L{{ view.right }},{{ view.bottom }}"/>',
        }
    )
    svg = parse_scene(doc).render({}, parse_aspect("4:3"))
    assert 'viewBox="0 -150 1600 1200"' in svg and 'width="1600" height="1200"' in svg
    assert '<rect x="0" y="-150" width="1600" height="1200"/>' in svg
    assert '<path d="M0,0 L1600,1050"/>' in svg
