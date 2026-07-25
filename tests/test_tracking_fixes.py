"""Velocity feed-forward, aim commitment, and dwell reliability.

Three problems that all showed up as "it nearly works": the pointer sat a fixed
distance behind anything moving, the aim point danced, and dwell clicks arrived
late or not at all.
"""

import math

import numpy as np
import pytest

import cursor_assist.cursor as cur
from cursor_assist.config import AppState
from cursor_assist.pointer import GainCurve, PointerSettings
from cursor_assist.targeting import TargetTracker


def _glider():
    return cur.CursorGlider(curve=GainCurve(PointerSettings(speed=10)))


# ------------------------------------------------- velocity feed-forward

def _chase(speed, follow, hz=240, seconds=1.6):
    """Chase a target moving at a constant speed; return steady-state lag."""
    pos = [0.0, 0.0]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))
    cur.move_relative = lambda dx, dy: (pos.__setitem__(0, pos[0] + dx),
                                        pos.__setitem__(1, pos[1] + dy))
    g = _glider()
    dt = 1.0 / hz
    errs = []
    for i in range(int(hz * seconds)):
        t = i * dt
        tx = 200.0 + speed * t
        g.step((int(tx), 0), dt, 0.078, 60000,
               target_vel=(speed * follow, 0.0))
        if t > seconds * 0.5:
            errs.append(abs(tx - pos[0]))
    return sum(errs) / len(errs)


@pytest.mark.parametrize("speed", [200, 500, 1000])
def test_feed_forward_removes_the_lag_behind_a_moving_target(speed):
    """A proportional controller cannot sit on a moving target.

    It settles wherever the error is big enough to produce the speed needed to
    keep up — a fixed distance behind, proportional to the easing constant.
    That is why raising the speed and acceleration limits never closed the gap.
    """
    without = _chase(speed, follow=0.0)
    with_ff = _chase(speed, follow=1.0)
    assert without > 0.4 * speed * 0.078      # the predicted ramp error
    assert with_ff < 0.25 * without, (without, with_ff)


def test_feed_forward_does_not_run_away_on_a_still_target():
    assert _chase(0, follow=1.0) < 2.0


def test_speed_and_accel_limits_alone_cannot_fix_the_lag():
    """The user's own experiment, as a test: turning them up does not help."""
    slow_caps = _chase(500, follow=0.0)
    pos = [0.0, 0.0]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))
    cur.move_relative = lambda dx, dy: (pos.__setitem__(0, pos[0] + dx),
                                        pos.__setitem__(1, pos[1] + dy))
    g = _glider()
    errs = []
    for i in range(int(240 * 1.6)):
        t = i / 240.0
        tx = 200.0 + 500.0 * t
        g.step((int(tx), 0), 1 / 240.0, 0.078, 10_000_000,   # huge caps
               max_accel_px_s2=10_000_000)
        if t > 0.8:
            errs.append(abs(tx - pos[0]))
    huge_caps = sum(errs) / len(errs)
    assert huge_caps > 0.5 * slow_caps        # barely different


# ------------------------------------------------------ aim commitment

def _noisy_track(commit_px, noise=6.0, frames=90, drift=0.0):
    """Feed a jittering target point and see how much the aim moves."""
    rng = np.random.default_rng(3)
    t = TargetTracker(ema=0.45)
    t.set_commit_px(commit_px)
    out = []
    now = 0.0
    base = np.array([500.0, 300.0])
    for i in range(frames):
        now += 1 / 60.0
        p = base + np.array([drift * i, 0.0]) + rng.normal(0, noise, 2)
        out.append(t._smooth(p, now, switched=(i == 0)))
    tail = out[len(out) // 2:]
    span = max(math.hypot(a[0] - b[0], a[1] - b[1])
               for a in tail for b in tail)
    moves = sum(1 for i in range(1, len(tail)) if tail[i] != tail[i - 1])
    return span, moves, tail[-1]


def test_commitment_holds_the_aim_still_through_detection_noise():
    """The knobs that key off *speed* cannot do this — noise looks fast."""
    loose_span, loose_moves, _ = _noisy_track(0)
    firm_span, firm_moves, _ = _noisy_track(10)
    assert firm_span < 0.4 * loose_span, (loose_span, firm_span)
    assert firm_moves < 0.5 * loose_moves, (loose_moves, firm_moves)


def test_commitment_still_follows_a_real_drift():
    """A held aim must not become a stuck aim."""
    _span, _moves, end = _noisy_track(10, drift=1.5, frames=120)
    # 120 frames of 1.5 px drift = 180 px; it must have gone most of the way.
    assert end[0] > 500 + 140, end


def test_commitment_fades_out_on_a_travelling_target():
    """It must cost nothing while actually tracking something."""
    t = TargetTracker(ema=0.45)
    t.set_commit_px(14)
    now = 0.0
    last = None
    for i in range(40):                       # 900 px/s, dead straight
        now += 1 / 60.0
        last = t._smooth(np.array([200.0 + 900.0 * now, 300.0]), now,
                         switched=(i == 0))
    assert abs(last[0] - (200.0 + 900.0 * now)) < 40, last


def test_commitment_off_by_zero():
    span_off, _m, _e = _noisy_track(0)
    assert span_off > 4.0                     # unfiltered noise gets through


# ------------------------------------------------------------ dwell click

def _dwell_run(monkeypatch, dwell_ms, radius, offsets, hz=240):
    """Feed a sequence of pointer-to-target offsets; count clicks.

    The clock is advanced through ``monkeypatch`` so it is restored even if an
    assertion fails — patching ``time.monotonic`` by hand leaked a broken clock
    into every test that ran afterwards.
    """
    fired = []
    d = cur.DwellClicker(on_fire=lambda: fired.append(1))
    clock = {"t": 1000.0}
    monkeypatch.setattr(cur.time, "monotonic", lambda: clock["t"])
    for off in offsets:
        d.update(cursor_screen=(int(off), 0), target_screen=(0, 0),
                 radius=radius, dwell_ms=dwell_ms, auto_click=True)
        clock["t"] += 1.0 / hz
    return len(fired)


def test_zero_dwell_clicks_on_arrival(monkeypatch):
    """0 ms must mean 0 ms, not 'one frame later'."""
    assert _dwell_run(monkeypatch, 0, 25, [100, 100, 5]) == 1


def test_a_dwell_time_is_still_waited_out(monkeypatch):
    """Instant at 0 must not mean instant at everything."""
    # 10 frames at 240 Hz is 42 ms — well short of the 200 ms asked for.
    assert _dwell_run(monkeypatch, 200, 25, [5] * 10) == 0
    assert _dwell_run(monkeypatch, 200, 25, [5] * 60) == 1


def test_jitter_does_not_restart_the_dwell_timer(monkeypatch):
    """Detection noise nudges the aim; the timer must survive it.

    A single threshold had the pointer crossing in and out of the radius many
    times a second, restarting the count each time — which is why a dwell click
    could take far longer than its setting, or never arrive.
    """
    # Sits right at the edge of a 20 px radius, wobbling either side of it.
    wobble = [19, 21, 19, 22, 18, 21, 19, 20] * 30
    assert _dwell_run(monkeypatch, 120, 20, wobble) >= 1


def test_leaving_properly_still_cancels(monkeypatch):
    """Hysteresis must not turn into 'never lets go'."""
    assert _dwell_run(monkeypatch, 120, 20,
                      [5] * 3 + [400] * 30 + [5] * 3) <= 1


def test_distance_is_reported_for_the_panel():
    d = cur.DwellClicker()
    d.update(cursor_screen=(30, 40), target_screen=(0, 0), radius=10,
             dwell_ms=100, auto_click=True)
    assert d.distance == pytest.approx(50.0)


def test_defaults_are_sane():
    s = AppState()
    assert s.aim_commit_px > 0
    assert 0.0 < s.velocity_follow <= 1.5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
