# Peripheral Display scene language (`peripheral-display/scene@1`)

A **scene** is one YAML file that describes an artwork and the data it reacts
to. Scenes are presets: the author decides *what* changes in the picture; each
household decides *what drives it* when they add the scene in Home Assistant.

```text
Home Assistant ──▶ bindings ──▶ signals ──▶ vars + conditions ──▶ SVG layers
(states, events,   (per home)   (typed,     (derived values,      (the artwork)
 templates,                      per scene)  shown/hidden layers)
 actions)
```

Built-in scenes live in `custom_components/peripheral_display/scenes/`. Your
own go in `<config>/peripheral_display/scenes/*.yaml`; a file with the same
`id` as a built-in replaces it. Invalid scenes are skipped with a warning in
the log that names the file and the problem.

## Document

```yaml
schema: peripheral-display/scene@1   # required, exact
id: my_scene                         # lower_snake_case, unique
name: My scene                       # shown in the scene picker
description: ...                     # optional
author: ...                          # optional
canvas: {width: 1600, height: 900}   # optional, these are the defaults
signals: {...}                       # required, at least one
vars: {...}                          # optional
defs: |                              # optional SVG <defs> content
style: |                             # optional CSS (animations, fonts)
layers: [...]                        # required, drawn in order (first = back)
```

## Signals

A signal is a named, typed input to the artwork.

```yaml
signals:
  motion:
    type: boolean            # boolean | level | enum | text | items
    label: Motion            # optional, defaults to the name
    description: A fox crosses the garden.
    options: [...]           # enum only: allowed values; the first is the default
    default: ...             # optional
    bind: {...}              # default binding (see below); defaults to manual
```

| Type      | Values                        | Default            | Truthy when              |
|-----------|-------------------------------|--------------------|--------------------------|
| `boolean` | `true` / `false`              | `false`            | `true`                   |
| `level`   | a number from 0 to 1          | `0`                | above 0                  |
| `enum`    | one of `options`              | the first option   | not `none` (or empty)    |
| `text`    | any string                    | `""`               | not empty                |
| `items`   | a list of items (see below)   | empty list         | not empty                |

An `items` value is a list of things that are currently relevant, such as the
bins due this week. Each item has `name`, `color` (`#rrggbb`), `day` (`MON` to
`SUN`) and `date` (`YYYY-MM-DD`). Items signals are drawn with `repeat` layers
and support only bare conditions (`when: bins`).

Raw values are coerced to the type: `on`, `true`, `yes`, `1`, `home`, `open`,
`detected` and `playing` are true; levels are clamped to 0–1; an enum value
that is not an option becomes the default.

### Standard signals

Scenes may declare any signals, but reusing these names (with these types)
means a household's bindings carry over when they switch scene, and the setup
form shows friendly labels:

| Signal     | Type    | Meaning                                         |
|------------|---------|-------------------------------------------------|
| `weather`  | enum    | `clear partly cloudy rain storm snow fog wind`  |
| `night`    | boolean | it is dark outside                              |
| `motion`   | boolean | a motion sensor has triggered recently          |
| `doorbell` | boolean | a doorbell rang recently                        |
| `side_door`| boolean | someone is at the side door                     |
| `lights`   | level   | the share of chosen lights that are on          |
| `heating`  | level   | how much heating is running                     |
| `cinema`   | boolean | a film is playing                               |
| `bins`     | items   | the bins due for collection in the coming week  |
| `offline`  | boolean | the internet connection is down                 |
| `season`   | enum    | `none halloween christmas`                      |
| `alert`    | text    | headline of a matching news or Google alert     |

## Bindings

A binding says where a signal's value comes from. The scene supplies a
default binding per signal; at setup the user only provides the missing input
(entities, an entity, keywords or a template). In **Configure → Advanced
bindings** they can override any key, or replace the binding with another
source, as YAML keyed by signal name. A signal with no complete binding stays
at its default.

| Source     | Drives                  | Setup asks for | Keys |
|------------|-------------------------|----------------|------|
| `state`    | boolean, level, text    | `entities`     | `match`, `attribute`, `mode`, `hold`, `invert` |
| `numeric`  | level, boolean, text    | `entity`       | `attribute`, `min`, `max`, `invert` |
| `map`      | enum                    | `entity`       | `map`, `compare`, `attribute` |
| `event`    | boolean, level, text    | `keywords`     | `event_type`, `data`, `fields`, `text_field`, `hold` |
| `calendar` | items                   | `items`        | `days` |
| `template` | any                     | `template`     | |
| `manual`   | any                     | nothing        | only set by actions |

All sources also accept `domains`, a list of entity domains offered by the
setup form's entity picker.

### `state`: entities in a given state

- `entities`: the entities to watch.
- `match`: states that count as active (default `["on"]`); compared
  case-insensitively. `unavailable`/`unknown` only match if listed.
- `attribute`: compare this attribute instead of the state, e.g.
  `hvac_action` with `match: [heating]`.
- `mode`: `any` (default) or `all`.
- `hold`: seconds an entity stays active after it stops matching.
- `invert`: negate the result.

Value: boolean = any/all active; level = share of entities active;
text = names of the active entities.

**Momentary entities.** Timestamp entities, meaning `event.*` entities (e.g.
doorbell events) and sensors with the `timestamp` device class (e.g. Ring's
*Last ding*, *Last motion* and *Last activity*), are triggered by each new
time rather than by being in a state; so is any binding whose `match`
contains `@changed`. They stay active for `hold` seconds (30 if unset),
counted from when Home Assistant saw the change or from the time the entity
reports, whichever is later. An old time present at start-up does not count,
and `clear_signal` dismisses the current trigger.

### `numeric`: a number scaled to 0–1

`level = (value − min) / (max − min)`, clamped; `min` defaults to 0 and `max`
to 100. Use `attribute` to read an attribute. For example, boiler power:

```yaml
heating: {source: numeric, entity: sensor.boiler_power, max: 24000}
```

### `map`: text to an enum option

`map` lists, per option, the values that select it; no match gives the
signal's default. `compare: exact` (default) or `contains` (substring). With
`contains`, the longest matching keyword wins, so `non-recycl` beats `recycl`
for "Non-recyclable waste".

```yaml
weather:
  source: map
  entity: weather.home
  map: {clear: [sunny, clear-night], rain: [rainy, pouring]}
```

### `calendar`: items from calendar events

`items` lists the things to look for, each with:

- `name`: shown in the artwork;
- `calendar`: a `calendar.*` entity;
- `match`: words that identify its events by title, case-insensitively;
  leave it out to count every event in that calendar;
- `color`: `#rrggbb` or `[r, g, b]` (default dark grey).

An item is included when its calendar has a matching event from today through
the next `days` days (default 7, so today plus six more), with `day` and `date`
from its earliest such event. Items are ordered by date, then by their order in
`items`. Events are re-read when a calendar changes and every 15 minutes. One
shared calendar (with `match` words) and one calendar per item both work.

```yaml
bins:
  source: calendar
  items:
    - {name: Recycling, calendar: calendar.bins, match: [Blue-lidded], color: "#2c6bd0"}
    - {name: General, calendar: calendar.bins, match: [General Waste], color: "#2b2b2e"}
    - {name: Food & Garden, calendar: calendar.bins, match: [Food and Garden], color: "#7a4e2d"}
    - {name: Glass & Plastics, calendar: calendar.bins, match: [Glass], color: "#3e8e3a"}
```

### `event`: Home Assistant bus events

- `event_type`: e.g. `feedreader` (fired for each new feed item).
- `keywords`: case-insensitive substrings to look for; `*` matches any event.
  The binding is inactive until at least one keyword is set.
- `fields`: the event data fields to search (default: all text fields).
- `data`: exact-match filters on event data.
- `text_field`: the field used as a text signal's value (default: the matched
  keyword).
- `hold`: seconds the signal stays active; `0` latches it until
  `peripheral_display.clear_signal`.

Google Alerts can deliver to an RSS feed. Add that feed to the Feed Reader
integration and set your keywords on the `alert` signal (or use `*` when the
feed is already your Google Alert).

### `template`: a Home Assistant template

The rendered result is coerced to the signal's type, and it updates whenever
the entities it references change. Use it for anything the other sources
cannot express:

```yaml
night:
  source: template
  template: >
    {{ is_state('sun.sun', 'below_horizon') or is_state('input_boolean.bedtime', 'on') }}
```

### Actions

Every signal can also be driven from automations and scripts:

```yaml
action: peripheral_display.set_signal
target: {entity_id: image.living_room_art}
data: {signal: doorbell, value: "on", duration: "00:01:00"}
```

`duration` is optional; without it the value holds until
`peripheral_display.clear_signal`, which also clears holds and latched events.

## Conditions

Conditions decide whether a layer is drawn and which var rule applies.

```yaml
when: motion                               # truthy
when: "!night"                             # not truthy (quote the !)
when: {signal: weather, is: rain}
when: {signal: weather, in: [rain, storm]}
when: {signal: lights, above: 0.5}         # level only; strict
when: {signal: heating, above: 0.2, below: 0.8}
when: {all: [night, motion]}
when: {any: [doorbell, motion]}
when: {not: {signal: weather, is: clear}}
```

Signals and enum options are checked when the scene loads, so a typo is an
error, not a silently missing layer.

## Vars

Vars compute values for placeholders.

```yaml
vars:
  ink: "#222"                                  # literal
  smoke_opacity: {signal: heating, range: [0.4, 1]}   # level or boolean, interpolated
  sky:                                         # rules: the first match wins
    - {when: night, value: "#070b26"}
    - {when: {signal: weather, is: storm}, value: "#353d4b"}
    - value: "#4fa3f7"                         # fallback (no when)
```

A rule list with no matching rule gives an empty string.

Vars cannot read `items` signals; use a `repeat` layer.

## Placeholders

`defs`, `style` and every layer's `svg` may contain `{{ name }}`, where `name`
is a var or a signal. Values are XML-escaped. Booleans render as `on`/`off`.
Inside a `repeat` layer, `{{ item.name }}`, `{{ item.color }}`,
`{{ item.day }}`, `{{ item.date }}` and `{{ index }}` (0, 1, ...) are also
available. Filters can be chained, e.g. `{{ item.name|upper|truncate:12 }}`.

| Filter          | Effect                                  |
|-----------------|-----------------------------------------|
| `upper`         | upper case                              |
| `lower`         | lower case                              |
| `truncate:N`    | at most N characters, ending in `…`     |

```yaml
svg: <text>{{ alert|truncate:34 }}</text>
```

Unknown names and filters are errors when the scene loads.

## Layers

```yaml
layers:
  - id: sky                       # unique lower_snake_case
    svg: <rect width="1600" height="900" fill="url(#sky)"/>
  - id: rain
    when: {signal: weather, in: [rain, storm]}
    svg: |
      <g class="fall"><rect y="-120" width="1600" height="1140" fill="url(#rain)"/></g>
```

A `repeat` layer is drawn once per item of an `items` signal, each copy
shifted by `step` (x, y) from the previous one, up to `max` copies:

```yaml
  - id: bins
    when: bins
    repeat: {signal: bins, step: [88, 0], max: 5}
    svg: |
      <rect x="1140" y="746" width="70" height="100" fill="{{ item.color }}"/>
      <text x="1175" y="790">{{ item.day }}</text>
```

Each drawn layer becomes `<g id="layer-ID">…</g>`. The output is a standalone
SVG served as an image, so it may use CSS and SMIL animation but not scripts
or external resources.

Authoring tips:

- An element with a `transform` attribute loses it if a CSS animation also
  sets `transform`; wrap animated content in its own `<g>`.
- Use `transform-box: fill-box` with `transform-origin` for rotations and
  scaling about an element's own centre.
- Prefer vars for anything that changes by day/night or weather, so layers stay
  readable.

## Rendering

The display is an `image` entity (`image/svg+xml`) that re-renders when any
signal changes. Show it with a Picture Entity or Picture card; a panel-view
dashboard with only that card makes a full-screen wall display. The companion
`sensor.*_active_signals` lists active signals and exposes every value as an
attribute, for debugging and automations.
