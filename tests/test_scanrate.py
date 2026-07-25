"""Tests for the configurable scan rate and display-refresh detection."""

import pytest

import cursor_assist.controller as ctrl
from cursor_assist.config import AppState
from cursor_assist.controller import AssistController


def make(**over):
    st = AppState()
    for k, v in over.items():
        st.set(k, v)
    c = AssistController(st)
    c._display_hz_at = 1e18       # freeze; don't re-read the real display
    return c, st


def rate(c, pulling=True):
    return 1.0 / c._scan_period(pulling)


def test_zero_means_match_the_display():
    """0 must follow the detected refresh, not a hardcoded number.

    A screen produces new content at its refresh rate and no faster, so this
    is the rate above which extra scans re-read unchanged frames. It differs
    per machine, which is exactly why it can't be a constant.
    """
    c, st = make(scan_fps=0)
    for hz in (60.0, 120.0, 165.0, 240.0):
        c._display_hz = hz
        assert rate(c) == pytest.approx(hz)


def test_explicit_rate_overrides_the_display():
    """An explicit value wins — the capture source may not be the display.

    An OBS virtual camera runs at whatever OBS is set to, unrelated to the
    panel's refresh, so the detected rate must not be a ceiling.
    """
    c, st = make(scan_fps=144)
    c._display_hz = 60.0
    assert rate(c) == pytest.approx(144.0)


def test_rate_is_clamped_to_something_sane():
    c, st = make()
    c._display_hz = 60.0
    st.set("scan_fps", 10_000_000)
    assert rate(c) == pytest.approx(ctrl.SCAN_HZ_MAX)
    st.set("scan_fps", 1)
    assert rate(c) == pytest.approx(ctrl.SCAN_HZ_MIN)
    st.set("scan_fps", -50)          # negative is falsy-ish garbage -> auto
    assert rate(c) == pytest.approx(ctrl.SCAN_HZ_MIN)


def test_idle_uses_its_own_slower_rate():
    """Guidance off should not scan at full speed just to light an indicator."""
    c, st = make(scan_fps=240, idle_scan_fps=12)
    c._display_hz = 240.0
    assert rate(c, pulling=True) == pytest.approx(240.0)
    assert rate(c, pulling=False) == pytest.approx(12.0)


def test_display_refresh_detection_returns_something_usable():
    from cursor_assist.capture import display_refresh_hz
    hz = display_refresh_hz()
    assert 20.0 <= hz <= 1000.0      # a real, plausible refresh rate


def test_refresh_falls_back_when_the_query_fails(monkeypatch):
    """A driver reporting 0/1 (documented 'hardware default') must not become
    a zero scan rate and stall the loop."""
    import cursor_assist.capture as cap

    class _Fake:
        def EnumDisplaySettingsW(self, *a):
            return 0                 # query failed
    monkeypatch.setattr(cap.ctypes, "windll",
                        type("W", (), {"user32": _Fake()})())
    assert cap.display_refresh_hz(default=75.0) == 75.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
