"""Geometry behind the drag-a-box detection-area picker.

The picker itself is a Tk window and needs a display, so what is covered here is
the part that can go quietly wrong: turning an absolute desktop box into
coordinates relative to whatever is being captured. Get that mapping wrong and
detection reads the correct pixels from the wrong place, which shows up as the
pointer aiming at a consistent offset from the target rather than as an error.
"""

import pytest

from cursor_assist.config import AppState
from cursor_assist import region_picker
from cursor_assist.region_picker import apply_region, capture_origin


@pytest.fixture(autouse=True)
def _clear_cache():
    region_picker._origin_cache.clear()
    yield
    region_picker._origin_cache.clear()


def _state(**cap):
    s = AppState()
    with s.lock:
        for k, v in cap.items():
            setattr(s.capture, k, v)
    return s


def test_area_is_stored_relative_to_an_explicit_capture_region():
    s = _state(left=200, top=100, width=1000, height=800)
    with s.lock:
        apply_region(s, "roi", (500, 300, 200, 150))
    assert (s.roi_x, s.roi_y, s.roi_w, s.roi_h) == (300, 200, 200, 150)


def test_area_picked_over_the_capture_corner_is_clipped_not_negative():
    """A box straddling the edge must clip, not wrap into huge coordinates."""
    s = _state(left=200, top=100, width=1000, height=800)
    with s.lock:
        apply_region(s, "roi", (150, 50, 300, 200))
    assert s.roi_x == 0 and s.roi_y == 0
    # The part outside the capture is dropped, keeping the box inside the frame.
    assert s.roi_w == 250 and s.roi_h == 150


def test_area_is_clipped_to_the_far_edge_too():
    s = _state(left=0, top=0, width=800, height=600)
    with s.lock:
        apply_region(s, "roi", (700, 500, 400, 400))
    assert s.roi_x == 700 and s.roi_y == 500
    assert s.roi_w == 100 and s.roi_h == 100


def test_obs_source_maps_one_to_one():
    """The OBS canvas is composited at desktop scale, so its origin is (0, 0)."""
    s = _state(source="obs")
    assert capture_origin(s) == (0, 0, 0, 0)
    with s.lock:
        apply_region(s, "roi", (300, 220, 160, 90))
    assert (s.roi_x, s.roi_y, s.roi_w, s.roi_h) == (300, 220, 160, 90)


def test_picking_a_capture_region_resets_the_detection_area():
    """The area was expressed against the old corner and would now mean
    somewhere else entirely."""
    s = _state(left=0, top=0, width=1920, height=1080)
    with s.lock:
        apply_region(s, "roi", (100, 100, 400, 400))
        assert s.roi_w == 400
        apply_region(s, "capture", (300, 200, 800, 600))
    assert (s.capture.left, s.capture.top) == (300, 200)
    assert (s.capture.width, s.capture.height) == (800, 600)
    assert (s.roi_x, s.roi_y, s.roi_w, s.roi_h) == (0, 0, 0, 0)


def test_capture_origin_is_cached_per_configuration():
    """The overlay asks 60 times a second; resolving a monitor is not free."""
    s = _state(left=10, top=20, width=100, height=200)
    assert capture_origin(s) == (10, 20, 100, 200)
    assert len(region_picker._origin_cache) == 1
    capture_origin(s)
    assert len(region_picker._origin_cache) == 1
    with s.lock:
        s.capture.width = 300
    assert capture_origin(s) == (10, 20, 300, 200)


def test_virtual_desktop_is_a_sane_box():
    x, y, w, h = region_picker.virtual_desktop()
    assert w > 0 and h > 0
    assert isinstance(x, int) and isinstance(y, int)


def test_a_picked_area_survives_a_save_and_load(tmp_path):
    from cursor_assist import persistence
    s = _state(left=0, top=0, width=1920, height=1080)
    with s.lock:
        apply_region(s, "roi", (400, 300, 640, 480))
    path = tmp_path / "settings.json"
    persistence.save(s, path)
    back = AppState()
    persistence.load(back, path)
    assert (back.roi_x, back.roi_y, back.roi_w, back.roi_h) == (400, 300, 640, 480)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
