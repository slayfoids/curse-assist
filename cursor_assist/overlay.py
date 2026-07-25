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

from . import region_picker
from .config import AppState
from .region_picker import apply_region, capture_origin

# Extended window styles.
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

KEY_COLOR = "#010203"   # this exact color renders fully transparent + click-through
SEARCH = "#b273ff"      # circle color while searching (Curse violet)
LOCKED = "#ff4df0"      # circle color while a target is locked (magenta)
AIM_LINE = "#00e5ff"    # cyan guide line from the pointer to the aim point
AIM_HALO = "#0090a8"    # dimmer casing, so the line reads on light backgrounds
ROI_EDGE = "#7c5cff"    # outline of the configured detection area


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
        self._picking = False
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

    # ------------------------------------------------------- region picker
    def _service_pick_request(self) -> None:
        """Run the drag-a-box picker when the panel has asked for one."""
        if self._picking:
            return
        what = self.state.get("region_pick")
        if not what:
            return
        self._picking = True
        titles = {"roi": "Drag to set the detection area",
                  "capture": "Drag to set the capture region"}

        def done(box):
            self._picking = False
            with self.state.lock:
                self.state.region_pick = ""
                if box is not None:
                    apply_region(self.state, what, box)

        try:
            region_picker.open_on(self.root, done, titles.get(what, ""))
        except Exception:
            self._picking = False
            self.state.set("region_pick", "")

    def _draw_roi(self) -> None:
        """Outline the detection area, so it is visible rather than inferred."""
        if not self.state.get("show_roi"):
            return
        w = int(self.state.get("roi_w"))
        h = int(self.state.get("roi_h"))
        if w <= 0 or h <= 0:
            return
        # roi_x/y are relative to the capture region's top-left corner.
        ox, oy, _cw, _ch = capture_origin(self.state)
        x = ox + int(self.state.get("roi_x"))
        y = oy + int(self.state.get("roi_y"))
        self.canvas.create_rectangle(x, y, x + w, y + h,
                                     outline=ROI_EDGE, width=2, dash=(7, 5))
        self.canvas.create_text(x + 4, max(y - 15, 2), anchor="nw",
                                fill=ROI_EDGE, text=f"detection area {w}x{h}",
                                font=("Segoe UI", 9, "bold"))

    def _tick(self) -> None:
        if self._quit_event is not None and self._quit_event.is_set():
            self.root.destroy()
            return

        # The panel can only *ask* for the region picker; Tk builds windows
        # solely on the thread running its loop, which is this one.
        self._service_pick_request()

        self.canvas.delete("all")
        try:
            self._draw_roi()
            show = self.state.get("show_overlay")
            # Circle size: explicit overlay_radius if set, else the pull radius.
            r = int(self.state.get("overlay_radius")) or int(
                self.state.get("pull_radius"))
            cursor = None
            if show and r > 0:
                x, y = cursor = self._cursor()
                enabled = self.state.get("pull_enabled")
                found = enabled and self.state.get("last_target_found")
                col = LOCKED if found else SEARCH
                self.canvas.create_oval(x - r, y - r, x + r, y + r,
                                        outline=col, width=2)
                # small crosshair at the center
                self.canvas.create_line(x - 9, y, x + 9, y, fill=col, width=1)
                self.canvas.create_line(x, y - 9, x, y + 9, fill=col, width=1)

            # Aim guide: a live line from the pointer to the pixel the engine
            # is steering toward. Purely informational — it shows the user
            # which way the assist wants to go so they can move *with* it
            # rather than unknowingly pulling against it.
            if (self.state.get("show_aim_line")
                    and self.state.get("aim_valid")
                    and self.state.get("pull_enabled")):
                if cursor is None:
                    cursor = self._cursor()
                cx, cy = cursor
                ax = int(self.state.get("aim_x"))
                ay = int(self.state.get("aim_y"))
                if (ax, ay) != (cx, cy):
                    self.canvas.create_line(cx, cy, ax, ay,
                                            fill=AIM_HALO, width=5)
                    self.canvas.create_line(cx, cy, ax, ay,
                                            fill=AIM_LINE, width=2)
                    # Ring the destination so the goal pixel is unambiguous.
                    self.canvas.create_oval(ax - 7, ay - 7, ax + 7, ay + 7,
                                            outline=AIM_LINE, width=2)
                    self.canvas.create_line(ax - 11, ay, ax - 4, ay,
                                            fill=AIM_LINE, width=1)
                    self.canvas.create_line(ax + 4, ay, ax + 11, ay,
                                            fill=AIM_LINE, width=1)
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
