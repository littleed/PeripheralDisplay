# Peripheral Display for Home Assistant

A Home Assistant integration that renders a piece of art whose details reflect
the state of your home: the weather in the scene follows the weather outside,
night falls when the sun sets, the windows light up with your lights, smoke
rises when the heating runs, and so on. It is meant for a wall tablet or a
frame: something you take in at a glance from the corner of your eye.

Scenes are presets written in a small YAML language (see
[docs/scene-language.md](docs/scene-language.md)). A scene declares the
*signals* it reacts to; when you add it you bind those signals to your own
entities, feeds, templates or automations.

## The test scene: Cottage in the Valley

| Signal     | In the picture                                              | Bind it to                         |
|------------|-------------------------------------------------------------|------------------------------------|
| weather    | sky colour, sun, clouds, rain, lightning, snow, fog, wind   | a `weather` entity                 |
| night      | night palette, moon and stars, glowing windows              | `sun.sun` (pre-filled)             |
| motion     | a fox trots through the garden; the security lamp floods    | motion sensors, or Ring's *Last motion* |
| doorbell   | a visitor at the door, porch lamp lit and ringing           | doorbell sensors, `event`s, or Ring's *Last ding* |
| lights     | windows light up with the share of lights that are on       | `light`s / `switch`es              |
| heating    | chimney smoke, denser with more heating                     | `climate` entities                 |
| cinema     | the snug window flickers, two viewers silhouetted           | `media_player`s                    |
| bin        | the bin out for Friday, in its colour and labelled          | a bin calendar or sensor           |
| offline    | the telephone wire snaps and sparks                         | connectivity sensors (e.g. Ping)   |
| alert      | a pigeon flies in with the matching headline                | keywords for Feed Reader items     |

## Install

1. Copy `custom_components/peripheral_display` into your Home Assistant
   `config/custom_components/` (or add this repository to HACS as a custom
   integration repository).
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Peripheral Display**.
   Name it, pick a scene, and choose what drives each signal. Every field is
   optional.
4. Add a **Picture Entity** card for `image.<name>`. For a wall display, put
   it alone in a *Panel* view; set the aspect ratio so the panel does not crop
   the sides:

   ```yaml
   type: picture-entity
   entity: image.living_room_art
   show_name: false
   show_state: false
   aspect_ratio: "16:9"
   fit_mode: contain
   ```

For the alert signal, create a Google Alert delivered to an RSS feed and add
that feed with the Feed Reader integration; then set the alert keywords (or
`*` for every item of that feed).

Use **Configure** on the integration to switch scene (bindings for standard
signals carry over) or to edit full bindings as YAML: longer motion holds,
a boiler power sensor for heating, a template for bin day, and so on.

## Automations

Any signal can be set from an automation or script, with an optional duration:

```yaml
action: peripheral_display.set_signal
target: {entity_id: image.living_room_art}
data: {signal: alert, value: "Parcel delivered", duration: "01:00:00"}
```

`peripheral_display.clear_signal` returns a signal (or all of them) to its
binding.

## Your own scenes

Put scene files in `<config>/peripheral_display/scenes/` and reload the
integration. Start from
[`scenes/test_cottage.yaml`](custom_components/peripheral_display/scenes/test_cottage.yaml);
the language reference is in [docs/scene-language.md](docs/scene-language.md).

## Development

```sh
uv venv -p 3.13 && uv pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```
