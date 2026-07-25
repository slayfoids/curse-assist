"""The detection Sensitivity slider must stay usable across its whole range.

The old mapping widened hue, saturation and value together at ``tol * 8``, so
both saturation and value pinned at 255 two thirds of the way along. Past that
point every pixel with roughly the right hue matched however washed out or
nearly black it was: measured on a cluttered frame, sensitivity 28 matched 55%
of the screen across 606 blobs, and past 36 the real target stopped being found
at all — it had merged into the flood.
"""

import colorsys

import numpy as np
import pytest

from cursor_assist.config import (SENSITIVITY_MAX, SENSITIVITY_MIN, AppState,
                                  ColorTarget, tolerances_for)
from cursor_assist.detection import find_shapes
from cursor_assist import persistence

TARGET_BGR = (40, 230, 60)          # a saturated green figure


def _scene():
    """A frame with the sort of clutter a real capture has."""
    rng = np.random.default_rng(7)
    f = np.zeros((450, 700, 3), np.uint8)
    f[:, :] = rng.integers(8, 55, (450, 700, 3), dtype=np.uint8)
    for (x, y, w, h, col) in [(40, 40, 120, 90, (70, 60, 55)),
                              (500, 300, 150, 110, (45, 65, 50)),
                              (250, 60, 90, 60, (60, 50, 70)),
                              (60, 320, 130, 80, (55, 58, 62))]:
        f[y:y + h, x:x + w] = col
    f[150:200, 420:520] = (60, 95, 65)      # a muted green prop, not the target
    f[200:290, 190:230] = TARGET_BGR        # the target
    return f


def _target_color(sensitivity):
    b, g, r = TARGET_BGR
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    h_tol, s_tol, v_tol = tolerances_for(sensitivity)
    return ColorTarget(h=int(h * 179), s=int(s * 255), v=int(v * 255),
                       h_tol=h_tol, s_tol=s_tol, v_tol=v_tol)


def _measure(sensitivity):
    shapes, mask = find_shapes(_scene(), [_target_color(sensitivity)], True, 60)
    coverage = 100.0 * float((mask > 0).sum()) / mask.size
    found = any(abs(s.center[0] - 210) < 25 and abs(s.center[1] - 245) < 45
                for s in shapes)
    return coverage, len(shapes), found


ALL_SETTINGS = [2, 8, 12, 20, 28, 36, 45]


@pytest.mark.parametrize("sensitivity", ALL_SETTINGS)
def test_target_is_found_at_every_sensitivity(sensitivity):
    _coverage, _n, found = _measure(sensitivity)
    assert found, f"target lost at sensitivity {sensitivity}"


@pytest.mark.parametrize("sensitivity", ALL_SETTINGS)
def test_the_mask_never_floods(sensitivity):
    coverage, n, _found = _measure(sensitivity)
    assert coverage < 15.0, f"{coverage:.1f}% of the frame matched"
    assert n < 30, f"{n} blobs — noise, not targets"


def test_hue_tolerance_widens_across_the_slider():
    """Raising sensitivity has to actually mean something."""
    lo = tolerances_for(SENSITIVITY_MIN)
    hi = tolerances_for(SENSITIVITY_MAX)
    assert hi[0] > lo[0] * 3          # hue opens up a lot...
    assert hi[1] < 255 and hi[2] < 255   # ...but S/V never pin wide open


def test_tolerances_rise_monotonically_and_stay_bounded():
    prev = (0, 0, 0)
    for t in range(SENSITIVITY_MIN, SENSITIVITY_MAX + 1):
        cur = tolerances_for(t)
        assert all(c >= p for c, p in zip(cur, prev))
        assert cur[1] <= 255 and cur[2] <= 255
        prev = cur


def test_out_of_range_sensitivity_is_clamped():
    assert tolerances_for(-5) == tolerances_for(SENSITIVITY_MIN)
    assert tolerances_for(9999) == tolerances_for(SENSITIVITY_MAX)


def test_old_settings_files_get_their_tolerances_rebuilt(tmp_path):
    """A v1 file carries the flooding tolerances; loading must not restore them.

    Otherwise the fix would apply only to people who had never run the tool.
    """
    old = {
        "version": 1,
        "sensitivity": 40,
        "colors": [{"h": 60, "s": 240, "v": 230,
                    "h_tol": 40, "s_tol": 255, "v_tol": 255}],
    }
    state = AppState()
    persistence.apply_dict(state, old)
    c = state.colors[0]
    assert (c.h_tol, c.s_tol, c.v_tol) == tolerances_for(40)
    assert c.s_tol < 255 and c.v_tol < 255


def test_current_settings_files_are_restored_verbatim():
    """A v2 file already holds good values and must round-trip untouched."""
    state = AppState()
    state.colors[0] = ColorTarget(h=60, s=240, v=230,
                                  h_tol=11, s_tol=77, v_tol=66)
    data = persistence.to_dict(state)
    assert data["version"] == persistence.SETTINGS_VERSION
    restored = AppState()
    persistence.apply_dict(restored, data)
    c = restored.colors[0]
    assert (c.h_tol, c.s_tol, c.v_tol) == (11, 77, 66)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
