# Using TARS

Start it with `tars` (or click TARS in the app grid). A Live2D avatar appears at the
bottom right, and a TARS icon in the top bar.

## Talking and typing

- **Talk:** hold **Right Ctrl**, speak, let go. TARS starts answering in about
  1.6 s and speaks while it works.
- **Type:** click the *Type to TARS…* box under the avatar and press Enter. Typed
  turns skip speech recognition, so they're quicker.
- **Subtitles** under the avatar show what TARS heard (or what you typed) and what
  it's saying, in step with its voice.
- **Approvals:** before anything risky TARS asks, for example *"Should I move
  old.log in Downloads to the Trash? Say yes or no."* Answer with Right Ctrl or by
  typing yes/no. If it wants to do something you didn't ask for, right after
  reading a file or page, it says so first: *"Careful, you didn't ask for this…"*.

## Stopping TARS

- **Tap Right Ctrl** (a short press) while TARS is busy: it stops at once, lets go of
  any keys it was holding, and ends any command it was running.
- Or choose **Stop what TARS is doing** in the top-bar menu, or type `stop`.
- While TARS is clicking or typing for you, an **orange border** runs round the
  screen saying *"TARS is in control · tap Right Ctrl to stop"*. Your clicks still
  go through it.

The top-bar menu also has *Type a message*, *Show / hide avatar* and *Quit TARS*.
Drag the avatar with the left mouse button.

## What you can ask

| Area | Try |
|---|---|
| Chat | "Tell me a joke", "What can you do?", "Humor 40 percent" |
| Files | "What's in my Downloads?", "Find PDFs in Downloads", "Move the PNGs on my Desktop into Pictures/screens", "Delete old.log" (goes to the Trash) |
| Your screen | "Explain the error on my screen" (terminal, VS Code, Firefox, other apps), "What's on my screen?" |
| Coding | "Check app.py for errors", "Fix the bug in calc.py" (shows the change, asks first), "Undo that", "Open my project folder in VS Code" |
| Apps | "Open lecture5.pdf" (Okular), "Open a terminal in Downloads", "Connect to ada in Termius", "Open Software Updater" |
| Super Productivity | "Remind me to submit the assignment tomorrow at 9", "What's my next task?", "Anything overdue?", "Sync my Super Productivity" |
| Music | "Play Believer", "Play my phonk playlist", "Play my liked songs", "Pause the music", "Next song" |
| Web | "Open YouTube", "Ask ChatGPT what the GATE exam is", "What tabs do I have open?" |
| Research | "Look up the latest stable Python version" (a hidden browser; your Firefox isn't touched) |
| System | "Set the volume to 30", "How much disk space do I have?", "What's using the most CPU?", "Set a timer for 10 minutes" |
| Memory | "Remember that my favourite editor is VS Code", "What's my favourite editor?" |

## Things TARS won't do

- Open or read **Moodle, IMS or Portals** (your college sites).
- Type **passwords**, or read secrets such as `~/.ssh`.
- **Delete permanently**: deleting always means the Trash.
- Use `sudo` or disk tools; it tells you the command to run yourself.
- Send, submit, post or pay without asking you first.

## Tips

- Keep the laptop **plugged in** for agent work: on battery the GPU slows down about 7×.
- The first answer after starting takes a few seconds longer while TARS loads its prompt.
- For a song in a particular version, say the artist too: "Believer by Imagine Dragons".
- `tars --no-avatar` runs without the avatar; `tars --ptt stdin` uses Enter instead of
  Right Ctrl; `tars --save-audio` keeps your clips locally for speech-recognition tests.
