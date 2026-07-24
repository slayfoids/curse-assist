"""Save and load user settings as JSON.

Everything the user tunes in the panel is persisted so their configuration
survives a restart. The pull on/off state is intentionally *not* saved -- the
app always starts with the assist disabled, which is the safe default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .config import REGIONS, AppState, CaptureConfig, ColorTarget

SETTINGS_VERSION = 1

# Scalar fields copied verbatim to/from JSON.
_SCALAR_FIELDS = (
    "smoothness",
    "max_speed",
    "target_ema",
    "dwell_ms",
    "click_radius",
    "click_repeat",
    "click_interval_ms",
    "detect_thin_border",
    "min_contour_area",
    "sensitivity",
    "detect_scale",
    "roi_x",
    "roi_y",
    "roi_w",
    "roi_h",
    "lock_target",
    "snap_to_best",
    "snap_after_ms",
    "body_part_detection",
    "active_region",
    "pull_radius",
    "show_overlay",
    "overlay_radius",
    "auto_click_enabled",
    "click_mode",
    "suppress_mouse",
    "hotkey_show_panel",
    "hotkey_toggle_pull",
    "hotkey_trigger",
)


def default_settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "CursorAssist" / "settings.json"


def to_dict(state: AppState) -> dict:
    with state.lock:
        data = {"version": SETTINGS_VERSION}
        for name in _SCALAR_FIELDS:
            data[name] = getattr(state, name)
        data["colors"] = [
            {
                "h": c.h, "s": c.s, "v": c.v,
                "h_tol": c.h_tol, "s_tol": c.s_tol, "v_tol": c.v_tol,
            }
            for c in state.colors
        ]
        cap = state.capture
        data["capture"] = {
            "source": cap.source,
            "left": cap.left, "top": cap.top,
            "width": cap.width, "height": cap.height,
            "monitor": cap.monitor,
            "obs_device_index": cap.obs_device_index,
        }
        return data


def apply_dict(state: AppState, data: dict) -> None:
    """Apply a settings dict onto ``state`` (unknown/invalid values ignored)."""
    with state.lock:
        for name in _SCALAR_FIELDS:
            if name in data:
                setattr(state, name, data[name])
        # Guard the region against typos so the loop never gets a bad key.
        if state.active_region not in REGIONS:
            state.active_region = "Torso"

        colors = data.get("colors")
        if isinstance(colors, list) and colors:
            state.colors[:] = [
                ColorTarget(
                    h=c.get("h", 60), s=c.get("s", 200), v=c.get("v", 200),
                    h_tol=c.get("h_tol", 10),
                    s_tol=c.get("s_tol", 80),
                    v_tol=c.get("v_tol", 80),
                )
                for c in colors
            ]

        cap = data.get("capture")
        if isinstance(cap, dict):
            state.capture = CaptureConfig(
                source=cap.get("source", "screen"),
                left=cap.get("left", 0),
                top=cap.get("top", 0),
                width=cap.get("width", 0),
                height=cap.get("height", 0),
                monitor=cap.get("monitor", 1),
                obs_device_index=cap.get("obs_device_index", 0),
            )


def save(state: AppState, path: Optional[Path] = None) -> Path:
    path = path or default_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(state), indent=2), encoding="utf-8")
    return path


def load(state: AppState, path: Optional[Path] = None) -> bool:
    """Load settings into ``state``. Returns True if a file was applied."""
    path = path or default_settings_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    apply_dict(state, data)
    return True
