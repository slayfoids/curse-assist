"""Drag-a-box screen region picker, in the style of the Snipping Tool.

Dims the whole desktop, lets the user drag a rectangle over the part that
matters, and hands back absolute desktop pixels. Typing four numbers into
X/Y/W/H boxes is a poor way to describe a region you are *looking at* — you
have to know where the window is in desktop coordinates, and there is no
feedback until the numbers are already wrong.

Multi-monitor aware: the window spans the whole virtual desktop, so a region on
a secondary screen (which sits at negative or offset coordinates) can be picked
directly instead of having to be worked out.

Tkinter insists on driving its own event loop from whichever thread created the
widget, and the crosshair overlay already owns one on the main thread. So this
module exposes two ways in:

* :func:`open_on` — attach to an existing ``Tk`` root, used by the overlay.
* :func:`pick_blocking` — stand up a private root, for ``--no-overlay`` runs.
"""

from __future__ import annotations

import ctypes
import tkinter as tk
from typing import Callable, Optional, Tuple

Box = Tuple[int, int, int, int]     # (left, top, width, height), absolute px

DIM = "#0b0714"          # backdrop wash
EDGE = "#c26bff"         # selection border (Curse violet)
EDGE_GLOW = "#ff4df0"
TEXT = "#f2edfa"
GUIDE = "#6f6580"        # crosshair guide lines
MIN_SIZE = 8             # smaller than this counts as a stray click, not a drag


def virtual_desktop() -> Box:
    """Bounding box of every monitor together, in absolute desktop pixels."""
    try:
        u = ctypes.windll.user32
        # SM_XVIRTUALSCREEN / YVIRTUALSCREEN / CXVIRTUALSCREEN / CYVIRTUALSCREEN
        x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        w, h = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return int(x), int(y), int(w), int(h)
    except Exception:
        pass
    return 0, 0, 1920, 1080


class _Picker:
    """One selection session over a full-desktop transparent window."""

    def __init__(self, root: tk.Tk, on_done: Callable[[Optional[Box]], None],
                 title: str = "Drag to set the detection area"):
        self._on_done = on_done
        self._done = False
        vx, vy, vw, vh = virtual_desktop()
        self._origin = (vx, vy)

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{vw}x{vh}+{vx}+{vy}")
        try:
            self.win.attributes("-alpha", 0.32)
        except tk.TclError:
            pass
        self.win.configure(bg=DIM, cursor="crosshair")

        self.cv = tk.Canvas(self.win, width=vw, height=vh, bg=DIM,
                            highlightthickness=0, bd=0, cursor="crosshair")
        self.cv.pack()

        self._x0 = self._y0 = 0
        self._rect = None
        self._label = None
        self._guides = []

        self.cv.bind("<Button-1>", self._press)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Motion>", self._hover)
        self.win.bind("<Escape>", lambda e: self._finish(None))
        # Grabbing input keeps the keystrokes here rather than leaking Escape
        # into whatever is behind, and makes the picker feel modal.
        self.win.after(10, self._grab)

        self._hint(vw, vh, title)

    def _grab(self) -> None:
        try:
            self.win.focus_force()
            self.win.grab_set()
        except tk.TclError:
            pass

    def _hint(self, vw: int, vh: int, title: str) -> None:
        self.cv.create_text(
            vw // 2, 46, fill=TEXT, justify="center", tags="hint",
            font=("Segoe UI", 17, "bold"), text=title)
        self.cv.create_text(
            vw // 2, 76, fill=TEXT, justify="center", tags="hint",
            font=("Segoe UI", 11),
            text="drag a box  ·  Esc cancels  ·  a single click selects "
                 "the whole screen")

    # ----------------------------------------------------------- interaction
    def _hover(self, e) -> None:
        for g in self._guides:
            self.cv.delete(g)
        self._guides = [
            self.cv.create_line(0, e.y, self.cv.winfo_width(), e.y,
                                fill=GUIDE, dash=(3, 5)),
            self.cv.create_line(e.x, 0, e.x, self.cv.winfo_height(),
                                fill=GUIDE, dash=(3, 5)),
        ]

    def _press(self, e) -> None:
        self._x0, self._y0 = e.x, e.y
        for item in (self._rect, self._label):
            if item:
                self.cv.delete(item)
        self._rect = self._label = None
        self.cv.delete("hint")

    def _drag(self, e) -> None:
        x0, y0 = min(self._x0, e.x), min(self._y0, e.y)
        x1, y1 = max(self._x0, e.x), max(self._y0, e.y)
        if self._rect is None:
            self._rect = self.cv.create_rectangle(x0, y0, x1, y1,
                                                  outline=EDGE, width=2)
            self._label = self.cv.create_text(0, 0, fill=TEXT, anchor="nw",
                                              font=("Segoe UI", 11, "bold"))
        self.cv.coords(self._rect, x0, y0, x1, y1)
        self.cv.itemconfig(self._rect,
                           outline=EDGE_GLOW if (x1 - x0) >= MIN_SIZE
                           and (y1 - y0) >= MIN_SIZE else EDGE)
        # Keep the size readout on screen when the box is dragged to an edge.
        ly = y0 - 22 if y0 > 26 else y1 + 6
        self.cv.coords(self._label, x0 + 2, ly)
        self.cv.itemconfig(self._label, text=f"{x1 - x0} x {y1 - y0}")

    def _release(self, e) -> None:
        x0, y0 = min(self._x0, e.x), min(self._y0, e.y)
        x1, y1 = max(self._x0, e.x), max(self._y0, e.y)
        ox, oy = self._origin
        if x1 - x0 < MIN_SIZE or y1 - y0 < MIN_SIZE:
            # A click rather than a drag: take the whole desktop, which is the
            # same thing as clearing the area back to "everything".
            vx, vy, vw, vh = virtual_desktop()
            self._finish((vx, vy, vw, vh))
            return
        self._finish((ox + x0, oy + y0, x1 - x0, y1 - y0))

    def _finish(self, box: Optional[Box]) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self._on_done(box)


def open_on(root: tk.Tk, on_done: Callable[[Optional[Box]], None],
            title: str = "Drag to set the detection area") -> None:
    """Start a picker on an existing Tk root. Must run on that root's thread."""
    _Picker(root, on_done, title)


# --------------------------------------------------------------- geometry
_origin_cache: dict = {}


def capture_origin(state) -> Box:
    """Where the configured capture region sits on the desktop.

    Detection-area coordinates are relative to this corner, so a box picked in
    absolute desktop pixels has to be rebased through it. Cached per capture
    configuration because the overlay asks 60 times a second and resolving a
    monitor means going out to ``mss``.
    """
    with state.lock:
        cap = state.capture
        key = (cap.source, cap.left, cap.top, cap.width, cap.height,
               cap.monitor)
    hit = _origin_cache.get(key)
    if hit is not None:
        return hit
    if key[0] == "obs":
        # The OBS canvas is composited at desktop scale and maps 1:1 onto it.
        box = (0, 0, 0, 0)
    elif key[3] > 0 and key[4] > 0:
        box = (key[1], key[2], key[3], key[4])
    else:
        box = _monitor_box(key[5])
    _origin_cache[key] = box
    return box


def _monitor_box(index: int) -> Box:
    try:
        import mss
        with mss.mss() as sct:
            m = sct.monitors[index]
            return int(m["left"]), int(m["top"]), int(m["width"]), \
                int(m["height"])
    except Exception:
        try:
            u = ctypes.windll.user32
            return 0, 0, int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
        except Exception:
            return 0, 0, 1920, 1080


def apply_region(state, what: str, box: Box) -> None:
    """Store a picked desktop box as the detection area or capture region.

    Must be called with ``state.lock`` already held.
    """
    left, top, w, h = (int(v) for v in box)
    if what == "capture":
        state.capture.left, state.capture.top = left, top
        state.capture.width, state.capture.height = w, h
        # The area was expressed against the old capture corner and would now
        # mean somewhere else, so it goes back to covering everything.
        state.roi_x = state.roi_y = state.roi_w = state.roi_h = 0
        _origin_cache.clear()
        return
    ox, oy, cw, ch = capture_origin(state)
    x, y = left - ox, top - oy
    # Clip into the captured frame; a region reaching past it would otherwise
    # be silently trimmed at grab time and the aim point offset with it.
    if cw > 0 and ch > 0:
        x0, y0 = max(0, x), max(0, y)
        w = min(w + min(0, x), cw - x0)
        h = min(h + min(0, y), ch - y0)
        x, y = x0, y0
    state.roi_x, state.roi_y = max(0, x), max(0, y)
    state.roi_w, state.roi_h = max(0, w), max(0, h)


def pick_blocking(title: str = "Drag to set the detection area"
                  ) -> Optional[Box]:
    """Run a picker with a private root and return the chosen box.

    For the ``--no-overlay`` case, where no Tk main loop exists to attach to.
    Call from a thread that owns no other Tk objects.
    """
    result: list = [None]
    root = tk.Tk()
    root.withdraw()

    def done(box):
        result[0] = box
        try:
            root.quit()
        except tk.TclError:
            pass

    _Picker(root, done, title)
    root.mainloop()
    try:
        root.destroy()
    except tk.TclError:
        pass
    return result[0]
