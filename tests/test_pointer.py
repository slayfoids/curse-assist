"""Pointer-ballistics model: seeding, learning, and the resolution floor.

The engine has to behave the same whether Windows is scaling its movement down
to a thirty-second or up by three and a half times. These cover the model that
makes that true.
"""

import pytest

from cursor_assist.pointer import (BIN_EDGES, GainCurve, N_BINS,
                                   PointerSettings, SPEED_TABLE, emit_vector,
                                   read_settings)


# ------------------------------------------------------------------ settings

def test_speed_table_matches_the_settings_slider():
    """The 11 notches Windows exposes, and their documented multipliers."""
    notches = {1: 0.03125, 2: 0.0625, 4: 0.25, 6: 0.5, 8: 0.75, 10: 1.0,
               12: 1.5, 14: 2.0, 16: 2.5, 18: 3.0, 20: 3.5}
    for value, mult in notches.items():
        assert PointerSettings(speed=value).multiplier == mult
    assert len(SPEED_TABLE) == 20


def test_settings_are_clamped_to_the_valid_range():
    assert PointerSettings(speed=0).multiplier == SPEED_TABLE[0]
    assert PointerSettings(speed=99).multiplier == SPEED_TABLE[-1]


def test_read_settings_never_raises():
    """Off Windows, or with the call refused, it must fall back not explode."""
    s = read_settings()
    assert 1 <= s.speed <= 20
    assert isinstance(s.enhance, bool)


# ---------------------------------------------------------------- seeding

@pytest.mark.parametrize("speed", [1, 4, 10, 14, 20])
def test_curve_is_correct_before_any_observation(speed):
    """Seeded from the OS, so the very first move is already the right size.

    Learning from a fixed 1.0 start meant every opening move was wrong by the
    full ratio — at 3.5x the first correction overshot by 250%.
    """
    mult = PointerSettings(speed=speed).multiplier
    curve = GainCurve(PointerSettings(speed=speed))
    for want in (10.0, 60.0, 400.0):
        units = curve.units_for(want)
        assert 0.85 * want <= units * mult <= 1.2 * want


def test_enhance_precision_seeds_a_rising_curve():
    """Acceleration means big requests travel further per unit than small ones."""
    flat = GainCurve(PointerSettings(speed=10, enhance=False)).snapshot()
    ramp = GainCurve(PointerSettings(speed=10, enhance=True)).snapshot()
    assert len(set(round(v, 6) for v in flat)) == 1     # flat when off
    assert ramp[0] < ramp[-1]                           # rising when on
    # Anchored so the average stays at the OS multiplier rather than drifting.
    assert abs(sum(ramp) / len(ramp) - 1.0) < 1e-6


def test_units_for_is_signed_and_zero_safe():
    c = GainCurve(PointerSettings(speed=10))
    assert c.units_for(0.0) == 0.0
    assert c.units_for(-50.0) == -c.units_for(50.0)


def test_emit_vector_preserves_direction():
    c = GainCurve(PointerSettings(speed=10))
    ux, uy = emit_vector(c, 30.0, 40.0)
    assert abs(ux / uy - 30.0 / 40.0) < 1e-6
    assert emit_vector(c, 0.0, 0.0) == (0.0, 0.0)


# ---------------------------------------------------------------- learning

def _teach(curve, true_gain, units=8.0, rounds=40):
    """Feed the curve honest observations from an OS with a flat multiplier."""
    for _ in range(rounds):
        curve.observe(units, units * true_gain)


def test_learns_the_real_ratio_when_the_seed_is_wrong():
    """A wrong seed — shared PC, a mouse changing DPI profile — self-corrects."""
    c = GainCurve(PointerSettings(speed=20))     # told 3.5x
    _teach(c, 0.4)                               # truth is 0.4x
    assert 0.3 <= c.gain_for(8.0) <= 0.55


def test_every_observation_informs_the_base_not_just_its_own_bin():
    """One bin's samples must move the whole curve.

    Learning a separate number per bin meant the pointer had to sweep the full
    range of speeds several times before any of it was right, and bins a run
    never visited stayed wrong indefinitely.
    """
    c = GainCurve(PointerSettings(speed=10))     # seeded 1.0 everywhere
    _teach(c, 0.3, units=8.0)                    # samples land in one bin only
    untouched = BIN_EDGES[-1] + 40.0             # a bin never sampled
    assert c.gain_for(untouched) < 0.6


def test_pooling_removes_the_integer_rounding_bias():
    """A one-unit request reads back as a whole number of pixels.

    At 3.5x that is 3 or 4 and never 3.5, so per-event ratios are biased. Pooled
    over several events the rounding cancels; without that the estimate settled
    on 4.0 and left every move 14% short.
    """
    c = GainCurve(PointerSettings(speed=10))
    # Alternating 3 px and 4 px for single-unit requests: truth is 3.5.
    for i in range(120):
        c.observe(1.0, 3.0 if i % 2 else 4.0)
    assert 3.2 <= c.gain_for(1.0) <= 3.8


def test_absurd_observations_are_ignored():
    """A move fought by the user's own hand must not poison the estimate."""
    c = GainCurve(PointerSettings(speed=10))
    _teach(c, 1.0)
    before = c.gain_for(8.0)
    for _ in range(3):
        c.observe(8.0, 8.0 * 400.0)              # impossible ratio
    assert abs(c.gain_for(8.0) - before) < 0.35


def test_scale_and_shape_stay_anchored():
    """Only their product is observable, so the split needs pinning.

    Unanchored, the two halves drift apart indefinitely while the product stays
    right, and the drift showed up as wasted, hunting motion.
    """
    c = GainCurve(PointerSettings(speed=10, enhance=True))
    for _ in range(30):
        for u in (1.5, 3.0, 6.0, 12.0, 24.0, 48.0):
            c.observe(u, u * (0.8 + 0.02 * u))
    shape_mean = sum(c.snapshot()) / (N_BINS * c.scale)
    assert abs(shape_mean - 1.0) < 0.05


def test_resolution_floor_reports_the_smallest_possible_move():
    low = GainCurve(PointerSettings(speed=4))     # 0.25x
    high = GainCurve(PointerSettings(speed=20))   # 3.5x
    assert low.unit_px() < 1.0
    assert high.unit_px() > 3.0


def test_refresh_picks_up_a_changed_windows_setting(monkeypatch):
    c = GainCurve(PointerSettings(speed=10))
    assert abs(c.scale - 1.0) < 1e-9
    monkeypatch.setattr("cursor_assist.pointer.read_settings",
                        lambda: PointerSettings(speed=20))
    c._checked_at = -1e9                          # force the recheck
    assert c.refresh() is True
    assert abs(c.scale - 3.5) < 1e-9


def test_describe_names_the_slider_notch():
    assert "6/11" in PointerSettings(speed=10).describe()
    assert "11/11" in PointerSettings(speed=20).describe()
    assert "enhance" in PointerSettings(speed=10, enhance=True).describe()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
