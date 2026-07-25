# Curse v1.0.7

**Best-coverage snap fixed, any mouse sensitivity, a drag-a-box detection area,
and every number back on screen.**

Download **`CursorAssist-v1.0.7.exe`** below. Single file, nothing to install —
it carries its own Python, OpenCV and numpy. Windows 10/11, 64-bit.

Your existing settings are picked up automatically and migrated where needed.

---

## ⭕ Best-coverage snap no longer ruins the aim

This is the big one. The snap circle was borrowing your **field-of-view circle**
— 250 px across by default — so it was answering "where is this colour thickest"
about a 500 px-wide patch of screen rather than about your target.

Measured with two figures 220 px apart, locked on the left one:

| Snap circle | Aim drift before | Aim drift now |
|---|---|---|
| 150 px | **89 px off** — landing *between* the two, on neither | 5 px |
| 250 px (the shipped default) | **47 px off** | 0 px |
| 400 px | 20 px off | 0 px |

The coverage search is now **confined to the blob you are locked on**, so it
refines the aim inside the current target and cannot walk it onto a neighbour.
It also keeps doing its actual job: on a figure whose centroid is dragged off by
a trailing limb, it still moves the aim **43 px onto the torso**.

- New **Snap circle** setting, separate from the drawn FOV circle. Leave it at
  **0** and it sizes itself from the target — about a third of its narrow side.
- It now declines to act when the circle is bigger than the area being searched.
  Every placement scores the same there, the winner is decided by floating-point
  noise, and it was adding a constant **~8 px diagonal bias** whenever
  target-follow shrank the scanned window.

## 🎚️ Works the same on a fast mouse and a slow one

Windows scales every movement by your pointer-speed setting — from **1/32× to
3.5×** — and *"enhance pointer precision"* bends it further depending on how
fast the pointer is already moving. That last part is why a single learned
number could never fit it: it is wrong at one end of the range or the other.

Curse now **reads both settings directly** and models the result as a curve, so
the very first movement is already the right size instead of being learned from
a wrong start. Measured across the full range against a simulated input path:

| | before | now |
|---|---|---|
| Travel wasted hunting (highest setting, precision enhancement on) | **1.96×** | **1.02×** |
| Resting jitter, lowest setting | **72.9 px** | **0 px** |
| Resting jitter, lowest setting + precision enhancement | **5.4 px** | **0 px** |
| Resting jitter, highest setting | **1.0 px** | **0 px** |
| Overshoot | 0.4–0.7 px | **0 px** |

Settling is faster in six of ten cases and unchanged in two. The two that read
slower were previously "arriving" by flying straight past the target — which is
what that 1.96× travel figure was.

- At a high pointer speed **one step of your mouse moves several pixels**, so
  the pointer cannot be placed closer than that by anything. It now settles
  there instead of stepping back and forth across the target, and the panel
  tells you how fine it can actually get.
- **Fixed: Extra gain worked backwards.** It divided the requested distance
  instead of multiplying it, so turning up the control labelled *"raise this if
  it still under-reaches"* made it under-reach further.
- The panel now shows your Windows setting (e.g. `6/11 (1x) + enhance
  precision`) so you can see what it is compensating for.

## 🎨 The top half of the Sensitivity slider was unusable

Sensitivity widened hue, saturation and value together, pinning saturation and
value at maximum two-thirds of the way along. Past that, any pixel with roughly
the right hue matched however washed out or nearly black it was.

On a cluttered frame:

| Sensitivity | Screen matched, before | Blobs, before | Target found? | Now |
|---|---|---|---|---|
| 20 | 2.7% | 2 | yes | 1.1% |
| 28 | **55.0%** | **606** | yes | 1.1% |
| 36 | 69.8% | 137 | **NO** | 1.1% |
| 45 | 84.8% | 3 | **NO** | 2.7% |

Hue now widens generously while saturation and value stay bounded, so the
**target is found at every setting** across the whole slider. The panel shows
what percentage of the frame your colours match — anything past about a quarter
is too much to aim at. Existing settings files are migrated automatically.

## ◫ Pick the detection area by dragging a box

Instead of typing four desktop-pixel coordinates, **Select on screen** dims the
desktop and lets you drag over the part you want watched, like a snipping tool.

- Live size readout while you drag, **Esc** cancels, a single click selects
  everything.
- Multi-monitor aware — a region on a second screen can be picked directly.
- **Crop a screenshot** does the same over a frozen frame inside the panel, for
  when reaching across the screen is the hard part.
- **Show the area on screen** outlines it on the desktop so you can see what is
  being watched.
- Exact numbers still available under *"Type exact numbers"*.

## 🖥️ Numbers were off the edge of the panel

Every slider's value sat **94 px past the right edge of its card** and was cut
off — **15 rows** across Guidance, Targeting and Detection. Sliders refuse to
shrink below their built-in width, so the row simply did not fit in the card.

Each row is now two lines: name and value on top, slider full width underneath.
Verified at **every window width from 400 px to 1600 px across all five tabs —
zero clipped rows**. The help bubbles were being cut off by the same card edges
and now float above everything, staying inside the window at any size.

---

## Also in this release

- 159 automated tests, up from 102 — including the two-figures-apart snap case,
  the full pointer-sensitivity range, the sensitivity mapping, and the
  detection-area geometry.
- The pointer-calibration readout no longer stays blank until guidance is
  switched on, which is exactly when you would be checking it.
- The legacy Tkinter panel (`--tk`) shares the corrected sensitivity mapping.

## Upgrading

Replace the exe. Settings carry over. Two things behave differently on purpose:

- **Snap circle** starts on *auto* rather than following your FOV circle. If you
  had deliberately tuned the FOV circle to control snapping, set **Snap circle**
  explicitly instead.
- **Sensitivity** values above ~24 now mean something usable rather than
  matching most of the screen; if you had wound it up to compensate, you can
  wind it back down.

**Full detail:** [CHANGELOG.md](CHANGELOG.md)
