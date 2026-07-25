"""Hold-to-activate by polling the real key state.

The global-hook route for this was never reliable. Three separate failure
modes hit it, all silent:

* the ``mouse`` package rewrites a press landing within the system
  double-click time of the previous button event into a ``double``;
* its X-button decode indexes a dict with the raw ``mouseData`` word, which
  raises on mice that set extra bits — inside the hook callback, where the
  exception just vanishes;
* a low-level hook competes with every other WH_MOUSE_LL hook on the system
  (including this app's own optional pointer-steadying hook), and a slow or
  throttled hook chain drops events.

``GetAsyncKeyState`` has none of that. It reads the same state Windows itself
reports, needs no hook, cannot be reordered or starved, and costs nothing at
250 Hz. It also treats mouse buttons and keyboard keys identically, so one
code path covers both.
"""

from __future__ import annotations

import ctypes
import threading
from typing import Callable, Optional

_user32 = ctypes.WinDLL("user32", use_last_error=True)

POLL_HZ = 250.0

# Virtual-key codes for everything the panel offers as a hold button, plus the
# usual modifiers. Names match the `keyboard` package's spelling so a token
# recorded by the panel resolves here unchanged.
VK_NAMES = {
    "LMB": 0x01, "RMB": 0x02, "MMB": 0x04, "MB4": 0x05, "MB5": 0x06,
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "esc": 0x1B,
    "escape": 0x1B, "space": 0x20, "page up": 0x21, "page down": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27,
    "down": 0x28, "insert": 0x2D, "delete": 0x2E, "caps lock": 0x14,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "left shift": 0xA0, "right shift": 0xA1,
    "left ctrl": 0xA2, "right ctrl": 0xA3,
    "left alt": 0xA4, "right alt": 0xA5,
}


def resolve_vk(token: str) -> Optional[int]:
    """Virtual-key code for a panel hold token, or ``None`` if unknown."""
    if not token:
        return None
    key = token.strip()
    vk = VK_NAMES.get(key) or VK_NAMES.get(key.lower())
    if vk:
        return vk
    low = key.lower()
    if len(low) == 1 and (low.isalpha() or low.isdigit()):
        return ord(low.upper())
    if low.startswith("f") and low[1:].isdigit():
        n = int(low[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    # Last resort: let the `keyboard` package name it, then map scan -> VK.
    try:
        import keyboard
        for scan in keyboard.key_to_scan_codes(key):
            got = _user32.MapVirtualKeyW(scan, 1)  # MAPVK_VSC_TO_VK
            if got:
                return int(got)
    except Exception:
        pass
    return None


def is_down(vk: int) -> bool:
    """True while the key/button is physically held."""
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


class HoldWatcher:
    """Calls ``on_change(bool)`` when the watched key is pressed or released.

    Only edges are reported, so the caller sees one call per real transition
    however long the key is held.
    """

    def __init__(self, on_change: Callable[[bool], None]):
        self._on_change = on_change
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._vk: Optional[int] = None

    @property
    def vk(self) -> Optional[int]:
        return self._vk

    def start(self, token: str) -> bool:
        """Watch ``token``. Returns False if it names nothing we can poll."""
        self.stop()
        vk = resolve_vk(token)
        if vk is None:
            return False
        self._vk = vk
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hold-watch",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._vk = None

    def _loop(self) -> None:
        vk = self._vk
        if vk is None:
            return
        # Seed from the current state so starting with the button already held
        # doesn't register as a fresh press.
        was = is_down(vk)
        period = 1.0 / POLL_HZ
        while not self._stop.wait(period):
            now = is_down(vk)
            if now != was:
                was = now
                try:
                    self._on_change(now)
                except Exception:
                    pass
