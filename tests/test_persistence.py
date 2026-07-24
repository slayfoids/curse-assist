"""Round-trip and validation tests for settings persistence (no display)."""

from cursor_assist.config import AppState
from cursor_assist import persistence


def test_round_trip_preserves_settings(tmp_path):
    st = AppState()
    st.set("pull_factor", 0.42)
    st.set("dwell_ms", 900)
    st.set("active_region", "L-Leg")
    st.set("hotkey_show_panel", "right shift")
    with st.lock:
        st.colors[0].h = 100
        st.capture.source = "obs"
        st.capture.width = 640

    path = tmp_path / "settings.json"
    persistence.save(st, path)

    fresh = AppState()
    assert persistence.load(fresh, path) is True
    assert fresh.get("pull_factor") == 0.42
    assert fresh.get("dwell_ms") == 900
    assert fresh.get("active_region") == "L-Leg"
    assert fresh.get("hotkey_show_panel") == "right shift"
    assert fresh.get("colors")[0].h == 100
    assert fresh.get("capture").source == "obs"
    assert fresh.get("capture").width == 640


def test_pull_enabled_is_not_persisted(tmp_path):
    st = AppState()
    st.set("pull_enabled", True)
    path = tmp_path / "s.json"
    persistence.save(st, path)
    fresh = AppState()
    persistence.load(fresh, path)
    # Always starts disabled regardless of what was saved.
    assert fresh.get("pull_enabled") is False


def test_load_missing_file_is_noop(tmp_path):
    st = AppState()
    assert persistence.load(st, tmp_path / "nope.json") is False


def test_invalid_region_is_sanitised(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"version": 1, "active_region": "Nose"}', encoding="utf-8")
    st = AppState()
    persistence.load(st, path)
    assert st.get("active_region") == "Torso"


def test_corrupt_json_is_ignored(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not valid json", encoding="utf-8")
    st = AppState()
    assert persistence.load(st, path) is False
