"""Accuracy tests: hue wraparound, centroids, blob scoring, body aim, configs."""

import numpy as np
import pytest

from cursor_assist.config import AppState, ColorTarget
from cursor_assist.detection import DetectedShape, find_shapes
from cursor_assist.segmentation import segment_regions
from cursor_assist.targeting import TargetTracker
from cursor_assist import persistence

import cv2


# ------------------------------------------------------------ hue wraparound

def test_hsv_ranges_split_at_low_hue_wrap():
    c = ColorTarget(h=3, s=200, v=200, h_tol=10, s_tol=80, v_tol=80)
    ranges = c.hsv_ranges()
    assert len(ranges) == 2
    (lo1, hi1), (lo2, hi2) = ranges
    assert lo1[0] == 0 and hi1[0] == 13       # 0..13
    assert lo2[0] == 173 and hi2[0] == 179    # wrapped tail

def test_hsv_ranges_split_at_high_hue_wrap():
    c = ColorTarget(h=176, h_tol=8)
    ranges = c.hsv_ranges()
    assert len(ranges) == 2
    assert ranges[0][0][0] == 168 and ranges[0][1][0] == 179
    assert ranges[1][0][0] == 0 and ranges[1][1][0] == 4

def test_hsv_ranges_no_split_mid_hue():
    assert len(ColorTarget(h=90, h_tol=10).hsv_ranges()) == 1

def test_red_detected_across_the_wrap():
    """A red at hue 177 must match a target color set at hue 2."""
    hsv = np.zeros((60, 60, 3), dtype=np.uint8)
    hsv[20:40, 20:40] = (177, 220, 220)
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    target = ColorTarget(h=2, s=220, v=220, h_tol=8, s_tol=80, v_tol=80)
    shapes, _ = find_shapes(bgr, [target], thin_border=False, min_area=10)
    assert len(shapes) == 1
    cx, cy = shapes[0].center
    assert 25 < cx < 35 and 25 < cy < 35


# ----------------------------------------------------------------- centroids

def test_centroid_is_center_of_mass_not_bbox_center():
    """For an L-shape the centroid must sit inside the ink, not the bbox middle."""
    img = np.zeros((120, 120, 3), dtype=np.uint8)
    green = (0, 255, 0)
    cv2.rectangle(img, (10, 10), (30, 110), green, -1)    # vertical bar
    cv2.rectangle(img, (10, 90), (110, 110), green, -1)   # horizontal bar
    shapes, mask = find_shapes(img, [ColorTarget(h=60, s=255, v=255)],
                               thin_border=False, min_area=50)
    assert len(shapes) == 1
    s = shapes[0]
    # True center of mass of the ink pixels.
    ys, xs = np.nonzero(mask)
    true_cx, true_cy = float(xs.mean()), float(ys.mean())
    bbox_cx = s.bbox[0] + s.bbox[2] / 2.0
    bbox_cy = s.bbox[1] + s.bbox[3] / 2.0
    # The moments centroid tracks the mass center closely; the bbox center
    # (~60,60, in the empty corner of the L) is way off it.
    assert abs(s.center[0] - true_cx) < 3 and abs(s.center[1] - true_cy) < 3
    assert np.hypot(bbox_cx - true_cx, bbox_cy - true_cy) > 15


# -------------------------------------------------------------- blob scoring

def _blob(x, y, w, h):
    contour = np.array([[[x, y]], [[x + w, y]], [[x + w, y + h]], [[x, y + h]]],
                       dtype=np.int32)
    return DetectedShape(contour=contour, bbox=(x, y, w, h),
                         area=float(w * h), kind="square",
                         center=(x + w / 2.0, y + h / 2.0))

def test_acquisition_prefers_real_target_over_slightly_closer_speck():
    t = TargetTracker(ema=1.0)
    speck = _blob(107, 162, 6, 6)     # center (110,165): 60px from cursor
    big = _blob(140, 100, 60, 60)     # center (170,130): 65px from cursor
    out = t.pick(shapes=[speck, big], figure=None, active_region="Torso",
                 cursor_screen=(110, 105), capture_origin=(0, 0))
    assert out == (170, 130)

def test_acquisition_still_takes_much_closer_blob():
    t = TargetTracker(ema=1.0)
    near = _blob(100, 100, 10, 10)    # center (105,105): 7px away
    big = _blob(300, 300, 80, 80)     # far
    out = t.pick(shapes=[near, big], figure=None, active_region="Torso",
                 cursor_screen=(110, 108), capture_origin=(0, 0))
    assert out == (105, 105)


# ------------------------------------------------------------------ body aim

def test_feet_region_is_bottom_strip():
    regions = segment_regions((0, 0, 100, 200))
    fx, fy, fw, fh = regions["Feet"]
    assert fx == 0 and fw == 100
    assert fy + fh == 200 and fh == 24     # bottom 12%

def test_segmentation_adapts_to_pose_aspect():
    tall = segment_regions((0, 0, 100, 200))     # standing
    square = segment_regions((0, 0, 100, 100))   # crouching
    assert tall["Head"][3] == 30     # 15% of 200
    assert square["Head"][3] == 20   # 20% of 100

def test_part_attraction_blends_toward_figure_center():
    # Diamond figure: only its top vertex (50, 0) falls in the head band.
    contour = np.array([[[50, 0]], [[100, 100]], [[50, 200]], [[0, 100]]],
                       dtype=np.int32)
    figure = DetectedShape(contour=contour, bbox=(0, 0, 100, 200),
                           area=20000.0, kind="poly", center=(50.0, 100.0))
    kw = dict(shapes=[figure], figure=figure, active_region="Head",
              cursor_screen=(50, 0), capture_origin=(0, 0), use_regions=True)
    full = TargetTracker(ema=1.0).pick(part_attraction=1.0, **kw)
    half = TargetTracker(ema=1.0).pick(part_attraction=0.5, **kw)
    assert full == (50, 0)           # aim exactly at the part
    assert half == (50, 50)          # halfway to the centroid (50,100)


# ------------------------------------------------------------- saved configs

def test_config_code_format_and_roundtrip(tmp_path):
    st = AppState()
    st.set("smoothness", 0.71)
    st.set("pull_radius", 333)
    code = persistence.save_config(st, "my setup", base=tmp_path)
    assert persistence._CODE_RE.match(code)

    listed = persistence.list_configs(base=tmp_path)
    assert [c["code"] for c in listed] == [code]
    assert listed[0]["name"] == "my setup"

    fresh = AppState()
    assert persistence.load_config(fresh, code.lower(), base=tmp_path)
    assert fresh.get("smoothness") == 0.71
    assert fresh.get("pull_radius") == 333

def test_config_codes_are_unique(tmp_path):
    st = AppState()
    codes = {persistence.save_config(st, base=tmp_path) for _ in range(20)}
    assert len(codes) == 20

def test_config_delete_and_bad_codes(tmp_path):
    st = AppState()
    code = persistence.save_config(st, base=tmp_path)
    assert persistence.delete_config(code, base=tmp_path)
    assert persistence.list_configs(base=tmp_path) == []
    # invalid / traversal-ish codes are rejected without touching the fs
    assert not persistence.load_config(st, "../settings", base=tmp_path)
    assert not persistence.load_config(st, "CRS-......", base=tmp_path)
    assert not persistence.delete_config("..\\..\\x", base=tmp_path)

def test_part_attraction_persists():
    st = AppState()
    st.set("part_attraction", 0.6)
    d = persistence.to_dict(st)
    fresh = AppState()
    persistence.apply_dict(fresh, d)
    assert fresh.part_attraction == 0.6


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
