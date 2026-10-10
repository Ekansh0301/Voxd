# Troubleshooting

Problems met while building TARS on this laptop, and their fixes. TARS logs to the
terminal you start it from, or to `~/.local/share/tars/logs/tars.log` when started
from the app icon.

## Speech

**It mishears me** ("Telling here Jew" for "tell me a joke"). Usually the microphone
is clipping: at 100% input volume the built-in mic flattens loud speech, and
TARS warns about it at startup. Lower it: `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 45%`.
To measure, run `tars --save-audio` for a few phrases; clips go to
`~/.local/share/tars/recordings/`.

**CUDA out of memory.** Whisper and the 4B model share 3.7 GB. The llama-swap
template already uses `-np 1 -ub 256`; if it happens anyway, speech recognition
falls back to the CPU for the rest of the session (slower, still works).

## Speed

**Replies are slow.** Check you're plugged in (the GPU drops to ~5 tok/s on battery)
and not overheating (`get_system_info` reports temperatures). The first answer after
start-up is slower while the prompt cache is primed (~11 s, done in the background).

**"CUDA 12 libraries missing", or the model server won't start** (llama-swap.log:
`libcudart.so.12: cannot open shared object file`). TARS's llama.cpp build and Whisper
need CUDA 12's runtime, cuBLAS and cuDNN, and take them from NVIDIA's wheels in
`.venv`, not the system (which may have CUDA 13). Reinstall them with the command
TARS prints, then `bash scripts/gen_llama_swap.sh` if `~/.config/tars/llama-swap.yaml`
predates 2026-10-10. After an NVIDIA driver update the first answer is slow once
(~1 min) while the GPU code is recompiled and cached.

## Firefox

**"Firefox is open normally."** TARS can only drive Firefox started as
*Firefox (TARS)*. Close Firefox and ask again; TARS starts it.

**Normal Firefox behaves oddly** (it doesn't offer to save passwords, popups aren't
blocked, the bookmarks bar is gone, add-ons don't update, sync fails). With remote
control on, Firefox switches on its test settings and undoes them only on a clean
quit; if it was killed, they stayed in your profile. Close Firefox and run
`python3 scripts/firefox_prefs_fix.py`. It removes them, keeps a backup of `prefs.js`,
and sets `remote.prefs.recommended = false` so they're never applied again. The
Firefox (TARS) launcher runs it on every start.

**Every browser action fails with "Server terminated early with status 0".**
The driver's geckodriver was a truncated download in `/tmp` (wiped at reboot).
TARS now uses the geckodriver inside the Firefox snap via
`~/.local/share/tars/opt/geckodriver/`; if that link is missing, restart TARS
(it recreates it).

**Typing into a page hangs.** Firefox draws nothing while it's hidden behind other
windows, and key presses wait for a frame. TARS brings Firefox forward before typing;
this needs the GNOME extension.

## Desktop

**TARS can't bring an app to the front / type into it.** The GNOME extension isn't
loaded: run `scripts/install_gnome_extension.sh`, then log out and back in.
Check: `gnome-extensions info tars-windows@tars.local` should say `ACTIVE`.

**"TARS has no screenshot permission."** Grant it once (the `busctl` command in
[SETUP.md](SETUP.md)). GNOME 50 can't show the prompt to TARS because it has no window.

**Flameshot asks "Allow screenshot?" every time, or flashes before opening.** Not
TARS: since GNOME 50, apps outside Flatpak need a screenshot permission, and with one
GNOME captures (flash and click) and hands the image to Flameshot. Allowing it in the
dialog stores it for *every* non-Flatpak app (app id `""`). To allow Flameshot alone,
store it for `org.flameshot.Flameshot` (the SETUP.md command with that app id), and
make the Print shortcut start Flameshot under that id:
`sh -c 'exec systemd-run --user --scope --quiet --unit=app-gnome-org.flameshot.Flameshot-$$ flameshot gui'`.
Remove a shared grant with `busctl … DeletePermission sss screenshot screenshot ""`.

**An app's buttons can't be read.** Electron apps (Termius, Super Productivity) need
`--force-renderer-accessibility`; `config/apps.yaml` launches them with it. Flutter
apps (Spotube) expose nothing, so TARS uses OCR and vision (`click_on_screen`).
GTK 4 popup menus aren't exposed to accessibility either.

**Killing a snap app fails with "permission denied".** Snap confinement blocks
signals from other processes. Stop it through its systemd scope:
`systemctl --user stop snap.<name>.<...>.scope` (see `/proc/<pid>/cgroup`).

## Apps

**Spotube plays the wrong song.** TARS takes the top search result; add the artist
("Believer by Imagine Dragons"). The window must be large (maximised): clicks are
placed by Spotube's layout.

**Reminders appear in Super Productivity but don't alarm.** Its REST API can't set
its own alarm, so TARS adds one as a systemd user timer: check with
`systemctl --user list-timers 'tars-reminder-*'`. Timers don't survive a reboot.

## Network

**Downloads hang.** IPv6 is broken on some networks here; the setup script uses
`curl -4 --http1.1`.
