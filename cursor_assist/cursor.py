"""Windows cursor control via ``SendInput`` and dwell-click logic.

All movement and clicking goes through the standard ``SendInput`` API, which is
indistinguishable from a real input device -- no DLL injection, no hooking. Only
relative mouse movement is used for the pull, per spec.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional, Tuple

# --- Win32 SendInput plumbing ---------------------------------------------

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)


def get_cursor_pos() -> Tuple[int, int]:
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _send(mi: MOUSEINPUT) -> None:
    inp = INPUT(type=INPUT_MOUSE, u=_INPUTunion(mi=mi))
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def move_relative(dx: int, dy: int) -> None:
    """Move the cursor by a pixel delta using a synthetic mouse input event."""
    if dx == 0 and dy == 0:
        return
    _send(MOUSEINPUT(dx=int(dx), dy=int(dy), mouseData=0,
                     dwFlags=MOUSEEVENTF_MOVE, time=0, dwExtraInfo=0))


def click_left() -> None:
    _send(MOUSEINPUT(dx=0, dy=0, mouseData=0,
                     dwFlags=MOUSEEVENTF_LEFTDOWN, time=0, dwExtraInfo=0))
    _send(MOUSEINPUT(dx=0, dy=0, mouseData=0,
                     dwFlags=MOUSEEVENTF_LEFTUP, time=0, dwExtraInfo=0))


# --- Smooth pull ----------------------------------------------------------

import math


class CursorGlider:
    """Frame-rate-independent easing toward a target, with true convergence.

    Each step covers a fraction ``alpha = 1 - exp(-dt/tau)`` of the remaining
    distance (so the *feel* is independent of tick rate), speed-capped in px/sec.

    Crucially it keeps a **sub-pixel accumulator**: a fractional step never gets
    rounded away to zero, it accumulates until it moves a whole pixel. Without
    this the cursor stalled several pixels short of the target on gentle settings
    ("doesn't fully go to the color"). Within ``lock_px`` it lands exactly on the
    target, so aim is pixel-accurate.
    """

    def __init__(self):
        self._ax = 0.0  # carried sub-pixel remainder
        self._ay = 0.0
        self._speed = 0.0   # current pointer speed, px/s (for accel limiting)
        # Measured ratio of pixels actually travelled to pixels requested.
        # Windows scales relative mouse input by the pointer-speed slider and
        # "enhance pointer precision", so on a low-sensitivity setting a
        # requested 10 px move can land 4 px. Dividing by the measured gain
        # makes the pull behave the same at any Windows pointer speed.
        self._gain = 1.0

    def reset(self) -> None:
        self._ax = 0.0
        self._ay = 0.0
        self._speed = 0.0

    @property
    def gain(self) -> float:
        return self._gain

    def step(self, target_screen: Tuple[int, int], dt: float, tau: float,
             max_speed_px_s: float, lock_px: float = 2.0,
             max_accel_px_s2: float = 0.0,
             precision_px: float = 0.0, precision_slow: float = 1.0,
             gain_scale: float = 1.0, auto_gain: bool = True
             ) -> Tuple[int, int]:
        cx, cy = get_cursor_pos()
        rx = target_screen[0] - cx
        ry = target_screen[1] - cy
        dist = math.hypot(rx, ry)

        # Close enough: land exactly on the target (imperceptible, pixel-perfect).
        if dist <= lock_px:
            self.reset()
            move_relative(int(round(rx / max(self._gain, 0.05))),
                          int(round(ry / max(self._gain, 0.05))))
            return get_cursor_pos()

        # Precision zone: ease off near the target so the pointer settles onto
        # it instead of darting the last few px and ringing around it. Scales
        # smoothly from full speed at the edge to `precision_slow` at dead
        # centre, so there is no discontinuity to feel.
        if precision_px > 0 and dist < precision_px:
            k = dist / precision_px
            ease = precision_slow + (1.0 - precision_slow) * k
            ease = max(0.02, min(1.0, ease))
            max_speed_px_s *= ease
            tau = tau / ease

        alpha = 1.0 - math.exp(-dt / max(tau, 1e-3))
        sx = rx * alpha
        sy = ry * alpha

        # Cap by speed (px/sec) while preserving direction.
        max_step = max_speed_px_s * dt
        step = math.hypot(sx, sy)
        if step > max_step and step > 0:
            f = max_step / step
            sx *= f
            sy *= f
            step = max_step

        # Acceleration limit: bound how fast the pointer's own speed may
        # change. One bad target frame can then never fling the pointer — it
        # can only ramp, and the next frame corrects it.
        if max_accel_px_s2 > 0 and dt > 0:
            want = step / dt
            ceiling = self._speed + max_accel_px_s2 * dt
            if want > ceiling and step > 0:
                f = (ceiling * dt) / step
                sx *= f
                sy *= f
                step = ceiling * dt
            self._speed = step / dt
        else:
            self._speed = step / dt if dt > 0 else 0.0

        # Compensate for the OS pointer gain, then accumulate sub-pixel
        # movement; emit only whole pixels and carry the rest.
        g = max(self._gain, 0.05) * max(gain_scale, 0.05)
        self._ax += sx / g
        self._ay += sy / g
        mx = int(self._ax)   # trunc toward zero
        my = int(self._ay)
        self._ax -= mx
        self._ay -= my
        if mx or my:
            move_relative(mx, my)
        nx, ny = get_cursor_pos()

        # Learn the gain from what actually happened. Only large moves are
        # informative -- a 1 px request rounds too coarsely to measure.
        if auto_gain:
            asked = math.hypot(mx, my)
            if asked >= 4.0:
                got = math.hypot(nx - cx, ny - cy)
                if got > 0.0:
                    obs = max(0.15, min(4.0, got / asked))
                    self._gain += 0.08 * (obs - self._gain)
        return nx, ny


# --- Dwell click ----------------------------------------------------------

class DwellClicker:
    """Fires a click once the cursor holds within ``radius`` of the target.

    The timer starts when the cursor first enters the radius and is cancelled
    the moment it leaves. ``on_start`` fires when a fresh dwell begins so the UI
    can show/sound a cue that a click is imminent.
    """

    def __init__(self, on_start=None, on_fire=None):
        self._entered_at: Optional[float] = None
        self._armed = True  # re-arm required after each fire to avoid repeats
        self._last_fire = 0.0
        self._on_start = on_start
        self._on_fire = on_fire

    def reset(self) -> None:
        self._entered_at = None
        self._armed = True

    def update(
        self,
        cursor_screen: Tuple[int, int],
        target_screen: Optional[Tuple[int, int]],
        radius: int,
        dwell_ms: int,
        auto_click: bool,
        repeat: bool = False,
        interval_ms: int = 120,
    ) -> bool:
        """Advance the dwell state one frame. Returns True if a click fired.

        With ``repeat`` on, once the initial dwell fires it keeps auto-clicking
        every ``interval_ms`` while the cursor stays within the radius (an
        auto-clicker). With it off, it clicks once and won't fire again until the
        cursor leaves and re-enters the radius.
        """
        if target_screen is None or not auto_click:
            self._entered_at = None
            return False

        dx = cursor_screen[0] - target_screen[0]
        dy = cursor_screen[1] - target_screen[1]
        within = (dx * dx + dy * dy) <= radius * radius

        if not within:
            # Left the radius: cancel timer and re-arm for the next approach.
            self._entered_at = None
            self._armed = True
            return False

        now = time.monotonic()
        if self._entered_at is None:
            self._entered_at = now
            if self._on_start:
                self._on_start()
            return False

        held_ms = (now - self._entered_at) * 1000.0

        # First click after the dwell time.
        if self._armed and held_ms >= dwell_ms:
            click_left()
            self._armed = False
            self._last_fire = now
            if self._on_fire:
                self._on_fire()
            return True

        # Subsequent auto-fire clicks while held (repeat mode only).
        if repeat and not self._armed and held_ms >= dwell_ms:
            if (now - self._last_fire) * 1000.0 >= max(20, interval_ms):
                click_left()
                self._last_fire = now
                if self._on_fire:
                    self._on_fire()
                return True
        return False
