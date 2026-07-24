"""Tests for target locking, spasm guards, and the max-coverage snap."""

import time

import numpy as np
import pytest

from cursor_assist import targeting
from cursor_assist.detection import DetectedShape
from cursor_assist.targeting import TargetTracker, best_circle_center


def blob(x, y, w=20, h=20):
    """A square DetectedShape whose bbox center is (x + w/2, y + h/2)."""
    contour = np.array(
        [[[x, y]], [[x + w, y]], [[x + w, y + h]], [[x, y + h]]],
        dtype=np.int32)
    return DetectedShape(contour=contour, bbox=(x, y, w, h),
                         area=float(w * h), kind="square",
                         center=(x + w / 2.0, y + h / 2.0))


def pick(tracker, shapes, cursor, **kw):
    kw.setdefault("figure", None)
    kw.setdefault("active_region", "Torso")
    kw.setdefault("capture_origin", (0, 0))
    return tracker.pick(shapes=shapes, cursor_screen=cursor, **kw)


# ----------------------------------------------------------------- lock logic

def test_lock_sticks_to_first_target_when_a_nearer_blob_appears():
    t = TargetTracker(ema=1.0)
    a = blob(100, 100)   # center (110, 110)
    b = blob(300, 100)   # center (310, 110)
    # Cursor near A: lock acquires A.
    out = pick(t, [a, b], (120, 120))
    assert out == (110, 110)
    # Cursor moves right next to B — the lock must NOT jump to B.
    out = pick(t, [a, b], (305, 112))
    assert out == (110, 110)


def test_lock_releases_after_target_gone_and_reacquires():
    t = TargetTracker(ema=1.0)
    a = blob(100, 100)
    b = blob(300, 100)
    pick(t, [a, b], (120, 120))
    # A disappears. Within the grace window the tracker holds A's position.
    out = pick(t, [b], (120, 120))
    assert out == (110, 110)
    # After the grace expires the lock releases and B is acquired.
    t._lock_seen -= targeting.LOCK_GRACE_S + 0.01
    out = pick(t, [b], (120, 120))
    assert out == (310, 110)


def test_no_target_returns_none_and_fully_resets():
    t = TargetTracker(ema=1.0)
    pick(t, [blob(100, 100)], (120, 120))
    t._lock_seen -= targeting.LOCK_GRACE_S + 0.01
    assert pick(t, [], (120, 120)) is None
    assert t._lock is None and t._prev_raw is None and t.speed() == 0.0


def test_lock_follows_its_blob_as_it_moves():
    t = TargetTracker(ema=1.0)
    out = pick(t, [blob(100, 100)], (120, 120))
    assert out == (110, 110)
    # Blob drifts 15px; still the same target, lock follows.
    out = pick(t, [blob(115, 100), blob(400, 400)], (120, 120))
    assert out is not None and abs(out[0] - 125) <= 20


# --------------------------------------------------------------- spasm guards

def test_switch_does_not_glide_or_lead_across_blobs():
    """A lock switch snaps cleanly: no velocity spike, no lead overshoot."""
    t = TargetTracker(ema=0.4)
    pick(t, [blob(100, 100)], (110, 110))
    time.sleep(0.01)
    pick(t, [blob(100, 100)], (110, 110))
    # Target vanishes; after grace a far blob is acquired.
    t._lock_seen -= targeting.LOCK_GRACE_S + 0.01
    out = pick(t, [blob(800, 800)], (110, 110))
    assert out == (810, 810)          # snapped exactly, not eased/overshot
    assert t.speed() == 0.0           # the jump never entered the velocity


def test_deadband_holds_still_on_pixel_noise():
    t = TargetTracker(ema=0.5)
    pick(t, [blob(100, 100)], (110, 110))
    for dx in (1, -1, 1, 0, -1):      # sub-deadband wiggle
        time.sleep(0.005)
        out = pick(t, [blob(100 + dx, 100)], (110, 110))
    assert out == (110, 110)


# ----------------------------------------------------------- coverage snapping

def test_best_circle_center_finds_densest_spot():
    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[40:120, 60:140] = 255        # one solid 80x80 block
    cx, cy = best_circle_center(mask, 70.0, 50.0, 20.0)
    # Optimum is anywhere fully inside the block; must be well inside it.
    assert 60 < cx < 140 and 40 < cy < 120
    kx, ky = best_circle_center(mask, 100.0, 80.0, 20.0)
    # From dead center it should stay put (distance-penalty hysteresis).
    assert abs(kx - 100) < 12 and abs(ky - 80) < 12


def test_best_circle_center_empty_mask_returns_none():
    mask = np.zeros((50, 50), dtype=np.uint8)
    assert best_circle_center(mask, 25.0, 25.0, 10.0) is None


def test_snap_engages_after_dwelling_on_color():
    t = TargetTracker(ema=1.0)
    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[90:170, 90:170] = 255        # 80x80 color block, center (130, 130)
    shapes = [blob(90, 90, 80, 80)]
    kw = dict(mask=mask, snap_enabled=True, snap_radius=30, snap_after_ms=1000)
    # Cursor sits on the color; before 1s the target is the bbox center.
    out = pick(t, shapes, (100, 100), **kw)
    assert out == (130, 130)
    # Fake 1s of on-color dwell: snap activates and aims at max coverage,
    # which stays inside the block.
    t._on_color_since -= 1.2
    out = pick(t, shapes, (100, 100), **kw)
    assert 90 < out[0] < 170 and 90 < out[1] < 170


def test_snap_timer_resets_when_cursor_leaves_color():
    t = TargetTracker(ema=1.0)
    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[90:170, 90:170] = 255
    shapes = [blob(90, 90, 80, 80)]
    kw = dict(mask=mask, snap_enabled=True, snap_radius=30, snap_after_ms=1000)
    pick(t, shapes, (100, 100), **kw)
    assert t._on_color_since is not None
    # Cursor far off the color, past the flicker grace: timer resets.
    pick(t, shapes, (300, 300), **kw)
    t._off_color_at -= targeting.SNAP_OFF_GRACE_S + 0.05
    pick(t, shapes, (300, 300), **kw)
    assert t._on_color_since is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
