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

# Sensitivity slider bounds, shared by the UI and the tolerance mapping below.
SENSITIVITY_MIN = 2
SENSITIVITY_MAX = 45


def tolerances_for(sensitivity: int) -> Tuple[int, int, int]:
    """HSV tolerances for one point on the Sensitivity slider.

    Hue is the channel that actually says *which colour* a pixel is, so raising
    sensitivity opens it up generously. Saturation and value are what separate
    the colour from grey and from black, and they stay bounded.

    The old mapping widened all three at ``tol * 8``, which saturated both at
    255 by two thirds of the way along the slider — every pixel with roughly
    the right hue then matched regardless of how washed out or how nearly black
    it was. Measured on a cluttered frame, sensitivity 28 matched 55% of the
    screen across 606 blobs, and past 36 the real target stopped being found at
    all: it had merged into the flood. That is the "struggles on a higher
    sensitivity" behaviour — the top half of the slider was unusable.
    """
    t = max(SENSITIVITY_MIN, min(SENSITIVITY_MAX, int(sensitivity)))
    h_tol = int(round(3 + t * 0.85))
    s_tol = int(round(30 + t * 3.0))
    v_tol = int(round(25 + t * 2.6))
    return h_tol, min(255, s_tol), min(255, v_tol)


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

    # How often the screen is scanned, in scans per second.
    #
    # 0 = match the display's refresh rate, which is the sensible default: a
    # screen produces new content at its refresh rate and no faster, so
    # scanning above it re-reads frames that have not changed — cost with no
    # information. Detected live, so a 60 Hz laptop panel and a 240 Hz monitor
    # each get the right value without configuration, and it follows the
    # display if the mode changes or a different monitor is plugged in.
    #
    # Set it explicitly to cap the work (a lower number leaves more CPU for
    # whatever else is running) or to push past the detected rate if the
    # capture source is not the display — an OBS virtual camera, for instance,
    # runs at whatever OBS is configured for, not at the panel's refresh.
    scan_fps: int = 0
    idle_scan_fps: int = 12          # rate while guidance is off (just for the
                                     # live "target found" light while tuning)

    # Detection area: crop the captured frame to this pixel box before detecting
    # (works for any source, incl. OBS). All zeros / w==0 / h==0 = whole frame.
    roi_x: int = 0
    roi_y: int = 0
    roi_w: int = 0
    roi_h: int = 0
    # Draw the detection area on screen so it can be seen rather than inferred
    # from four numbers.
    show_roi: bool = True
    # Set to "roi" or "capture" to ask for the drag-a-box screen picker; the
    # component owning the Tk main loop notices, runs it, and clears this back
    # to "". A request rather than a call because Tk will only build windows on
    # the thread that owns its loop, and the web server runs on another one.
    region_pick: str = ""

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
    # the position where a circle of snap_radius covers the most target color.
    # The search is confined to the locked blob, so this refines the aim inside
    # the current target and can never walk it onto a neighbouring one.
    snap_to_best: bool = True
    snap_after_ms: int = 1000
    # Radius of that coverage circle, in screen px. 0 = size it from the target
    # itself (about a third of its narrow side), which is the right default
    # because the useful size depends on the target, not on the user's setup.
    #
    # This used to borrow the drawn FOV circle — 250 px by default — so "where
    # is the color densest" was answered about a 500 px-wide patch of screen
    # rather than about the target. With two figures 220 px apart the aim
    # settled 47 px off the locked one; at some spacings it landed between the
    # two, aimed at neither.
    snap_radius: int = 0

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
    display_hz: float = 60.0         # detected refresh rate (read-only)
    last_target_found: bool = False
    pointer_gain_measured: float = 1.0   # learned OS pointer gain (read-only)
    pointer_profile: str = ""            # e.g. "6/11 (1x) + enhance precision"
    pointer_resolution: float = 1.0      # px per device unit (read-only)
    roi_following: bool = False          # adaptive ROI active right now
    # Percentage of the scanned area matching the target colors. A colour
    # selection loose enough to match most of the screen produces confident,
    # meaningless targets, so this is surfaced rather than left to be guessed
    # at from the pointer behaving strangely.
    mask_coverage: float = 0.0

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
