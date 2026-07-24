"""Target selection and jitter smoothing.

Turns a frame's detected contours + the active region into a single screen-space
target point: the contour point nearest the current cursor, restricted to the
active region. An exponential moving average is applied to the *target* (not the
cursor) so noisy detection doesn't make the pull twitch frame to frame.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from .detection import DetectedShape
from .segmentation import contour_points_in_region, segment_regions


class TargetTracker:
    """Chooses and smooths the point the cursor should be pulled toward."""

    def __init__(self, ema: float = 0.35):
        self._ema = ema
        self._smoothed: Optional[np.ndarray] = None  # screen-space (x, y) float

    def set_ema(self, ema: float) -> None:
        self._ema = max(0.0, min(1.0, ema))

    def reset(self) -> None:
        self._smoothed = None

    def pick(
        self,
        shapes: List[DetectedShape],
        figure: Optional[DetectedShape],
        active_region: str,
        cursor_screen: Tuple[int, int],
        capture_origin: Tuple[int, int],
        scale: float = 1.0,
        use_regions: bool = False,
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

        if not use_regions:
            # Pick the color blob whose center is nearest the cursor, and aim at
            # that center. Simple, stable "color magnet".
            best = None
            best_d = None
            for s in shapes:
                bx, by, bw, bh = s.bbox
                px, py = bx + bw / 2.0, by + bh / 2.0
                d = (px - cx) ** 2 + (py - cy) ** 2
                if best_d is None or d < best_d:
                    best_d, best = d, (px, py)
            target_det = best
        else:
            if figure is None:
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
        if self._smoothed is None:
            self._smoothed = raw
        else:
            a = self._ema
            self._smoothed = a * raw + (1.0 - a) * self._smoothed

        return int(round(self._smoothed[0])), int(round(self._smoothed[1]))
