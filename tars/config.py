"""Load config/tars.yaml, overlaid with ~/.config/tars/tars.yaml if present."""

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

DEFAULT = Path(__file__).resolve().parent.parent / "config" / "tars.yaml"
USER = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tars" / "tars.yaml"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(default: Path = DEFAULT, user: Path = USER) -> dict[str, Any]:
    cfg = yaml.safe_load(default.read_text()) or {}
    if user.exists():
        cfg = _merge(cfg, yaml.safe_load(user.read_text()) or {})
    return cfg
