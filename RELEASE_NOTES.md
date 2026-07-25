# Curse v1.0.9

**Keeps up with moving targets, the aim marker holds still, dwell clicks
instantly — and every setting is typable with a recommended value.**

Download **`CursorAssist-v1.0.9.exe`** below. Single file, nothing to install —
it carries its own Python, OpenCV and numpy. Windows 10/11, 64-bit.

Your existing settings carry over.

---

## 🏃 It no longer trails behind things that move

The pointer steered purely by *how far off it was*. Something steering that way
physically cannot sit on a target moving at a constant speed — it settles
wherever the error is big enough to generate exactly the speed needed to keep
pace, which is a fixed distance behind.

That is why turning up **Max speed** and **Accel limit** never helped: those cap
how fast it may *correct*, not how far behind it *settles*. No value of either
changes the answer.

The movement loop now also drives the pointer at the target's own velocity
(**Follow speed**), removing the error instead of trading against it:

| target speed | lag before | lag now |
|---|---|---|
| 200 px/s | 11.1 px | **8.6 px** |
| 400 px/s | 9.4 px | **4.4 px** |
| 700 px/s | 8.7 px | **5.4 px** |
| noisy animating figure, 300 px/s | 9.7 px | **4.1 px** |

The old position-lead was doing a rough version of the same job, so it is cut
back to cover only how stale a reading is by the time it is acted on. Left as
it was, the two compensated for the same lag twice — 30 px of lag *and* 36 px
of overshoot at 1000 px/s, against 8.9 / 13 once rebalanced.

Combined with the scan-rate work in 1.0.8, lag against a 500 px/s target is now
**2.1 px at 240 scans/s**, from 12.3 px originally.

## 🎯 The aim marker stops dancing

Every filter in the tool reacted to **how fast** the target was moving — and
camera noise looks fast to all of them. On an animating figure with ragged
edges the aim wandered **9 px and changed 20 times a second** while the figure
stood perfectly still, and this is what that did to the existing settings:

| setting tried | aim wander |
|---|---|
| defaults | 9 px |
| jitter floor 3.0 | 6 px |
| target steadiness 0.05 | 5 px |
| smoothness 0.90 | 6 px |
| precision zone 120 / slowdown 0.1 | 6 px |

None of them could fix it, because they were all adjusting the wrong variable.

New **Aim lock-in** reacts to how far the point has *strayed* rather than how
fast it is going — which is what actually separates noise from movement, since
noise stays bounded and averages out while movement accumulates. Same scene:
**9 px → 1 px of wander, 20 changes a second → 1**. It fades out entirely once a
target is genuinely travelling, so it never costs you tracking.

## ✦ Dwell clicks: instant, and reliable

- **0 ms now means 0 ms.** The minimum was 50 ms, and even that waited an extra
  frame. Set it to 0 and it clicks the moment the pointer arrives.
- **Clicks that just never happened.** The click radius was a single threshold,
  so the aim jitter above pushed the pointer in and out of it many times a
  second, restarting the countdown each time. Leaving now takes a larger
  excursion than arriving did, so a dwell rides out the wobble.
- The panel shows the **live distance from pointer to target** next to your
  radius, so a radius set too small to ever be satisfied is a number you can
  see rather than "it just doesn't click sometimes". Range widened to 3–200 px.

## ⌨️ Type any setting, and see what it should be

- **Every slider has a number box.** Type an exact value, paste one in, or read
  one off to send to someone. Out-of-range numbers are pulled back into range
  rather than refused, invalid text is flagged as you type and reverts, and the
  box always shows the value that actually landed.
- **Every setting carries a recommended value** and a one-line reason, and
  clicking it puts the setting back. After hunting through six sliders looking
  for a fix, nothing on screen used to tell you which ones were fine to begin
  with.

## 🔊 Volume control for the cues

`winsound.Beep` has no volume, so the cues were fixed at whatever Windows chose
— startling on some machines. They are now synthesised as tones in memory,
which makes volume simply a multiplier on the samples. There is a **Cue
volume** slider and a **Test** button. Nothing is written to disk.

## 🔎 Also

- The **snap circle is sized from the target's thickness**, not its bounding
  box. An L-shaped target 200 px across is made of 40 px bars; sizing from the
  box gave a circle three times too big — big enough that every position scored
  the same and the aim stayed in the empty inside corner. It now searches the
  whole target too, which for a concave shape it previously never reached.
- 195 automated tests, up from 179.

## Upgrading

Replace the exe; settings carry over. Two new controls start switched on
because they are the fixes above: **Aim lock-in** (10 px) and **Follow speed**
(1.00), both under *Guidance → Fine tracking*. If you preferred the old feel,
set them to 0.

**Full detail:** [CHANGELOG.md](CHANGELOG.md)
