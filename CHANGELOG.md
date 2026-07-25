# Changelog

All notable changes to **Curse (Cursor Assist)**. Newest first.

The version is stamped from `__version__` in
[`cursor_assist/__init__.py`](cursor_assist/__init__.py) — it names the built
exe and is shown in the panel header and the console banner, so you can always
tell which build you are running.

---

## v1.0.7

**Best-coverage snap fixed, sensitivity handled at both extremes, a
drag-a-box detection area, and every number back on screen.**

- **Best-coverage snap no longer drags the aim onto whatever is nearby.** The
  snap circle borrowed the field-of-view circle — 250 px by default — so "where
  is this colour densest" was answered about a 500 px-wide patch of screen
  rather than about the target. Measured with two figures 220 px apart, the aim
  settled **47 px off** the locked one, and at some spacings landed *between*
  the two, pointing at neither. The search is now confined to the locked blob,
  so it refines the aim inside the current target and cannot walk to a
  different one, and it has its own **Snap circle** setting that defaults to
  sizing itself from the target. Same scene now: **≤ 5 px at every radius**,
  while still moving the aim 43 px onto the torso of a figure whose centroid
  was dragged off by a trailing limb.
  - It also declines to act when the circle is bigger than the area being
    searched. Every placement scores alike there, the winner is decided by
    floating-point noise, and it was adding a constant ~8 px diagonal bias
    whenever target-follow shrank the scanned window.
- **Pointer sensitivity: both ends of the slider, not just the low one.**
  Windows scales movement by the pointer-speed setting (1/32× to 3.5×) and
  bends it further with "enhance pointer precision", which makes the scaling
  depend on how fast the pointer is already moving — something a single learned
  number cannot represent. The engine now **reads both settings** and models the
  gain as a curve, so the first move is already the right size instead of being
  learned from a wrong start. Measured against a simulated input path across
  the full range:
  - travel wasted on hunting: **1.96× → 1.02×** at the highest setting;
  - resting jitter: **72.9 px → 0** at the lowest, **5.4 px → 0** with
    precision enhancement on, **1.0 px → 0** at the highest;
  - overshoot: **0 px everywhere** (was 0.4–0.7 px);
  - settling is faster in six of ten cases and unchanged in two. The two that
    read slower were previously "arriving" by flying past the target — which is
    what the 1.96× travel figure was.
  - At a high pointer speed one step of the mouse moves several pixels, so the
    pointer cannot be placed closer than that. It now settles there instead of
    stepping back and forth across the target, and the panel says how fine it
    can actually get.
  - **Extra gain worked backwards.** It divided the requested distance instead
    of multiplying it, so turning up the control labelled "raise this if it
    still under-reaches" made it under-reach further.
- **Detection sensitivity is usable across its whole range.** The mapping
  widened hue, saturation and value together, pinning saturation and value at
  maximum two thirds of the way along — past that, any pixel with roughly the
  right hue matched however washed out or nearly black it was. On a cluttered
  frame, sensitivity 28 matched **55% of the screen across 606 blobs**, and past
  36 **the target stopped being found at all**. Hue now widens generously while
  saturation and value stay bounded: the target is found at **every** setting
  and coverage stays near 1%. The panel shows what percentage of the frame your
  colours match, so a selection that is too loose is visible rather than
  guessed at. Existing settings files are migrated.
- **Detection area is now a drag-a-box tool.** "Select on screen" dims the
  desktop and takes a dragged rectangle the way a screen-capture tool does,
  with a live size readout, Escape to cancel, and multi-monitor support. There
  is also "Crop a screenshot" for cropping a frozen frame inside the panel, and
  the area is drawn on the desktop so you can see what is being watched. Typing
  four numbers still works, tucked under "Type exact numbers".
- **Every value is back on screen.** A range input keeps an intrinsic width of
  about 129 px and `flex:1` does not let it shrink below that, so each control
  row demanded 355 px inside a 248 px card and the number on the end was cut
  off by the card edge — **15 rows, each 94 px out of view**. Rows are now a
  grid: label and value on one line, slider full width beneath. Verified at
  every width from 400 px to 1600 px across all five tabs: **zero clipped
  rows**. The help bubbles were being clipped by the same card edges and now
  float above everything, staying inside the window at any size.

## v1.0.6

**Searching for a target is ~5× faster, and the panel is grouped into tabs.**

- **Acquisition no longer grabs the whole screen.** The follow window only
  existed once a target was locked, so with guidance on and nothing found yet
  the engine fell back to a full-screen grab (~67 ms) and sat near **10 scans a
  second**, whatever the scan rate was set to. It now searches a window around
  the pointer, sized from the pull radius. That is not a shortcut: targets
  outside the pull radius are already discarded during selection, so the rest
  of the screen was being captured and scanned only for the result to be thrown
  away. Measured end to end with guidance on: **10 → 52 scans/s** against a
  60 Hz display.
- **The Detection readout says when it is idling.** A low number with guidance
  switched off is a deliberate slow tick, not a stall. It now reads
  `12/s · idle`, and `52/s · following` when locked onto something.
- **Panel tabs.** Fourteen cards on screen at once was too much to take in.
  They are grouped into **Guidance / Targeting / Clicking / Detection / Setup**,
  the status header stays visible, and the chosen tab is remembered.

> If **Pull radius** is set to `0` (unlimited), the search window cannot apply
> and scanning returns to full-screen speed. That is inherent — "unlimited"
> means the whole screen really is in play.

## v1.0.5

**Scan rate is adjustable, and matches your monitor by default.**

- New **Scan rate** setting. At `0` (default) it follows the display's actual
  refresh rate, re-read every few seconds so plugging in a different monitor is
  picked up while running — a 60 Hz laptop panel and a 240 Hz desktop each get
  the right value with no configuration.
- Matching the display is the right default because a screen produces new
  content at its refresh rate and no faster: scanning above it re-reads frames
  that have not changed. An explicit value still wins, because the capture
  source is not always the display — an OBS virtual camera runs at whatever OBS
  is set to.
- The panel shows the target rate next to the achieved one. The rate is a
  ceiling, not a promise: if a grab takes longer than the target period the loop
  simply runs slower, and showing both makes that visible.

## v1.0.4

**Capture, not detection, was the bottleneck.**

- v1.0.3 cropped to the follow window *after* grabbing, which cut the detection
  work and left the real cost untouched. The capture backends now take the
  follow window themselves: a 260 px window grabs in ~17 ms versus ~67 ms for
  the full screen — **4.4× faster**.
- Detection of a full frame costs ~3 ms; the grab costs ~67 ms. The grab was
  always the ceiling.

## v1.0.3

**Aim line, in-panel help, and two input fixes.**

- **Dwell clicks that never fired.** The timer was cancelled the moment the
  target went missing for a single frame — which happens on any colour flicker
  or capture stutter — so on a jumpy source the click could never complete. A
  dwell in progress now rides out brief dropouts. Moving off the target still
  cancels immediately.
- **Record binding the wrong key.** Recording only ever watched the keyboard,
  so pressing a mouse button left it waiting, and it then captured whichever
  key arrived next — usually the Windows key. Recording now polls real key
  state, so mouse buttons and keys go through one path. Esc cancels.
- **Aim guide line.** A cyan line from the pointer to the exact pixel being
  steered for, with the goal ringed. Purely visual — it exists so you can move
  *with* the assist instead of unknowingly fighting it.
- **Target follow (adaptive ROI).** Once locked, only a window around the target
  is scanned, at full resolution.
- **Plain-language help** on 19 settings, a **Latest updates** card, a
  first-paint loader, and a new monoline logo.

## v1.0.2

**Hold rewritten, low-sensitivity support, spasm damping.**

- **Hold works.** It was going through a global event hook that failed three
  separate silent ways — a quick re-press being rewritten as a double-click, an
  X-button decode that raises on some mice inside the hook callback, and hook
  contention. It now reads the button state directly, and reports a button it
  cannot use instead of doing nothing.
- **Low mouse sensitivity.** Windows scales relative mouse input by the pointer
  speed slider and "enhance pointer precision", so on a low setting a requested
  move landed short and the pull crawled. The engine measures the real ratio and
  compensates.
- **Precision zone** — the pointer eases off near the target and settles instead
  of darting the last stretch.
- **Acceleration limit** — caps how sharply the pointer can speed up, so one bad
  detection frame cannot fling it.
- **Screenshot colour picker** — freeze a frame and click the exact pixel.
- **Motion response** and **Jitter floor** split following a moving target from
  steadying a still one.
- Version stamping through the build, panel and console banner.

## Earlier

- **Tracking overhaul.** The velocity estimate lagged ~100 ms, so on a target
  moving back and forth the pointer was thrown the wrong way on every direction
  change. Fixed at the source; smoothing is now frame-rate independent, and the
  teleport guard no longer misfires on genuinely fast targets.
- **Instant snap.** Snap delay can be set to 0 for targets that keep moving.
- Single-target lock, best-coverage snap, body-part aim, saved configs, and the
  live-motion simulation suite.
