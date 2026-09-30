"""TARS — local, hands-free desktop agent (v2). See docs/PLAN.md."""

from pathlib import Path

TARS_HOME = Path.home() / ".local" / "share" / "tars"
MODELS_DIR = TARS_HOME / "models"
BIN_DIR = TARS_HOME / "opt" / "bin"
