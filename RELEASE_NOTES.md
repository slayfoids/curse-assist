# Curse v1.0.10

**Body-part aiming rebuilt on the locked target, and two ways the pointer could
be driven past the thing it was aiming at.**

Download **`CursorAssist-v1.0.10.exe`** below. Single file, nothing to install —
it carries its own Python, OpenCV and numpy. Windows 10/11, 64-bit.

Your existing settings carry over.

---

## 🧍 Body-part aiming was on a completely separate path

Everything fixed over the last three releases — the target lock, switch
detection, straightness gating, aim lock-in, follow speed — lived in the colour
tracking path. Body-part mode never went through any of it.

Instead it took whichever colour blob was **largest that frame**, kept no lock,
and never reported when it changed its mind. So with two people on screen the
aim jumped to whoever was momentarily bigger — and because the switch was never
declared, that jump was handed to the velocity estimate as though the target had
sprinted across the screen:

| scene | colour mode | body-part mode |
|---|---|---|
| two figures, peak pointer speed — **before** | 247 px/s | **4583 px/s** |
| two figures, peak pointer speed — **now** | 220 px/s | **229 px/s** |

It now runs the *same* selection as colour tracking and only then splits the
chosen target into regions, so it finally inherits the lot.

**A person is rarely one blob.** Different colours for hair and shirt, a dark
strap across the chest, part of the body behind cover — every one of those
arrives as separate pieces, and aiming at the biggest piece means aiming at
whichever one happens to win this frame. Nearby pieces are now assembled into
one figure — all of them still only the colours you picked, since nothing else
can be in the mask — with a distance limit so somebody standing nearby is not
absorbed into them.

**Regions only use that figure's own pixels.** The head / torso / leg bands used
to gather contour points from *every* shape on screen, so a second person
overlapping a band pulled the aim toward themselves. The aim would sit between
two people while reporting it was on one of their heads.

A target too small to divide sensibly now falls back to aiming at the target
itself, instead of inventing a "head" band across eight pixels.

## ↔️ The pointer can't be pushed past what it's aiming at

Two separate ways it could, both fixed:

**Overshoot.** The catch-up push (proportional to how far off it is) and the
keep-pace push (velocity feed-forward) are added together, and their sum can
exceed the gap remaining. Overshooting puts the error on the *other* side, so
the next tick drives back — that is an oscillation, and at a low smoothness
setting there is almost nothing damping it. A step is now capped at the distance
to the target, which makes overshoot arithmetically impossible and costs nothing
during pursuit.

**Standoff.** Worse and less obvious: feed-forward could push forward exactly as
hard as the error pulled back, parking the pointer a fixed distance *ahead* of
the target. With a wrong velocity estimate that measured **129 px past a
stationary target** — and no single-step cap can prevent it, because every
individual step is small and pointed the right way. Feed-forward now fades out
as the pointer draws level, so it can only ever help it catch up.

## 🎯 Aim lock-in now works on moving targets too

It used to switch off entirely above a travel speed, on the grounds that a
deadband would add tracking lag. That assumes detection noise stops when a
target starts moving. It does not — if anything a moving figure detects worse.

But the two are not alike: movement happens **along** a heading, while noise is
scattered in every direction. So the along-track correction is followed
outright, keeping tracking exact, and only the cross-track part is held.

Engaging that needs the target to have genuinely *got somewhere*, measured over
a window long enough to tell a sway from a journey — straightness is judged over
about 80 ms, and a figure whose limbs swing through a one-second cycle looks
perfectly straight over any 80 ms of it. A standing figure was registering as
travelling and having its own swaying passed straight through.

## 📊 Where tracking stands now

Against the version you first reported these on:

| | before | now |
|---|---|---|
| lag behind a 200 px/s target | 11.1 px | **4.0 px** |
| lag behind a 400 px/s target | 9.4 px | **5.3 px** |
| lag behind a 700 px/s target | 8.7 px | **6.7 px** |
| aim wander, still noisy figure | 9 px @ 20 changes/s | **1 px @ 1/s** |
| body-part mode, two figures | 4583 px/s peak | **229 px/s** |

207 automated tests, up from 195.

## Upgrading

Replace the exe; settings carry over. Nothing needs changing — if you had turned
**Body-part detection** off because it was unusable, it is worth another look.

**Full detail:** [CHANGELOG.md](CHANGELOG.md)
