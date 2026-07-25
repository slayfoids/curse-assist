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
from .capture import display_refresh_hz, make_capture
from .config import AppState
from .detection import find_shapes, largest_figure
from .mouse_block import MouseSuppressor
from .targeting import TargetTracker

MOVE_HZ = 240.0            # cursor easing rate (time-based, so mostly for polish)
MOVE_DT = 1.0 / MOVE_HZ
# Hard bounds on the configurable scan rate. The ceiling is a safety rail, not
# a target — the useful rate is the display's refresh (see AppState.scan_fps).
SCAN_HZ_MIN = 5.0
SCAN_HZ_MAX = 1000.0
DISPLAY_HZ_RECHECK_S = 3.0  # re-read the refresh rate this often, so plugging
                            # in a different monitor is picked up while running
TARGET_STALE_S = 0.25      # ignore targets older than this

# Pursuit easing. Below the knee the easing constant is untouched, so a resting
# or slow target keeps the full smooth, precise feel. Above it the constant
# decays continuously with speed so the pointer doesn't trail a moving object.
# The previous curve bottomed out at 0.35 of the base constant, which still
# left tens of px of lag on anything crossing the screen quickly.
PURSUIT_KNEE = 80.0        # px/s at which shortening begins
PURSUIT_SCALE = 500.0      # px/s of extra speed per halving of the constant
PURSUIT_FLOOR = 0.14       # never shorten below this fraction of the base

# The precision zone is for *settling* onto a target, not for chasing one.
# Easing off near a moving target would mean never catching it, so the zone
# fades out as the target's own speed rises and is gone by this speed.
PRECISION_FADE_SPEED = 220.0   # px/s

# Adaptive ROI ("target follow"). Detection frame rate is the ceiling on how
# well a moving target can be tracked, and scanning the whole screen is what
# costs the frames. Once locked we scan a window around the target instead —
# at full resolution, because the window is small enough to afford it.
ADAPT_MIN_HALF = 110       # px; smallest follow window half-size
ADAPT_SPEED_LEAD = 0.18    # s of target travel to allow for at the edges
ADAPT_MISS_MAX = 3         # empty follow frames before falling back to full
ADAPT_RESCAN_EVERY = 12    # force a full scan this often, to find new targets
ADAPT_MAX_AREA_FRAC = 0.45  # skip the window if it isn't actually smaller

# Search window used *before* anything is locked. Sized from the pull radius,
# because selection already discards every target outside it — grabbing the
# rest of the screen is work whose result is guaranteed to be thrown away.
# The margin lets a blob straddling the edge still register.
SEARCH_MARGIN = 1.3
SEARCH_PAD = 48


def _intersect(a, b):
    """Overlap of two (left, top, w, h) boxes, or None if they don't meet."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


class AssistController:
    def __init__(self, state: AppState, on_dwell_start: Optional[Callable] = None,
                 on_click: Optional[Callable] = None,
                 on_error: Optional[Callable] = None):
        self._state = state
        self._on_error = on_error
        self._stop = threading.Event()

        self._tracker = TargetTracker(ema=state.get("target_ema"))
        self._glider = cur.CursorGlider()
        self._dwell = cur.DwellClicker(on_start=on_dwell_start, on_fire=on_click)
        self._suppressor = MouseSuppressor()
        self._suppressor_started = False

        # Shared target published by detection, consumed by movement.
        self._tlock = threading.Lock()
        self._target: Optional[Tuple[int, int]] = None
        self._target_at = 0.0
        self._target_speed = 0.0  # px/s, set by detection, read by movement
        self._last_trigger = 0.0  # cooldown for the instant trigger click

        self._capture = None
        self._capture_key = None
        self._last_error_msg = None

        # Display refresh, re-read periodically rather than once at startup so
        # swapping monitors mid-session is picked up.
        self._display_hz = display_refresh_hz()
        self._display_hz_at = 0.0

        # Adaptive ROI follow-window state.
        self._adapt_at: Optional[Tuple[int, int]] = None  # screen coords
        self._adapt_miss = 0
        self._adapt_frames = 0
        self._adapt_active = False

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

    def trigger_click(self) -> None:
        """Fire a click immediately (bound to the trigger hotkey).

        Instant — no dwell wait. A short cooldown prevents a single key press
        from registering as several clicks.
        """
        now = time.perf_counter()
        if now - self._last_trigger < 0.05:
            return
        self._last_trigger = now
        cur.click_left()

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

    def _scan_period(self, pulling: bool) -> float:
        """Seconds between scans, honouring the configured rate.

        ``scan_fps`` of 0 means "match the display", which is the rate above
        which extra scans only re-read frames the screen has not redrawn yet.

        Reads live state rather than a snapshot: this also runs on the error
        path, where a snapshot may not have been taken yet.
        """
        now = time.perf_counter()
        if now - self._display_hz_at > DISPLAY_HZ_RECHECK_S:
            self._display_hz = display_refresh_hz()
            self._display_hz_at = now
            self._state.set("display_hz", round(self._display_hz, 1))

        if not pulling:
            want = float(self._state.get("idle_scan_fps"))
        else:
            want = float(self._state.get("scan_fps")) or self._display_hz
        return 1.0 / max(SCAN_HZ_MIN, min(SCAN_HZ_MAX, want))

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
            pulling = self._state.get("pull_enabled")

            try:
                snap = self._state.snapshot()
                # Nothing to look for yet: don't open the camera, just idle.
                if not snap.colors:
                    self._publish(None)
                    self._state.set("last_target_found", False)
                    time.sleep(0.1)
                    continue
                capture = self._ensure_capture(snap)

                # Ask the capture for just the follow window *before* grabbing.
                # Grab cost scales with captured area and dominates everything
                # else — a full-screen grab alone caps the loop near 15 fps on
                # a 1920x1200 desktop, so cropping only after the grab left the
                # real cost untouched.
                self._adapt_frames += 1
                self._adapt_active = False
                follow_box = None
                search_box = None
                # The user's detection area, in absolute desktop pixels. A
                # backend that predates follow support has no base_origin;
                # without a follow window the two are the same thing anyway.
                base_ox, base_oy = getattr(capture, "base_origin",
                                           capture.origin)
                roi_abs = None
                if snap.roi_w > 0 and snap.roi_h > 0:
                    roi_abs = (base_ox + snap.roi_x, base_oy + snap.roi_y,
                               snap.roi_w, snap.roi_h)

                # Both windows are intersected with the detection area here, in
                # one shared coordinate space. Cropping again after the grab
                # would apply the area's offset a second time, inside the
                # window, and put the aim point somewhere else entirely.
                if (snap.adaptive_roi and snap.lock_target
                        and self._adapt_at is not None
                        and self._adapt_miss < ADAPT_MISS_MAX
                        and self._adapt_frames % ADAPT_RESCAN_EVERY != 0):
                    # Locked: follow the target, at full resolution.
                    half = int(max(ADAPT_MIN_HALF,
                                   self._tracker.speed() * ADAPT_SPEED_LEAD))
                    follow_box = (self._adapt_at[0] - half,
                                  self._adapt_at[1] - half,
                                  2 * half, 2 * half)
                    if roi_abs is not None:
                        follow_box = _intersect(follow_box, roi_abs)
                    self._adapt_active = follow_box is not None
                elif snap.adaptive_roi and snap.pull_radius > 0:
                    # Nothing locked yet: search a window around the pointer
                    # rather than the whole screen. Not a heuristic — selection
                    # already discards every target outside the pull radius, so
                    # the rest of the screen was being grabbed and scanned only
                    # for the result to be thrown away. That full grab is
                    # ~67 ms, which is why acquisition sat near 10 scans a
                    # second however high the scan rate was set.
                    cx, cy = cur.get_cursor_pos()
                    m = int(snap.pull_radius * SEARCH_MARGIN + SEARCH_PAD)
                    search_box = (cx - m, cy - m, 2 * m, 2 * m)
                    if roi_abs is not None:
                        search_box = _intersect(search_box, roi_abs)

                box = follow_box if self._adapt_active else search_box
                try:
                    capture.set_follow(box)
                except AttributeError:      # a backend without follow support
                    self._adapt_active = False
                    box = None

                frame = capture.grab()
                if frame is None:
                    self._publish(None)
                    self._state.set("last_target_found", False)
                    time.sleep(0.01)
                    continue

                # Optional detection area (ROI): crop the frame and shift the
                # origin so screen mapping stays correct. Skipped while
                # following — the follow window was already intersected with
                # the area above, in absolute coordinates.
                origin = capture.origin
                if box is None and roi_abs is not None:
                    fh, fw = frame.shape[:2]
                    x0 = max(0, min(snap.roi_x, fw - 1))
                    y0 = max(0, min(snap.roi_y, fh - 1))
                    x1 = max(x0 + 1, min(snap.roi_x + snap.roi_w, fw))
                    y1 = max(y0 + 1, min(snap.roi_y + snap.roi_h, fh))
                    frame = frame[y0:y1, x0:x1]
                    origin = (origin[0] + x0, origin[1] + y0)

                # A follow window is already small; scanning it at full
                # resolution costs little and keeps downscale rounding out of
                # the aim point.
                scale = (1.0 if self._adapt_active
                         else max(0.2, min(1.0, snap.detect_scale)))

                small = (cv2.resize(frame, None, fx=scale, fy=scale,
                                    interpolation=cv2.INTER_AREA)
                         if scale < 0.999 else frame)

                self._tracker.set_ema(snap.target_ema)
                self._tracker.set_tuning(response=snap.motion_response,
                                         floor=snap.jitter_floor)
                min_area = max(1, int(snap.min_contour_area * scale * scale))
                shapes, mask = find_shapes(small, snap.colors,
                                           snap.detect_thin_border, min_area)
                figure = largest_figure(shapes)

                # "Circle size" drives the max-coverage snap; it falls back to
                # the pull radius when the drawn circle matches it (0).
                snap_r = (snap.overlay_radius if snap.overlay_radius > 0
                          else snap.pull_radius)
                target = self._tracker.pick(
                    shapes=shapes, figure=figure,
                    active_region=snap.active_region,
                    cursor_screen=cur.get_cursor_pos(),
                    capture_origin=origin,
                    scale=scale,
                    use_regions=snap.body_part_detection,
                    pull_radius=snap.pull_radius,
                    mask=mask,
                    lock_enabled=snap.lock_target,
                    snap_enabled=snap.snap_to_best,
                    snap_radius=snap_r,
                    snap_after_ms=snap.snap_after_ms,
                    part_attraction=snap.part_attraction,
                )
                self._publish(target)
                self._target_speed = self._tracker.speed()
                self._state.set("last_target_found", target is not None)

                # Steer the follow window. A miss inside the window only
                # widens the search after a few frames, so one dropped
                # detection doesn't throw away the speed-up.
                if target is not None:
                    self._adapt_at = target
                    self._adapt_miss = 0
                elif self._adapt_active:
                    self._adapt_miss += 1
                else:
                    self._adapt_at = None
                    self._adapt_miss = 0
                self._state.set("roi_following", self._adapt_active)
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

            # Configured rate while pulling; a slow idle tick otherwise (enough
            # for live "target found" feedback while tuning, without pegging a
            # core). Note this is a *floor* on the interval — if a grab takes
            # longer than the target period the loop simply runs slower, which
            # is why the panel reports the achieved rate next to the target.
            pace = self._scan_period(pulling)
            dt = time.perf_counter() - t0
            if dt < pace:
                time.sleep(pace - dt)
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
                # A dwell already in progress rides out a brief dropout rather
                # than restarting; see DwellClicker.target_lost.
                self._dwell.target_lost(self._state.get("dwell_grace_ms"))
                self._glider.reset()
                self._state.set("aim_valid", False)
                time.sleep(MOVE_DT)
                continue

            self._state.set("aim_x", int(target[0]))
            self._state.set("aim_y", int(target[1]))
            self._state.set("aim_valid", True)

            smoothness = self._state.get("smoothness")
            tau = 0.03 + max(0.0, min(1.0, smoothness)) * 0.22
            # Adaptive: follow snappier while the target is moving (cuts pursuit
            # lag) without touching the smooth, precise feel on a static target.
            sp = self._target_speed
            if sp > PURSUIT_KNEE:
                tau *= max(PURSUIT_FLOOR,
                           1.0 / (1.0 + (sp - PURSUIT_KNEE) / PURSUIT_SCALE))
            # Fade the precision zone out as the target starts moving (see
            # PRECISION_FADE_SPEED) so it steadies an arrival without ever
            # holding the pointer back during a chase.
            prec = float(self._state.get("precision_px"))
            if prec > 0:
                prec *= max(0.0, 1.0 - sp / PRECISION_FADE_SPEED)

            cursor_pos = self._glider.step(
                target_screen=target,
                dt=dt,
                tau=tau,
                max_speed_px_s=float(self._state.get("max_speed")),
                max_accel_px_s2=float(self._state.get("max_accel")),
                precision_px=prec,
                precision_slow=float(self._state.get("precision_slow")),
                gain_scale=float(self._state.get("pointer_gain")),
                auto_gain=bool(self._state.get("pointer_gain_auto")),
            )
            self._state.set("pointer_gain_measured",
                            round(self._glider.gain, 3))
            self._dwell.update(
                cursor_screen=cursor_pos,
                target_screen=target,
                radius=self._state.get("click_radius"),
                dwell_ms=self._state.get("dwell_ms"),
                auto_click=(self._state.get("click_mode") == "dwell"),
                repeat=self._state.get("click_repeat"),
                interval_ms=self._state.get("click_interval_ms"),
            )

            slack = MOVE_DT - (time.perf_counter() - now)
            if slack > 0:
                time.sleep(slack)

    def _apply_suppression(self, want: bool) -> None:
        if want and not self._suppressor_started:
            self._suppressor_started = self._suppressor.start()
        if self._suppressor_started:
            self._suppressor.set_suppressing(want)
