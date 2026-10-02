# TARS tools

Generated from the code by `scripts/gen_tools_doc.py`; don't edit by hand.
66 tools. Tiers decide what happens when the model calls one (see [SAFETY.md](SAFETY.md)); a tool can also ask for approval itself for a risky case, such as replacing a file or clicking a Send button.

| Tier | Meaning |
|---|---|
| T0 | read-only, runs at once |
| T1 | reversible, runs and is logged |
| T2 | asks you first |
| T3 | always asks (send, submit, delete…) |

## System, timers and notifications

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `cancel_timer` | T1 | Cancel a running timer. | `timer_id` |
| `get_datetime` | T0 | Current local date and time. | none |
| `get_system_info` | T0 | CPU, RAM, disk, temperatures, GPU, battery, power and top processes. | none |
| `list_timers` | T0 | Show running timers. | none |
| `set_timer` | T1 | Start a countdown timer or reminder. Give the duration in the units the user said. | `hours`?, `minutes`?, `seconds`?, `label`? |

## Files

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `copy_path` | T1 | Copy a file or folder exactly (use this for backups, never read+write). | `source`, `destination` |
| `find_files` | T0 | Find files by name pattern (e.g. '*.pdf', '*invoice*'), newest first. | `pattern`, `under`? |
| `list_dir` | T0 | List a folder's contents with sizes and dates. | `path`?, `show_hidden`? |
| `make_dir` | T1 | Create a folder. | `path` |
| `move_path` | T1 | Move or rename a file or folder (one item per call). | `source`, `destination` |
| `read_file` | T0 | Read a text file. | `path` |
| `trash_path` | T1 | Move a file or folder to the Trash (restorable; asks first). | `path` |
| `write_file` | T1 | Create a text file (overwriting needs overwrite=true and approval). | `path`, `content`, `overwrite`? |

## Shell (sandboxed)

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `run_command` | T0 | Run a bash command in a sandbox. Read-only commands run immediately; anything that changes files or the system asks the user first. sudo is never available. | `command`, `timeout`? |

## Desktop, apps, volume, media

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `media_control` | T1 | Control music/video playback in any player. | `action` |
| `notify` | T1 | Show a desktop notification. | `message` |
| `open_app` | T1 | Launch an installed desktop application by name. | `name` |
| `open_url` | T1 | Open a website in Firefox: a URL or a known site name (outlook, youtube, github...). To search or play something on the user's sites, use open_site instead. | `url` |
| `set_volume` | T1 | Set the volume (level 0-100), change it (e.g. +10 / -10), or mute/unmute. | `level`?, `change`?, `mute`? |

## Reading and operating app windows

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `click` | T1 | Click one button/link/item shown by the last read_screen, by its name. | `name` |
| `click_sequence` | T1 | Click several elements in order, by name, e.g. ['1', '2', '×', '7', '=']. | `names` |
| `list_windows` | T0 | List open windows. | none |
| `read_screen` | T0 | Read what is in the active window (or a named one): buttons, fields, text, with [ids]. | `window`? |
| `read_terminal` | T0 | Read the latest output of the terminal (tmux). | `lines`? |
| `type_into` | T1 | Replace the text of a field shown by the last read_screen, by its name. | `name`, `text` |

## Looking at the screen

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `look_at_screen` | T0 | Look at the screen image and answer a question about it. Use when read_screen shows too little. For small text, zoom with a region (top-left, top-right, center, ...). | `question`, `region`? |

## Memory

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `forget` | T1 | Delete a remembered fact by its number. | `fact_id` |
| `recall` | T0 | Search what the user told you before (facts, earlier conversations). Not for doing tasks: to do something, call its tool. | `query` |
| `remember` | T1 | Save a fact about the user or their preferences for future sessions. | `fact` |

## Your apps

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `add_reminder` | T1 | Add a task to Super Productivity, optionally with a reminder time in the user's words ('tomorrow at 9 am', 'in 30 minutes'). | `title`, `when`?, `notes`? |
| `list_apps` | T0 | The user's apps and what each is for. | none |
| `list_tasks` | T0 | The user's open tasks in Super Productivity: overdue, today, upcoming. Use for 'what's my next task', 'anything overdue?'. | none |
| `open_file` | T1 | Open a file in the right app (PDFs in Okular) or in a named app. | `path`, `app`? |
| `sync_tasks` | T1 | Sync Super Productivity (its Sync button). | none |
| `terminal_open` | T1 | Open a Ghostty terminal in a folder, optionally running a command. | `folder`?, `command`? |
| `termius_connect` | T1 | Open Termius and connect to one of the user's saved hosts (e.g. ada, turing). | `host` |
| `vscode_open` | T1 | Open a folder or file in VS Code, optionally at a line. | `path`, `line`? |

## Coding

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `apply_patch` | T1 | Apply a unified diff that changes one or more files (e.g. a fix across a project). Checks it applies, shows the change, asks first, keeps backups. | `patch`, `folder`? |
| `check_code` | T0 | Check Python code for errors: syntax, then ruff / pylint / mypy if available. | `path` |
| `edit_file` | T1 | Change code in a file: replace one exact, unique snippet (copy it from read_file) with new text. Shows the change and asks first; keeps a backup. | `path`, `find`, `replace` |
| `undo_edit` | T1 | Revert the last edit_file or apply_patch change. | none |

## Spotube

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `play_music` | T1 | Play music in Spotube: a song ('Believer', 'death bed by Powfu') or one of the user's playlists ('phonk', 'liked songs'). Both empty = resume. Pause/next/previous: media_control. | `song`?, `playlist`? |

## Keyboard and window focus

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `focus_window` | T1 | Bring an open app's window to the front, e.g. 'spotube', 'firefox'. | `name` |
| `press_keys` | T1 | Press keyboard shortcuts in the focused window, e.g. 'ctrl+s', 'Enter', 'ctrl+k, Escape' (comma-separated, in order). | `keys`, `window`? |
| `type_text` | T1 | Type text with the keyboard into the focused window (for apps whose fields type_into can't reach), optionally then a key like Enter. | `text`, `then_key`?, `window`? |

## What's on screen

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `screen_context` | T0 | What the user is looking at right now, gathered for its app (terminal output, the open file and its errors in VS Code, the page in Firefox). Use first for 'explain this error', 'what's on my screen', 'why did this fail'. | `question`? |

## Research (hidden browser)

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `deep_research` | T0 | Research a question properly: search, read the top few pages, and return the relevant passages with numbered sources to cite. For questions needing several sources. | `question`, `sources`? |
| `read_page` | T0 | Read a web page's text in the hidden browser (e.g. a web_search result). | `url` |
| `web_search` | T0 | Search the web (DuckDuckGo) in a hidden browser; returns titles, links and snippets. For research and questions needing current information. Doesn't touch the user's Firefox. | `query` |

## Clicking by sight

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `click_on_screen` | T1 | Click something by how it looks, for apps that read_screen can't see into (e.g. Spotube): a text label ('Search') or a described icon ('the play button'). Prefer read_screen + click when that works. | `target`, `window`?, `index`? |

## Your Firefox (TARS)

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `web_back` | T1 | Go back in the current tab. | none |
| `web_click` | T1 | Click a link/button on the page by its name from web_read. | `name` |
| `web_fill` | T1 | Fill a form field on the page by its name from web_read. | `name`, `text` |
| `web_key` | T1 | Press a key on the page, e.g. Enter, Escape, Tab, ArrowDown, Control+a. | `key` |
| `web_read` | T0 | Read the current Firefox tab: mode 'elements' (buttons, links, fields by name) or 'text'. | `mode`? |
| `web_switch` | T1 | Switch to a Firefox tab by its index. | `tab` |
| `web_tabs` | T0 | List the tabs open in Firefox. | none |
| `web_type` | T1 | Type into the focused field on the page, optionally then a key like Enter. | `text`, `then_key`? |

## ask_ai

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `ask_ai` | T1 | Ask a web AI (ChatGPT by default, else Gemini or Claude) a question in the user's Firefox and return its answer. For hard questions or when the user asks an AI site. Personal details are removed before sending. | `question`, `site`? |

## documents

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `index_documents` | T0 | Index a folder's documents (text, notes, PDFs) so search_documents can find them. | `folder`? |
| `search_documents` | T0 | Search the user's own documents and PDFs for a topic; returns passages with the file they're from. | `query` |

## forms

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `fill_form` | T1 | Fill the form on the current Firefox page from the user's saved profile (name, email, phone, roll number, college...). Never submits; returns what was filled for review. | none |

## routines

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `create_routine` | T1 | Save a named routine the user describes: a list of requests run in order when they say its name (e.g. 'study mode': open my project in VS Code; play my phonk playlist). | `name`, `steps` |
| `forget_routine` | T1 | Delete a named routine, or a learned one by its #number. | `name` |
| `list_routines` | T0 | The user's named routines and the ones TARS learned from finished tasks. | none |

## site_actions

| Tool | Tier | What it does | Parameters |
|---|---|---|---|
| `open_site` | T1 | Open one of the user's sites, optionally at a shortcut: youtube search/play/subscriptions, github notifications/repo/search/pulls/issues, leetcode problem/search, cheatsheet topic (QuickRef, e.g. 'git'), linkedin notifications/messages/search/jobs. | `site`, `action`?, `query`? |

`?` = optional parameter.
