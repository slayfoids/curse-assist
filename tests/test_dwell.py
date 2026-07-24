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
