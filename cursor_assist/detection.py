"""Color-based contour detection in HSV space.

Produces a color mask from one or more :class:`ColorTarget` ranges, then finds
contours. Supports both filled-blob shapes and thin colored outlines (the
latter matters for figures drawn as an outline rather than a solid fill).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import cv2
import numpy as np

from .config import ColorTarget


@dataclass
class DetectedShape:
    contour: np.ndarray            # Nx1x2 int32 points, in frame coordinates
    bbox: tuple                    # (x, y, w, h)
    area: float
    kind: str                      # rough classification: triangle/rect/poly/circle
    center: tuple = (0.0, 0.0)     # centroid (moments), truer than bbox center


def build_mask(
    hsv: np.ndarray,
    colors: List[ColorTarget],
    thin_border: bool,
) -> np.ndarray:
    """Combine every color target into a single binary mask."""
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for c in colors:
        # A color may span the hue wrap point (red): OR every sub-range.
        for lo, hi in c.hsv_ranges():
            band = cv2.inRange(hsv, np.array(lo, dtype=np.uint8),
                               np.array(hi, dtype=np.uint8))
            mask = cv2.bitwise_or(mask, band)

    if thin_border:
        # Thin outlines survive better and connect small gaps if we dilate
        # slightly; a light close joins broken strokes without fattening blobs.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    else:
        # For fills, open away speckle noise then close pinholes.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


def _classify(contour: np.ndarray) -> str:
    peri = cv2.arcLength(contour, True)
    if peri == 0:
        return "point"
    approx = cv2.approxPolyDP(contour, 0.03 * peri, True)
    v = len(approx)
    if v == 3:
        return "triangle"
    if v == 4:
        x, y, w, h = cv2.boundingRect(approx)
        ar = w / float(h) if h else 0
        return "square" if 0.9 <= ar <= 1.1 else "rect"
    if v <= 6:
        return "poly"
    # Many vertices + high circularity -> treat as circle/ellipse.
    area = cv2.contourArea(contour)
    circ = 4 * np.pi * area / (peri * peri) if peri else 0
    return "circle" if circ > 0.7 else "poly"


def find_shapes(
    frame_bgr: np.ndarray,
    colors: List[ColorTarget],
    thin_border: bool,
    min_area: int,
) -> tuple[List[DetectedShape], np.ndarray]:
    """Return detected shapes plus the mask used (handy for debug overlays)."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = build_mask(hsv, colors, thin_border)

    # RETR_LIST keeps every contour including outline strokes (no nesting rules).
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    shapes: List[DetectedShape] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        bbox = cv2.boundingRect(c)
        # Moments centroid: the shape's true center of mass. For irregular
        # shapes this is a much better aim point than the bbox center (an
        # L-shape's bbox center can even sit outside the shape).
        m = cv2.moments(c)
        if m["m00"] > 1e-6:
            center = (m["m10"] / m["m00"], m["m01"] / m["m00"])
        else:  # degenerate (thin line): fall back to the bbox center
            center = (bbox[0] + bbox[2] / 2.0, bbox[1] + bbox[3] / 2.0)
        shapes.append(
            DetectedShape(
                contour=c,
                bbox=bbox,
                area=area,
                kind=_classify(c),
                center=center,
            )
        )
    return shapes, mask


def largest_figure(shapes: List[DetectedShape]) -> DetectedShape | None:
    """The dominant shape, assumed to be the human-figure drawing."""
    return max(shapes, key=lambda s: s.area) if shapes else None
