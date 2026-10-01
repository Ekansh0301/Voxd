"""
Build the TARS avatar web app from your Cubism SDK for Web download.

    .venv/bin/python -m tars.ui.live2d.build

Live2D's licence doesn't allow redistributing their SDK, so the repo holds only
TARS's own files (this folder). This script copies the official Demo sources
from your SDK copy into a build folder, applies a few small patches (each must
match exactly once, so an SDK update fails loudly instead of half-working),
drops in TARS's entry point and lip-sync source, and bundles it with Vite.

Output: ~/.local/share/tars/avatar/app (served to the Qt window as tars://app/).
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from tars import TARS_HOME

HERE = Path(__file__).resolve().parent
AVATAR = TARS_HOME / "avatar"
BUILD = AVATAR / "build"
APP = AVATAR / "app"
SDK = Path(os.environ.get("TARS_CUBISM_SDK", TARS_HOME / "opt" / "CubismSdkForWeb-5-r.5"))
MODEL_RUNTIME = AVATAR / "models" / "mao_pro" / "runtime"

PATCHES: dict[str, list[tuple[str, str]]] = {
    "lappdefine.ts": [
        (
            r"export const ResourcesPath = '[^']*';",
            "export const ResourcesPath = 'tars://avatar/live2d/';",
        ),
        (
            r"export const ShaderPath = '[^']*';",
            "export const ShaderPath = 'tars://avatar/shaders/WebGL/';",
        ),
        (
            r"export const ModelDir: string\[\] = \[[^\]]*\];",
            "export const ModelDir: string[] = ['mao_pro'];",
        ),
        (r"export const DebugLogEnable = true;", "export const DebugLogEnable = false;"),
        (
            r"export const ViewMaxScale = [\d.]+;",
            "export const ViewMaxScale = 4.0;",
        ),  # allow upper-body zoom
        (r"LogLevel\.LogLevel_Verbose", "LogLevel.LogLevel_Warning"),
    ],
    "lappview.ts": [
        # no demo background image or model-switch gear icon
        (
            r"(public initializeSprite\(\): void \{)",
            r"\1\n    return; // TARS: no background/gear sprites",
        ),
        (r"this\._gear\.isHit\(", "this._gear && this._gear.isHit("),
        # framing set by TARS's main.ts; re-applied whenever the view re-initialises (resize)
        (
            r"this\._viewMatrix\.scale\(LAppDefine\.ViewScale, LAppDefine\.ViewScale\);",
            "const tz = (window as any).__tarsZoom ?? LAppDefine.ViewScale;\n"
            "    this._viewMatrix.scale(tz, tz);\n"
            "    this._viewMatrix.translate(0, (window as any).__tarsY ?? 0);",
        ),
    ],
    "lappsubdelegate.ts": [
        (
            r"gl\.clearColor\(0\.0, 0\.0, 0\.0, 1\.0\);",
            "gl.clearColor(0.0, 0.0, 0.0, 0.0); // TARS: transparent",
        ),
    ],
}
OURS = ["main.ts", "lappwavfilehandler.ts"]  # replace the Demo's versions


def patch(src: str, name: str) -> str:
    for pattern, repl in PATCHES.get(name, []):
        src, n = re.subn(pattern, repl, src)
        if n != 1:
            sys.exit(f"patch failed for {name}: /{pattern}/ matched {n} times (SDK changed?)")
    return src


def main():
    demo = SDK / "Samples" / "TypeScript" / "Demo" / "src"
    core = SDK / "Core" / "live2dcubismcore.min.js"
    for p in (demo, core, MODEL_RUNTIME / "mao_pro.model3.json"):
        if not p.exists():
            sys.exit(f"missing {p}: unpack the Cubism SDK for Web and the Mao sample first")

    (BUILD / "src").mkdir(parents=True, exist_ok=True)
    for f in demo.glob("*.ts"):
        text = f.read_text() if f.name not in OURS else (HERE / f.name).read_text()
        (BUILD / "src" / f.name).write_text(patch(text, f.name))
    for name in ("index.html", "package.json", "vite.config.mts"):
        shutil.copy(HERE / name, BUILD / name)

    # Files the page loads at runtime through tars://avatar/
    (AVATAR / "core").mkdir(exist_ok=True)
    shutil.copy(core, AVATAR / "core" / core.name)
    shutil.copytree(SDK / "Framework" / "Shaders", AVATAR / "shaders", dirs_exist_ok=True)
    live2d = AVATAR / "live2d"
    live2d.mkdir(exist_ok=True)
    link = live2d / "mao_pro"  # the Demo expects <dir>/<dir>.model3.json
    if not link.exists():
        link.symlink_to(MODEL_RUNTIME, target_is_directory=True)

    env = {**os.environ, "TARS_CUBISM_SDK": str(SDK), "TARS_AVATAR_APP": str(APP)}
    if not (BUILD / "node_modules" / ".bin" / "vite").exists():
        subprocess.run(["npm", "install", "--no-fund", "--no-audit"], cwd=BUILD, check=True)
    subprocess.run(["npx", "vite", "build"], cwd=BUILD, env=env, check=True)
    print(f"avatar app built: {APP}")


if __name__ == "__main__":
    main()
