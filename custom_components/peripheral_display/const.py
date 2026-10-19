"""Constants for Peripheral Display."""

from pathlib import Path

DOMAIN = "peripheral_display"

CONF_SCENE = "scene"
CONF_SELECTIONS = "selections"
CONF_OVERRIDES = "overrides"
CONF_ASPECT_RATIO = "aspect_ratio"
DEFAULT_ASPECT_RATIO = "16:9"

BUILTIN_SCENES_DIR = Path(__file__).parent / "scenes"
# Relative to the Home Assistant config directory.
USER_SCENES_DIR = "peripheral_display/scenes"
