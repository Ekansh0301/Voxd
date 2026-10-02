# Safety and privacy

TARS controls your computer, so the rules that keep it safe are written in code,
not left to the model. A small model can be talked into things; the policy can't.

## Local first

- Everything runs on the laptop: speech recognition, the model, speech, memory.
- The microphone records only while you hold Right Ctrl.
- TARS goes online only when you ask for something online (a website, research via
  DuckDuckGo, a question to ChatGPT). Cloud model APIs aren't used.
- **Before asking a web AI**, your profile details, emails, phone numbers and long ID
  numbers are replaced with placeholders like `[EMAIL1]`, and put back in the answer
  you hear; the site never sees them.
- **Forms** are filled only from your profile, never with passwords, card, OTP, PIN,
  Aadhaar/PAN or bank details, and never submitted without your yes.

## Permission tiers

Every tool has a tier ([TOOLS.md](TOOLS.md) lists them):

| Tier | Examples | What happens |
|---|---|---|
| T0 | read a file, list a folder, read the screen | runs at once |
| T1 | create a folder, open an app, type into a field | runs, and is logged |
| T2 | replace a file, run a command that changes things | **asks you first** |
| T3 | Send / Submit / Pay / Delete buttons, Ctrl+Enter | **always asks** |

Tools also ask for risky cases themselves: clicking anything labelled send,
submit, delete, pay, post, confirm…; replacing a file; closing windows with
Alt+F4 / Ctrl+W.

## Refused outright (no approval can unlock these)

- **Your college sites** (Moodle, IMS, Portals): never opened, read or listed in
  search results ([config/sites.yaml](../config/sites.yaml)). Some other sites are
  open-only or navigate-only.
- **Passwords:** TARS never types into password fields, by accessibility role, by
  the page's own field type, or by the focused field.
- **Secrets:** `~/.ssh`, keyrings, browser profiles, `.env` files and similar are
  never read, and are hidden even inside the sandbox.
- **Permanent deletes:** `rm`, `rmdir`, `unlink`, `find -delete`, `git clean -f`.
  Deleting goes to the Trash (`trash_path`), so it can be undone.
- `sudo`, disk tools, piping downloads into a shell.
- Typing into **terminals** (commands go through the policy instead) and into
  Firefox's own settings pages.

## The sandbox

Shell commands are classified in code with `shlex`, not by the model. Read-only
commands run in a **bubblewrap** sandbox with the filesystem read-only and no
network. Anything else asks first, then runs in the sandbox with only your home
folder writable. Desktop apps can't be started from it (TARS uses its own launcher).

## Text from outside is data

Tool output (files, web pages, the screen, terminals) is labelled as data, not
instructions. The 4B model still occasionally follows planted text (about 1 run in
11 in the injection test), so there's a second line: if TARS asks to do something
you never mentioned, right after reading something, the question starts with
*"Careful, you didn't ask for this; it came right after reading readme.txt."*

## Staying in control

- **Tap Right Ctrl** (or *Stop* in the top-bar menu, or type `stop`) to stop at once.
  TARS releases any held keys and buttons and kills a running command.
- An **orange border** shows whenever TARS is clicking or typing.
- Edits made with `edit_file` keep a backup; `undo_edit` restores it.

## Permissions TARS holds, and how to revoke them

| Permission | Scope | Revoke |
|---|---|---|
| Push-to-talk (`tars-pttd`) | Right Ctrl down/up only | `sudo systemctl disable --now tars-pttd.socket` |
| Screenshots | app id `org.tars.TARS` only | `busctl … DeletePermission sss screenshot screenshot org.tars.TARS` ([SETUP.md](SETUP.md)) |
| Keyboard and mouse | RemoteDesktop portal; top-bar icon while active | delete `~/.local/share/tars/remote-desktop.token` |
| Window list and focus | GNOME extension | `gnome-extensions disable tars-windows@tars.local` |
| VS Code (read-only) | active file, Problems, terminal output | `code --uninstall-extension tars.tars-bridge` |
| Your Firefox | only when started as Firefox (TARS), localhost only | use the normal Firefox launcher |

Local connections are private too: the avatar bus needs a per-run token (passed
in the environment, not on the command line), and the VS Code sockets sit in
your private runtime folder.

## What's stored

`~/.local/share/tars/memory.db` holds facts you asked TARS to remember and past
turns (for "what did I say about…"). Logs are in `~/.local/share/tars/logs/`. Voice
clips are saved only if you run `tars --save-audio`. Nothing is uploaded.
