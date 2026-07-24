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

def pull_toward(
    target_screen: Tuple[int, int],
    pull_factor: float,
    max_px_per_frame: int,
) -> Tuple[int, int]:
    """Ease the cursor one step toward ``target_screen``.

    Implements ``new = current + (target - current) * pull_factor`` via a
    single relative move, capped at ``max_px_per_frame`` so even a strong pull
    never snaps. Returns the cursor position after moving.
    """
    cx, cy = get_cursor_pos()
    dx = (target_screen[0] - cx) * pull_factor
    dy = (target_screen[1] - cy) * pull_factor

    # Cap magnitude while preserving direction.
    dist = (dx * dx + dy * dy) ** 0.5
    if dist > max_px_per_frame and dist > 0:
        scale = max_px_per_frame / dist
        dx *= scale
        dy *= scale

    move_relative(round(dx), round(dy))
    return get_cursor_pos()


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
    ) -> bool:
        """Advance the dwell state one frame. Returns True if a click fired."""
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

        if self._armed and (now - self._entered_at) * 1000.0 >= dwell_ms:
            click_left()
            self._armed = False  # don't machine-gun; require leaving the radius
            if self._on_fire:
                self._on_fire()
            return True
        return False
