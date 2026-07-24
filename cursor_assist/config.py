"""Shared, thread-safe application state.

The GUI (main thread) writes to this object; the detection/pull loop
(background thread) reads from it. A single lock guards every field so the two
threads never see a half-updated configuration.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import List, Tuple


# The named body regions exposed as selectable targets in the UI.
REGIONS = ["Head", "Torso", "L-Arm", "R-Arm", "L-Leg", "R-Leg"]


@dataclass
class ColorTarget:
    """One HSV color target with a symmetric tolerance box around it."""

    # Stored in OpenCV HSV ranges: H 0-179, S 0-255, V 0-255.
    h: int = 60
    s: int = 200
    v: int = 200
    h_tol: int = 10
    s_tol: int = 80
    v_tol: int = 80

    def lower(self) -> Tuple[int, int, int]:
        return (
            max(0, self.h - self.h_tol),
            max(0, self.s - self.s_tol),
            max(0, self.v - self.v_tol),
        )

    def upper(self) -> Tuple[int, int, int]:
        return (
            min(179, self.h + self.h_tol),
            min(255, self.s + self.s_tol),
            min(255, self.v + self.v_tol),
        )


@dataclass
class CaptureConfig:
    """Where and how frames are grabbed from."""

    # "obs" reads the OBS virtual cam (default/recommended); "screen" uses mss.
    source: str = "obs"
    # Screen region in absolute desktop pixels. width/height == 0 means full monitor.
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    monitor: int = 1  # mss monitor index used when width/height are 0
    obs_device_index: int = 0  # cv2.VideoCapture index for the OBS virtual camera


@dataclass
class AppState:
    """Everything the loop needs, plus a lock for cross-thread access."""

    lock: threading.RLock = field(default_factory=threading.RLock)

    # --- Master switches -------------------------------------------------
    pull_enabled: bool = False       # toggled by hotkey / button
    auto_click_enabled: bool = True  # dwell-click master enable

    # --- Pull / movement tuning -----------------------------------------
    # Motion is time-based and frame-rate independent (see controller). These
    # tune *feel*, not per-frame steps, so it stays smooth regardless of FPS.
    smoothness: float = 0.35         # 0 = snappy .. 1 = very smooth (glide)
    max_speed: int = 4000            # px/second cap (stops overshoot on jumps)
    target_ema: float = 0.4          # smoothing applied to the *target* point

    # --- Dwell click -----------------------------------------------------
    dwell_ms: int = 600              # 200 - 1500 ms
    click_radius: int = 25           # px radius the cursor must hold within

    # --- Detection -------------------------------------------------------
    colors: List[ColorTarget] = field(default_factory=lambda: [ColorTarget()])
    detect_thin_border: bool = True  # detect colored outlines, not just fills
    min_contour_area: int = 60       # ignore specks below this many px^2
    sensitivity: int = 12            # global color tolerance applied to all colors
    detect_scale: float = 0.5        # downscale factor for detection speed (0.25-1)

    # --- Region selection ------------------------------------------------
    active_region: str = "Torso"

    # --- Capture ---------------------------------------------------------
    capture: CaptureConfig = field(default_factory=CaptureConfig)

    # --- Input control ---------------------------------------------------
    suppress_mouse: bool = False     # block physical mouse movement while pulling

    # --- Hotkeys (editable/recordable in the panel; `keyboard` syntax) ----
    hotkey_show_panel: str = "right shift"  # show/hide the settings panel
    hotkey_toggle_pull: str = "f8"          # turn the pull assist on/off

    # --- Loop status (loop -> GUI, read-only for the GUI) ----------------
    loop_fps: float = 0.0
    last_target_found: bool = False

    # Convenience helpers so callers don't have to remember the lock -------
    def get(self, name: str):
        with self.lock:
            return getattr(self, name)

    def set(self, name: str, value) -> None:
        with self.lock:
            setattr(self, name, value)

    def snapshot(self) -> "AppState":
        """Return a shallow copy safe to read without holding the lock.

        Mutable members that the loop only reads are copied so a mid-frame
        GUI edit cannot tear a single iteration.
        """
        import copy

        with self.lock:
            # The RLock can't be deep-copied; share the same lock object in the
            # copy by seeding the memo with it.
            memo = {id(self.lock): self.lock}
            return copy.deepcopy(self, memo)
