"""Windows pointer ballistics: what a requested move actually travels.

``SendInput`` relative movement is not delivered to the screen verbatim. It goes
through the same pointer pipeline as a physical mouse, so what lands is

    pixels = units x speed_multiplier x acceleration_curve(speed)

Two separate settings drive that, and the tool has to survive both extremes:

* **Pointer speed** (Settings > Mouse, an 11-notch slider) is a flat multiplier
  from 1/32x to 3.5x. On a low setting a requested 10 px move lands as 1 px and
  the pull crawls; on a high one it lands as 35 px and the pull overshoots the
  target and rings around it.
* **Enhance pointer precision** (on by default) adds a velocity-dependent
  acceleration curve on top. This is the part a single learned number cannot
  represent: the same 10-unit request travels a different distance depending on
  how fast the pointer is already going, so any scalar fit is wrong at one end
  of the range or the other — slow corrections undershoot while fast sweeps
  overshoot, which is exactly how "works at low sensitivity, struggles at high"
  presents.

So the gain is modelled as a small **curve** over request size rather than one
number, and it is *seeded from the OS settings* instead of being learned from
scratch. Seeding matters: learning from a 1.0 start took tens of corrective
moves to converge, and every one of those moves was visibly wrong — at 3.5x the
first moves overshot by 250%.

Nothing here changes any Windows setting; it only reads them.
"""

from __future__ import annotations

import ctypes
import math
import statistics
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

SPI_GETMOUSESPEED = 0x0070
SPI_GETMOUSE = 0x0003

# Multiplier applied to mouse input for each value of the pointer-speed setting
# (SPI_GETMOUSESPEED returns 1-20; 10 is the default 1:1 position). The 11
# notches the Settings slider exposes are values 1, 2, 4, 6, 8, 10, 12, 14, 16,
# 18, 20 — i.e. 1/32x at the far left through 3.5x at the far right.
SPEED_TABLE = (
    0.03125, 0.0625, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0,
    1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5,
)

SETTINGS_RECHECK_S = 2.0   # notice the user moving the Windows slider

# Curve bins, in requested units per emitted event. Log-spaced because the
# acceleration curve does most of its bending at small requests; the top bin
# catches everything above it.
BIN_EDGES = (2.0, 4.0, 8.0, 16.0, 32.0, 64.0)
N_BINS = len(BIN_EDGES) + 1

SAMPLES_PER_BIN = 7        # median window — one contaminated sample can't move it
SCALE_SAMPLES = 9
# Observations are pooled until this many units have been requested, and only
# then turned into one sample.
#
# A single event is a biased measurement: the cursor position is an integer, so
# one unit at 3.5x reads back as 3 px or 4 px and never as 3.5. Discarding small
# requests does not help — on a high pointer speed nearly every request *is* one
# or two units, so the setting that most needs measuring would teach the curve
# nothing. Pooling instead lets the rounding cancel, which is what stops the
# estimate settling on 4.0 when the truth is 3.5 and leaving every move 14%
# short.
POOL_UNITS = 4.0
GAIN_MIN, GAIN_MAX = 0.02, 12.0
SHAPE_MIN, SHAPE_MAX = 0.3, 4.0    # how far one bin may depart from the base
SHAPE_DAMPING = 0.5                # pull toward the seeded curve, see observe()


@dataclass(frozen=True)
class PointerSettings:
    """The two Windows settings that decide how far a request travels."""

    speed: int = 10          # SPI_GETMOUSESPEED, 1-20
    enhance: bool = False    # "enhance pointer precision" (acceleration)

    @property
    def multiplier(self) -> float:
        return SPEED_TABLE[max(1, min(20, self.speed)) - 1]

    def describe(self) -> str:
        notch = {1: 1, 2: 2, 4: 3, 6: 4, 8: 5, 10: 6,
                 12: 7, 14: 8, 16: 9, 18: 10, 20: 11}.get(self.speed)
        where = f"{notch}/11" if notch else f"value {self.speed}"
        return (f"{where} ({self.multiplier:g}x)"
                + (" + enhance precision" if self.enhance else ""))


def read_settings() -> PointerSettings:
    """Current pointer speed and acceleration, straight from Windows."""
    try:
        u = ctypes.windll.user32
        speed = ctypes.c_int(10)
        u.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(speed), 0)
        accel = (ctypes.c_int * 3)()
        u.SystemParametersInfoW(SPI_GETMOUSE, 0, ctypes.byref(accel), 0)
        return PointerSettings(speed=int(speed.value),
                               enhance=bool(accel[2]))
    except Exception:
        return PointerSettings()


def _bin_for(units: float) -> int:
    u = abs(units)
    for i, edge in enumerate(BIN_EDGES):
        if u < edge:
            return i
    return N_BINS - 1


class GainCurve:
    """Pixels travelled per unit requested, as a function of request size.

    Factored deliberately into two parts, because the two Windows settings that
    produce it behave differently:

    * a **base scale**, the flat pointer-speed multiplier. Every observation is
      evidence about it whatever size the request was, so it converges within a
      handful of moves — which is what makes an unexpected sensitivity (a
      shared machine, a gaming mouse switching DPI profile) correct itself
      almost immediately rather than over a second of visibly wrong movement.
    * a **shape**, the acceleration curve's per-size departure from that base.
      Only requests of a given size say anything about that size's bin, so it
      refines more slowly — but it is a small correction on top of a base that
      is already right.

    Learning it as one number per bin instead made every bin start from scratch:
    the pointer had to sweep the full range of speeds several times before any
    of it was right, and bins the run never visited stayed wrong indefinitely.

    Each estimate is the **median** of a short window, so a sample polluted by
    the user's own hand moving the mouse at the same moment cannot drag it the
    way a running average did.
    """

    def __init__(self, settings: Optional[PointerSettings] = None):
        self._lock = threading.Lock()
        self._settings = settings or PointerSettings()
        self._scale = 1.0
        self._shape: List[float] = [1.0] * N_BINS
        self._bins: List[List[float]] = [[] for _ in range(N_BINS)]
        self._pool: List[tuple] = [(0.0, 0.0)] * N_BINS
        self._scale_window: List[float] = []
        self._checked_at = 0.0
        self._reseed(self._settings)

    # ------------------------------------------------------------- settings
    def _reseed(self, settings: PointerSettings) -> None:
        self._settings = settings
        self._scale = max(GAIN_MIN, min(GAIN_MAX, settings.multiplier))
        self._bins = [[] for _ in range(N_BINS)]
        self._pool = [(0.0, 0.0)] * N_BINS
        self._scale_window = []
        # "Enhance pointer precision" damps slow movement and amplifies fast
        # movement, so the seeded shape starts below the base for small
        # requests and rises above it for large ones. A flat-or-rising seed
        # over-estimated what a *small* request would travel, which is the
        # common case on a high pointer speed, and left the last stretch of
        # every approach crawling.
        shape = [(0.75 + 0.15 * i) if settings.enhance else 1.0
                 for i in range(N_BINS)]
        m = sum(shape) / len(shape)
        self._seed_shape = [s / m for s in shape]   # mean 1, see _renormalise
        self._shape = list(self._seed_shape)

    def refresh(self, now: Optional[float] = None) -> bool:
        """Re-read the OS settings occasionally; reseed if the user changed them.

        Returns True when a change was picked up.
        """
        now = now if now is not None else time.perf_counter()
        if now - self._checked_at < SETTINGS_RECHECK_S:
            return False
        self._checked_at = now
        s = read_settings()
        if s == self._settings:
            return False
        with self._lock:
            self._reseed(s)
        return True

    @property
    def settings(self) -> PointerSettings:
        return self._settings

    # ---------------------------------------------------------------- query
    def _gain_locked(self, i: int) -> float:
        return max(GAIN_MIN, min(GAIN_MAX, self._scale * self._shape[i]))

    def gain_for(self, units: float) -> float:
        with self._lock:
            return self._gain_locked(_bin_for(units))

    @property
    def scale(self) -> float:
        """The learned flat multiplier — the pointer-speed part alone."""
        with self._lock:
            return self._scale

    def unit_px(self) -> float:
        """Pixels moved by the smallest possible request — the resolution floor.

        At 3.5x one unit is 3.5 px, so no amount of filtering can place the
        pointer more accurately than that; the caller uses this to stop hunting
        for precision the input path cannot deliver.
        """
        with self._lock:
            return max(self._gain_locked(0), 1e-3)

    def units_for(self, want_px: float) -> float:
        """Units to request so that roughly ``want_px`` pixels are travelled.

        ``gain`` depends on the size of the request, so this is a fixed point
        rather than a division. Two passes is plenty at these bin widths.
        """
        if want_px == 0.0:
            return 0.0
        sign = 1.0 if want_px > 0 else -1.0
        mag = abs(want_px)
        with self._lock:
            gains = [self._gain_locked(i) for i in range(N_BINS)]
        u = mag / gains[_bin_for(mag)]
        for _ in range(2):
            u = mag / gains[_bin_for(u)]
        return sign * u

    def mean_gain(self) -> float:
        """A single representative number, for display only."""
        with self._lock:
            return float(sum(self._gain_locked(i) for i in range(N_BINS))
                         / N_BINS)

    # ------------------------------------------------------------- learning
    def observe(self, units: float, got_px: float) -> None:
        """Record that a request of ``units`` actually moved ``got_px`` pixels.

        Pooled per bin until there is enough travel to measure without the
        integer-rounding bias; see :data:`POOL_UNITS`.
        """
        u = abs(units)
        if u <= 0.0 or got_px < 0.0:
            return
        i = _bin_for(u)
        with self._lock:
            pu, ppx = self._pool[i]
            pu += u
            ppx += got_px
            if pu < POOL_UNITS:
                self._pool[i] = (pu, ppx)
                return
            self._pool[i] = (0.0, 0.0)
            ratio = ppx / pu
        if not (GAIN_MIN <= ratio <= GAIN_MAX):
            return
        with self._lock:
            # Every sample updates the base, whatever size it was: divide out
            # this bin's known shape and what remains is evidence about the
            # flat multiplier.
            implied = ratio / max(self._shape[i], 1e-3)
            self._scale_window.append(
                max(GAIN_MIN, min(GAIN_MAX, implied)))
            if len(self._scale_window) > SCALE_SAMPLES:
                self._scale_window.pop(0)
            self._scale = float(statistics.median(self._scale_window))

            # Then this bin's departure from that base — the acceleration
            # curve. Needs a real window before it is trusted at all, since a
            # single sample cannot be told apart from noise.
            window = self._bins[i]
            window.append(ratio)
            if len(window) > SAMPLES_PER_BIN:
                window.pop(0)
            if len(window) >= 3:
                med = float(statistics.median(window))
                want = med / max(self._scale, 1e-3)
                # Damped toward the seeded shape. Only the *product* of scale
                # and shape is observable, so letting both chase each sample at
                # full speed lets them trade against one another — measured as
                # 40% of the travel spent hunting at 2x with acceleration on.
                # Pulling the poorly-identified half back toward its seed
                # settles that.
                blend = SHAPE_DAMPING * self._seed_shape[i] + \
                    (1.0 - SHAPE_DAMPING) * want
                self._shape[i] = max(SHAPE_MIN, min(SHAPE_MAX, blend))
                self._renormalise()

    def _renormalise(self) -> None:
        """Hold ``mean(shape) == 1`` so the split stays pinned.

        Without an anchor the pair is only determined up to a constant, and the
        two halves drift in opposite directions indefinitely even while their
        product stays right. Rescaling the recorded scale samples by the same
        factor keeps every stored measurement consistent with the new split.
        """
        m = sum(self._shape) / len(self._shape)
        if m <= 1e-6 or abs(m - 1.0) < 1e-6:
            return
        self._shape = [s / m for s in self._shape]
        self._scale_window = [s * m for s in self._scale_window]
        if self._scale_window:
            self._scale = float(statistics.median(self._scale_window))

    def snapshot(self) -> List[float]:
        with self._lock:
            return [self._gain_locked(i) for i in range(N_BINS)]


def emit_vector(curve: GainCurve, dx_px: float, dy_px: float):
    """Split a desired pixel move into the unit vector that delivers it.

    Returned as ``(ux, uy)`` floats — the caller accumulates the fractional part
    so small moves are not rounded away to nothing.
    """
    mag = math.hypot(dx_px, dy_px)
    if mag <= 0.0:
        return 0.0, 0.0
    units = abs(curve.units_for(mag))
    return units * dx_px / mag, units * dy_px / mag
