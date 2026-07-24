"""On-screen crosshair / FOV overlay.

A transparent, always-on-top, click-through window that draws a circle around the
cursor showing the **pull radius** — the area within which the assist will grab a
color and drag the cursor. The circle turns green while a target is locked.

Windows-specific: uses a layered + transparent extended window style so mouse
input passes straight through it (it's purely visual and never steals clicks).

Tkinter must own the main thread, so in web mode this runs the mainloop while the
web server and engine run in background threads.
"""

from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes

from .config import AppState

# Extended window styles.
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

KEY_COLOR = "#010203"   # this exact color renders fully transparent + click-through
SEARCH = "#5bc8ff"      # circle color while searching
LOCKED = "#33ff88"      # circle color while a target is locked


class CrosshairOverlay:
    def __init__(self, state: AppState, quit_event=None):
        self.state = state
        self._quit_event = quit_event
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", KEY_COLOR)
        except tk.TclError:
            pass
        self.root.configure(bg=KEY_COLOR)

        self.sw = self.root.winfo_screenwidth()
        self.sh = self.root.winfo_screenheight()
        self.root.geometry(f"{self.sw}x{self.sh}+0+0")
        self.canvas = tk.Canvas(self.root, width=self.sw, height=self.sh,
                                bg=KEY_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack()

        self.root.update_idletasks()
        self._make_click_through()
        self._user32 = ctypes.windll.user32
        self._tick()

    def _make_click_through(self) -> None:
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            cur = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                cur | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE)
        except Exception:
            pass

    def _cursor(self):
        pt = wintypes.POINT()
        self._user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _tick(self) -> None:
        if self._quit_event is not None and self._quit_event.is_set():
            self.root.destroy()
            return

        self.canvas.delete("all")
        try:
            show = self.state.get("show_overlay")
            r = int(self.state.get("pull_radius"))
            if show and r > 0:
                x, y = self._cursor()
                enabled = self.state.get("pull_enabled")
                found = enabled and self.state.get("last_target_found")
                col = LOCKED if found else SEARCH
                self.canvas.create_oval(x - r, y - r, x + r, y + r,
                                        outline=col, width=2)
                # small crosshair at the center
                self.canvas.create_line(x - 9, y, x + 9, y, fill=col, width=1)
                self.canvas.create_line(x, y - 9, x, y + 9, fill=col, width=1)
        except Exception:
            pass
        self.root.after(16, self._tick)   # ~60 fps

    def stop(self) -> None:
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()
