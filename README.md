# Color-Based Cursor Assist

An accessibility tool for people with limited hand movement and reduced pointing
accuracy. It captures the screen, detects colored shapes/outlines with OpenCV,
and **gently pulls the mouse cursor toward a selected target** so the user can
more easily interact with on-screen art — for example, tracing or clicking parts
of a hand-drawn human figure — without needing precise manual control.

The pull is a smooth, frame-rate-independent easing motion (never a snap), and
clicks fire by **dwelling** over a target rather than requiring a physical button
press. The control panel is a **sleek local web app** that opens in your browser.

> Windows only. Cursor movement and clicks go through the standard `SendInput`
> API — the same path a real mouse uses. The one optional exception is the
> "block my mouse" feature, which uses a standard Windows low-level mouse hook
> (see [Input control](#controls)); it is off by default. Screen-pixel input
> only — nothing reads another process's memory.

---

## Install

Requires Python 3.10+ (with Tkinter, which ships with the standard Windows
CPython installer).

```bash
py -m pip install -r requirements.txt
```

If `keyboard` fails to install (it needs admin on some systems), the app still
runs — the global hotkey falls back to a window-focused key binding.

> **New to this / setting it up for someone else?** Follow the full step-by-step
> [**INSTALL.md**](INSTALL.md) — it covers installing Python, getting the
> project, and running in background mode, with nothing assumed.

## Run

```bash
py -m cursor_assist
```

This starts the engine and opens the **web control panel** in your default
browser (a local server on `http://127.0.0.1:8756`, loopback only — never exposed
to the network). Or double-click / run `run.py`.

Options:

```bash
py -m cursor_assist --port 9000     # use a different port
py -m cursor_assist --no-browser    # don't auto-open; just print the URL
py -m cursor_assist --tk            # legacy Tkinter panel instead of the web UI
```

### Run in the background (no console window)

Day-to-day use, with **no terminal window** left open — just the control panel.
Each launch gets a **randomly generated instance name** (also the process name in
Task Manager). Double-click **`Start Cursor Assist (background).cmd`**, or:

```bash
py background\start_hidden.py
```

Stop it with **`Stop Cursor Assist.cmd`**, or:

```bash
py background\stop_hidden.py
```

Under the hood this runs the app with `pythonw.exe` (the windowless interpreter)
via a randomly named copy, and records the name + PID in `.runtime\instance.json`
so it's easy to find and stop. It is transparent, not stealthy — the control
panel stays visible and nothing auto-starts at boot unless you set that up
yourself (see [INSTALL.md](INSTALL.md#step-7--optional-start-automatically-when-you-log-in)).
See [background/start_hidden.py](background/start_hidden.py) for details.

### Capture options

```bash
# Capture a specific desktop region (left top width height):
py -m cursor_assist --region 100 100 1280 720

# Capture monitor 2 full-screen:
py -m cursor_assist --monitor 2

# Read a composited OBS scene via the OBS Virtual Camera instead of the desktop:
py -m cursor_assist --source obs --obs-index 0
```

The OBS virtual camera is the **default and recommended** source — start
**Start Virtual Camera** in OBS before launching.

---

## The control panel (web UI)

A sleek, all-black web panel that opens in your browser, organised into cards.
Everything is exposed and **persists between runs** (saved to
`%LOCALAPPDATA%\CursorAssist\settings.json`). **Press Right Shift** any time to
re-open/focus the panel tab.

Cards: **Motion** (smoothness, max speed, target steadiness) · **Click** (mode:
dwell/trigger/off, dwell time, radius, trigger key) · **Field of view** (pull
radius + crosshair circle) · **Target colors** (multiple colors, picker,
eyedropper, sensitivity, min area, thin-outline) · **Target region** (six
buttons) · **Capture source** (Screen/OBS, monitor, region, index, detail) ·
**Detection area** (pixel ROI to search within) · **Input control** (block my
mouse) · **Hotkeys** (all rebindable, with Record).

## How to use it

1. Launch the app — the panel opens in your browser. Start OBS's virtual camera.
2. Add one or more **Target colors**: **＋ Pick** a color, or use the
   **⦿ Eyedropper** and click the exact pixel on screen you want to match. Add as
   many colors as you like. Tune **Sensitivity** until the status dot turns green
   — detection runs live even before you turn the pull on, so you can tune first.
3. By default it **just tracks the color** (pulls toward the colored blob nearest
   the cursor). Turn on **Body-part detection** only if you want to target a
   specific region (Head / Torso / Arms / Legs) of a figure.
4. Toggle **PULL** on (button or your **Toggle pull** hotkey, default **F8**).
5. Move roughly toward the target; the cursor glides the rest of the way. Hold
   near it and, after the **Dwell time**, a click fires automatically.

Set **Click mode** to *Trigger key* for an instant click on a key press, or *Off*
to click manually. The on-screen **FOV circle** shows the radius around the
cursor within which the assist engages.

### Controls

| Control | What it does |
|---|---|
| **PULL ON/OFF** | Master toggle for the pull assist (also the *Toggle pull* hotkey). |
| **Smoothness** | 0 = snappy, 1 = long buttery glide. Motion is frame-rate independent. |
| **Max speed** | Cap on cursor speed (px/sec, up to 30000). Higher = catches fast-moving colors and keeps them centered. |
| **Target steadiness** | Jitter smoothing on the target point (EMA). |
| **Click mode** | **Dwell** (auto-click after holding on target), **Trigger key** (press a key to click instantly), or **Off** (manual). |
| **Dwell time** | In dwell mode, how long to hold before a click fires (50–1500 ms). |
| **Trigger key** | In trigger mode, the (recordable) key that fires an instant click. |
| **Click radius** | How close counts as "on target" for dwell. |
| **Repeat clicks** | Keep auto-clicking while on target (auto-clicker), at the chosen interval. |
| **Click interval** | Time between repeated clicks (30–1000 ms). |
| **Pull radius** | FOV: only assist toward colors within this circle of the cursor (0 = whole screen). |
| **Show crosshair circle** | Draw the FOV circle over the cursor (green when locked on). |
| **Target colors** | Add multiple colors via picker or on-screen **eyedropper**; click a swatch to remove. |
| **Sensitivity** | Global HSV tolerance applied to all colors (higher = matches more). |
| **Min area** | Ignores colored specks smaller than this (px²). |
| **Detect thin outlines** | Detect colored *outlines*, not just filled color. |
| **Body-part detection** | Off (default) = track the color directly. On = target a body region of a figure. |
| **Target region** | When body-part detection is on, which region (Head/Torso/Arms/Legs) to aim at. |
| **Capture source** | OBS virtual cam (recommended) or desktop; monitor / region / OBS index. |
| **Detail (speed)** | Detection downscale — lower = faster, higher = more detail. |
| **Detection area** | Restrict color detection to a pixel box (X/Y/W/H); 0 0 0 0 = whole frame. Works for OBS too. |
| **Block my mouse** | While the bot is moving, suppress your *physical* mouse so a shaky hand doesn't fight it (uses a Windows low-level mouse hook; clicks still pass). |
| **Hotkeys** | Rebind either hotkey — type it or click **Record** and press the keys. |
| **Reset / Quit** | Restore defaults · stop the app. Changes autosave. |

> **Hotkeys are fully rebindable.** Defaults are **Right Shift** (show panel) and
> **F8** (toggle pull). Click **Record** and press any key or combo to rebind.
> Note Right Shift also still works as a normal Shift while typing — rebind it if
> that bothers you.

---

## How it works

```
 DETECTION thread (runs as fast as the source allows)
   OBS vcam / mss ─▶ (crop ROI) ─▶ downscale ─▶ HSV mask (all colors) ─▶ contours
       ─▶ color mode: aim at nearest color blob's center   (default)
       ─▶ body-part mode: split figure into regions, aim in the active one
       ─▶ EMA smoothing ─▶ publishes the current target ─┐
                                                          │  (shared target)
 MOVEMENT thread (~180 Hz, independent)                   ▼
   read latest target ─▶ time-based ease: new = cur + (target-cur)·α(dt)
       ─▶ SendInput relative move (speed-capped) ─▶ dwell timer ─▶ click
       ─▶ (optional) suppress physical mouse while pulling
```

**Why it's smooth:** motion and detection are **decoupled**. The cursor is eased
by a dedicated ~180 Hz loop using *time-based* smoothing (`α = 1 − e^(−dt/τ)`),
so it glides analog-smoothly regardless of how fast detection runs. Detection
runs on a downscaled frame for speed and only *publishes* a target; a slow
detection frame no longer makes the cursor stutter. Smoothing on the **target**
(not the cursor) kills detection jitter; the speed cap prevents snapping.

### Modules

| File | Responsibility |
|---|---|
| `config.py` | Thread-safe shared state (`AppState`, `ColorTarget`, capture config). |
| `capture.py` | `mss` screen capture and OBS virtual-camera capture. |
| `detection.py` | HSV masking (multi-color), contour finding, shape classification. |
| `segmentation.py` | Split a figure's bounding box into named body regions. |
| `targeting.py` | Nearest in-region contour point + EMA (downscale-aware). |
| `cursor.py` | `SendInput` relative move + click; time-based ease; dwell machine. |
| `mouse_block.py` | Optional low-level hook to suppress physical mouse while pulling. |
| `overlay.py` | Transparent click-through crosshair / FOV-circle overlay. |
| `controller.py` | Decoupled detection + ~180 Hz movement threads. |
| `webserver.py` | Local HTTP server + JSON API for the web UI. |
| `webpage.py` | The self-contained dark web control panel (HTML/CSS/JS). |
| `gui.py` | Legacy Tkinter panel (`--tk`). |
| `persistence.py` | Save/load all settings to JSON so they persist. |

## Body-region heuristics

Regions are derived proportionally from the figure's bounding box: Head is the
top ~15%, Torso the next ~40% (center width), Arms the outer thirds of that same
band, and Legs the bottom ~45% split on the vertical midline. **L-Arm / R-Arm**
and **L-Leg / R-Leg** are labeled from the *viewer's* perspective. These are
intentionally coarse — good enough to bias the cursor, and the operator can
switch regions at any time.

## Notes & limitations

- Best results come from a clean, saturated target color against a contrasting
  background. Tune tolerance if detection flickers.
- Windows display scaling (DPI) can offset coordinates; run at 100% scaling, or
  capture the region you actually work in, for the tightest mapping.
- The tool assumes the largest colored contour is the figure. Busy scenes with
  large same-colored areas may need a tighter color/tolerance or a capture region.

## Testing

Pure-logic pieces (segmentation, color helpers, glider convergence, persistence)
have unit tests that run without a display or camera:

```bash
py -m pytest -q
```

### Aim simulation

`tools/aim_sim.py` drives the **real** engine (detection + movement threads,
targeting, easing, dwell) against a synthetic colored target using a *virtual*
cursor — no display, OBS, or real mouse. It measures how close the cursor gets to
the color (static) and how well it follows a moving target (tracking):

```bash
py tools/aim_sim.py
```

Current results — static final error **~1 px** (settles ~0.4 s), moving-target
error **~2 px** on default settings. This harness is how the "doesn't fully reach
the color" bug (an easing step that rounded sub-pixel moves to zero and stalled
~13 px short) was found and fixed. Accuracy comes from a sub-pixel accumulator
with pixel-exact lock-on, plus a velocity **lead** that aims ahead of a moving
target (and is disabled when the target is static, so it never costs precision).

## License

MIT — see [LICENSE](LICENSE).
