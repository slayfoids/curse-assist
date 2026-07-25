"""Unit tests for the hold-to-activate mode and audio-cue plumbing."""

import sys

import pytest

from cursor_assist.config import AppState
from cursor_assist import persistence
from cursor_assist.webserver import WebApp


class _FakeMouse:
    """Stand-in for the `mouse` package: records hooks and replays events."""

    def __init__(self):
        self.hooks = []

    def on_button(self, callback, args=(), buttons=(), types=()):
        h = (callback, tuple(buttons), tuple(types))
        self.hooks.append(h)
        return h

    def unhook(self, h):
        self.hooks.remove(h)

    def emit(self, button, event_type):
        for cb, buttons, types in list(self.hooks):
            if button in buttons and event_type in types:
                cb()


class _FakeKeyboard:
    """Minimal `keyboard` stand-in; rejects the literal key 'not-a-key'."""

    def add_hotkey(self, key, cb):
        if key == "not-a-key":
            raise ValueError("unknown key: not-a-key")
        return object()

    def hook_key(self, key, cb):
        return object()

    def remove_hotkey(self, h):
        pass

    def unhook(self, h):
        pass


@pytest.fixture
def fake_mouse(monkeypatch):
    fm = _FakeMouse()
    monkeypatch.setitem(sys.modules, "mouse", fm)
    return fm


def make_app():
    st = AppState()
    st.set("audio_cues", False)
    app = WebApp(st, open_browser=False)
    # Unit scope: no real global hooks, no writes to the user's settings file.
    app._register_hotkeys = lambda: None
    app._save = lambda: None
    return app, st


def test_set_pull_flips_state_and_dedupes():
    app, st = make_app()
    assert st.get("pull_enabled") is False
    app._set_pull(True)
    assert st.get("pull_enabled") is True
    app._set_pull(True)                 # repeat press (key auto-repeat): no-op
    assert st.get("pull_enabled") is True
    app._set_pull(False)
    assert st.get("pull_enabled") is False


def test_toggle_action_goes_through_set_pull():
    app, st = make_app()
    app.do_action({"action": "toggle_pull"})
    assert st.get("pull_enabled") is True
    app.do_action({"action": "set_pull", "value": False})
    assert st.get("pull_enabled") is False


def test_activation_mode_validated_and_forces_pull_off():
    app, st = make_app()
    st.set("pull_enabled", True)
    app.set_scalar("activation_mode", "banana")
    assert st.get("activation_mode") == "toggle"    # rejected
    app.set_scalar("activation_mode", "hold")
    assert st.get("activation_mode") == "hold"
    assert st.get("pull_enabled") is False          # safety: start released


def test_hold_button_and_cues_persist():
    st = AppState()
    st.set("activation_mode", "hold")
    st.set("hotkey_hold", "MB5")
    st.set("audio_cues", False)
    d = persistence.to_dict(st)
    fresh = AppState()
    persistence.apply_dict(fresh, d)
    assert fresh.activation_mode == "hold"
    assert fresh.hotkey_hold == "MB5"
    assert fresh.audio_cues is False


def test_pull_cue_respects_audio_setting():
    app, st = make_app()
    # audio_cues False: must return without spawning anything / raising.
    app._pull_cue(True)
    app._pull_cue(False)


# ------------------------------------------------- hold button: event plumbing

def test_hold_button_survives_the_double_click_rewrite(fake_mouse):
    """A quick re-press arrives as "double", not "down" -- it must still fire.

    The `mouse` package rewrites any press landing within the system
    double-click time of the previous button event (including the preceding
    release) into a "double". Listening for "down" alone dropped every quick
    re-press, so hold mode worked once and then looked completely dead.
    """
    app, st = make_app()
    app._hook_mouse_hold("x")

    fake_mouse.emit("x", "down")          # first press: a plain "down"
    assert st.get("pull_enabled") is True
    fake_mouse.emit("x", "up")
    assert st.get("pull_enabled") is False

    fake_mouse.emit("x", "double")        # quick re-press: rewritten
    assert st.get("pull_enabled") is True
    fake_mouse.emit("x", "up")
    assert st.get("pull_enabled") is False


def test_trigger_button_survives_the_double_click_rewrite(fake_mouse):
    app, st = make_app()
    fired = []
    app.controller.trigger_click = lambda: fired.append(1)
    app._hook_mouse_trigger("x2")
    fake_mouse.emit("x2", "down")
    fake_mouse.emit("x2", "double")
    assert len(fired) == 2


def test_one_bad_binding_does_not_block_the_hold_hook(monkeypatch, fake_mouse):
    """One unusable key name must not take the later bindings down with it."""
    monkeypatch.setitem(sys.modules, "keyboard", _FakeKeyboard())
    st = AppState()
    st.set("audio_cues", False)
    st.set("hotkey_show_panel", "not-a-key")   # this binding raises
    st.set("activation_mode", "hold")
    st.set("hotkey_hold", "MB4")
    app = WebApp(st, open_browser=False)
    app._save = lambda: None

    app._register_hotkeys()

    # The hold hook still got registered, and the failure was reported.
    assert any("x" in buttons for _cb, buttons, _t in fake_mouse.hooks)
    assert "not-a-key" in app._last_error
    fake_mouse.emit("x", "down")
    assert st.get("pull_enabled") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
