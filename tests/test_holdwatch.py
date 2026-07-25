"""Tests for hold-to-activate key resolution and edge detection."""

import time

import pytest

from cursor_assist import holdwatch
from cursor_assist.holdwatch import HoldWatcher, resolve_vk


@pytest.mark.parametrize("token,vk", [
    ("MB4", 0x05), ("MB5", 0x06), ("MMB", 0x04), ("RMB", 0x02),
    ("right ctrl", 0xA3), ("space", 0x20), ("f8", 0x77),
    ("a", 0x41), ("5", 0x35),
])
def test_every_preset_hold_button_resolves(token, vk):
    """Each button the panel offers must map to a real virtual-key code.

    An unresolvable token used to mean hold silently did nothing at all.
    """
    assert resolve_vk(token) == vk


def test_unknown_token_is_reported_not_swallowed():
    assert resolve_vk("definitely not a key") is None
    assert resolve_vk("") is None


def test_watcher_reports_one_event_per_transition(monkeypatch):
    """Holding a button must fire once on press and once on release.

    The old hook route fired on raw events, so key auto-repeat and the
    `mouse` package's double-click rewrite both distorted the sequence.
    Polling reports edges only.
    """
    state = {"down": False}
    monkeypatch.setattr(holdwatch, "is_down", lambda vk: state["down"])
    monkeypatch.setattr(holdwatch, "POLL_HZ", 500.0)

    seen = []
    w = HoldWatcher(seen.append)
    assert w.start("MB4") is True
    try:
        time.sleep(0.05)
        assert seen == []                  # nothing while untouched
        state["down"] = True
        time.sleep(0.08)
        assert seen == [True]              # one press, not a stream
        time.sleep(0.08)
        assert seen == [True]              # still held: no repeats
        state["down"] = False
        time.sleep(0.08)
        assert seen == [True, False]
    finally:
        w.stop()


def test_watcher_rejects_a_key_it_cannot_poll(monkeypatch):
    w = HoldWatcher(lambda v: None)
    assert w.start("definitely not a key") is False
    assert w.vk is None


def test_watcher_does_not_fire_if_already_held_at_start(monkeypatch):
    """Starting with the button already down must not count as a press."""
    monkeypatch.setattr(holdwatch, "is_down", lambda vk: True)
    monkeypatch.setattr(holdwatch, "POLL_HZ", 500.0)
    seen = []
    w = HoldWatcher(seen.append)
    w.start("MB4")
    try:
        time.sleep(0.08)
        assert seen == []
    finally:
        w.stop()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
