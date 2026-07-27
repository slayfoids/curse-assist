# Curse v1.0.10 — final release

Download **`CursorAssist-v1.0.10.exe`** below. Single file, nothing to install —
it carries its own Python, OpenCV and numpy. Windows 10/11, 64-bit. Existing
settings carry over.

This release closes out the work in 1.0.7 – 1.0.10. Everything below was
measured before and after, against a simulation harness that runs the real
engine.

---

## What changed across these four releases

### Tracking

| | before | now |
|---|---|---|
| lag behind a 200 px/s target | 11.1 px | **4.0 px** |
| lag behind a 400 px/s target | 9.4 px | **5.3 px** |
| lag behind a 700 px/s target | 8.7 px | **6.7 px** |
| lag at 500 px/s, 240 scans/s | 12.3 px | **2.1 px** |
| aim wander, still noisy figure | 9 px @ 20 changes/s | **1 px @ 1/s** |
| reaction to a target appearing elsewhere | 418 ms | **63 ms** |
| travel wasted hunting, highest mouse sensitivity | 1.96× | **1.02×** |
| resting jitter, lowest mouse sensitivity | 72.9 px | **0 px** |
| body-part mode, two figures on screen | 4583 px/s peak | **229 px/s** |

### The specific faults found

- **Best-coverage snap** borrowed the field-of-view circle (250 px), so it
  answered "where is this colour densest" about half the screen rather than
  about the target. Two figures 220 px apart: the aim settled 47 px off the
  locked one, and at some spacings landed between the two, on neither.
- **The target lock's grace period** was the single largest source of latency in
  the pipeline: when the locked blob missed a frame the aim kept pointing where
  it used to be for 0.4 s. Frozen aim followed by a lurch is also exactly what
  "spasming" looks like — the two complaints were one bug.
- **A proportional controller cannot sit on a moving target.** It settles
  wherever the error generates just enough speed to keep pace — a fixed distance
  behind. **Max speed** and **Accel limit** cap how fast it corrects, not how far
  behind it sits, which is why raising them never helped.
- **Every filter keyed off speed**, and detection noise looks fast to all of
  them. No combination of smoothness, steadiness, jitter floor or precision zone
  got the aim wander below 6 px, because they were all adjusting the wrong
  variable.
- **Detection sensitivity above ~24 was unusable** — at 28 it matched 55% of the
  screen across 606 blobs, and above 36 the target stopped being found at all.
- **Body-part aiming ran down a completely separate path** and inherited none of
  the above fixes.
- **"Extra gain" was inverted** — the control labelled "raise this if it
  under-reaches" made it under-reach further.

### Added

- **Drag-a-box detection area**, snipping-tool style, multi-monitor aware.
- **Share codes** — a config as one pasteable string (269 characters for a
  fully tuned setup), loadable on anyone else's install. No account, no server.
- **Any mouse sensitivity** — reads Windows' pointer speed and acceleration
  and models them as a curve, so the first move is the right size at 1/32× or
  3.5×.
- **Typable values and a recommended setting** on every control.
- **Cue volume** with a test button.

207 automated tests, up from 102.

---

## The honest limitation

If it still feels like it lags, this is the part worth knowing, because no
amount of further tuning changes it.

The tool works by reading pixels off the screen. That imposes a floor:

1. The app draws a frame. On a 60 Hz display that frame is on screen for
   **16.7 ms**.
2. Curse captures it — on average half a scan interval old (**~4 ms** at 120
   scans/s).
3. Detection, then the movement tick: **~5 ms**.
4. The cursor moves — and you don't *see* it until the display draws its next
   frame: **another 16.7 ms**.

So the minimum round trip you can perceive is roughly **25–35 ms on a 60 Hz
display**, and about two thirds of that is the display itself, not the software.
Measured tracking lag is now 5.3 px at 400 px/s — that is **13 ms of target
travel, less than a single display frame**. The pointer is closer to the target
than one frame of your monitor can show.

What that means practically:

- **The largest remaining lever is your monitor.** A 120 Hz or 144 Hz panel
  halves the two display terms above, and the scan rate follows it
  automatically. That is a bigger improvement than anything left in the code.
- **Anything reading the screen has this floor.** It is not specific to this
  implementation; it is what "look at the screen, then move the pointer" costs.
- If the requirement is to feel like there is no delay at all on a 60 Hz
  display, screen capture is the wrong mechanism for it, and more tuning will
  not get there. I would rather say that plainly than keep shipping
  improvements against a target the approach cannot reach.

The numbers above are real and reproducible from the test suite. Whether they
add up to something useful for you is your call, and I would not argue with you
if the answer is no.

**Full detail:** [CHANGELOG.md](CHANGELOG.md)
