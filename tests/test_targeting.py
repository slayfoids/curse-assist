"""Tests for target locking, spasm guards, and the max-coverage snap."""

import math
import time

import cv2
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


def test_best_circle_center_declines_when_the_circle_swallows_everything():
    """A circle larger than the search region has no best position.

    Every placement then covers the same pixels, the arg-max is decided by
    floating-point noise, and the answer is an artefact. It showed up as a
    constant ~8 px diagonal bias whenever target-follow shrank the scanned
    window below the snap circle.
    """
    mask = np.zeros((220, 220), dtype=np.uint8)
    mask[60:160, 90:130] = 255
    assert best_circle_center(mask, 110.0, 110.0, 250.0) is None
    # A sensible radius on the same mask still works.
    assert best_circle_center(mask, 110.0, 110.0, 20.0) is not None


def test_best_circle_center_stays_inside_the_bounds_it_is_given():
    """The snap refines within one target; it must not wander to a better one."""
    mask = np.zeros((320, 460), dtype=np.uint8)
    mask[100:190, 100:190] = 255      # the locked blob, 90x90 at (100, 100)
    mask[70:260, 250:430] = 255       # a much denser neighbour to the right
    box = (100, 100, 90, 90)

    # Given a circle big enough to see past the blob, the free search walks off
    # it and onto the neighbour...
    free = best_circle_center(mask, 145.0, 145.0, 130.0)
    assert free is not None and free[0] > 190

    # ...while the bounded one stays on the target, at every radius.
    for radius in (20, 45, 80, 130, 200):
        held = best_circle_center(mask, 145.0, 145.0, float(radius), bounds=box)
        if held is None:
            continue                  # circle too big to have an optimum at all
        margin = radius * targeting.SNAP_BOUND_MARGIN
        assert box[0] - margin <= held[0] <= box[0] + box[2] + margin
        assert box[1] - margin <= held[1] <= box[1] + box[3] + margin


def test_snap_does_not_drag_the_aim_toward_a_neighbouring_target():
    """The regression that made the feature unusable.

    The snap circle used to be the field-of-view circle — 250 px by default —
    so "where is this colour densest" was answered about a 500 px-wide patch of
    screen rather than about the target. With two figures 220 px apart the aim
    settled 47 px off the locked one, and at some spacings landed between the
    two, pointing at neither.
    """
    scale = 0.5
    mask = np.zeros((450, 700), dtype=np.uint8)
    mask[200:290, 190:230] = 255      # locked target,  centre det (210, 245)
    mask[200:290, 300:340] = 255      # neighbour,      centre det (320, 245)
    shapes = [blob(190, 200, 40, 90), blob(300, 200, 40, 90)]
    want = (420, 490)                 # the locked target, in screen px

    for radius in (0, 30, 150, 250, 400):
        t = TargetTracker(ema=1.0)
        out = t.pick(shapes=shapes, figure=None, active_region="Torso",
                     cursor_screen=want, capture_origin=(0, 0), scale=scale,
                     mask=mask, snap_enabled=True, snap_radius=radius,
                     snap_after_ms=0, lock_enabled=True)
        assert abs(out[0] - want[0]) <= 12, (radius, out)
        assert abs(out[1] - want[1]) <= 12, (radius, out)


def test_snap_still_moves_the_aim_onto_the_densest_part():
    """Confining it must not turn it into a no-op."""
    scale = 0.5
    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[100:160, 100:180] = 255      # torso block
    mask[160:260, 100:110] = 255      # thin leg, which drags the centroid down
    shapes = [blob(100, 100, 80, 160)]
    kw = dict(figure=None, active_region="Torso", capture_origin=(0, 0),
              scale=scale, mask=mask, snap_after_ms=0, lock_enabled=True,
              snap_radius=0)
    cursor = (280, 360)
    plain = TargetTracker(ema=1.0).pick(shapes=shapes, cursor_screen=cursor,
                                        snap_enabled=False, **kw)
    snapped = TargetTracker(ema=1.0).pick(shapes=shapes, cursor_screen=cursor,
                                          snap_enabled=True, **kw)
    torso = (140 / scale, 130 / scale)
    before = math.hypot(plain[0] - torso[0], plain[1] - torso[1])
    after = math.hypot(snapped[0] - torso[0], snapped[1] - torso[1])
    assert after < before - 20        # meaningfully closer to the mass


def _auto_radius(shape, mask, scale=1.0):
    t = TargetTracker(ema=1.0)
    x, y, w, h = shape.bbox
    t.pick(shapes=[shape], figure=None, active_region="Torso",
           cursor_screen=(x + w // 2, y + h // 2), capture_origin=(0, 0),
           scale=scale, mask=mask, snap_enabled=True, snap_radius=0,
           snap_after_ms=0, lock_enabled=True)
    return t._snap_radius_used


def test_auto_snap_radius_scales_with_the_target():
    """Radius 0 sizes the circle from the target, not from the user's FOV."""
    mask = np.zeros((600, 600), dtype=np.uint8)
    radii = []
    for (x, y, w, h) in ((100, 100, 40, 90), (100, 100, 160, 300)):
        mask[:] = 0
        mask[y:y + h, x:x + w] = 255
        r = _auto_radius(blob(x, y, w, h), mask)
        # 2 * area / perimeter is the shape's limb thickness.
        thick = 2.0 * (w * h) / (2.0 * (w + h))
        assert abs(r - targeting.SNAP_AUTO_THICK * thick) < 1.5, (w, h, r)
        radii.append(r)
    assert radii[1] > radii[0] * 2          # a bigger target, a bigger circle


def test_auto_snap_radius_uses_thickness_not_the_bounding_box():
    """An L-shape is 200 px across but made of 40 px bars.

    Sizing from the bounding box gave a circle three times too big — so big
    that every placement scored alike and the aim stayed in the empty inside
    corner of the L, which is exactly where it must not be.
    """
    mask = np.zeros((500, 500), dtype=np.uint8)
    mask[100:300, 100:140] = 255          # vertical bar, 40 wide
    mask[260:300, 100:300] = 255          # horizontal bar, 40 tall
    contour, _ = cv2.findContours(mask, cv2.RETR_LIST,
                                  cv2.CHAIN_APPROX_SIMPLE)
    shape = DetectedShape(contour=contour[0],
                          bbox=cv2.boundingRect(contour[0]),
                          area=float(cv2.contourArea(contour[0])),
                          kind="poly", center=(180.0, 200.0))
    r = _auto_radius(shape, mask)
    assert 10 < r < 30, r                 # sized to the bar, not to the box
    assert r < 0.32 * 200 / 2             # far under the old box-based figure


def test_snap_is_skipped_when_no_blob_was_matched_this_frame():
    """With nothing detected there is no target to refine against."""
    t = TargetTracker(ema=1.0)
    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[90:170, 90:170] = 255
    shapes = [blob(90, 90, 80, 80)]
    kw = dict(mask=mask, snap_enabled=True, snap_radius=20, snap_after_ms=0)
    pick(t, shapes, (100, 100), **kw)
    assert t._lock_box is not None
    pick(t, [], (100, 100), **kw)     # blob vanishes, lock held within grace
    assert t._lock_box is None


def test_snap_engages_after_dwelling_on_color():
    t = TargetTracker(ema=1.0)
    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[90:170, 90:170] = 255        # 80x80 color block, center (130, 130)
    shapes = [blob(90, 90, 80, 80)]
    kw = dict(mask=mask, snap_enabled=True, snap_radius=30, snap_after_ms=1000)
    # Cursor sits on the color; before 1s the target is the bbox centroid.
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


def test_instant_snap_bypasses_the_dwell_gate():
    """``snap_after_ms=0`` must snap on the very first frame, off-color.

    The timed path only starts its dwell clock once the cursor is *resting on*
    the color. A moving target never lets that happen, so without the bypass a
    0 ms delay would still never engage -- on exactly the targets that need it.
    """
    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[90:130, 90:130] = 255        # dense block centered on (110, 110)
    shapes = [blob(90, 90, 80, 80)]   # bbox centroid is (130, 130)
    kw = dict(mask=mask, snap_enabled=True, snap_radius=15)
    far = (350, 350)                  # cursor still chasing; nowhere near color

    # Timed: the gate never opens from off-color, so we get the plain centroid.
    timed = TargetTracker(ema=1.0)
    assert pick(timed, shapes, far, snap_after_ms=1000, **kw) == (130, 130)
    assert timed._on_color_since is None

    # Instant: engages immediately and re-aims onto the dense block.
    now = TargetTracker(ema=1.0)
    out = pick(now, shapes, far, snap_after_ms=0, **kw)
    assert now._on_color_since is not None
    assert out != (130, 130)
    assert 90 < out[0] < 130 and 90 < out[1] < 130


# ------------------------------------------------------- motion / lag guards

def _travel(tracker, speed, hz, steps, y=300.0):
    """Feed a constant-speed horizontal target at a fixed sample rate."""
    dt = 1.0 / hz
    x = 100.0
    for i in range(steps):
        x = 100.0 + speed * (i * dt)
        tracker._smooth(np.array([x, y]), i * dt, switched=(i == 0))
    return x


def test_smoothing_is_frame_rate_independent():
    """Identical motion at different sample rates must smooth the same.

    The old fixed per-frame blend applied its coefficient once per detection
    frame, so it smoothed about twice as hard at 30 fps as at 60 — the same
    settings drifted in feel with whatever the capture source and CPU were
    doing. The time-based filter derives its coefficient from real elapsed
    time, so the steady-state lag is a property of the settings alone.
    """
    lags = []
    for hz in (30.0, 120.0):
        t = TargetTracker(ema=0.45)
        x = _travel(t, 600.0, hz, int(hz * 0.8))
        lags.append(x - t._smoothed[0])       # steady-state position lag
    slow, fast = lags
    assert slow > 0 and fast > 0              # both genuinely trail the target
    assert abs(slow - fast) <= 0.25 * max(slow, fast)


def test_fast_continuous_motion_is_not_treated_as_a_teleport():
    """A target crossing faster than TELEPORT_SPEED must keep its track.

    Judging a teleport on speed alone reset tracking on every frame of a
    genuinely fast target, which threw away the velocity estimate the lead
    depends on and made fast motion jerky.
    """
    t = TargetTracker(ema=0.45)
    speed = 4000.0                            # well above TELEPORT_SPEED
    assert speed > targeting.TELEPORT_SPEED
    _travel(t, speed, 60.0, 12)
    assert t._track_frames >= 8               # never reset mid-flight
    assert t.speed() > 2000.0                 # velocity estimate survived


def test_unpredicted_jump_still_resets_tracking():
    """The guard must still fire for a real discontinuity."""
    t = TargetTracker(ema=0.45)
    _travel(t, 600.0, 60.0, 8)
    assert t._track_frames >= 6
    # Blob re-identified somewhere the velocity never pointed.
    t._smooth(np.array([900.0, 700.0]), 8 / 60.0, switched=False)
    # Track restarted (the counter takes its unconditional +1 for this frame,
    # so it lands at 1, well under LEAD_WARMUP) and velocity was discarded.
    assert t._track_frames <= 1
    assert t.speed() == 0.0
    assert tuple(t._smoothed) == (900.0, 700.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
