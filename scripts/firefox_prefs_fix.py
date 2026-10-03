#!/usr/bin/env python3
"""
Undo Firefox's automation settings in your profile, and stop them coming back.

When Firefox starts with remote control on (the Firefox (TARS) launcher), it switches
on ~100 "recommended" test settings: password saving, the popup blocker, safe browsing
and add-on updates off, a hidden bookmarks bar, dummy sync and update servers... It
undoes them on a clean quit, but if Firefox is killed or crashes they stay in prefs.js,
and from then on Firefox treats them as yours. This removes every setting that still
holds exactly the automation value (keeping a backup of prefs.js), and sets
remote.prefs.recommended = false so remote control never applies them again.

Firefox must be closed (it rewrites prefs.js when it quits).
    python3 scripts/firefox_prefs_fix.py           # report and fix
    python3 scripts/firefox_prefs_fix.py --check   # report only
"""

import configparser
import json
import re
import subprocess
import sys
import time
from pathlib import Path

OMNI = Path("/snap/firefox/current/usr/lib/firefox/omni.ja")
SOURCE = "chrome/remote/content/shared/RecommendedPreferences.sys.mjs"
ROOTS = [Path.home() / "snap/firefox/common/.mozilla/firefox", Path.home() / ".mozilla/firefox"]
OPT_OUT = 'user_pref("remote.prefs.recommended", false);'
USER_PREF = re.compile(r'^user_pref\("([^"]+)",\s*(.*)\);$')


def automation_prefs() -> dict:
    # Python's zipfile can't open omni.ja (it's an optimised jar); unzip can.
    src = subprocess.run(["unzip", "-p", str(OMNI), SOURCE], capture_output=True, text=True).stdout
    if "COMMON_PREFERENCES" not in src:
        sys.exit(f"couldn't read the automation settings list from {OMNI}")
    body = src[src.index("COMMON_PREFERENCES") : src.index("export const RecommendedPreferences")]
    prefs = {}
    for k, v in re.findall(r'\[\s*"([^"]+)",\s*([^\]]+?)\s*,?\s*\]', body, re.S):
        try:
            prefs[k] = json.loads(v.strip().rstrip(","))
        except ValueError:
            pass
    return prefs


def profiles() -> list[Path]:
    found = []
    for root in ROOTS:
        ini = configparser.ConfigParser()
        if not ini.read(root / "profiles.ini"):
            continue
        for s in ini.sections():
            if "Path" in ini[s]:
                p = ini[s]["Path"]
                path = root / p if ini[s].get("IsRelative", "1") == "1" else Path(p)
                if (path / "prefs.js").exists():
                    found.append(path)
    return found


def fix(profile: Path, rec: dict, check: bool) -> None:
    prefs_js = profile / "prefs.js"
    lines = prefs_js.read_text().splitlines()
    keep, stuck = [], []
    for line in lines:
        m = USER_PREF.match(line)
        if m and m.group(1) in rec:
            try:
                same = json.loads(m.group(2)) == rec[m.group(1)]
            except ValueError:
                same = False
            if same:
                stuck.append(m.group(1))
                continue
        keep.append(line)
    opted_out = OPT_OUT in lines
    print(f"{profile.name}: {len(stuck)} automation settings stuck"
          + ("" if opted_out else "; remote.prefs.recommended not yet off"))  # fmt: skip
    if check or (not stuck and opted_out):
        return
    backup = profile / f"prefs.js.before-tars-fix-{time.strftime('%Y%m%d-%H%M%S')}"
    backup.write_text(prefs_js.read_text())
    if not opted_out:
        keep.append(OPT_OUT)
    prefs_js.write_text("\n".join(keep) + "\n")
    print(f"  fixed; the old file is kept as {backup.name}")


def main() -> None:
    check = "--check" in sys.argv
    if (
        not check
        and subprocess.run(["pgrep", "-x", "firefox"], capture_output=True).returncode == 0
    ):
        sys.exit("Firefox is running. Close it (Ctrl+Q), then run this again.")
    rec = automation_prefs()
    for profile in profiles():
        fix(profile, rec, check)


if __name__ == "__main__":
    main()
