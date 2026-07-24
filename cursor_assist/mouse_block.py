"""Optional suppression of the user's *physical* mouse movement while pulling.

When the assist is actively moving the cursor, a shaky physical hand can fight
the pull. This installs a standard Windows low-level mouse hook (``WH_MOUSE_LL``)
that, while "suppressing", drops **physical** mouse-move events but lets the
app's own **injected** moves through (they carry the ``LLMHF_INJECTED`` flag).

Notes
-----
* This is a global input hook, not DLL injection -- it observes mouse events
  system-wide and is torn down cleanly on stop (and automatically by Windows if
  the process dies).
* Only mouse *movement* is ever suppressed. Clicks, wheel, and all keyboard
  input are always passed through, so the user can still click and type.
* Suppression is only in effect while :meth:`set_suppressing` is ``True`` -- the
  controller turns it on only during an active pull and off the instant it ends.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
LLMHF_INJECTED = 0x00000001
WM_QUIT = 0x0012
HC_ACTION = 0

LRESULT = ctypes.c_ssize_t
LPARAM = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)

# Explicit restypes: without these, ctypes truncates 64-bit handles to a 32-bit
# int, which corrupts the module/hook handles (a NULL hMod then fails with
# error 126, MOD_NOT_FOUND).
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE,
                                      wintypes.DWORD]
_user32.CallNextHookEx.restype = LRESULT
_user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, WPARAM, LPARAM]
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, WPARAM,
                                       LPARAM]


class MouseSuppressor:
    def __init__(self):
        self._suppressing = False       # eat physical moves while True
        self._hook = None
        self._thread_id = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        # Keep a strong ref to the callback so it isn't garbage-collected.
        self._proc = HOOKPROC(self._callback)

    # -- called from the hook thread for every low-level mouse event ---------
    def _callback(self, nCode, wParam, lParam):
        if nCode == HC_ACTION and wParam == WM_MOUSEMOVE and self._suppressing:
            info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (info.flags & LLMHF_INJECTED):
                return 1  # swallow the physical movement
        return _user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def _run(self):
        self._thread_id = _kernel32.GetCurrentThreadId()
        hmod = _kernel32.GetModuleHandleW(None)
        self._hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, hmod, 0)
        self._ready.set()
        if not self._hook:
            return
        # Low-level hooks require a message loop on the installing thread.
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    # -- public API ---------------------------------------------------------
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="mouse-hook",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return bool(self._hook)

    def set_suppressing(self, value: bool) -> None:
        self._suppressing = bool(value)

    def stop(self) -> None:
        self._suppressing = False
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._hook:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
