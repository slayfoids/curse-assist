"""Target selection and jitter smoothing.

Turns a frame's detected contours + the active region into a single screen-space
target point: the contour point nearest the current cursor, restricted to the
active region. An exponential moving average is applied to the *target* (not the
cursor) so noisy detection doesn't make the pull twitch frame to frame.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

import time

from .detection import DetectedShape
from .segmentation import contour_points_in_region, segment_regions

# Motion prediction. A moving target is only *known* as of the last detection
# frame, so the pointer trails by roughly the detection interval plus smoothing.
# We predict ahead by (LEAD_FRAMES x measured detection interval), which
# auto-scales with frame rate: more lead when detection is slow, less when fast.
# A static target is below LEAD_DEADZONE and gets zero prediction, so precision
# on a still target is never affected.
# Predicted lead time = LEAD_BASE (smoothing latency, ~constant) + LEAD_FRAMES x
# detection interval (sampling latency, scales with frame rate).
LEAD_BASE = 0.02
LEAD_FRAMES = 2.1
LEAD_MIN_S = 0.02
LEAD_MAX_S = 0.16
LEAD_DEADZONE = 45.0
LEAD_MAX = 220.0  # absolute cap (px) so a fast flick can't overshoot wildly


class TargetTracker:
    """Chooses and smooths the point the cursor should be pulled toward."""

    def __init__(self, ema: float = 0.35):
        self._ema = ema
        self._smoothed: Optional[np.ndarray] = None  # screen-space (x, y) float
        self._vel = np.zeros(2)                       # smoothed velocity px/s
        self._prev_raw: Optional[np.ndarray] = None
        self._prev_t: Optional[float] = None
        self._dt = 1.0 / 60.0                         # smoothed detection interval

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
    ) -> Optional[Tuple[int, int]]:
        """Return a smoothed screen-space target, or ``None`` if none found.

        Two modes:
        * ``use_regions=False`` (default) — **just track the color**: pull toward
          the center of the color blob nearest the cursor. No figure/region
          assumptions, so it works for any colored shape.
        * ``use_regions=True`` — split the largest figure into body regions and
          only target contour points inside the active region.

        Coordinate spaces
        -----------------
        * Contours are in *detection* coordinates, which may be downscaled by
          ``scale`` relative to the captured frame.
        * The cursor and returned target are in absolute *desktop* pixels.
        Mapping: ``detection = (screen - origin) * scale`` and
        ``screen = origin + detection / scale``.
        """
        if not shapes:
            self._smoothed = None
            return None

        ox, oy = capture_origin
        inv = 1.0 / scale if scale else 1.0
        # Cursor expressed in detection coordinates.
        cx = (cursor_screen[0] - ox) * scale
        cy = (cursor_screen[1] - oy) * scale
        # FOV radius in detection coordinates (0 = unlimited).
        r_det = pull_radius * scale if pull_radius and pull_radius > 0 else None

        if not use_regions:
            # Pick the color blob whose center is nearest the cursor, and aim at
            # that center. Simple, stable "color magnet". Only blobs inside the
            # FOV radius are eligible.
            best = None
            best_d = None
            for s in shapes:
                bx, by, bw, bh = s.bbox
                px, py = bx + bw / 2.0, by + bh / 2.0
                d = (px - cx) ** 2 + (py - cy) ** 2
                if r_det is not None and d > r_det * r_det:
                    continue
                if best_d is None or d < best_d:
                    best_d, best = d, (px, py)
            if best is None:
                self._smoothed = None
                return None
            target_det = best
        else:
            if figure is None:
                self._smoothed = None
                return None
            # Respect the FOV: ignore a figure whose center is out of range.
            if r_det is not None:
                fx, fy, fw, fh = figure.bbox
                fcx, fcy = fx + fw / 2.0, fy + fh / 2.0
                if (fcx - cx) ** 2 + (fcy - cy) ** 2 > r_det * r_det:
                    self._smoothed = None
                    return None
            region_rect = segment_regions(figure.bbox).get(active_region)
            if region_rect is None:
                self._smoothed = None
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
                target_det = (nearest[0], nearest[1])
            else:
                # Filled figure (no edge points inside the region): aim at the
                # center of the region box so the pull still heads to that area.
                rx, ry, rw, rh = region_rect
                target_det = (rx + rw / 2.0, ry + rh / 2.0)

        # Back to screen space (undo the downscale), then smooth.
        raw = np.array([ox + target_det[0] * inv, oy + target_det[1] * inv],
                       dtype=np.float64)

        # Estimate a smoothed target velocity from raw deltas.
        now = time.perf_counter()
        if self._prev_raw is not None and self._prev_t is not None:
            dt = now - self._prev_t
            if dt > 1e-3:
                inst = (raw - self._prev_raw) / dt
                # Heavy velocity smoothing: keeps prediction stable at low fps
                # (noisy per-frame deltas won't cause overshoot spikes).
                self._vel = 0.85 * self._vel + 0.15 * inst
                if dt < 0.5:  # ignore long stalls when estimating the interval
                    self._dt = 0.8 * self._dt + 0.2 * dt
        self._prev_raw = raw
        self._prev_t = now

        speed = float(np.hypot(self._vel[0], self._vel[1]))

        # Adaptive follow: track a moving target a bit faster (less position
        # lag), but stay gentle when static so aim is rock-steady and precise.
        # Kept mild to avoid oscillation on curved paths / low frame rates.
        ema_eff = self._ema
        if speed > 250:
            ema_eff = min(0.65, self._ema + 0.18)
        elif speed > 80:
            ema_eff = min(0.6, self._ema + 0.1)

        if self._smoothed is None:
            self._smoothed = raw.copy()
        else:
            self._smoothed = ema_eff * raw + (1.0 - ema_eff) * self._smoothed

        # Lead the target when it's actually moving (zero lead when static, so
        # static aim stays pixel-accurate). The lead time scales with the
        # detection interval so it compensates frame-rate latency automatically.
        out = self._smoothed
        if speed > LEAD_DEADZONE:
            lead_time = min(LEAD_MAX_S,
                            max(LEAD_MIN_S, LEAD_BASE + LEAD_FRAMES * self._dt))
            lead = self._vel * lead_time
            n = float(np.hypot(lead[0], lead[1]))
            if n > LEAD_MAX:
                lead = lead * (LEAD_MAX / n)
            out = self._smoothed + lead

        return int(round(out[0])), int(round(out[1]))
