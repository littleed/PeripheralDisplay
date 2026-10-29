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
| weather    | sky colour, sun, clouds, rain, lightning, snow, fog         | a `weather` entity                 |
| wind       | above 30 km/h, on top of any weather: the trees bend, leaves and smoke blow, gusts cross the sky (a windy or stormy condition does this too) | a `weather` entity, for its wind speed |
| night      | night palette, moon and stars, glowing windows              | `sun.sun` (pre-filled)             |
| motion     | a fox trots through the garden; the security lamp floods    | motion sensors, or Ring's *Last motion* |
| doorbell   | a visitor at the door, porch lamp lit and ringing           | doorbell sensors, `event`s, or Ring's *Last ding* |
| side door  | a visitor at the side door, its lamp lit                    | door, motion or doorbell sensors at the side door |
| lights     | windows light up with the share of lights that are on       | `light`s / `switch`es              |
| heating    | chimney smoke, denser with more heating                     | `climate` entities                 |
| cinema     | the snug window flickers, two viewers silhouetted           | `media_player`s                    |
| bins       | every bin due this week at the fence, in its colour, with its day | one entry per bin: name, calendar, title words, colour |
| offline    | the telephone wire snaps and sparks                         | connectivity sensors (e.g. Ping)   |
| alert      | a pigeon flies in with the matching headline                | keywords for Feed Reader items     |
| season     | Halloween: pumpkins, bats, cobweb, full moon. Christmas: roof lights, wreath, decorated tree, a snowman when it snows | automatic: December, and 24 Oct – 7 Nov (editable) |

## The Stranger at the Door: a golden-age film poster

A painted 1946 Hollywood half-sheet for a film-noir thriller, with billing,
tagline and National Screen Service fine print on aged, folded paper.

| Signal     | In the picture                                              | Bind it to                         |
|------------|-------------------------------------------------------------|------------------------------------|
| weather    | the poster's colour, a weather emblem around the title (sunburst, painted clouds, a lightning bolt, snowflakes, wind swirls), a tagline to match, and rain, snow or fog over the picture | a `weather` entity |
| night      | a night-blue poster with a crescent moon and stars          | `sun.sun` (pre-filled)             |
| doorbell   | the red front door swings open on a shadowy man in a fedora | doorbell sensors, `event`s, or Ring's *Last ding* |
| side door  | the green side door swings open on a woman in a wide hat    | door, motion or doorbell sensors at the side door |
| heating    | smoke from the steam train when bins are due, heavier with more heating | `climate` entities                 |
| bins       | a train in the colours of the bins due this week; no train when none are due | one entry per bin: name, calendar, title words, colour |
| cinema     | a studio camera on the lawn, its reels turning              | `media_player`s                    |
| season     | holiday editions of the painting. Christmas: the stars in a fur-trimmed cape and a snowy fedora with a gift, by a snowy house. Halloween: a scream queen and a vampire count | automatic: December, and 24 Oct – 7 Nov (editable) |

The train supports **at most two bin colours in the coming seven days** (today
plus six more). With one bin due, both the locomotive and tender take its
colour. With two, the locomotive takes the first bin's colour and the tender
takes the second. Any further bins are not represented. Collections are ordered
by date, then by their configured order when dates match, just as in Cottage in
the Valley. No bin names, collection days or dates are printed in the scene.
When nothing is due (or bins are not configured), the train and its smoke are
absent, leaving an empty railway; a black train therefore means a black bin is
due, not that there is no collection.

## Install

1. Copy `custom_components/peripheral_display` into your Home Assistant
   `config/custom_components/` (or add this repository to HACS as a custom
   integration repository).
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Peripheral Display**.
   Name it, pick a scene and your screen's aspect ratio (16:10 for a Fire HD
   8 or 10, 4:3 for an iPad, or any `W:H` or resolution such as `1280x800`),
   and choose what drives each signal. Every field is optional. The scene
   always shows whole and extends its sky and ground to fill the screen.
4. Add a **Picture Entity** card for `image.<name>`. For a wall display, put
   it alone in a *Panel* view, with the same aspect ratio as the display:

   ```yaml
   type: picture-entity
   entity: image.living_room_art
   show_name: false
   show_state: false
   aspect_ratio: "16:10"
   fit_mode: cover
   ```

   Use the ratio of the area the card fills: the whole screen in a kiosk or
   full-screen browser, or less the header and status bar otherwise.

For the alert signal, create a Google Alert delivered to an RSS feed and add
that feed with the Feed Reader integration; then set the alert keywords (or
`*` for every item of that feed).

Use **Configure** on the integration to change the screen aspect ratio,
switch scene (a choice carries over
when the new scene has a signal of that name taking the same kind of input) or
to edit full bindings as YAML: longer motion holds,
a boiler power sensor for heating, a template for night, and so on.

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

## Fire TV screensaver

[`firetv-screensaver/`](firetv-screensaver/README.md) is a separate Android
TV app that shows a display's `image` entity as the Fire TV screensaver
(Fire OS 7 and older). HACS installs only the integration, not the app.

## Development

```sh
uv venv -p 3.13 && uv pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```
