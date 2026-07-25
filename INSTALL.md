# Install Guide (Windows)

**Curse** (Cursor Assist) is an assistive-technology tool that helps someone with
limited hand movement or tremor place and click the mouse pointer on their own
screen.

There is nothing to install. It is a **single file** — download it, double-click
it, done. No Python, no packages, no setup.

---

## Step 1 — Download it

Go to the **[Releases page](https://github.com/slayfoids/curse-assist/releases)**
and download **`CursorAssist-v1.0.2.exe`** (or whatever the newest version is)
from the latest release.

Put it anywhere you like — Desktop, Downloads, a USB stick. It doesn't matter,
and it doesn't need to stay in any particular folder.

> It's about **67 MB**, because it carries its own copy of Python and the vision
> library inside it. That's what lets it run on a PC with nothing installed.

---

## Step 2 — Run it

**Double-click `CursorAssist-v1.0.2.exe`.**

### The blue "Windows protected your PC" box

The first time you run it, Windows SmartScreen will show a blue box. This is
normal and happens for **every** program that hasn't been code-signed (which
costs a few hundred pounds a year). To get past it:

1. Click **More info**.
2. Click **Run anyway**.

Windows remembers the choice — you'll only see this once.

### What you should see

- A small black console window appears and stays open. **That's normal** — leave
  it. It shows the panel address and is where any error would appear.
- Your browser opens the **control panel**: an all-black page at
  `http://127.0.0.1:8756`, with cards for Motion, Click, Target colors, Region,
  Capture, Input control, and Hotkeys.

> **Press Right Shift at any time** to re-open or focus the panel tab. All
> settings save automatically and come back next time. (Hotkeys are rebindable —
> Right Shift still works as a normal Shift key too, so change it if that
> bothers you.)

To stop it: click **Quit** in the page, or close the console window.

---

## Step 3 — Point it at your target

Out of the box it watches **your screen**. Then:

1. Under **Target colors**, click **＋ Pick** — or **⦿ Eyedropper**, then click
   the exact pixel on screen whose colour you want to follow. Add as many
   colours as you like.
2. Adjust **Sensitivity** until the status dot (top-right) turns **green** when
   your target is on screen.
3. Leave **Body-part detection** off to guide straight to the colour. Turn it on
   only if you want to aim at a specific region — Head / Torso / etc. — of a
   drawn figure.
4. Turn the guidance **on** with the large button at the top of the panel, or
   press **F8**.
5. Move the mouse roughly toward the target — the pointer eases the rest of the
   way, and a click is issued automatically after the **Dwell time**.
6. If the user's hand tremor fights the guidance, turn on the pointer-steadying
   option in the **Input control** card.

### Two settings worth knowing

| Setting | What it does |
|---|---|
| **Snap after (ms)** | After the pointer rests on the colour for this long, aim refines to where the circle covers the *most* colour. **Set it to 0 for an instant snap** — best for targets that keep moving, since the timed version waits for the pointer to settle, which a moving target never allows. |
| **Activation: Toggle / Hold** | **Toggle** flips guidance on and off with F8. **Hold** keeps it live only while you hold a chosen key or mouse button (Mouse4 by default) — releasing it stops the pull instantly. |

### Using an OBS scene instead of your screen

If you'd rather it watched an OBS scene:

1. In **OBS**, click **Start Virtual Camera**.
2. In the panel's **Capture** card, switch the source to **OBS**.

---

## Step 4 — (Optional) Start it automatically at login

1. Press `Win + R`, type `shell:startup`, press Enter. The **Startup** folder
   opens.
2. Right-click the `CursorAssist-v...exe` file → **Copy**.
3. In the Startup folder, right-click → **Paste shortcut** (a shortcut, not the
   file itself — so the exe can stay where it is).

To undo, delete that shortcut from the Startup folder.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Blue "Windows protected your PC" box | Click **More info** → **Run anyway**. Expected for any unsigned program. |
| Antivirus flags or quarantines it | Also expected for an unsigned, self-extracting build. Restore it and add an exclusion for the file. The build is deliberately unpacked and unobfuscated so it can be inspected. |
| It closes instantly / nothing opens | Run it from Command Prompt (`cd` to the folder, then the exe's name) so the error stays on screen, and send a screenshot. |
| No target is ever found (`target: --`) | Raise **Sensitivity**, re-pick the colour with the eyedropper, or narrow the detection area in the **Capture** card. |
| Pointer lands slightly off the target | Set Windows display scaling to 100%, or capture the exact region you work in. |
| Hold button does nothing | Make sure **Activation** is set to **Hold** and a button is bound. Any binding failure is reported at the top of the panel. |
| Want to remove it | Close it, delete the exe, and remove the Startup shortcut if you made one. Settings live in `%LOCALAPPDATA%\CursorAssist` — delete that folder too for a clean sweep. |

---

## Running from source (developers)

Only needed if you want to change the code or build the exe yourself.

```bat
git clone https://github.com/slayfoids/curse-assist.git
cd curse-assist
py -m pip install -r requirements.txt
py -m cursor_assist
```

Requires Python 3.10+ with Tkinter (tick **"tcl/tk and IDLE"** and **"Add
python.exe to PATH"** in the Python installer).

Run the tests:

```bat
py -m pip install pytest
py -m pytest -q
```

Build the distributable exe:

```bat
py -m pip install pyinstaller
py tools/build_exe.py
```

That writes `dist/CursorAssist-v<version>.exe`, stamped from `__version__`
in `cursor_assist/__init__.py`. The build is defined by
[`CursorAssist.spec`](CursorAssist.spec) — plain and unobfuscated, console left
on so startup failures stay visible, UPX off because packing only trips
antivirus heuristics. To build a no-console version instead, set `console=False`
in the spec.

There is also a **background (no-console) mode** for the from-source install,
which runs under `pythonw.exe` — see `background/start_hidden.py` and
`Start Cursor Assist (background).cmd`.

---

Back to the overview: [README.md](README.md).
