"""Body-region segmentation for human-figure drawings.

Given the bounding box of the detected figure outline, split it into six named
regions using simple proportional heuristics. These are deliberately crude --
they only need to be good enough to bias the cursor toward the right area, and
the operator can always switch the active region by hand.

Region layout within the figure bounding box (x right, y down):

    ┌───────────────┐  top
    │     Head      │  top 15%
    ├───┬───────┬───┤
    │L- │ Torso │R- │  next 40%, arms are the outer thirds of that band
    │Arm│       │Arm│
    ├───┴───┬───┴───┤
    │ L-Leg │ R-Leg │  bottom 45%, split on the vertical midline
    └───────┴───────┘  bottom
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

Rect = Tuple[int, int, int, int]  # (x, y, w, h) in frame coordinates


def segment_regions(bbox: Rect) -> Dict[str, Rect]:
    """Return a rectangle per named region, in frame coordinates."""
    x, y, w, h = bbox

    head_h = int(h * 0.15)
    torso_h = int(h * 0.40)
    # legs take the remainder so rounding never leaves a gap
    torso_y = y + head_h
    legs_y = y + head_h + torso_h
    legs_h = (y + h) - legs_y

    arm_w = int(w * 0.28)        # outer thirds (ish) of the torso band are arms
    torso_x = x + arm_w
    torso_w = w - 2 * arm_w
    mid_x = x + w // 2

    return {
        "Head":  (x, y, w, head_h),
        "Torso": (torso_x, torso_y, torso_w, torso_h),
        "L-Arm": (x, torso_y, arm_w, torso_h),
        # L-Arm / R-Arm are labeled from the *viewer's* left and right.
        "R-Arm": (x + w - arm_w, torso_y, arm_w, torso_h),
        "L-Leg": (x, legs_y, mid_x - x, legs_h),
        "R-Leg": (mid_x, legs_y, (x + w) - mid_x, legs_h),
    }


def point_in_rect(px: int, py: int, rect: Rect) -> bool:
    x, y, w, h = rect
    return x <= px < x + w and y <= py < y + h


def contour_points_in_region(contour: np.ndarray, rect: Rect) -> np.ndarray:
    """Filter a contour's points down to those inside ``rect``.

    ``contour`` is an ``Nx1x2`` array as returned by OpenCV. Returns an ``Mx2``
    array of ``(x, y)`` points (possibly empty).
    """
    pts = contour.reshape(-1, 2)
    x, y, w, h = rect
    inside = (
        (pts[:, 0] >= x)
        & (pts[:, 0] < x + w)
        & (pts[:, 1] >= y)
        & (pts[:, 1] < y + h)
    )
    return pts[inside]
