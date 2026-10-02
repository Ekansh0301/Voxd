# Setting up TARS

TARS needs some one-time setup because Ubuntu on Wayland (rightly) doesn't let
an app read keys, take screenshots, type, or move other windows without asking.
Each step below says what it gives TARS and how to undo it.

**Needs:** Ubuntu 26.04 (GNOME 50, Wayland), an NVIDIA GPU with 4 GB or more,
its driver and the CUDA toolkit (`nvcc`), Python 3.11, cmake, git, and about
15 GB of disk. Models and binaries go to `~/.local/share/tars/`, never into the repo.

## 1. Models, llama.cpp and the Python environment

```bash
git clone https://github.com/Ekansh0301/Voxd.git tars && cd tars
bash scripts/setup.sh           # llama.cpp (CUDA, Pascal/MMQ kernels), llama-swap, models (~12 GB), .venv
bash scripts/gen_llama_swap.sh  # writes ~/.config/tars/llama-swap.yaml
```

`setup.sh` is safe to re-run and resumes interrupted downloads. It builds
llama.cpp with the MMQ kernel path, which prefills about 3× faster on GTX 16-series
cards than the default build. TARS starts the model server (llama-swap) itself;
you don't need to run it.

**Avatar:** Live2D's licence requires you to download two files yourself: the
[Cubism SDK for Web](https://www.live2d.com/en/sdk/download/web/) and the
[Mao sample](https://www.live2d.com/en/learn/sample/). Put both zips in `~/Downloads`;
`setup.sh` unpacks them and builds the avatar (`python -m tars.ui.live2d.build`).
None of Live2D's files enter this repo. Without them, run TARS with `--no-avatar`.

## 2. The `tars` command and app icon

```bash
bash scripts/install_launcher.sh   # ~/.local/bin/tars and the TARS entry in the app grid
```

## 3. Push-to-talk (Right Ctrl)

```bash
sudo bash scripts/install_pttd.sh  # read it first
```

A small sandboxed system service, `tars-pttd`, watches only the Right Ctrl key and
reports "down", "up" or "cancelled": nothing about any other key. That's why you
don't need to join the `input` group, which would let every program read every
keystroke. Without it, `tars --ptt stdin` uses Enter in the terminal instead.
Remove: `sudo systemctl disable --now tars-pttd.socket`.

## 4. Window focus: the TARS GNOME extension

```bash
bash scripts/install_gnome_extension.sh   # then log out and back in once
```

Lets TARS list your windows and bring one to the front, and nothing else. Wayland
gives apps no other way to do that, and TARS needs it to type into the right app,
sync Super Productivity, or search Spotube.
Remove: `gnome-extensions disable tars-windows@tars.local`.

## 5. Screenshots (for apps that hide their contents)

GNOME 50 only shows its "Allow screenshot?" prompt to the app in front, and TARS
has no window of its own, so grant it once by hand:

```bash
busctl --user call org.freedesktop.impl.portal.PermissionStore /org/freedesktop/impl/portal/PermissionStore org.freedesktop.impl.portal.PermissionStore SetPermission sbssas screenshot true screenshot org.tars.TARS 1 yes
```

It applies to TARS's own app id (`org.tars.TARS`) only; Flameshot and other apps
are unaffected. Revoke: the same command with `DeletePermission sss screenshot screenshot org.tars.TARS`.
To make TARS drop it after every capture instead, set `screen.keep_screenshot_permission: false`.

## 6. Keyboard and mouse

```bash
.venv/bin/python -m tars.perception.keyboard   # GNOME asks once: allow remote interaction
```

Approve the dialog. GNOME remembers it through a restore token kept in
`~/.local/share/tars/remote-desktop.token` (readable only by you), and shows a
remote-control icon in the top bar whenever TARS is using it.
Revoke: delete that file.

## 7. Your Firefox

Start Firefox from the **Firefox (TARS)** entry (TARS also starts it itself when it
needs to). It's your normal profile with remote control switched on for
localhost only; the address bar shows stripes while it is. If ordinary Firefox is
already open, TARS asks you to close it first.

## 8. VS Code (optional)

```bash
bash scripts/install_vscode_extension.sh   # reload open VS Code windows afterwards
```

A ~100-line extension that lets TARS read, never change, the active file, the
Problems list and recent integrated-terminal output, over a socket only you can
open. Remove: `code --uninstall-extension tars.tars-bridge`.

## 9. App-specific bits

- **Super Productivity:** Settings → Misc → *Enable local REST API* (for reminders
  and "what's my next task").
- **Spotube:** nothing needed. Spotube Connect is optional (faster for songs in your
  liked list), but when on it listens on your whole network with no password.
- **Microphone:** at 100% input volume the built-in mic clips, which garbles speech
  recognition; TARS warns at startup if it does. `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 45%`.

## Check it works

```bash
tars                       # hold Right Ctrl and say "what time is it?", or type in the box
.venv/bin/python -m pytest # unit tests
```

See [USAGE.md](USAGE.md) for what to say, and [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
if something doesn't respond.
