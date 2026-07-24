"""Virtual world for live-motion simulations.

Runs the *real* :class:`AssistController` (detection + movement threads,
targeting, lock, snap, easing) against synthetic frames drawn per grab, with a
virtual mouse standing in for the OS cursor. Patches are applied on ``__enter__``
and restored on ``__exit__`` so other tests are unaffected.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional

import numpy as np

import cursor_assist.controller as ctrl
import cursor_assist.cursor as cur
from cursor_assist.config import AppState, ColorTarget

W, H = 1000, 700
RED = (0, 0, 255)  # BGR — red also exercises the hue-wraparound path


def make_state(**overrides) -> AppState:
    st = AppState()
    with st.lock:
        st.colors[:] = [ColorTarget(h=0, s=255, v=255,
                                    h_tol=12, s_tol=120, v_tol=120)]
        st.body_part_detection = False
        st.smoothness = 0.22
        st.max_speed = 25000
        st.target_ema = 0.45
        st.click_mode = "off"
        st.pull_radius = 0
        st.detect_scale = 0.5
        st.snap_to_best = False
        st.pull_enabled = True
        st.audio_cues = False
        for k, v in overrides.items():
            setattr(st, k, v)
    return st


class SimWorld:
    """``draw(frame, t)`` renders the scene for time ``t`` (s since enter)."""

    def __init__(self, draw: Callable[[np.ndarray, float], None],
                 fps: int = 90, w: int = W, h: int = H):
        self.draw = draw
        self.fps = fps
        self.w = w
        self.h = h
        self.x = w / 2.0
        self.y = h / 2.0
        self.clicks = 0
        self._t0: Optional[float] = None
        self._last_grab = 0.0
        self._saved = {}

    # --- fake cursor I/O --------------------------------------------------
    def _get_pos(self):
        return int(round(self.x)), int(round(self.y))

    def _move_rel(self, dx, dy):
        self.x = min(max(self.x + dx, 0), self.w - 1)
        self.y = min(max(self.y + dy, 0), self.h - 1)

    def _click(self):
        self.clicks += 1

    def t(self) -> float:
        return time.perf_counter() - self._t0

    def frame_now(self) -> np.ndarray:
        """Render the scene as it looks right now (for assertions)."""
        f = np.zeros((self.h, self.w, 3), np.uint8)
        self.draw(f, self.t())
        return f

    # --- patching ---------------------------------------------------------
    def __enter__(self):
        self._saved = dict(get=cur.get_cursor_pos, move=cur.move_relative,
                           click=cur.click_left, mk=ctrl.make_capture)
        cur.get_cursor_pos = self._get_pos
        cur.move_relative = self._move_rel
        cur.click_left = self._click
        world = self

        class Cap:
            origin = (0, 0)

            def grab(_c):
                period = 1.0 / world.fps
                wait = world._last_grab + period - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
                world._last_grab = time.perf_counter()
                return world.frame_now()

            def close(_c):
                pass

        ctrl.make_capture = lambda cfg: Cap()
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        cur.get_cursor_pos = self._saved["get"]
        cur.move_relative = self._saved["move"]
        cur.click_left = self._saved["click"]
        ctrl.make_capture = self._saved["mk"]
        return False

    # --- running ----------------------------------------------------------
    def run(self, state: AppState, dur: float,
            sample: Optional[Callable[[float], object]] = None,
            warmup: float = 0.0) -> List:
        """Run the real engine for ``dur`` seconds, sampling every ~4 ms."""
        c = ctrl.AssistController(state)
        c.start()
        samples: List = []
        t0 = time.perf_counter()
        try:
            while True:
                now = time.perf_counter() - t0
                if now >= dur:
                    break
                if sample is not None and now >= warmup:
                    samples.append(sample(now))
                time.sleep(0.004)
        finally:
            c.stop()
        return samples
