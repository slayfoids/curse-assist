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
REGIONS = ["Head", "Torso", "L-Arm", "R-Arm", "L-Leg", "R-Leg", "Feet"]


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

    def hsv_ranges(self) -> list:
        """(lower, upper) HSV range boxes, splitting when hue wraps at 0/179.

        OpenCV hue is circular (red sits at both ends), so a red target near
        H=0 must also match hues near 179 — clamping instead of wrapping
        silently dropped half the reds.
        """
        s_lo, s_hi = max(0, self.s - self.s_tol), min(255, self.s + self.s_tol)
        v_lo, v_hi = max(0, self.v - self.v_tol), min(255, self.v + self.v_tol)
        h_lo, h_hi = self.h - self.h_tol, self.h + self.h_tol
        if self.h_tol >= 90:  # tolerance covers the whole hue circle
            return [((0, s_lo, v_lo), (179, s_hi, v_hi))]
        ranges = []
        if h_lo < 0:
            ranges.append(((0, s_lo, v_lo), (h_hi, s_hi, v_hi)))
            ranges.append(((180 + h_lo, s_lo, v_lo), (179, s_hi, v_hi)))
        elif h_hi > 179:
            ranges.append(((h_lo, s_lo, v_lo), (179, s_hi, v_hi)))
            ranges.append(((0, s_lo, v_lo), (h_hi - 180, s_hi, v_hi)))
        else:
            ranges.append(((h_lo, s_lo, v_lo), (h_hi, s_hi, v_hi)))
        return ranges


@dataclass
class CaptureConfig:
    """Where and how frames are grabbed from."""

    # "screen" uses mss desktop capture (default); "obs" reads the virtual cam.
    source: str = "screen"
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
    # How the pull is activated: "toggle" (hotkey flips it on/off) or "hold"
    # (active only while hotkey_hold is physically held down).
    activation_mode: str = "toggle"
    hotkey_hold: str = "MB4"         # key or mouse button held in "hold" mode
    audio_cues: bool = True          # two high beeps = on, two low beeps = off
    auto_click_enabled: bool = True  # (legacy) dwell-click master enable
    # How clicks fire: "dwell" (auto after hovering), "trigger" (press the
    # trigger key to click instantly), or "off" (manual clicks only).
    click_mode: str = "dwell"

    # --- Pull / movement tuning -----------------------------------------
    # Motion is time-based and frame-rate independent (see controller). These
    # tune *feel*, not per-frame steps, so it stays smooth regardless of FPS.
    smoothness: float = 0.22         # 0 = snappy .. 1 = very smooth (glide)
    max_speed: int = 25000           # px/second cap (higher = catches fast colors)
    target_ema: float = 0.45         # smoothing applied to the *target* point

    # --- Fine tracking control -------------------------------------------
    # How readily the target filter opens up as the target speeds up. Higher
    # = follows fast motion with less lag; lower = stays smooth but trails.
    motion_response: float = 1.0     # multiplier on the adaptive cutoff
    # How hard a *stationary* target is filtered. Higher = calmer pointer on
    # a still target, at the cost of a beat more lag when it starts moving.
    jitter_floor: float = 1.0        # multiplier on the resting cutoff

    # Precision zone: within this many px of the target the pointer eases off
    # and steadies, so it settles instead of darting across the last few px
    # (the "spasm" on arrival). 0 disables it.
    # Defaults are deliberately mild: measured on the sim harness, a 60 px
    # zone at 0.35 doubled the settle time (0.43 s -> 0.86 s), which is too
    # sluggish to ship as standard. Turn them up for more damping.
    precision_px: int = 40
    precision_slow: float = 0.55     # speed multiplier at the very centre

    # Acceleration limit: cap on how fast the pointer's own speed may change,
    # in px/s^2. A hard cap means no single frame can fling the pointer, even
    # if detection hands over a bad target for one frame. 0 disables it.
    # High enough not to be felt in normal use; it only clips real flings.
    max_accel: int = 300000

    # Pointer gain: Windows scales relative mouse input by the pointer-speed
    # slider and "enhance pointer precision", so a requested move of N px
    # lands short on a low-sensitivity setting. The engine measures the real
    # ratio and divides by it; this is an extra manual multiplier on top.
    pointer_gain: float = 1.0
    pointer_gain_auto: bool = True

    # --- Dwell click -----------------------------------------------------
    dwell_ms: int = 300              # how long to hold on target before click
    click_radius: int = 25           # px radius the cursor must hold within
    # How long a target may vanish without cancelling a dwell in progress.
    # Detection drops a frame whenever the colour flickers or the source
    # stutters; without this the timer restarted on every blip and a dwell
    # click could never complete on a slow capture source.
    dwell_grace_ms: int = 400
    click_repeat: bool = False       # keep auto-clicking while on target
    click_interval_ms: int = 120     # time between repeated clicks

    # --- Detection -------------------------------------------------------
    colors: List[ColorTarget] = field(default_factory=lambda: [ColorTarget()])
    detect_thin_border: bool = True  # detect colored outlines, not just fills
    min_contour_area: int = 60       # ignore specks below this many px^2
    sensitivity: int = 12            # global color tolerance applied to all colors
    detect_scale: float = 0.5        # downscale factor for detection speed (0.25-1)

    # Detection area: crop the captured frame to this pixel box before detecting
    # (works for any source, incl. OBS). All zeros / w==0 / h==0 = whole frame.
    roi_x: int = 0
    roi_y: int = 0
    roi_w: int = 0
    roi_h: int = 0

    # --- Targeting stability ---------------------------------------------
    # Lock onto one blob and keep pulling toward it until it disappears,
    # instead of re-picking the nearest blob every frame. Prevents the cursor
    # from settling in the middle of several same-color targets and stops the
    # jitter/spasms caused by the pick flip-flopping between blobs.
    lock_target: bool = True
    # Adaptive ROI ("target follow"): once locked, scan only a small window
    # around the target — at full resolution instead of downscaled. Detection
    # frame rate is the hard ceiling on tracking a moving target (no amount of
    # filtering recovers samples that were never taken), and a small window is
    # dramatically cheaper *and* more precise than the whole screen. Falls back
    # to a full scan when the target is lost, and rescans periodically anyway
    # so a better target elsewhere can still be picked up.
    adaptive_roi: bool = True
    # After the cursor has been on the target color for snap_after_ms, aim at
    # the position where a circle of the "circle size" radius (overlay_radius,
    # falling back to pull_radius) covers the most target color.
    snap_to_best: bool = True
    snap_after_ms: int = 1000

    # --- Region selection ------------------------------------------------
    # Off = just track the color directly. On = split the figure into body
    # regions and only target the active one (Head/Torso/Arms/Legs).
    body_part_detection: bool = False
    active_region: str = "Torso"
    # How strongly the aim is drawn to the chosen part: 1.0 = aim exactly at
    # the part, lower values blend toward the figure's center of mass, which
    # is steadier when the part band jitters at the figure's edge.
    part_attraction: float = 0.85

    # --- Capture ---------------------------------------------------------
    capture: CaptureConfig = field(default_factory=CaptureConfig)

    # --- Field of view / overlay ----------------------------------------
    # Only assist toward colors within this many px of the cursor (0 = no
    # limit). Drawn on screen as the crosshair circle.
    pull_radius: int = 250
    show_overlay: bool = True        # draw the FOV circle over the cursor
    overlay_radius: int = 0          # drawn circle size; 0 = match pull_radius
    # Purely visual: a line from the pointer to the pixel currently being aimed
    # at, so the user can see where the assist is heading and move with it
    # instead of unknowingly pulling against it.
    show_aim_line: bool = True
    aim_x: int = 0                   # published by the engine, read by overlay
    aim_y: int = 0
    aim_valid: bool = False

    # --- Input control ---------------------------------------------------
    suppress_mouse: bool = False     # block physical mouse movement while pulling

    # --- Hotkeys (editable/recordable in the panel; `keyboard` syntax) ----
    hotkey_show_panel: str = "right shift"  # show/hide the settings panel
    hotkey_toggle_pull: str = "f8"          # turn the pull assist on/off
    hotkey_trigger: str = "right ctrl"      # instant click (in "trigger" mode)

    # --- Loop status (loop -> GUI, read-only for the GUI) ----------------
    loop_fps: float = 0.0
    last_target_found: bool = False
    pointer_gain_measured: float = 1.0   # learned OS pointer gain (read-only)
    roi_following: bool = False          # adaptive ROI active right now

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
