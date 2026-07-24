# Full Install Guide (Windows, step by step)

This guide takes you from a fresh Windows PC to running **Cursor Assist**,
including the **background (no-console) mode**. No prior Python experience needed
— just follow each step in order.

---

## Step 1 — Install Python

1. Go to <https://www.python.org/downloads/windows/> and download the latest
   **Windows installer (64-bit)** for Python 3.10 or newer.
2. Run the installer. On the **first screen**, before clicking Install:
   - ✅ Tick **"Add python.exe to PATH"** (bottom of the window).
   - Click **"Customize installation"**.
3. On the *Optional Features* screen, make sure **"tcl/tk and IDLE"** is ticked
   (this is Tkinter — the control panel needs it). Click **Next**.
4. On the *Advanced Options* screen, leave the defaults and click **Install**.
5. When it finishes, click **Close**.

### Verify Python installed

Open **Command Prompt** (press `Win`, type `cmd`, press Enter) and run:

```bat
py --version
```

You should see something like `Python 3.14.4`. If instead you get an error,
restart the PC and try again (PATH changes need a restart sometimes).

---

## Step 2 — Get the project onto the PC

**Option A — Download a ZIP (simplest):**

1. Open the repository page in a browser:
   <https://github.com/slayfoids/cursor-assist>
2. Click the green **`<> Code`** button → **Download ZIP**.
3. Right-click the downloaded ZIP → **Extract All…** → extract to somewhere easy
   like `C:\cursor-assist`.

**Option B — Clone with Git** (if you have Git installed):

```bat
git clone https://github.com/slayfoids/cursor-assist.git
cd cursor-assist
```

For the rest of this guide, "the project folder" means wherever you extracted or
cloned it (e.g. `C:\cursor-assist`).

---

## Step 3 — Install the required packages

1. Open **Command Prompt**.
2. Change into the project folder (adjust the path to match yours):

   ```bat
   cd C:\cursor-assist
   ```

3. Install the dependencies:

   ```bat
   py -m pip install -r requirements.txt
   ```

   This installs `mss`, `opencv-python`, `numpy`, and `keyboard`. It may take a
   minute. A note that `keyboard` scripts are "not on PATH" is harmless.

> **If `keyboard` fails to install**, the app still works — the global hotkey
> just falls back to only working when the control panel window is focused.

---

## Step 4 — First run (normal mode, to confirm it works)

```bat
py -m cursor_assist
```

The always-on-top **control panel** should appear — a small dark window with
sections for Assist, Click, Target color, Region, Capture, and Hotkeys. A console
window stays open too — that is expected in this mode; we remove it in Step 6.

> **Press Right Shift at any time to show or hide the panel.** All settings save
> automatically and come back next time you launch. (Right Shift also still works
> as a normal Shift key — if that bothers you, rebind it in the *Hotkeys* section.)

Quick check:
1. Click **Pick color…** and choose the color of the shape/outline you want to
   target.
2. Adjust **Color tolerance** until the status line shows **`target: yes`** in
   green when your target is on screen.
3. Pick a **Target region** (Head / Torso / etc.).
4. Click **Pull: OFF** to turn it **ON** (or press **Ctrl+Alt+Space**).
5. Move the mouse roughly toward the target — the cursor should ease the rest of
   the way, and clicking happens automatically after the **Dwell time**.

Close the window (or the console) to stop it. Once you're happy it works, move on
to background mode.

---

## Step 5 — (Optional) Run the tests

To confirm the core logic is healthy:

```bat
py -m pip install pytest
py -m pytest -q
```

You should see all tests pass.

---

## Step 6 — Run it in the background (no console window)

This is the mode you'll use day to day: **no black terminal window**, just the
control panel. Each launch is given a **randomly generated instance name**, which
is also the process name you'll see in Task Manager.

### Start it

Either **double-click** this file in the project folder:

> **`Start Cursor Assist (background).cmd`**

…or run from Command Prompt:

```bat
py background\start_hidden.py
```

You'll see a short confirmation (if run from a terminal) like:

```
Cursor Assist started in the background (no console window).
  instance name : k7f3q9x2m1a8p0dz
  process (PID) : k7f3q9x2m1a8p0dz.exe  (12345)
```

The control panel appears with **no console window** behind it. The chosen name
and process ID are saved to `.runtime\instance.json` inside the project folder so
you can always find and stop it.

### Stop it

Either **double-click**:

> **`Stop Cursor Assist.cmd`**

…or run:

```bat
py background\stop_hidden.py
```

This ends the background process and cleans up the temporary named copy.

### How the background mode works (for the curious)

- The app is launched with **`pythonw.exe`**, the windowless Python interpreter —
  that is what removes the console window.
- To make the process show your requested **random name**, the launcher copies
  `pythonw.exe` to `.runtime\<random-name>.exe` and runs through that copy.
- It is intentionally **not stealthy**: the app still shows its visible control
  panel, the name/PID are written to `.runtime\instance.json`, and the stop
  script removes everything. Nothing is installed to start at boot unless you do
  Step 7 yourself.

---

## Step 7 — (Optional) Start automatically when you log in

If you want Cursor Assist to be ready every time the PC starts:

1. Press `Win + R`, type `shell:startup`, press Enter. This opens your
   **Startup** folder.
2. Right-click **`Start Cursor Assist (background).cmd`** in the project folder →
   **Copy**.
3. In the Startup folder, right-click → **Paste shortcut** (not the file itself —
   a shortcut, so the project can stay where it is).

Now it launches at login. To undo, delete that shortcut from the Startup folder.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `py` is not recognized | Reinstall Python with **"Add to PATH"** ticked, then restart. |
| Control panel doesn't open in background mode | Run `py -m cursor_assist` in a console first — the error will be visible there. |
| No target is ever found (`target: --`) | Increase **Color tolerance**, re-pick the color, or capture a smaller region: `py -m cursor_assist --region LEFT TOP WIDTH HEIGHT`. |
| Cursor lands slightly off the target | Set Windows display scaling to 100%, or capture the exact region you work in. |
| Using an OBS scene instead of the desktop | Start **Start Virtual Camera** in OBS, then run `py -m cursor_assist --source obs`. |
| Want to fully remove it | Run the stop script, delete the project folder, and remove the Startup shortcut from Step 7 if you added one. |

---

Back to the overview: [README.md](README.md).
