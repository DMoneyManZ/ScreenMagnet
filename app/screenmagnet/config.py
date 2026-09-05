"""Config file location and (de)serialisation.

Its own module so settings_window.py can read and write settings without
importing tray.py: tray.py pulls in caster.py's GStreamer/discovery stack,
which the --settings launch path deliberately avoids dragging in.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG = Path.home() / ".config/screenmagnet/config.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(data: dict) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def update_config(**values) -> dict:
    """Merge `values` into the stored config and save. Returns the new config."""
    cfg = load_config()
    cfg.update(values)
    save_config(cfg)
    return cfg
