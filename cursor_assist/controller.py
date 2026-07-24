"""Detection and movement engine.

Smoothness comes from **decoupling** two rates that used to share one loop:

* **Detection thread** — captures (downscaled for speed), finds the figure, and
  publishes the current target point. Runs as fast as the source allows; its
  speed no longer affects how smooth the cursor feels.
* **Movement thread** — a high-frequency loop that eases the cursor toward the
  latest published target using time-based smoothing, and services the dwell
  click. Because it runs fast and is frame-rate independent, motion glides.

Optionally, while a pull is active, the user's physical mouse movement is
suppressed (see :mod:`mouse_block`) so a shaky hand doesn't fight the assist.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Tuple

import cv2

from . import cursor as cur
from .capture import make_capture
from .config import AppState
from .detection import find_shapes, largest_figure
from .mouse_block import MouseSuppressor
from .targeting import TargetTracker

MOVE_HZ = 180.0            # cursor easing rate
MOVE_DT = 1.0 / MOVE_HZ
DETECT_MAX_HZ = 90.0       # cap detection so it doesn't peg a core
DETECT_MIN_DT = 1.0 / DETECT_MAX_HZ
TARGET_STALE_S = 0.25      # ignore targets older than this


class AssistController:
    def __init__(self, state: AppState, on_dwell_start: Optional[Callable] = None,
                 on_click: Optional[Callable] = None,
                 on_error: Optional[Callable] = None):
        self._state = state
        self._on_error = on_error
        self._stop = threading.Event()

        self._tracker = TargetTracker(ema=state.get("target_ema"))
        self._dwell = cur.DwellClicker(on_start=on_dwell_start, on_fire=on_click)
        self._suppressor = MouseSuppressor()
        self._suppressor_started = False

        # Shared target published by detection, consumed by movement.
        self._tlock = threading.Lock()
        self._target: Optional[Tuple[int, int]] = None
        self._target_at = 0.0

        self._capture = None
        self._capture_key = None
        self._last_error_msg = None

        self._det_thread: Optional[threading.Thread] = None
        self._move_thread: Optional[threading.Thread] = None

    # --- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._det_thread and self._det_thread.is_alive():
            return
        self._stop.clear()
        self._det_thread = threading.Thread(target=self._detection_loop,
                                            name="assist-detect", daemon=True)
        self._move_thread = threading.Thread(target=self._movement_loop,
                                             name="assist-move", daemon=True)
        self._det_thread.start()
        self._move_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for t in (self._det_thread, self._move_thread):
            if t:
                t.join(timeout=2.0)
        if self._capture:
            self._capture.close()
            self._capture = None
        if self._suppressor_started:
            self._suppressor.stop()
            self._suppressor_started = False

    # --- helpers ---------------------------------------------------------
    def _report(self, exc) -> None:
        msg = str(exc)
        if msg != self._last_error_msg and self._on_error:
            self._last_error_msg = msg
            self._on_error(exc)

    def _ensure_capture(self, snap: AppState):
        cfg = snap.capture
        key = (cfg.source, cfg.left, cfg.top, cfg.width, cfg.height,
               cfg.monitor, cfg.obs_device_index)
        if self._capture is None or key != self._capture_key:
            if self._capture:
                self._capture.close()
                self._capture = None
            self._capture = make_capture(cfg)
            self._capture_key = key
        return self._capture

    def _publish(self, target: Optional[Tuple[int, int]]) -> None:
        with self._tlock:
            self._target = target
            self._target_at = time.perf_counter()

    def _read_target(self) -> Optional[Tuple[int, int]]:
        with self._tlock:
            if self._target is None:
                return None
            if (time.perf_counter() - self._target_at) > TARGET_STALE_S:
                return None
            return self._target

    # --- detection loop --------------------------------------------------
    def _detection_loop(self) -> None:
        fps = 30.0
        while not self._stop.is_set():
            t0 = time.perf_counter()

            if not self._state.get("pull_enabled"):
                self._tracker.reset()
                self._publish(None)
                self._state.set("last_target_found", False)
                time.sleep(0.03)
                continue

            try:
                snap = self._state.snapshot()
                capture = self._ensure_capture(snap)
                frame = capture.grab()
                if frame is None:
                    self._publish(None)
                    self._state.set("last_target_found", False)
                    time.sleep(0.01)
                    continue

                scale = max(0.2, min(1.0, snap.detect_scale))
                small = (cv2.resize(frame, None, fx=scale, fy=scale,
                                    interpolation=cv2.INTER_AREA)
                         if scale < 0.999 else frame)

                self._tracker.set_ema(snap.target_ema)
                min_area = max(1, int(snap.min_contour_area * scale * scale))
                shapes, _mask = find_shapes(small, snap.colors,
                                            snap.detect_thin_border, min_area)
                figure = largest_figure(shapes)

                target = self._tracker.pick(
                    shapes=shapes, figure=figure,
                    active_region=snap.active_region,
                    cursor_screen=cur.get_cursor_pos(),
                    capture_origin=capture.origin,
                    scale=scale,
                )
                self._publish(target)
                self._state.set("last_target_found", target is not None)
            except Exception as exc:
                self._report(exc)
                self._publish(None)
                self._state.set("last_target_found", False)
                # Force a capture rebuild in case the source dropped.
                if self._capture:
                    self._capture.close()
                self._capture = None
                self._capture_key = None
                time.sleep(0.3)

            dt = time.perf_counter() - t0
            if dt < DETECT_MIN_DT:
                time.sleep(DETECT_MIN_DT - dt)
            dt = time.perf_counter() - t0
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)
                self._state.set("loop_fps", round(fps, 1))

    # --- movement loop ---------------------------------------------------
    def _movement_loop(self) -> None:
        last = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            dt = now - last
            last = now
            if dt <= 0:
                dt = MOVE_DT

            enabled = self._state.get("pull_enabled")
            target = self._read_target() if enabled else None

            # Physical-mouse suppression: only while actually pulling a target.
            want_suppress = bool(enabled and target is not None
                                 and self._state.get("suppress_mouse"))
            self._apply_suppression(want_suppress)

            if target is None:
                self._dwell.reset()
                time.sleep(MOVE_DT)
                continue

            smoothness = self._state.get("smoothness")
            tau = 0.03 + max(0.0, min(1.0, smoothness)) * 0.22
            cursor_pos = cur.ease_step(
                target_screen=target,
                dt=dt,
                tau=tau,
                max_speed_px_s=float(self._state.get("max_speed")),
            )
            self._dwell.update(
                cursor_screen=cursor_pos,
                target_screen=target,
                radius=self._state.get("click_radius"),
                dwell_ms=self._state.get("dwell_ms"),
                auto_click=self._state.get("auto_click_enabled"),
            )

            slack = MOVE_DT - (time.perf_counter() - now)
            if slack > 0:
                time.sleep(slack)

    def _apply_suppression(self, want: bool) -> None:
        if want and not self._suppressor_started:
            self._suppressor_started = self._suppressor.start()
        if self._suppressor_started:
            self._suppressor.set_suppressing(want)
