# Color-Based Cursor Assist

An accessibility tool for people with limited hand movement and reduced pointing
accuracy. It captures the screen, detects colored shapes/outlines with OpenCV,
and **gently pulls the mouse cursor toward a selected target** so the user can
more easily interact with on-screen art — for example, tracing or clicking parts
of a hand-drawn human figure — without needing precise manual control.

The pull is a smooth easing motion (never a snap), and clicks fire by **dwelling**
over a target rather than requiring a physical button press.

> Windows only. All cursor control goes through the standard `SendInput` API —
> the same path a real mouse uses. No DLL injection, no hooking, no reading of any
> other process's memory. Screen-pixel input only.

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

or double-click / run `run.py`.

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

For the OBS source, start **Start Virtual Camera** in OBS first.

---

## How to use it

1. Launch the panel (it stays always-on-top).
2. Click **Pick color…** and choose the color of the outline/shape you want to
   target. Adjust **Color tolerance** until the target is reliably picked up
   (the `target: yes` status turns green when a target is found).
3. Pick a **Target region** with the big buttons — Head / Torso / L-Arm / R-Arm /
   L-Leg / R-Leg. The cursor will only be pulled toward contour points inside
   that region of the detected figure.
4. Toggle **Pull** on (button or the global hotkey **Ctrl+Alt+Space**).
5. Move roughly toward the target; the cursor eases the rest of the way. Hold
   near the target and, after the **Dwell time**, a click fires automatically.
   A short beep signals that a dwell has started.

Turn **Auto dwell-click** off to keep the pull assist but click manually.

### Controls

| Control | What it does |
|---|---|
| **Pull ON/OFF** | Master toggle for the pull assist (also **Ctrl+Alt+Space**). |
| **Pull strength** | Easing factor per frame (0.1–0.5). Higher = stronger pull. |
| **Dwell time** | How long to hold near a target before a click fires (200–1500 ms). |
| **Click radius** | How close counts as "on target" for dwell. |
| **Color tolerance** | Widens the HSV match around the picked color. |
| **Target region** | Restricts the pull to one body region of the figure. |
| **Auto dwell-click** | Master enable for automatic clicking (off = manual only). |
| **Detect thin outlines** | Detect colored *outlines*, not just filled color. |

---

## How it works

```
 mss / OBS vcam ─▶ HSV color mask ─▶ findContours ─▶ largest = "the figure"
                                                        │
                        proportional body-region split ─┤ (Head/Torso/Arms/Legs)
                                                        ▼
        nearest contour point in the active region ─▶ EMA smoothing ─▶ target
                                                        │
       SendInput relative move: cur += (target-cur)*pull, capped per frame
                                                        │
                       dwell timer within click radius ─▶ SendInput click
```

The loop runs in a background thread at ~60 Hz; the Tkinter GUI owns the main
thread. Smoothing is applied to the **target** point (not the cursor) so noisy
detection doesn't make the pull twitch, and per-frame travel is capped so even a
strong pull never visibly snaps.

### Modules

| File | Responsibility |
|---|---|
| `config.py` | Thread-safe shared state (`AppState`, `ColorTarget`, capture config). |
| `capture.py` | `mss` screen capture and OBS virtual-camera capture. |
| `detection.py` | HSV masking, contour finding, shape classification. |
| `segmentation.py` | Split a figure's bounding box into named body regions. |
| `targeting.py` | Pick the nearest in-region contour point; EMA smoothing. |
| `cursor.py` | `SendInput` relative move + click; dwell-click state machine. |
| `controller.py` | The 60 Hz capture → detect → pull → click loop. |
| `gui.py` | Always-on-top Tkinter control panel + global hotkey. |

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

Pure-logic pieces (segmentation math, config/color helpers) have unit tests that
run without a display or camera:

```bash
py -m pytest -q
```

## License

MIT — see [LICENSE](LICENSE).
