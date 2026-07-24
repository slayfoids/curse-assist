"""Background detection + pull loop.

Runs in its own thread at a target 60 Hz. Each frame it captures, detects the
figure, picks a smoothed target inside the active region, eases the cursor
toward it, and services the dwell-click timer. The GUI thread only reads/writes
:class:`AppState`; it never touches OpenCV or the cursor directly.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from . import cursor as cur
from .capture import make_capture
from .config import AppState
from .detection import find_shapes, largest_figure
from .targeting import TargetTracker

TARGET_HZ = 60.0
FRAME_DT = 1.0 / TARGET_HZ


class AssistController:
    def __init__(self, state: AppState, on_dwell_start: Optional[Callable] = None,
                 on_click: Optional[Callable] = None,
                 on_error: Optional[Callable] = None):
        self._state = state
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._tracker = TargetTracker(ema=state.get("target_ema"))
        self._dwell = cur.DwellClicker(on_start=on_dwell_start, on_fire=on_click)
        self._on_error = on_error
        self._capture = None
        self._capture_source = None

    # --- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="assist-loop",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._capture:
            self._capture.close()
            self._capture = None

    # --- helpers ---------------------------------------------------------
    def _ensure_capture(self, snap: AppState):
        """(Re)build the capture backend if the source config changed."""
        cfg = snap.capture
        key = (cfg.source, cfg.left, cfg.top, cfg.width, cfg.height,
               cfg.monitor, cfg.obs_device_index)
        if self._capture is None or key != self._capture_source:
            if self._capture:
                self._capture.close()
            self._capture = make_capture(cfg)
            self._capture_source = key
        return self._capture

    # --- main loop -------------------------------------------------------
    def _run(self) -> None:
        fps_ema = TARGET_HZ
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                self._tick()
            except Exception as exc:  # keep the loop alive; surface once to UI
                if self._on_error:
                    self._on_error(exc)
                time.sleep(0.25)

            # Pace to ~60 Hz.
            elapsed = time.perf_counter() - t0
            if elapsed < FRAME_DT:
                time.sleep(FRAME_DT - elapsed)

            dt = time.perf_counter() - t0
            if dt > 0:
                fps_ema = 0.9 * fps_ema + 0.1 * (1.0 / dt)
                self._state.set("loop_fps", round(fps_ema, 1))

    def _tick(self) -> None:
        snap = self._state.snapshot()

        if not snap.pull_enabled:
            # Idle: keep smoothing state fresh so re-enabling doesn't lurch.
            self._tracker.reset()
            self._dwell.reset()
            self._state.set("last_target_found", False)
            time.sleep(0.02)
            return

        capture = self._ensure_capture(snap)
        frame = capture.grab()
        if frame is None:
            self._state.set("last_target_found", False)
            return

        self._tracker.set_ema(snap.target_ema)
        shapes, _mask = find_shapes(
            frame,
            snap.colors,
            snap.detect_thin_border,
            snap.min_contour_area,
        )
        figure = largest_figure(shapes)

        cursor_pos = cur.get_cursor_pos()
        target = self._tracker.pick(
            shapes=shapes,
            figure=figure,
            active_region=snap.active_region,
            cursor_screen=cursor_pos,
            capture_origin=capture.origin,
        )

        self._state.set("last_target_found", target is not None)
        if target is None:
            self._dwell.reset()
            return

        cursor_pos = cur.pull_toward(target, snap.pull_factor,
                                     snap.max_px_per_frame)
        self._dwell.update(
            cursor_screen=cursor_pos,
            target_screen=target,
            radius=snap.click_radius,
            dwell_ms=snap.dwell_ms,
            auto_click=snap.auto_click_enabled,
        )
