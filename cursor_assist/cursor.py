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

from . import pointer

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
    ("doesn't fully go to the color").

    Requests are converted to device units through :class:`~.pointer.GainCurve`,
    which knows what Windows will actually do with them at this machine's
    pointer-speed and acceleration settings — see :mod:`.pointer`. Within
    ``lock_px`` it lands as precisely as that path allows: exactly on the target
    at a normal pointer speed, and within one device unit on a high one, where
    nothing finer is reachable at all.
    """

    def __init__(self, curve=None):
        self._ax = 0.0  # carried sub-pixel remainder, in device units
        self._ay = 0.0
        self._speed = 0.0   # current pointer speed, px/s (for accel limiting)
        # How far a request actually travels, as a function of its size.
        # Windows scales relative mouse input by the pointer-speed slider and
        # bends it further with "enhance pointer precision", so a requested
        # 10 px move can land as 1 px on a low setting or 35 px on a high one.
        # The curve is seeded from the OS settings, so the very first move is
        # already right, and refined from what actually happens.
        self._curve = curve if curve is not None else pointer.GainCurve()

    def reset(self) -> None:
        self._ax = 0.0
        self._ay = 0.0
        self._speed = 0.0

    @property
    def curve(self):
        return self._curve

    @property
    def gain(self) -> float:
        """Learned pixels-per-unit at base speed, for display."""
        return self._curve.scale

    @property
    def resolution_px(self) -> float:
        """Smallest move the pointer can make at all, in screen pixels.

        One device unit is ``gain`` pixels, so at 3.5x nothing finer than
        3.5 px is reachable. Chasing below this is what makes a
        high-sensitivity pointer buzz around the target instead of settling.
        """
        return self._curve.unit_px()

    def _best_landing(self, rx: float, ry: float, dist: float):
        """Whole-unit move that lands closest to the target, or ``(0, 0)``.

        The gliding path scales both axes by one shared factor, which keeps the
        motion straight but means the reachable landing points are limited to
        that line. On a high pointer speed, where a single unit is several
        pixels, that was the difference between stopping 2.5 px out and landing
        on the target: choosing each axis separately reaches the whole lattice.

        ``(0, 0)`` when no move clearly improves on standing still — at a
        coarse resolution the nearest whole unit is often *further* away, and
        taking it anyway is what turned "arrived" into a permanent twitch.

        The improvement has to clear a margin rather than merely be positive.
        Only the integer cursor position is observable, and the gain is an
        estimate, so a move that lands the same distance out on the *opposite*
        side can still look like progress against those rounded numbers — which
        is exactly what it does, symmetrically, from over there. Measured, that
        produced a perfect (1,1)/(-1,-1) cycle running at the full tick rate and
        68% of the travel spent going nowhere.
        """
        ux, uy = pointer.emit_vector(self._curve, rx, ry)
        bx, by = int(round(ux)), int(round(uy))
        margin = max(0.5, 0.3 * self._curve.unit_px())
        best = (0, 0)
        best_err = dist - margin
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                mx, my = bx + dx, by + dy
                if not (mx or my):
                    continue
                g = self._curve.gain_for(math.hypot(mx, my))
                err = math.hypot(rx - mx * g, ry - my * g)
                if err < best_err:
                    best_err, best = err, (mx, my)
        return best

    def step(self, target_screen: Tuple[int, int], dt: float, tau: float,
             max_speed_px_s: float, lock_px: float = 2.0,
             max_accel_px_s2: float = 0.0,
             precision_px: float = 0.0, precision_slow: float = 1.0,
             gain_scale: float = 1.0, auto_gain: bool = True,
             target_vel: Tuple[float, float] = (0.0, 0.0)
             ) -> Tuple[int, int]:
        if auto_gain:
            self._curve.refresh()
        cx, cy = get_cursor_pos()
        rx = target_screen[0] - cx
        ry = target_screen[1] - cy
        dist = math.hypot(rx, ry)

        # Nothing finer than one device unit can be expressed, so on a high
        # pointer speed the landing zone has to widen to match. Held at the old
        # fixed 2 px, a 3.5x pointer could never satisfy it: every correction
        # overshot to the other side and the pointer sat there vibrating.
        res = self._curve.unit_px()
        lock_px = max(lock_px, 0.6 * res)

        # Close enough: place the pointer as precisely as the input path allows.
        if dist <= lock_px:
            self.reset()
            mx, my = self._best_landing(rx, ry, dist)
            if mx or my:
                move_relative(mx, my)
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

        # Feed-forward: travel at the target's own speed as well as toward it.
        #
        # The term above is proportional to the *error*, and a proportional
        # controller cannot sit on a moving target — it settles wherever the
        # error is large enough to generate exactly the speed needed to keep
        # up, which is a fixed distance behind. That distance does not depend
        # on the speed or acceleration caps at all, which is why raising them
        # never closed the gap. Matching the target's velocity removes the
        # error rather than trading against it, and the proportional term is
        # then left correcting only what feed-forward did not predict.
        sx += target_vel[0] * dt
        sy += target_vel[1] * dt

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

        # Convert the wanted pixels into device units through the curve, then
        # accumulate the fraction; emit only whole units and carry the rest.
        #
        # `gain_scale` is the user's manual trim and *multiplies* the distance
        # asked for. It used to divide it, so the slider documented as "raise
        # this if it still under-reaches" made it under-reach further — turning
        # it up was the exact opposite of the fix its own label suggested.
        gs = max(gain_scale, 0.05)
        ux, uy = pointer.emit_vector(self._curve, sx * gs, sy * gs)
        self._ax += ux
        self._ay += uy
        mx = int(self._ax)   # trunc toward zero
        my = int(self._ay)
        self._ax -= mx
        self._ay -= my
        if mx or my:
            move_relative(mx, my)
        nx, ny = get_cursor_pos()

        # Learn from what actually happened, per request size — with
        # acceleration on, the same request travels a different distance
        # depending on how big it is, so one number cannot describe it.
        if auto_gain and (mx or my):
            self._curve.observe(math.hypot(mx, my),
                                math.hypot(nx - cx, ny - cy))
        return nx, ny


# --- Dwell click ----------------------------------------------------------

# How much further than the click radius the pointer must stray before a dwell
# in progress is abandoned. See the note in `update`.
EXIT_SLACK = 1.6


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
        self._lost_at: Optional[float] = None   # when the target vanished
        self._distance = 0.0                    # px to target, for the panel

    @property
    def distance(self) -> float:
        """How far the pointer currently is from the target, in px.

        Reported so a click radius set too small to ever be satisfied is
        visible as a number rather than as "it just doesn't click sometimes".
        """
        return self._distance

    def reset(self) -> None:
        self._entered_at = None
        self._armed = True
        self._lost_at = None

    def target_lost(self, grace_ms: int = 0) -> None:
        """The engine has no target this frame.

        A dwell in progress survives a brief gap. Detection drops frames
        whenever the colour flickers or the capture source stutters, and the
        engine also discards targets older than a fraction of a second — so
        cancelling the timer on the first missing frame meant that on a slow
        or noisy source the dwell click simply never fired, which is the
        "sometimes it just doesn't click" report.
        """
        if self._entered_at is None:
            self.reset()
            return
        now = time.monotonic()
        if self._lost_at is None:
            self._lost_at = now
        elif (now - self._lost_at) * 1000.0 > max(0, grace_ms):
            self.reset()

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
        if not auto_click:
            self.reset()
            return False
        if target_screen is None:
            # Handled by target_lost(); never silently drop the timer here.
            return False
        self._lost_at = None

        dx = cursor_screen[0] - target_screen[0]
        dy = cursor_screen[1] - target_screen[1]
        dist2 = dx * dx + dy * dy
        self._distance = math.sqrt(dist2)
        # Hysteresis: it takes a bigger excursion to *leave* than to enter.
        # Detection noise moves the aim point a few px many times a second, so
        # a single threshold had the cursor crossing in and out of the radius
        # constantly, restarting the timer each time — which is why a dwell
        # click could take far longer than its setting or never arrive at all.
        limit = radius if self._entered_at is None else radius * EXIT_SLACK
        within = dist2 <= limit * limit

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
            # A zero dwell means "click as soon as you get there", so there is
            # nothing to wait for — waiting even one frame is the difference
            # between instant and not.
            if dwell_ms > 0:
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
