#!/usr/bin/env python
"""Visual strafe simulation — watch the engine track a rapidly juking target.

Drives the *real* :class:`AssistController` against a synthetic scene where the
target strafes hard up and down (the case where tracking visibly falls apart),
with a virtual mouse standing in for the OS cursor. Nothing real is touched.

Two outputs:

* **A watchable view** — target, pointer, the error between them, and fading
  trails for both, plus a live metrics HUD. ``--live`` opens a window;
  ``--record out.mp4`` writes a file you can scrub through.
* **Numbers** — signed vertical error over time, so *lag* (pointer behind the
  target) is distinguishable from *overshoot* (pointer flung past it). Mean
  absolute error alone hides the difference, and they have opposite fixes.

Run::

    py tools/strafe_sim.py --live              # watch it
    py tools/strafe_sim.py --record strafe.mp4 # save it
    py tools/strafe_sim.py --hz 2.5 --amp 220  # tune the juke

The scene is rendered twice per frame: a **clean** frame is what detection
sees, and the annotated view is drawn on a copy. Keeping them separate matters
-- HUD text drawn in the target colour would otherwise be detected as targets.
"""

from __future__ import annotations

import argparse
import colorsys
import math
import os
import statistics
import sys
import time

# Allow running as a plain script from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

import cursor_assist.controller as ctrl
import cursor_assist.cursor as cur
from cursor_assist.config import AppState, ColorTarget

W, H = 1000, 700
RADIUS = 18
TARGET_BGR = (0, 0, 255)      # red
CURSOR_BGR = (80, 255, 80)    # green — never matches the red target
TRAIL_LEN = 90


class VMouse:
    def __init__(self):
        self.x = W / 2.0
        self.y = H / 2.0
        self.clicks = 0


vm = VMouse()
_tgt = {"x": W / 2.0, "y": H / 2.0}
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


def scene_frame() -> np.ndarray:
    """The clean frame detection sees: the target and nothing else."""
    f = np.zeros((H, W, 3), np.uint8)
    cv2.circle(f, (int(_tgt["x"]), int(_tgt["y"])), RADIUS, TARGET_BGR, -1)
    return f


class FakeCapture:
    origin = (0, 0)

    def grab(self):
        period = 1.0 / max(1, _cam["fps"])
        wait = _cam["last"] + period - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        _cam["last"] = time.perf_counter()
        return scene_frame()

    def close(self):
        pass


ctrl.make_capture = lambda cfg: FakeCapture()


def _cv_hsv(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return int(h * 179), int(s * 255), int(v * 255)


def make_state(**overrides) -> AppState:
    st = AppState()
    h, s, v = _cv_hsv(255, 0, 0)
    with st.lock:
        st.colors[:] = [ColorTarget(h=h, s=s, v=v,
                                    h_tol=15, s_tol=120, v_tol=120)]
        st.body_part_detection = False
        st.click_mode = "off"
        st.pull_radius = 0
        st.detect_scale = 0.5
        st.snap_to_best = False
        st.pull_enabled = True
        st.audio_cues = False
        for k, val in overrides.items():
            setattr(st, k, val)
    return st


def draw_view(t, err_y, stats, tgt_trail, cur_trail) -> np.ndarray:
    """Annotated view — built on a copy so detection never sees this."""
    f = scene_frame()
    # Fading trails.
    for trail, colour in ((tgt_trail, (0, 0, 160)), (cur_trail, (0, 150, 0))):
        for i in range(1, len(trail)):
            a = i / len(trail)
            cv2.line(f, trail[i - 1], trail[i],
                     tuple(int(c * a) for c in colour), 2)
    tx, ty = int(_tgt["x"]), int(_tgt["y"])
    cx, cy = int(vm.x), int(vm.y)
    # Error line: red when the pointer is off, green when it's on.
    on = abs(err_y) <= RADIUS
    cv2.line(f, (cx, cy), (tx, ty), (0, 200, 0) if on else (0, 165, 255), 2)
    cv2.circle(f, (tx, ty), RADIUS + 3, (0, 0, 255), 1)
    cv2.drawMarker(f, (cx, cy), CURSOR_BGR, cv2.MARKER_CROSS, 22, 2)

    hud = [
        f"t={t:5.2f}s   signed dy={err_y:+7.1f}px   {'ON' if on else 'OFF'}",
        f"mean|dy|={stats['mean']:6.1f}  p95={stats['p95']:6.1f}"
        f"  max={stats['max']:6.1f}",
        f"overshoot={stats['over']:6.1f}px  lag={stats['lag']:6.1f}px",
    ]
    for i, line in enumerate(hud):
        cv2.putText(f, line, (14, 28 + i * 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (255, 255, 255), 1, cv2.LINE_AA)
    return f


def run(hz, amp, dur, fps, live, record, state=None, quiet=False):
    """Strafe the target vertically; return the signed vertical error series."""
    _cam["fps"] = fps
    st = state if state is not None else make_state()
    c = ctrl.AssistController(st)

    cy = H / 2.0
    _tgt["x"], _tgt["y"] = W / 2.0, cy
    vm.x, vm.y = W / 2.0, cy

    writer = None
    if record:
        writer = cv2.VideoWriter(record, cv2.VideoWriter_fourcc(*"mp4v"),
                                 30.0, (W, H))
    tgt_trail, cur_trail = [], []
    errs, signed = [], []
    c.start()
    t0 = time.perf_counter()
    last_draw = 0.0
    try:
        while True:
            t = time.perf_counter() - t0
            if t >= dur:
                break
            # Rapid vertical strafe. Peak speed = 2*pi*hz*amp px/s.
            _tgt["y"] = cy + amp * math.sin(2 * math.pi * hz * t)
            dy = vm.y - _tgt["y"]
            if t > 0.7:                      # skip initial acquisition
                errs.append(abs(dy))
                signed.append(dy)

            if (live or writer) and (t - last_draw) >= 1 / 30.0:
                last_draw = t
                tgt_trail.append((int(_tgt["x"]), int(_tgt["y"])))
                cur_trail.append((int(vm.x), int(vm.y)))
                del tgt_trail[:-TRAIL_LEN]
                del cur_trail[:-TRAIL_LEN]
                stats = _stats(errs, signed)
                view = draw_view(t, dy, stats, tgt_trail, cur_trail)
                if writer:
                    writer.write(view)
                if live:
                    cv2.imshow("strafe sim  (q to quit)", view)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
            time.sleep(0.003)
    finally:
        c.stop()
        if writer:
            writer.release()
        if live:
            cv2.destroyAllWindows()

    s = _stats(errs, signed)
    if not quiet:
        peak = 2 * math.pi * hz * amp
        print(f"  strafe {hz}Hz amp={amp}px (peak {peak:.0f} px/s) "
              f"@{fps}fps capture")
        print(f"    mean|dy| = {s['mean']:6.2f} px    p95 = {s['p95']:6.2f} px"
              f"    max = {s['max']:6.2f} px")
        print(f"    overshoot= {s['over']:6.2f} px    lag = {s['lag']:6.2f} px"
              f"    on-target = {s['on']:5.1f}%")
    return s


def _stats(errs, signed):
    if not errs:
        return dict(mean=0.0, p95=0.0, max=0.0, over=0.0, lag=0.0, on=0.0)
    ordered = sorted(errs)
    # Overshoot vs lag: the pointer's error relative to where the target is
    # heading. Split on the sign of the target's motion at that instant is
    # overkill here -- the extremes of the signed series capture both ends.
    return dict(
        mean=statistics.mean(errs),
        p95=ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))],
        max=max(errs),
        over=abs(min(signed)),
        lag=abs(max(signed)),
        on=100.0 * sum(1 for e in errs if e <= RADIUS) / len(errs),
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hz", type=float, default=2.0, help="strafes per second")
    p.add_argument("--amp", type=float, default=200.0, help="strafe amplitude px")
    p.add_argument("--dur", type=float, default=6.0, help="seconds to run")
    p.add_argument("--fps", type=int, default=60, help="simulated capture fps")
    p.add_argument("--live", action="store_true", help="show a live window")
    p.add_argument("--record", metavar="PATH", help="write an mp4 of the run")
    p.add_argument("--sweep", action="store_true",
                   help="run a range of strafe speeds and report a table")
    args = p.parse_args()

    print(f"Strafe simulation on a {W}x{H} virtual screen, target r={RADIUS}px.")
    if args.sweep:
        print("\n=== strafe speed sweep (default settings) ===")
        for hz in (0.5, 1.0, 1.5, 2.0, 3.0):
            run(hz, args.amp, args.dur, args.fps, False, None, quiet=False)
        return 0
    run(args.hz, args.amp, args.dur, args.fps, args.live, args.record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
