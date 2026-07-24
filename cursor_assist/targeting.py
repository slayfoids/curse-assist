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
    ) -> Optional[Tuple[int, int]]:
        """Return a smoothed screen-space target, or ``None`` if none found.

        Coordinate spaces
        -----------------
        * Contours are in *frame* coordinates (0,0 at the capture top-left).
        * The cursor and the returned target are in absolute *desktop* pixels.
        ``capture_origin`` bridges the two: ``screen = frame + origin``.
        """
        if figure is None:
            self._smoothed = None
            return None

        ox, oy = capture_origin
        # Cursor expressed in frame coordinates for the nearest-point search.
        cx = cursor_screen[0] - ox
        cy = cursor_screen[1] - oy

        region_rect = segment_regions(figure.bbox).get(active_region)
        if region_rect is None:
            self._smoothed = None
            return None

        # Gather candidate contour points inside the region across all shapes.
        candidates: List[np.ndarray] = []
        for s in shapes:
            pts = contour_points_in_region(s.contour, region_rect)
            if len(pts):
                candidates.append(pts)

        if not candidates:
            self._smoothed = None
            return None

        pts = np.vstack(candidates).astype(np.float64)
        d2 = (pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2
        nearest = pts[int(np.argmin(d2))]

        # Back to screen space, then smooth.
        raw = np.array([nearest[0] + ox, nearest[1] + oy], dtype=np.float64)
        if self._smoothed is None:
            self._smoothed = raw
        else:
            a = self._ema
            self._smoothed = a * raw + (1.0 - a) * self._smoothed

        return int(round(self._smoothed[0])), int(round(self._smoothed[1]))
