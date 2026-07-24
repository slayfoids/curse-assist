"""Tests for the display/camera-free logic: segmentation and config helpers.

These run anywhere (no OpenCV, mss, or Windows APIs are touched).
"""

import numpy as np
import pytest

from cursor_assist.config import AppState, ColorTarget
from cursor_assist.segmentation import (
    contour_points_in_region,
    point_in_rect,
    segment_regions,
)


def test_regions_tile_the_bbox_without_gaps_or_overlap_in_area():
    bbox = (0, 0, 100, 200)
    regions = segment_regions(bbox)
    assert set(regions) == {"Head", "Torso", "L-Arm", "R-Arm", "L-Leg", "R-Leg"}

    # Head spans full width at the top.
    hx, hy, hw, hh = regions["Head"]
    assert (hx, hy, hw) == (0, 0, 100)
    assert hh == 30  # 15% of 200

    # Torso band sits directly under the head.
    tx, ty, tw, th = regions["Torso"]
    assert ty == hh
    assert th == 80  # 40% of 200

    # Arms flank the torso in the same vertical band.
    lax, lay, law, lah = regions["L-Arm"]
    rax, ray, raw, rah = regions["R-Arm"]
    assert lay == ty == ray
    assert lax == 0
    assert rax + raw == 100
    assert tx == lax + law  # torso begins where the left arm ends

    # Legs fill the remainder and split on the midline.
    llx, lly, llw, llh = regions["L-Leg"]
    rlx, rly, rlw, rlh = regions["R-Leg"]
    assert lly == rly == hh + th
    assert lly + llh == 200  # legs reach the bottom exactly
    assert llx == 0 and llw == 50
    assert rlx == 50 and rlw == 50


def test_region_offsets_follow_bbox_origin():
    regions = segment_regions((10, 20, 100, 200))
    hx, hy, _, _ = regions["Head"]
    assert (hx, hy) == (10, 20)


def test_point_in_rect_edges():
    rect = (0, 0, 10, 10)
    assert point_in_rect(0, 0, rect)
    assert point_in_rect(9, 9, rect)
    assert not point_in_rect(10, 10, rect)  # exclusive upper bound
    assert not point_in_rect(-1, 5, rect)


def test_contour_points_in_region_filters():
    # Contour points as OpenCV would give them: Nx1x2.
    contour = np.array([[[5, 5]], [[50, 50]], [[9, 1]]], dtype=np.int32)
    inside = contour_points_in_region(contour, (0, 0, 10, 10))
    assert inside.tolist() == [[5, 5], [9, 1]]


def test_color_target_ranges_clamp():
    c = ColorTarget(h=5, s=10, v=250, h_tol=10, s_tol=80, v_tol=80)
    assert c.lower() == (0, 0, 170)      # clamped at 0 for H and S
    assert c.upper() == (15, 90, 255)    # clamped at 255 for V


def test_appstate_snapshot_is_independent():
    st = AppState()
    snap = st.snapshot()
    st.set("smoothness", 0.99)
    st.get("colors")[0].h = 123
    # Snapshot is a deep copy: later edits don't leak in.
    assert snap.smoothness != 0.99 and snap.colors[0].h != 123


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
