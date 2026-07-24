"""Target selection, locking, and jitter smoothing.

Turns a frame's detected contours + the active region into a single screen-space
target point. Three layers of stability:

* **Target lock** — once a blob is chosen it stays the target until it actually
  disappears (with a short grace period), instead of re-picking the nearest blob
  every frame. Without this, several same-color blobs made the nearest-pick
  flip-flop each frame: the smoothed point averaged out to the middle of the
  group ("equal pull") and the velocity estimator saw the flips as violent
  motion, flinging the cursor around (the random "spasms").
* **Teleport guard + deadband** — a raw target jump too fast to be physical
  resets velocity/smoothing instead of feeding the lead predictor; sub-2px
  detection noise is ignored entirely so a still target is rock steady.
* **Max-coverage snap** — after the cursor has been on the target color for a
  while, aim at the pixel where a circle of the configured size covers the most
  target color, instead of the blob's bbox center.

An exponential moving average is applied to the *target* (not the cursor) so
noisy detection doesn't make the pull twitch frame to frame.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

import cv2

from .detection import DetectedShape
from .segmentation import contour_points_in_region, segment_regions

# Motion prediction. A moving target is only *known* as of the last detection
# frame, so the pointer trails by roughly the detection interval plus smoothing.
# We predict ahead by (LEAD_FRAMES x measured detection interval), which
# auto-scales with frame rate: more lead when detection is slow, less when fast.
# A static target is below LEAD_DEADZONE and gets zero prediction, so precision
# on a still target is never affected.
LEAD_BASE = 0.02
LEAD_FRAMES = 1.8
LEAD_MIN_S = 0.02
LEAD_MAX_S = 0.14
LEAD_DEADZONE = 60.0
LEAD_MAX = 140.0      # absolute cap (px) so a fast flick can't overshoot wildly
LEAD_WARMUP = 6       # frames of continuous tracking before lead kicks in

# Stability guards.
TELEPORT_SPEED = 3000.0  # px/s; faster raw jumps are treated as a new target
DEADBAND_PX = 2.0        # ignore raw wiggle below this on a static target

# Target lock.
LOCK_MATCH_MIN = 70.0    # screen px; base radius for re-identifying the lock
LOCK_GRACE_S = 0.40      # keep aiming at a vanished target this long before
                         # releasing the lock and picking a new one

# Max-coverage snap.
SNAP_OFF_GRACE_S = 0.30  # brief mask flicker doesn't reset the on-color timer
SNAP_MAX_KERNEL_R = 16   # downscale the search so the kernel stays this small

_kernel_cache: Dict[int, np.ndarray] = {}


def _circle_kernel(r: int) -> np.ndarray:
    k = _kernel_cache.get(r)
    if k is None:
        d = 2 * r + 1
        k = np.zeros((d, d), dtype=np.float32)
        cv2.circle(k, (r, r), r, 1.0, -1)
        _kernel_cache[r] = k
    return k


def best_circle_center(
    mask: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
) -> Optional[Tuple[float, float]]:
    """Center of the ``radius`` circle that covers the most mask pixels.

    Searches a window around ``(cx, cy)`` (all in mask/detection coordinates).
    The search runs on a downscaled crop so even large circles stay cheap. Ties
    and near-ties are broken toward the current position so the snap point
    doesn't oscillate between equally-good centers.
    """
    h, w = mask.shape[:2]
    if h == 0 or w == 0 or radius <= 0:
        return None
    search = radius * 1.5 + 4
    x0 = max(0, int(cx - search))
    x1 = min(w, int(cx + search) + 1)
    y0 = max(0, int(cy - search))
    y1 = min(h, int(cy + search) + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = mask[y0:y1, x0:x1]

    ds = max(1.0, radius / SNAP_MAX_KERNEL_R)
    sw = max(2, int(round((x1 - x0) / ds)))
    sh = max(2, int(round((y1 - y0) / ds)))
    small = cv2.resize(crop, (sw, sh), interpolation=cv2.INTER_AREA)
    rr = max(1, int(round(radius / ds)))
    score = cv2.filter2D((small > 0).astype(np.float32), -1, _circle_kernel(rr),
                         borderType=cv2.BORDER_CONSTANT)
    if float(score.max()) <= 0.0:
        return None

    # Small distance penalty = hysteresis toward where we already are.
    fx = (x1 - x0) / float(sw)
    fy = (y1 - y0) / float(sh)
    px = (cx - x0) / fx
    py = (cy - y0) / fy
    yy, xx = np.mgrid[0:sh, 0:sw]
    score = score - 0.02 * ((xx - px) ** 2 + (yy - py) ** 2)

    by, bx = divmod(int(np.argmax(score)), sw)
    return (x0 + (bx + 0.5) * fx, y0 + (by + 0.5) * fy)


class TargetTracker:
    """Chooses, locks onto, and smooths the point the cursor is pulled toward."""

    def __init__(self, ema: float = 0.35):
        self._ema = ema
        self._smoothed: Optional[np.ndarray] = None  # screen-space (x, y) float
        self._vel = np.zeros(2)                       # smoothed velocity px/s
        self._prev_raw: Optional[np.ndarray] = None
        self._prev_t: Optional[float] = None
        self._dt = 1.0 / 60.0                         # smoothed detection interval
        self._track_frames = 0                        # frames on the same target
        # Target lock (screen space so it survives detect-scale changes).
        self._lock: Optional[Tuple[float, float]] = None
        self._lock_seen = 0.0                         # last time the lock matched
        # Max-coverage snap.
        self._on_color_since: Optional[float] = None
        self._off_color_at: Optional[float] = None

    def set_ema(self, ema: float) -> None:
        self._ema = max(0.0, min(1.0, ema))

    def speed(self) -> float:
        """Current estimated target speed in px/s (0 when static)."""
        return float(np.hypot(self._vel[0], self._vel[1]))

    def reset(self) -> None:
        self._smoothed = None
        self._vel = np.zeros(2)
        self._prev_raw = None
        self._prev_t = None
        self._track_frames = 0
        self._lock = None
        self._on_color_since = None
        self._off_color_at = None

    # ------------------------------------------------------------------ pick
    def pick(
        self,
        shapes: List[DetectedShape],
        figure: Optional[DetectedShape],
        active_region: str,
        cursor_screen: Tuple[int, int],
        capture_origin: Tuple[int, int],
        scale: float = 1.0,
        use_regions: bool = False,
        pull_radius: int = 0,
        mask: Optional[np.ndarray] = None,
        lock_enabled: bool = True,
        snap_enabled: bool = False,
        snap_radius: int = 0,
        snap_after_ms: int = 1000,
    ) -> Optional[Tuple[int, int]]:
        """Return a smoothed screen-space target, or ``None`` if none found.

        Two modes:
        * ``use_regions=False`` (default) — **track one color blob**: lock onto
          the blob nearest the cursor and keep pulling toward *that* blob until
          it disappears (plus a short grace), then re-acquire.
        * ``use_regions=True`` — split the largest figure into body regions and
          only target contour points inside the active region.

        With ``snap_enabled``, once the cursor has sat on the target color for
        ``snap_after_ms``, the aim point becomes the center of the
        ``snap_radius`` circle that covers the most target color.

        Coordinate spaces
        -----------------
        * Contours/mask are in *detection* coordinates, which may be downscaled
          by ``scale`` relative to the captured frame.
        * The cursor and returned target are in absolute *desktop* pixels.
        Mapping: ``detection = (screen - origin) * scale`` and
        ``screen = origin + detection / scale``.
        """
        now = time.perf_counter()
        ox, oy = capture_origin
        inv = 1.0 / scale if scale else 1.0
        # Cursor expressed in detection coordinates.
        cx = (cursor_screen[0] - ox) * scale
        cy = (cursor_screen[1] - oy) * scale
        # FOV radius in detection coordinates (0 = unlimited).
        r_det = pull_radius * scale if pull_radius and pull_radius > 0 else None

        if not shapes:
            target_det = self._hold_lock_det(now, ox, oy, scale)
            if target_det is None:
                self.reset()
                return None
            switched = False
        elif not use_regions:
            target_det, switched = self._pick_color(
                shapes, cx, cy, r_det, ox, oy, inv, scale, now, lock_enabled)
            if target_det is None:
                self.reset()
                return None
        else:
            target_det = self._pick_region(
                shapes, figure, active_region, cx, cy, r_det)
            if target_det is None:
                self.reset()
                return None
            switched = False

        # Max-coverage snap: after dwelling on the color, aim at the circle
        # position with the most color instead of the blob center.
        if (mask is not None and snap_enabled and snap_radius > 0
                and not use_regions):
            self._update_on_color(mask, cx, cy, now)
            if (self._on_color_since is not None
                    and (now - self._on_color_since) * 1000.0 >= snap_after_ms):
                best = best_circle_center(mask, target_det[0], target_det[1],
                                          snap_radius * scale)
                if best is not None:
                    target_det = best

        # Back to screen space (undo the downscale), then smooth.
        raw = np.array([ox + target_det[0] * inv, oy + target_det[1] * inv],
                       dtype=np.float64)
        return self._smooth(raw, now, switched)

    # -------------------------------------------------------------- selection
    def _pick_color(self, shapes, cx, cy, r_det, ox, oy, inv, scale, now,
                    lock_enabled):
        """Blob-center picking with a sticky lock. Returns (target, switched)."""
        cands = []
        for s in shapes:
            bx, by, bw, bh = s.bbox
            cands.append((bx + bw / 2.0, by + bh / 2.0, math.hypot(bw, bh)))

        # 1) Try to re-identify the locked target among this frame's blobs.
        if lock_enabled and self._lock is not None:
            lx = (self._lock[0] - ox) * scale
            ly = (self._lock[1] - oy) * scale
            best = None
            best_d = None
            for (px, py, diag) in cands:
                d = math.hypot(px - lx, py - ly)
                if best_d is None or d < best_d:
                    best_d, best = d, (px, py, diag)
            if best is not None:
                # Allow more drift for big blobs, fast targets, and stale locks.
                match_r = (max(LOCK_MATCH_MIN * scale, 0.8 * best[2])
                           + self.speed() * scale
                           * max(0.0, now - self._lock_seen) * 1.5)
                in_fov = (r_det is None or
                          math.hypot(best[0] - cx, best[1] - cy) <= 1.3 * r_det)
                if best_d <= match_r and in_fov:
                    self._lock = (ox + best[0] * inv, oy + best[1] * inv)
                    self._lock_seen = now
                    return (best[0], best[1]), False
            # Lock missed this frame: hold position briefly, then release.
            held = self._hold_lock_det(now, ox, oy, scale)
            if held is not None:
                return held, False
            self._lock = None

        # 2) No lock: acquire the blob nearest the cursor (inside the FOV).
        best = None
        best_d = None
        for (px, py, diag) in cands:
            d = math.hypot(px - cx, py - cy)
            if r_det is not None and d > r_det:
                continue
            if best_d is None or d < best_d:
                best_d, best = d, (px, py)
        if best is None:
            return None, False
        if lock_enabled:
            self._lock = (ox + best[0] * inv, oy + best[1] * inv)
            self._lock_seen = now
        return best, True

    def _hold_lock_det(self, now, ox, oy, scale):
        """Last known lock position (detection coords) while within grace."""
        if self._lock is None or (now - self._lock_seen) > LOCK_GRACE_S:
            return None
        return ((self._lock[0] - ox) * scale, (self._lock[1] - oy) * scale)

    def _pick_region(self, shapes, figure, active_region, cx, cy, r_det):
        if figure is None:
            return None
        # Respect the FOV: ignore a figure whose center is out of range.
        if r_det is not None:
            fx, fy, fw, fh = figure.bbox
            fcx, fcy = fx + fw / 2.0, fy + fh / 2.0
            if (fcx - cx) ** 2 + (fcy - cy) ** 2 > r_det * r_det:
                return None
        region_rect = segment_regions(figure.bbox).get(active_region)
        if region_rect is None:
            return None
        candidates: List[np.ndarray] = []
        for s in shapes:
            pts = contour_points_in_region(s.contour, region_rect)
            if len(pts):
                candidates.append(pts)
        if candidates:
            # Outline strokes cross the region: aim at the nearest one.
            pts = np.vstack(candidates).astype(np.float64)
            d2 = (pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2
            nearest = pts[int(np.argmin(d2))]
            return (nearest[0], nearest[1])
        # Filled figure (no edge points inside the region): aim at the
        # center of the region box so the pull still heads to that area.
        rx, ry, rw, rh = region_rect
        return (rx + rw / 2.0, ry + rh / 2.0)

    # ------------------------------------------------------------- snap timer
    def _update_on_color(self, mask, cx, cy, now) -> None:
        h, w = mask.shape[:2]
        ix, iy = int(round(cx)), int(round(cy))
        on = False
        if 0 <= ix < w and 0 <= iy < h:
            x0, x1 = max(0, ix - 2), min(w, ix + 3)
            y0, y1 = max(0, iy - 2), min(h, iy + 3)
            on = bool(mask[y0:y1, x0:x1].any())
        if on:
            if self._on_color_since is None:
                self._on_color_since = now
            self._off_color_at = None
        else:
            if self._off_color_at is None:
                self._off_color_at = now
            elif (now - self._off_color_at) > SNAP_OFF_GRACE_S:
                self._on_color_since = None

    # -------------------------------------------------------------- smoothing
    def _smooth(self, raw: np.ndarray, now: float,
                switched: bool) -> Tuple[int, int]:
        # A fresh or switched target starts clean: snap the smoothing there and
        # zero the velocity so no cross-blob "movement" leaks into prediction.
        if (switched or self._smoothed is None or self._prev_raw is None
                or self._prev_t is None):
            self._smoothed = raw.copy()
            self._vel = np.zeros(2)
            self._prev_raw = raw
            self._prev_t = now
            self._track_frames = 0
            return int(round(raw[0])), int(round(raw[1]))

        dt = now - self._prev_t
        if dt > 1e-3:
            inst = (raw - self._prev_raw) / dt
            if float(np.hypot(inst[0], inst[1])) > TELEPORT_SPEED:
                # Physically impossible jump (blob re-id error, scene cut):
                # restart tracking there instead of poisoning the velocity.
                self._vel = np.zeros(2)
                self._smoothed = raw.copy()
                self._track_frames = 0
            else:
                # Heavy velocity smoothing: keeps prediction stable at low fps
                # (noisy per-frame deltas won't cause overshoot spikes).
                self._vel = 0.85 * self._vel + 0.15 * inst
            if dt < 0.5:  # ignore long stalls when estimating the interval
                self._dt = 0.8 * self._dt + 0.2 * dt
        self._prev_raw = raw
        self._prev_t = now
        self._track_frames += 1

        speed = self.speed()

        # Deadband: a static target that wiggles by a pixel of detection noise
        # holds perfectly still instead of trembling.
        delta = raw - self._smoothed
        if float(np.hypot(delta[0], delta[1])) <= DEADBAND_PX \
                and speed < LEAD_DEADZONE:
            self._vel *= 0.8
            return (int(round(self._smoothed[0])),
                    int(round(self._smoothed[1])))

        # Adaptive follow: track a moving target a bit faster (less position
        # lag), but stay gentle when static so aim is rock-steady and precise.
        ema_eff = self._ema
        if speed > 250:
            ema_eff = min(0.65, self._ema + 0.18)
        elif speed > 80:
            ema_eff = min(0.6, self._ema + 0.1)
        self._smoothed = ema_eff * raw + (1.0 - ema_eff) * self._smoothed

        # Lead the target when it's really moving — and only after the velocity
        # estimate has warmed up on this target, so a fresh lock never flings.
        out = self._smoothed
        if speed > LEAD_DEADZONE and self._track_frames >= LEAD_WARMUP:
            lead_time = min(LEAD_MAX_S,
                            max(LEAD_MIN_S, LEAD_BASE + LEAD_FRAMES * self._dt))
            lead = self._vel * lead_time
            n = float(np.hypot(lead[0], lead[1]))
            if n > LEAD_MAX:
                lead = lead * (LEAD_MAX / n)
            out = self._smoothed + lead

        return int(round(out[0])), int(round(out[1]))
