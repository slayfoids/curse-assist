"""Tests for DwellClicker, including the repeat/auto-fire behavior."""

import types

import cursor_assist.cursor as cur


def _setup():
    """Give the clicker a controllable clock and a click counter."""
    clock = [0.0]
    cur.time = types.SimpleNamespace(monotonic=lambda: clock[0])
    clicks = []
    cur.click_left = lambda: clicks.append(clock[0])
    return clock, clicks


def test_single_click_then_no_repeat():
    clock, clicks = _setup()
    d = cur.DwellClicker()
    d.update((0, 0), (0, 0), 10, 100, True)          # enter radius (t=0)
    clock[0] = 0.05
    d.update((0, 0), (0, 0), 10, 100, True)          # held 50ms < 100: no click
    assert clicks == []
    clock[0] = 0.11
    assert d.update((0, 0), (0, 0), 10, 100, True)   # held 110ms: click
    assert len(clicks) == 1
    clock[0] = 1.0
    d.update((0, 0), (0, 0), 10, 100, True)          # no repeat -> still 1
    assert len(clicks) == 1


def test_repeat_auto_fire():
    clock, clicks = _setup()
    d = cur.DwellClicker()
    d.update((0, 0), (0, 0), 10, 0, True, repeat=True, interval_ms=50)  # enter
    clock[0] = 0.001
    d.update((0, 0), (0, 0), 10, 0, True, repeat=True, interval_ms=50)  # 1st
    for t in (0.06, 0.12, 0.18, 0.24):
        clock[0] = t
        d.update((0, 0), (0, 0), 10, 0, True, repeat=True, interval_ms=50)
    # ~5 clicks over 240ms at 50ms spacing.
    assert len(clicks) >= 4


def test_leaving_radius_cancels():
    clock, clicks = _setup()
    d = cur.DwellClicker()
    d.update((0, 0), (0, 0), 10, 50, True)
    clock[0] = 0.03
    d.update((100, 100), (0, 0), 10, 50, True)       # outside radius: cancels
    clock[0] = 0.2
    d.update((100, 100), (0, 0), 10, 50, True)
    assert clicks == []


def test_dwell_survives_a_brief_target_dropout():
    """A flicker in detection must not restart the dwell timer.

    Detection drops a frame whenever the colour flickers or the capture source
    stutters, and the engine also discards targets older than a fraction of a
    second. Cancelling on the first missing frame meant that on a jumpy source
    the dwell click could never complete -- "sometimes it just doesn't click".
    """
    clock, clicks = _setup()
    d = cur.DwellClicker()
    d.update((0, 0), (0, 0), 10, 100, True)          # enter radius at t=0
    clock[0] = 0.05
    d.target_lost(400)                               # blip: target gone 1 frame
    clock[0] = 0.07
    d.target_lost(400)                               # still gone, inside grace
    clock[0] = 0.12
    assert d.update((0, 0), (0, 0), 10, 100, True)   # timer kept running: click
    assert len(clicks) == 1


def test_dwell_resets_after_a_long_target_loss():
    """Past the grace window the timer really does start over."""
    clock, clicks = _setup()
    d = cur.DwellClicker()
    d.update((0, 0), (0, 0), 10, 100, True)
    clock[0] = 0.05
    d.target_lost(200)
    clock[0] = 0.40                                  # 350ms gone > 200ms grace
    d.target_lost(200)
    clock[0] = 0.42
    assert d.update((0, 0), (0, 0), 10, 100, True) is False   # fresh timer
    assert clicks == []
    clock[0] = 0.55
    assert d.update((0, 0), (0, 0), 10, 100, True)   # now it fires
    assert len(clicks) == 1


def test_leaving_the_radius_still_cancels_immediately():
    """The grace is only for lost targets, not for moving off one."""
    clock, clicks = _setup()
    d = cur.DwellClicker()
    d.update((0, 0), (0, 0), 10, 100, True)
    clock[0] = 0.05
    d.update((500, 500), (0, 0), 10, 100, True)      # cursor left the radius
    clock[0] = 0.12
    assert d.update((0, 0), (0, 0), 10, 100, True) is False
    assert clicks == []
