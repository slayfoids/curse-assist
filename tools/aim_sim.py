"""Aim-training simulation — functionally test the pull/aim engine offline.

Drives the *real* :class:`AssistController` (detection + movement threads,
targeting, easing, dwell) against a synthetic scene: a colored target is drawn
into fake capture frames, and a *virtual* mouse stands in for the OS cursor. No
display, OBS, or real mouse is touched, so accuracy can be measured precisely.

Scenarios
---------
* **Static**: teleport the target to random spots; measure how close the cursor
  finally gets (this is the "does it fully go to the color?" test) and how long
  it takes to settle.
* **Tracking**: move the target along a path; measure steady-state tracking
  error once locked on.

Run:  ``py tools/aim_sim.py``   (exits non-zero if static accuracy is poor)
"""

from __future__ import annotations

import colorsys
import math
import os
import random
import statistics
import sys
import time

# Allow running as a plain script (py tools/aim_sim.py) from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

import cursor_assist.controller as ctrl
import cursor_assist.cursor as cur
from cursor_assist.config import AppState, ColorTarget

W, H = 1000, 700          # virtual screen
RADIUS = 18               # target disc radius (px)
TARGET_BGR = (0, 0, 255)  # red


# --- virtual mouse (replaces the Win32 cursor I/O) -------------------------
class VMouse:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.clicks = 0


vm = VMouse()
_tgt = {"x": W / 2.0, "y": H / 2.0}
# Simulated camera frame rate (OBS virtual cam is typically 30/60). grab()
# throttles to this so detection runs at a realistic rate, not an ideal 240.
_cam = {"fps": 60, "last": 0.0}


def _get_pos():
    return int(round(vm.x)), int(round(vm.y))


def _move_rel(dx, dy):
    vm.x = min(max(vm.x + dx, 0), W - 1)
    vm.y = min(max(vm.y + dy, 0), H - 1)


def _click():
    vm.clicks += 1


cur.get_cursor_pos = _get_pos
cur.move_relative = _move_rel
cur.click_left = _click


class FakeCapture:
    origin = (0, 0)

    def grab(self):
        # Throttle to the simulated capture rate so detection sees realistic
        # frame timing (screen capture is typically ~60+ fps).
        period = 1.0 / max(1, _cam["fps"])
        wait = _cam["last"] + period - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        _cam["last"] = time.perf_counter()
        f = np.zeros((H, W, 3), np.uint8)
        cv2.circle(f, (int(_tgt["x"]), int(_tgt["y"])), RADIUS, TARGET_BGR, -1)
        return f

    def close(self):
        pass


ctrl.make_capture = lambda cfg: FakeCapture()


def _cv_hsv(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return int(h * 179), int(s * 255), int(v * 255)


def make_state(smoothness, max_speed, ema):
    st = AppState()
    h, s, v = _cv_hsv(255, 0, 0)
    with st.lock:
        st.colors[:] = [ColorTarget(h=h, s=s, v=v, h_tol=15, s_tol=120, v_tol=120)]
        st.body_part_detection = False
        st.smoothness = smoothness
        st.max_speed = max_speed
        st.target_ema = ema
        st.auto_click_enabled = False
        st.click_mode = "off"  # measure aim only; don't fire clicks
        st.pull_radius = 0     # no FOV limit — measure raw aim accuracy
        st.detect_scale = 0.5
        st.pull_enabled = True
    return st


def run_static(st, trials=8, dur=1.3):
    c = ctrl.AssistController(st)
    c.start()
    finals, settles = [], []
    rng = random.Random(7)
    try:
        for _ in range(trials):
            tx = rng.uniform(120, W - 120)
            ty = rng.uniform(120, H - 120)
            _tgt["x"], _tgt["y"] = tx, ty
            vm.x, vm.y = rng.uniform(0, W - 1), rng.uniform(0, H - 1)
            c._glider.reset()
            c._tracker.reset()
            t0 = time.perf_counter()
            settle = None
            while time.perf_counter() - t0 < dur:
                if settle is None and math.hypot(vm.x - tx, vm.y - ty) < 3:
                    settle = time.perf_counter() - t0
                time.sleep(0.004)
            finals.append(math.hypot(vm.x - tx, vm.y - ty))
            settles.append(settle if settle is not None else float("nan"))
    finally:
        c.stop()
    return finals, settles


def run_tracking(st, dur=5.0, period=4.0):
    """Target circles the screen; `period` seconds per lap (smaller = faster)."""
    c = ctrl.AssistController(st)
    c.start()
    errs = []
    rx, ry = 240, 160
    _tgt["x"], _tgt["y"] = W / 2 + rx, H / 2
    vm.x, vm.y = W / 2, H / 2
    peak = 2 * math.pi * max(rx, ry) / period  # px/s at the fastest point
    t0 = time.perf_counter()
    try:
        while True:
            t = time.perf_counter() - t0
            if t >= dur:
                break
            _tgt["x"] = W / 2 + rx * math.cos(2 * math.pi * t / period)
            _tgt["y"] = H / 2 + ry * math.sin(2 * math.pi * t / period)
            if t > 1.2:  # after initial acquisition
                errs.append(math.hypot(vm.x - _tgt["x"], vm.y - _tgt["y"]))
            time.sleep(0.004)
    finally:
        c.stop()
    return errs, peak


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]


def report(name, smoothness, max_speed, ema, fps):
    _cam["fps"] = fps
    print(f"\n=== {name}  (smoothness={smoothness}, max_speed={max_speed}, "
          f"steadiness={ema}, capture={fps}fps) ===")
    finals, settles = run_static(make_state(smoothness, max_speed, ema))
    good_settles = [s for s in settles if not math.isnan(s)]
    print(f"  STATIC   final error px: mean={statistics.mean(finals):.2f}  "
          f"median={statistics.median(finals):.2f}  max={max(finals):.2f}")
    print(f"           settle<3px: {len(good_settles)}/{len(settles)} trials, "
          f"mean {statistics.mean(good_settles):.2f}s" if good_settles
          else "           settle<3px: none reached")
    for per, label in ((6.0, "slow"), (2.5, "fast")):
        errs, peak = run_tracking(make_state(smoothness, max_speed, ema),
                                  period=per)
        print(f"  TRACK {label:<4} (~{peak:.0f} px/s): mean="
              f"{statistics.mean(errs):.1f}  p95={_pct(errs, 95):.1f}  "
              f"max={max(errs):.1f}")
    return statistics.mean(finals), max(finals)


def main():
    print(f"Aim simulation on a {W}x{H} virtual screen, target r={RADIUS}px.")
    # Screen capture (the mode actually used) at realistic frame rates.
    m1, mx1 = report("DEFAULT", 0.22, 12000, 0.45, fps=60)
    m2, mx2 = report("DEFAULT @30fps", 0.22, 12000, 0.45, fps=30)
    m3, mx3 = report("STRONG (snappy)", 0.12, 20000, 0.7, fps=60)

    ok = all(m <= 2.5 for m in (m1, m2, m3)) and all(
        mx <= 5.0 for mx in (mx1, mx2, mx3))
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} "
          f"(static mean must be <=2.5px and max <=5px)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
