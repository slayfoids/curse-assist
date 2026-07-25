"""Save and load user settings as JSON, plus named config snapshots.

Everything the user tunes in the panel is persisted so their configuration
survives a restart. The pull on/off state is intentionally *not* saved -- the
app always starts with the assist disabled, which is the safe default.

Config snapshots ("saved configs") capture the entire current setup under a
unique random code like ``CRS-7KQ2XN``. They live as individual JSON files in
a ``configs`` folder next to the settings file and can be loaded, listed, or
deleted by code.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import List, Optional

from .config import REGIONS, AppState, CaptureConfig, ColorTarget

SETTINGS_VERSION = 1

# Unambiguous alphabet (no 0/O/1/I/L) for the random config codes.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_RE = re.compile(r"^[A-Z]{3}-[A-Z0-9]{6}$")

# Scalar fields copied verbatim to/from JSON.
_SCALAR_FIELDS = (
    "smoothness",
    "max_speed",
    "target_ema",
    "motion_response",
    "jitter_floor",
    "precision_px",
    "precision_slow",
    "max_accel",
    "pointer_gain",
    "pointer_gain_auto",
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
    "part_attraction",
    "pull_radius",
    "show_overlay",
    "overlay_radius",
    "auto_click_enabled",
    "click_mode",
    "suppress_mouse",
    "hotkey_show_panel",
    "hotkey_toggle_pull",
    "hotkey_trigger",
    "activation_mode",
    "hotkey_hold",
    "audio_cues",
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


# ----------------------------------------------------------- config snapshots
def configs_dir(base: Optional[Path] = None) -> Path:
    return (base or default_settings_path().parent) / "configs"


def _normalize_code(code: str) -> Optional[str]:
    """Uppercase and validate a code; None if it isn't a legal code.

    Codes come from user input, so this is also the path-traversal guard —
    only exact ``XXX-XXXXXX`` codes ever touch the filesystem.
    """
    code = (code or "").strip().upper()
    return code if _CODE_RE.match(code) else None


def new_code(existing: Optional[set] = None) -> str:
    """A fresh random config code, avoiding collisions with ``existing``."""
    while True:
        code = "CRS-" + "".join(secrets.choice(_CODE_ALPHABET)
                                for _ in range(6))
        if not existing or code not in existing:
            return code


def save_config(state: AppState, name: str = "",
                base: Optional[Path] = None) -> str:
    """Snapshot the current settings under a new random code; returns it."""
    d = configs_dir(base)
    d.mkdir(parents=True, exist_ok=True)
    code = new_code({p.stem for p in d.glob("*.json")})
    data = to_dict(state)
    data["config_name"] = str(name)[:60]
    data["config_created"] = time.time()
    (d / f"{code}.json").write_text(json.dumps(data, indent=2),
                                    encoding="utf-8")
    return code


def list_configs(base: Optional[Path] = None) -> List[dict]:
    """All saved configs as ``{code, name, created}``, newest first."""
    d = configs_dir(base)
    out: List[dict] = []
    if not d.exists():
        return out
    for p in d.glob("*.json"):
        if _normalize_code(p.stem) != p.stem:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        out.append({
            "code": p.stem,
            "name": data.get("config_name", ""),
            "created": data.get("config_created", p.stat().st_mtime),
        })
    out.sort(key=lambda c: c["created"], reverse=True)
    return out


def load_config(state: AppState, code: str,
                base: Optional[Path] = None) -> bool:
    """Apply the snapshot saved under ``code``. Returns True on success."""
    norm = _normalize_code(code)
    if norm is None:
        return False
    p = configs_dir(base) / f"{norm}.json"
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    apply_dict(state, data)
    return True


def delete_config(code: str, base: Optional[Path] = None) -> bool:
    norm = _normalize_code(code)
    if norm is None:
        return False
    p = configs_dir(base) / f"{norm}.json"
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


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
