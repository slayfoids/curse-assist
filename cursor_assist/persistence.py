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

import base64
import json
import os
import re
import secrets
import time
import zlib
from pathlib import Path
from typing import List, Optional

from .config import (REGIONS, AppState, CaptureConfig, ColorTarget,
                     tolerances_for)

# 2: colour tolerances are derived from Sensitivity by config.tolerances_for.
# Files written by version 1 carry tolerances from the old mapping, which
# saturated saturation and value at 255 over the top half of the slider and
# matched most of the screen; they are recomputed on load rather than restored.
SETTINGS_VERSION = 2

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
    "aim_commit_px",
    "velocity_follow",
    "audio_volume",
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
    "scan_fps",
    "idle_scan_fps",
    "roi_x",
    "roi_y",
    "roi_w",
    "roi_h",
    "show_roi",
    "lock_target",
    "adaptive_roi",
    "show_aim_line",
    "dwell_grace_ms",
    "snap_to_best",
    "snap_after_ms",
    "snap_radius",
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


def _coerce(current, value):
    """Cast an incoming value to the type of the field it is replacing.

    Settings now arrive from other people's machines through share codes, so
    "it came out of JSON" is no longer a good reason to trust it. A string
    where a float belongs would otherwise be stored verbatim and blow up in the
    detection loop, a thread away from anything that could explain why.
    Anything that cannot be converted is rejected and the current value kept.
    """
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, str):
        return str(value)[:120]
    raise TypeError(type(current))


def apply_dict(state: AppState, data: dict) -> None:
    """Apply a settings dict onto ``state`` (unknown/invalid values ignored)."""
    with state.lock:
        for name in _SCALAR_FIELDS:
            if name not in data:
                continue
            try:
                setattr(state, name,
                        _coerce(getattr(state, name), data[name]))
            except (TypeError, ValueError, OverflowError):
                continue
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
            # Pre-v2 files store tolerances from the old mapping. Restoring
            # them verbatim would carry the flooding fault across the upgrade,
            # so they are rebuilt from the Sensitivity the user actually set.
            if int(data.get("version", 1)) < 2:
                h_tol, s_tol, v_tol = tolerances_for(state.sensitivity)
                for c in state.colors:
                    c.h_tol, c.s_tol, c.v_tol = h_tol, s_tol, v_tol

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


# ------------------------------------------------------------- share codes
# A saved config used to be a file on one machine and a six-character code that
# only meant anything to the machine that wrote it — there was no way to hand a
# setup to somebody else. A share code carries the whole configuration inside
# itself instead, so it can be pasted into a chat window and used on any other
# install, with no server, no account and no network access.
#
# Layout: ``CURSE1-`` + base64url( crc32(json) as 4 bytes || zlib(json) ).
# The checksum is what makes a truncated paste — the usual failure, since these
# are long enough for chat clients to wrap them — report itself as damaged
# rather than load half a configuration.
SHARE_PREFIX = "CURSE1-"
SHARE_MAX_BYTES = 256 * 1024   # ceiling on what a paste may expand to


def encode_share(state: AppState, name: str = "") -> str:
    """The whole current setup as one pasteable string.

    Only settings that differ from the defaults are carried, so an ordinary
    setup produces a code short enough to paste in a chat message rather than
    one that has to be sent as a file.
    """
    data = to_dict(state)
    base = to_dict(AppState())
    diff = {k: v for k, v in data.items()
            if k == "version" or base.get(k) != v}
    if name:
        diff["config_name"] = str(name)[:60]
    raw = json.dumps(diff, separators=(",", ":"),
                     sort_keys=True).encode("utf-8")
    body = zlib.crc32(raw).to_bytes(4, "big") + zlib.compress(raw, 9)
    return SHARE_PREFIX + base64.urlsafe_b64encode(body).decode().rstrip("=")


def decode_share(code: str) -> Optional[dict]:
    """Settings carried by a share code, or ``None`` if it isn't a valid one."""
    text = "".join((code or "").split())
    if not text.upper().startswith(SHARE_PREFIX):
        return None
    payload = text[len(SHARE_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        if len(raw) < 5:
            return None
        want, blob = int.from_bytes(raw[:4], "big"), raw[4:]
        # Bounded decompression: this is a string a stranger pasted in, and an
        # unbounded one is a few hundred bytes that expands into all of memory.
        js = zlib.decompressobj().decompress(blob, SHARE_MAX_BYTES)
        if zlib.crc32(js) != want:
            return None
        data = json.loads(js.decode("utf-8"))
    except (ValueError, zlib.error, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def apply_share(state: AppState, code: str) -> Optional[str]:
    """Load a share code onto ``state``. Returns its name, or ``None``.

    Defaults are laid down first, so importing reproduces the *sender's* setup
    rather than mixing it with whatever the receiver already had — which is the
    entire point of handing someone your config.
    """
    data = decode_share(code)
    if data is None:
        return None
    full = to_dict(AppState())
    full.update(data)
    apply_dict(state, full)
    return str(data.get("config_name", ""))[:60]


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
