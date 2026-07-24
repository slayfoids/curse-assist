"""Unit tests for the hold-to-activate mode and audio-cue plumbing."""

import pytest

from cursor_assist.config import AppState
from cursor_assist import persistence
from cursor_assist.webserver import WebApp


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
