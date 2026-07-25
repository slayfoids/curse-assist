# Curse v1.0.8

**The lock's latency and its "spasms" turned out to be the same bug. Plus
configs you can share with other people.**

Download **`CursorAssist-v1.0.8.exe`** below. Single file, nothing to install —
it carries its own Python, OpenCV and numpy. Windows 10/11, 64-bit.

Your existing settings carry over.

---

## 🔒 "Still a bit of latency" and "lock breaks it" were one problem

When the target you were locked onto wasn't spotted in a given frame, the aim
kept pointing at **where it used to be** for the full grace period before it
would look anywhere else. Measured end to end:

| | reaction to a target appearing somewhere new |
|---|---|
| lock **on** (as shipped) | **418 ms** |
| lock **off** | 10 ms |
| lock on, after this release | **63 ms** |

The delay tracked the grace constant exactly — 0.40 s of grace, 419 ms of
reaction. And what half a second of frozen aim followed by a lurch across the
screen *looks* like is the assist spasming. Both reports, one cause.

- The grace now depends on what is actually on screen: **0.06 s** when other
  targets are visible — continuing to aim at a memory while a real target sits
  there is a refusal to look at evidence — and **0.18 s** when nothing at all
  was detected and there is nothing better to aim at anyway.
- An empty **follow window** no longer counts as "the target vanished". It
  means the target left that box, which is simply what moving targets do. The
  window now widens on each consecutive miss instead of staring at the one
  place the target is known not to be. Target-follow's share of the reaction
  time went from **136 ms to 5 ms**.

## 🎯 It no longer throws the pointer past a target that isn't moving

A velocity estimate tells you how fast the detected *point* is moving, not
whether the target is going anywhere. A figure that keeps breaking into two
pieces behind cover makes that point flip between two centroids — which reads
as **900 px/s from something standing still**. The lead then threw the pointer
23 px *beyond the range of both positions it was flipping between*.

Speed is now gated by **straightness** — net displacement over distance
travelled, across a short window. Real travel scores near 1; vibration scores
near 0 because the path cancels itself out. Everything that reacts to speed
uses the gated figure.

| scenario | peak pointer speed before | after |
|---|---|---|
| target repeatedly splits in two | **3474 px/s** | **1973 px/s** (same as lock off) |
| fast target passing a decoy | 2.7× the travel of lock-off | matches lock-off |

All five stress scenarios now measure **identically with the lock on and off**.

## 🌀 Turning the lock off had been switching off all smoothing

Every frame reported itself as a brand-new target, so the filter, the deadband
and the lead reset on every single frame and the pointer rode raw detection
output. "Is this the same target?" is now answered the same way whether the
lock is on or off — which is why the two now behave the same everywhere.

## ⚡ Scanning faster now genuinely helps

Most of the pipeline lag is **fixed** — smoothing and easing take the same time
however often the screen is scanned — but the lead was weighted almost entirely
on the detection interval. Raising the scan rate therefore *removed*
compensation the pointer still needed:

| tracking lag, 500 px/s target | 60 scans/s | 120 | 240 |
|---|---|---|---|
| before | 12.3 px | 14.8 px | **16.3 px** (worse!) |
| after | 11.3 px | 10.0 px | **9.2 px** |

**Auto is now twice your display's refresh** — 120 a second on a 60 Hz screen.
Matching the refresh exactly is the right answer about *information* (a screen
shows no more than one new picture per refresh) but not about *latency*: a scan
lands at an arbitrary point inside the refresh interval, so sampling at the
refresh rate leaves half a frame of staleness on average, and sampling twice as
often halves it. It is nearly free — a follow-window scan costs 0.19 ms, so
120/s is about **2% of one core**.

## 🔗 Share your setup with someone else

Saved configs used to be a file on your PC plus a code that meant nothing on
anyone else's. **Get share code** now produces a single string that *contains*
the whole setup:

```
CURSE1-76WNCHjaZZDRCoMwDEV_ZeRZhk4n2l8ZoxTNbFltS1vdhvjvSzccDJ-SHnJvbrqA6KKaRVTW…
```

- **269 characters** for a fully tuned setup, **41** for a near-default one —
  paste it into a chat message and the other person gets your exact settings.
  No account, no server, no internet.
- One box takes **either** kind of code, so nobody has to know which sort they
  were handed. Anything loaded from a share code is saved on your PC too, so
  you can go back to it without hunting for the original message.
- Importing lays down defaults first, so you get the **sender's** setup rather
  than a mixture with whatever you had already changed.
- A checksum means a code your chat app truncated says *"that code is damaged,
  copy it again"* instead of half-loading a configuration. Decompression is
  bounded and incoming values are type-checked before they reach the engine —
  these arrive from other people now, so "it came out of JSON" stopped being a
  reason to trust them.

## 🔎 Also

- The status tile distinguishes **holding** from **locked**, so a pointer
  riding out a brief detection gap looks like what it is rather than looking
  stuck.
- 179 automated tests, up from 159.

## Upgrading

Replace the exe; settings carry over. One thing changes on purpose: **Scan
rate** at `0` (auto) now means twice your refresh rate rather than exactly your
refresh rate. If you would rather cap it, set the number you want explicitly.

**Full detail:** [CHANGELOG.md](CHANGELOG.md)
