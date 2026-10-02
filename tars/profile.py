"""Your details, for filling forms and for keeping them out of what TARS sends to
web AIs. You write ~/.config/tars/profile.yaml yourself, for example:

    name: Your Name
    email: you@example.com
    phone: "+91 98765 43210"
    roll_number: "2021xxxxx"
    college: Your College

Never put passwords here: TARS never types them anyway.
"""

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from tars.config import USER

PROFILE = USER.parent / "profile.yaml"


def load(path: Path = PROFILE) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return {
        str(k): str(v)
        for k, v in data.items()
        if v is not None and "password" not in str(k).lower()
    }
