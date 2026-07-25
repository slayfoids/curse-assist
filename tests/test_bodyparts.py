"""Body-region aiming: it must aim at *one* figure, the one it locked onto.

This path used to bypass target selection entirely — it took whichever blob was
largest each frame, kept no lock, and never reported a switch. With two people
on screen the aim jumped between them and the jump was fed to the velocity
estimate as real motion, which measured as a 4583 px/s fling against 247 px/s
for the same scene in plain colour mode.
"""

import math

import cv2
import numpy as np
import pytest

from cursor_assist import targeting
from cursor_assist.detection import find_shapes
from cursor_assist.config import ColorTarget
from cursor_assist.targeting import TargetTracker

RED = (0, 0, 255)
COL = [ColorTarget(h=0, s=255, v=255, h_tol=12, s_tol=120, v_tol=120)]


def humanoid(f, x, y, gap=0):
    """Head / torso / legs. ``gap`` separates the head, as a strap or a
    different-coloured collar does in a real capture."""
    cv2.circle(f, (int(x), int(y - 60 - gap)), 16, RED, -1)
    cv2.rectangle(f, (int(x - 22), int(y - 40)), (int(x + 22), int(y + 20)),
                  RED, -1)
    cv2.rectangle(f, (int(x - 18), int(y + 20)), (int(x - 4), int(y + 80)),
                  RED, -1)
    cv2.rectangle(f, (int(x + 4), int(y + 20)), (int(x + 18), int(y + 80)),
                  RED, -1)


def scene(*figures, gap=0):
    f = np.zeros((500, 900, 3), np.uint8)
    for (x, y) in figures:
        humanoid(f, x, y, gap)
    shapes, mask = find_shapes(f, COL, True, 60)
    return shapes, mask


def aim(shapes, mask, region, cursor, tracker=None, **kw):
    t = tracker or TargetTracker(ema=1.0)
    return t, t.pick(shapes=shapes, figure=None, active_region=region,
                     cursor_screen=cursor, capture_origin=(0, 0), scale=1.0,
                     mask=mask, use_regions=True, lock_enabled=True,
                     part_attraction=1.0, **kw)


def test_regions_land_on_the_right_part_of_the_figure():
    shapes, mask = scene((300, 250))
    heights = {}
    for region in ("Head", "Torso", "Feet"):
        _t, out = aim(shapes, mask, region, (300, 250))
        assert out is not None
        heights[region] = out[1]
    assert heights["Head"] < heights["Torso"] < heights["Feet"]
    assert heights["Head"] < 220           # up around the head disc
    assert heights["Feet"] > 290           # down at the boots


def test_aim_stays_on_the_locked_figure_when_another_is_present():
    """The core fix: a second person must not steal the aim."""
    shapes, mask = scene((300, 250), (620, 250))
    t, first = aim(shapes, mask, "Torso", (300, 250))
    assert abs(first[0] - 300) < 40, first
    # Now the cursor drifts toward the other figure. The lock must hold.
    for _ in range(6):
        _t, out = aim(shapes, mask, "Torso", (600, 250), tracker=t)
    assert abs(out[0] - 300) < 60, out


def test_a_figure_in_several_pieces_is_treated_as_one():
    """Head detached from the body must still be part of the same figure.

    Different colours for hair and shirt, a dark collar, a strap — all produce
    separate blobs. Taking only the largest aims at whichever piece happens to
    win this frame.
    """
    shapes, mask = scene((300, 250), gap=14)
    assert len(shapes) >= 2                # genuinely separate blobs
    t, out = aim(shapes, mask, "Head", (300, 250))
    assert out is not None
    # The head band must be found from the *assembled* figure, so the aim
    # lands on the detached disc rather than the top of the torso.
    assert out[1] < 215, out


def test_a_distant_figure_is_not_absorbed():
    """Grouping must not swallow a bystander into the same body."""
    shapes, mask = scene((300, 250), (620, 250))
    t = TargetTracker(ema=1.0)
    aim(shapes, mask, "Torso", (300, 250), tracker=t)
    group, bbox = t._figure_parts(shapes, 1.0)
    assert bbox[2] < 200, bbox              # not spanning both figures
    for s in group:
        assert s.bbox[0] < 450, s.bbox


def test_switching_figures_is_declared_as_a_switch():
    """The jump between two figures must reset tracking, not feed velocity.

    Reporting it as continuous motion is what turned a re-selection into a
    fling.
    """
    shapes, mask = scene((300, 250), (620, 250))
    t = TargetTracker(ema=0.45)
    aim(shapes, mask, "Torso", (300, 250), tracker=t)
    for _ in range(8):
        aim(shapes, mask, "Torso", (300, 250), tracker=t)
    # Force the lock to expire, then aim from beside the far figure.
    t._lock_seen -= targeting.LOCK_GRACE_S + 1.0
    aim(shapes, mask, "Torso", (620, 250), tracker=t)
    assert t.raw_speed() == 0.0, t.raw_speed()


def test_a_tiny_target_falls_back_to_aiming_at_it():
    """Regions across a handful of pixels are meaningless."""
    f = np.zeros((300, 300, 3), np.uint8)
    cv2.circle(f, (150, 150), 6, RED, -1)
    shapes, mask = find_shapes(f, COL, True, 20)
    _t, out = aim(shapes, mask, "Head", (150, 150))
    assert out is not None
    assert math.hypot(out[0] - 150, out[1] - 150) < 12, out


def test_region_aiming_respects_the_pull_radius():
    shapes, mask = scene((700, 250))
    _t, out = aim(shapes, mask, "Torso", (100, 250), pull_radius=120)
    assert out is None


def test_body_mode_inherits_the_lock_and_commit_machinery():
    """It goes through the same selection as colour mode, so it gets the lot."""
    shapes, mask = scene((300, 250))
    t = TargetTracker(ema=1.0)
    t.set_commit_px(10)
    aim(shapes, mask, "Torso", (300, 250), tracker=t)
    assert t._lock is not None            # locked, which it never used to be
    assert t.matched() is True
    assert t._committed is not None       # and commitment is active


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
