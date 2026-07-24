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
    ├───────┴───────┤
    │     Feet      │  bottom 12% (overlaps the leg boxes)
    └───────────────┘  bottom

The proportions adapt mildly to the figure's aspect ratio: a squat/crouching
figure (wide box) gets a taller head band and shorter legs than a standing one,
which keeps the bands roughly on the right body parts as the pose changes.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

Rect = Tuple[int, int, int, int]  # (x, y, w, h) in frame coordinates


def segment_regions(bbox: Rect) -> Dict[str, Rect]:
    """Return a rectangle per named region, in frame coordinates."""
    x, y, w, h = bbox

    # Aspect-adaptive proportions: a standing figure (tall box) has a small
    # head band and long legs; a crouched/squat figure (near-square or wide
    # box) has a proportionally bigger head and shorter legs.
    aspect = h / float(w) if w else 2.0
    if aspect >= 1.6:            # standing
        head_f, torso_f = 0.15, 0.40
    elif aspect >= 1.0:          # crouching / kneeling
        head_f, torso_f = 0.20, 0.45
    else:                        # prone / very wide: bands compress
        head_f, torso_f = 0.25, 0.50

    head_h = int(h * head_f)
    torso_h = int(h * torso_f)
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
        # Feet overlap the bottom of the leg boxes on purpose: aiming "Feet"
        # means the very bottom strip of the figure regardless of leg split.
        "Feet":  (x, y + h - max(1, int(h * 0.12)), w, max(1, int(h * 0.12))),
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
