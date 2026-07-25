"""Dark, sectioned, always-on-top settings panel.

A small black control panel exposing every tunable. Runs on the main thread and
writes settings into :class:`AppState`, which the engine reads.

Highlights:
  * Multiple target colors (add via color picker or an on-screen eyedropper).
  * Global **Sensitivity** applied to all colors.
  * Both hotkeys are freely rebindable, including a **Record** button that
    captures whatever key/combo you press next.
  * Optional suppression of your physical mouse while the assist is pulling.

Settings persist to JSON between runs (see :mod:`persistence`).
"""

from __future__ import annotations

import colorsys
import ctypes
import threading
import tkinter as tk
from tkinter import colorchooser
from typing import Callable, Optional

from . import persistence
from .config import REGIONS, AppState, ColorTarget, tolerances_for
from .controller import AssistController

# --- Theme -----------------------------------------------------------------
BG = "#0b0b0d"
CARD = "#151519"
EDGE = "#26262d"
FG = "#e8e8ec"
MUTED = "#8a8a93"
FIELD = "#1d1d22"
ACCENT = "#3aa0ff"
ON = "#27c04a"
OFF = "#c0392b"
FONT = ("Segoe UI", 9)
FONT_B = ("Segoe UI", 9, "bold")
FONT_TITLE = ("Segoe UI", 11, "bold")

VK_LBUTTON = 0x01
VK_ESCAPE = 0x1B


def _rgb_to_cv_hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return int(h * 179), int(s * 255), int(v * 255)


def _cv_hsv_to_hex(c: ColorTarget) -> str:
    rr, gg, bb = colorsys.hsv_to_rgb(c.h / 179.0, c.s / 255.0, c.v / 255.0)
    return f"#{int(rr*255):02x}{int(gg*255):02x}{int(bb*255):02x}"


def _sample_screen_pixel(x: int, y: int):
    """Exact on-screen color at (x, y) via GDI GetPixel. Returns (r, g, b)."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc = user32.GetDC(0)
    try:
        col = gdi32.GetPixel(hdc, x, y)
    finally:
        user32.ReleaseDC(0, hdc)
    if col < 0 or col == 0xFFFFFFFF:  # CLR_INVALID
        return None
    return col & 0xFF, (col >> 8) & 0xFF, (col >> 16) & 0xFF


class ControlPanel:
    def __init__(self, state: AppState, load_settings: bool = True):
        self.state = state
        if load_settings:
            persistence.load(state)

        self.root = tk.Tk()
        self.root.title("Cursor Assist")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        self.controller = AssistController(
            state,
            on_dwell_start=self._on_dwell_start,
            on_click=self._on_click,
            on_error=self._on_error,
        )

        self._region_buttons: dict[str, tk.Button] = {}
        self._source_buttons: dict[str, tk.Button] = {}
        self._hotkey_handles: list = []
        self._autosave_job = None
        self._panel_visible = True
        self._eyedrop_active = False
        self._lbtn_was_down = False

        self._build_ui()
        self._apply_sensitivity(self.state.get("sensitivity"))
        self._register_hotkeys()

        self.controller.start()
        self.root.protocol("WM_DELETE_WINDOW", self._hide_panel)
        self._poll_status()

    # =====================================================================
    # Dark widget builders
    # =====================================================================
    def _section(self, title: str) -> tk.Frame:
        outer = tk.Frame(self.root, bg=EDGE, padx=1, pady=1)
        outer.pack(fill="x", padx=8, pady=(0, 6))
        inner = tk.Frame(outer, bg=CARD, padx=10, pady=8)
        inner.pack(fill="x")
        tk.Label(inner, text=title.upper(), bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 4))
        body = tk.Frame(inner, bg=CARD)
        body.pack(fill="x")
        return body

    def _slider(self, parent, label, var, lo, hi, res, cb):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=label, bg=CARD, fg=FG, font=FONT, width=14,
                 anchor="w").pack(side="left")
        tk.Label(row, textvariable=var, bg=CARD, fg=ACCENT, font=FONT_B,
                 width=5, anchor="e").pack(side="right")
        tk.Scale(row, variable=var, from_=lo, to=hi, resolution=res,
                 orient="horizontal", showvalue=False, length=150,
                 bg=CARD, fg=FG, troughcolor=FIELD, highlightthickness=0,
                 bd=0, activebackground=ACCENT, sliderrelief="flat",
                 command=lambda v: (cb(v), self._schedule_autosave())
                 ).pack(side="right", padx=6)

    def _check(self, parent, label, initial, cb):
        var = tk.BooleanVar(value=initial)
        tk.Checkbutton(
            parent, text=label, variable=var, bg=CARD, fg=FG, font=FONT,
            activebackground=CARD, activeforeground=FG, selectcolor=FIELD,
            highlightthickness=0, bd=0, anchor="w",
            command=lambda: (cb(bool(var.get())), self._schedule_autosave()),
        ).pack(fill="x", anchor="w", pady=1)
        return var

    def _entry(self, parent, width=6, value=""):
        e = tk.Entry(parent, width=width, bg=FIELD, fg=FG, font=FONT,
                     insertbackground=FG, relief="flat", highlightthickness=1,
                     highlightbackground=EDGE, highlightcolor=ACCENT)
        e.insert(0, str(value))
        return e

    def _button(self, parent, text, cb, accent=False, **kw):
        return tk.Button(
            parent, text=text, command=cb, font=FONT_B,
            bg=ACCENT if accent else FIELD, fg="#04121f" if accent else FG,
            activebackground=ACCENT, activeforeground="#04121f",
            relief="flat", bd=0, padx=8, pady=4, cursor="hand2", **kw)

    # =====================================================================
    # Layout
    # =====================================================================
    def _build_ui(self) -> None:
        st = self.state

        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=8, pady=(8, 6))
        tk.Label(header, text="⛶ Cursor Assist", bg=BG, fg=FG,
                 font=FONT_TITLE).pack(side="left")
        self._button(header, "Hide", self._hide_panel).pack(side="right")

        self.toggle_btn = tk.Button(
            self.root, text="PULL: OFF", command=self._toggle_pull,
            font=("Segoe UI", 12, "bold"), fg="white", bg=OFF,
            activebackground=OFF, activeforeground="white", relief="flat",
            bd=0, pady=8, cursor="hand2")
        self.toggle_btn.pack(fill="x", padx=8, pady=(0, 6))

        self.status_lbl = tk.Label(self.root, text="target: --    fps: --",
                                   bg=BG, fg=MUTED, font=FONT)
        self.status_lbl.pack(anchor="w", padx=10, pady=(0, 6))

        # --- Motion ------------------------------------------------------
        sec = self._section("Motion")
        self.smooth_var = tk.DoubleVar(value=round(st.get("smoothness"), 2))
        self._slider(sec, "Smoothness", self.smooth_var, 0.0, 1.0, 0.05,
                     lambda v: st.set("smoothness", float(v)))
        self.speed_var = tk.IntVar(value=st.get("max_speed"))
        self._slider(sec, "Max speed", self.speed_var, 500, 8000, 100,
                     lambda v: st.set("max_speed", int(float(v))))
        self.ema_var = tk.DoubleVar(value=round(st.get("target_ema"), 2))
        self._slider(sec, "Target steadiness", self.ema_var, 0.05, 0.9, 0.05,
                     lambda v: st.set("target_ema", float(v)))

        # --- Click -------------------------------------------------------
        sec = self._section("Click")
        self.autoclick_var = self._check(
            sec, "Auto dwell-click (off = manual only)",
            st.get("auto_click_enabled"),
            lambda b: st.set("auto_click_enabled", b))
        self.dwell_var = tk.IntVar(value=st.get("dwell_ms"))
        self._slider(sec, "Dwell time (ms)", self.dwell_var, 200, 1500, 50,
                     lambda v: st.set("dwell_ms", int(float(v))))
        self.radius_var = tk.IntVar(value=st.get("click_radius"))
        self._slider(sec, "Click radius", self.radius_var, 5, 80, 1,
                     lambda v: st.set("click_radius", int(float(v))))

        # --- Colors (multiple) ------------------------------------------
        sec = self._section("Target colors")
        self._swatch_row = tk.Frame(sec, bg=CARD)
        self._swatch_row.pack(fill="x", pady=(0, 2))
        tk.Label(sec, text="click a swatch to remove it", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w")
        brow = tk.Frame(sec, bg=CARD)
        brow.pack(fill="x", pady=3)
        self._button(brow, "＋ Pick", self._pick_color, accent=True).pack(
            side="left", padx=(0, 4))
        self._button(brow, "⦿ Eyedropper", self._start_eyedrop).pack(
            side="left", padx=(0, 4))
        self._button(brow, "Clear", self._clear_colors).pack(side="left")
        self.sens_var = tk.IntVar(value=st.get("sensitivity"))
        self._slider(sec, "Sensitivity", self.sens_var, 2, 45, 1,
                     lambda v: self._apply_sensitivity(int(float(v))))
        self.minarea_var = tk.IntVar(value=st.get("min_contour_area"))
        self._slider(sec, "Min area (px²)", self.minarea_var, 5, 500, 5,
                     lambda v: st.set("min_contour_area", int(float(v))))
        self.thin_var = self._check(
            sec, "Detect thin outlines (not just fills)",
            st.get("detect_thin_border"),
            lambda b: st.set("detect_thin_border", b))
        self._refresh_swatches()

        # --- Region ------------------------------------------------------
        sec = self._section("Target region")
        grid = tk.Frame(sec, bg=CARD)
        grid.pack()
        for i, name in enumerate(REGIONS):
            b = tk.Button(grid, text=name, width=7, height=1, font=FONT_B,
                          relief="flat", bd=0, cursor="hand2",
                          command=lambda n=name: self._select_region(n))
            b.grid(row=i // 3, column=i % 3, padx=3, pady=3)
            self._region_buttons[name] = b
        self._highlight_region(st.get("active_region"))

        # --- Capture -----------------------------------------------------
        sec = self._section("Capture source  (OBS recommended)")
        row = tk.Frame(sec, bg=CARD)
        row.pack(fill="x", pady=(0, 4))
        for label, src in (("OBS cam", "obs"), ("Screen", "screen")):
            b = tk.Button(row, text=label, width=8, font=FONT_B, relief="flat",
                          bd=0, cursor="hand2",
                          command=lambda s=src: self._select_source(s))
            b.pack(side="left", padx=(0, 4))
            self._source_buttons[src] = b
        self._highlight_source(st.get("capture").source)

        grid = tk.Frame(sec, bg=CARD)
        grid.pack(fill="x", pady=2)
        cap = st.get("capture")
        tk.Label(grid, text="Monitor", bg=CARD, fg=MUTED, font=FONT, width=8,
                 anchor="w").grid(row=0, column=0, sticky="w")
        self.monitor_e = self._entry(grid, 4, cap.monitor)
        self.monitor_e.grid(row=0, column=1, sticky="w", padx=2)
        tk.Label(grid, text="OBS idx", bg=CARD, fg=MUTED, font=FONT, width=8,
                 anchor="w").grid(row=0, column=2, sticky="w")
        self.obs_e = self._entry(grid, 4, cap.obs_device_index)
        self.obs_e.grid(row=0, column=3, sticky="w", padx=2)

        tk.Label(sec, text="Region L / T / W / H  (0 0 0 0 = full monitor)",
                 bg=CARD, fg=MUTED, font=FONT).pack(anchor="w", pady=(4, 0))
        rrow = tk.Frame(sec, bg=CARD)
        rrow.pack(fill="x", pady=2)
        self.region_entries = []
        for val in (cap.left, cap.top, cap.width, cap.height):
            e = self._entry(rrow, 5, val)
            e.pack(side="left", padx=2)
            self.region_entries.append(e)
        self._button(rrow, "Apply", self._apply_capture, accent=True).pack(
            side="left", padx=6)
        self.scale_var = tk.DoubleVar(value=round(st.get("detect_scale"), 2))
        self._slider(sec, "Detail (speed)", self.scale_var, 0.25, 1.0, 0.05,
                     lambda v: st.set("detect_scale", float(v)))

        # --- Input control ----------------------------------------------
        sec = self._section("Input control")
        self.suppress_var = self._check(
            sec, "Block my mouse while the bot is moving",
            st.get("suppress_mouse"),
            lambda b: st.set("suppress_mouse", b))

        # --- Hotkeys -----------------------------------------------------
        sec = self._section("Hotkeys")
        self.hk_show_e = self._hotkey_row(sec, "Show panel",
                                          st.get("hotkey_show_panel"), "show")
        self.hk_pull_e = self._hotkey_row(sec, "Toggle pull",
                                          st.get("hotkey_toggle_pull"), "pull")
        self._button(sec, "Apply hotkeys", self._apply_hotkeys).pack(
            anchor="e", pady=(4, 0))

        # --- Footer ------------------------------------------------------
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=8, pady=(2, 8))
        self._button(foot, "Save", self._save_now).pack(side="left")
        self._button(foot, "Reset defaults", self._reset_defaults).pack(
            side="left", padx=6)
        self._button(foot, "Quit", self._quit).pack(side="right")

    def _hotkey_row(self, parent, label, value, which):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=label, bg=CARD, fg=FG, font=FONT, width=11,
                 anchor="w").pack(side="left")
        e = self._entry(row, 14, value)
        e.pack(side="left", padx=2)
        self._button(row, "Record", lambda: self._record_hotkey(which)).pack(
            side="left", padx=2)
        return e

    # =====================================================================
    # Colors
    # =====================================================================
    def _refresh_swatches(self) -> None:
        for w in self._swatch_row.winfo_children():
            w.destroy()
        colors = self.state.get("colors")
        if not colors:
            tk.Label(self._swatch_row, text="(none — add a color)", bg=CARD,
                     fg=MUTED, font=("Segoe UI", 8)).pack(side="left")
            return
        for i, c in enumerate(colors):
            sw = tk.Label(self._swatch_row, text="  ✕", bg=_cv_hsv_to_hex(c),
                          fg="#000", font=("Segoe UI", 8, "bold"), width=4,
                          cursor="hand2")
            sw.pack(side="left", padx=2, pady=1)
            sw.bind("<Button-1>", lambda e, idx=i: self._remove_color(idx))

    def _apply_sensitivity(self, tol: int) -> None:
        h_tol, s_tol, v_tol = tolerances_for(tol)
        self.state.set("sensitivity", tol)
        with self.state.lock:
            for c in self.state.colors:
                c.h_tol, c.s_tol, c.v_tol = h_tol, s_tol, v_tol
        self._schedule_autosave()

    def _add_color_rgb(self, r: int, g: int, b: int) -> None:
        h, s, v = _rgb_to_cv_hsv(r, g, b)
        h_tol, s_tol, v_tol = tolerances_for(int(self.state.get("sensitivity")))
        with self.state.lock:
            self.state.colors.append(ColorTarget(
                h=h, s=s, v=v, h_tol=h_tol, s_tol=s_tol, v_tol=v_tol))
        self._refresh_swatches()
        self._schedule_autosave()

    def _remove_color(self, idx: int) -> None:
        with self.state.lock:
            if 0 <= idx < len(self.state.colors):
                self.state.colors.pop(idx)
        self._refresh_swatches()
        self._schedule_autosave()

    def _clear_colors(self) -> None:
        with self.state.lock:
            self.state.colors.clear()
        self._refresh_swatches()
        self._schedule_autosave()

    def _pick_color(self) -> None:
        rgb, _ = colorchooser.askcolor(title="Pick target color")
        if rgb:
            self._add_color_rgb(*(int(c) for c in rgb))

    # --- Eyedropper --------------------------------------------------------
    def _start_eyedrop(self) -> None:
        if self._eyedrop_active:
            return
        self._eyedrop_active = True
        self._lbtn_was_down = bool(
            ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        self._flash_status("Eyedropper: click any pixel  (Esc to cancel)", ACCENT)
        self.root.withdraw()  # get the panel out of the way
        self.root.after(60, self._poll_eyedrop)

    def _poll_eyedrop(self) -> None:
        if not self._eyedrop_active:
            return
        u = ctypes.windll.user32
        if u.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
            self._finish_eyedrop(None)
            return
        down = bool(u.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        if down and not self._lbtn_was_down:
            pt = wintypes_point()
            u.GetCursorPos(ctypes.byref(pt))
            self._finish_eyedrop(_sample_screen_pixel(pt.x, pt.y))
            return
        self._lbtn_was_down = down
        self.root.after(30, self._poll_eyedrop)

    def _finish_eyedrop(self, rgb) -> None:
        self._eyedrop_active = False
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        if rgb:
            self._add_color_rgb(*rgb)
            self._flash_status(f"sampled #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}",
                               ON)
        else:
            self._flash_status("eyedropper cancelled", MUTED)

    # =====================================================================
    # Other actions
    # =====================================================================
    def _toggle_pull(self) -> None:
        self.state.set("pull_enabled", not self.state.get("pull_enabled"))
        self._refresh_toggle()

    def _refresh_toggle(self) -> None:
        on = self.state.get("pull_enabled")
        self.toggle_btn.config(text=f"PULL: {'ON' if on else 'OFF'}",
                               bg=ON if on else OFF,
                               activebackground=ON if on else OFF)

    def _select_region(self, name: str) -> None:
        self.state.set("active_region", name)
        self._highlight_region(name)
        self._schedule_autosave()

    def _highlight_region(self, active: str) -> None:
        for name, btn in self._region_buttons.items():
            on = name == active
            btn.config(bg=ACCENT if on else FIELD, fg="#04121f" if on else FG,
                       activebackground=ACCENT if on else FIELD)

    def _select_source(self, src: str) -> None:
        with self.state.lock:
            self.state.capture.source = src
        self._highlight_source(src)
        self._schedule_autosave()

    def _highlight_source(self, active: str) -> None:
        for src, btn in self._source_buttons.items():
            on = src == active
            btn.config(bg=ACCENT if on else FIELD, fg="#04121f" if on else FG,
                       activebackground=ACCENT if on else FIELD)

    def _apply_capture(self) -> None:
        def as_int(entry, default):
            try:
                return int(entry.get().strip())
            except ValueError:
                return default
        with self.state.lock:
            cap = self.state.capture
            cap.monitor = max(0, as_int(self.monitor_e, cap.monitor))
            cap.obs_device_index = max(0, as_int(self.obs_e, cap.obs_device_index))
            cap.left = as_int(self.region_entries[0], 0)
            cap.top = as_int(self.region_entries[1], 0)
            cap.width = max(0, as_int(self.region_entries[2], 0))
            cap.height = max(0, as_int(self.region_entries[3], 0))
        self._flash_status("capture applied", ACCENT)
        self._save_now()

    # =====================================================================
    # Hotkeys
    # =====================================================================
    def _register_hotkeys(self) -> None:
        self._clear_hotkeys()
        show = self.state.get("hotkey_show_panel")
        pull = self.state.get("hotkey_toggle_pull")
        try:
            import keyboard
            self._hotkey_handles.append(keyboard.add_hotkey(show, self._hk_show))
            self._hotkey_handles.append(keyboard.add_hotkey(pull, self._hk_pull))
        except Exception:
            self.root.bind("<KeyPress-Shift_R>", lambda e: self._hk_show())

    def _clear_hotkeys(self) -> None:
        try:
            import keyboard
            for h in self._hotkey_handles:
                try:
                    keyboard.remove_hotkey(h)
                except (KeyError, ValueError):
                    pass
        except Exception:
            pass
        self._hotkey_handles = []

    def _apply_hotkeys(self) -> None:
        show = self.hk_show_e.get().strip() or "right shift"
        pull = self.hk_pull_e.get().strip() or "f8"
        self.state.set("hotkey_show_panel", show)
        self.state.set("hotkey_toggle_pull", pull)
        try:
            self._register_hotkeys()
            self._flash_status(f"hotkeys: {show} / {pull}", ACCENT)
            self._save_now()
        except Exception as exc:
            self._flash_status(f"bad hotkey: {exc}", OFF)

    def _record_hotkey(self, which: str) -> None:
        self._flash_status("press a key or combo…", ACCENT)

        def worker():
            hk = None
            try:
                import keyboard
                hk = keyboard.read_hotkey(suppress=False)
            except Exception:
                hk = None
            self.root.after(0, lambda: self._finish_record(which, hk))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_record(self, which: str, hk: Optional[str]) -> None:
        if not hk:
            self._flash_status("recording needs the 'keyboard' package", OFF)
            return
        entry = self.hk_show_e if which == "show" else self.hk_pull_e
        entry.delete(0, "end")
        entry.insert(0, hk)
        self._apply_hotkeys()

    def _hk_show(self) -> None:
        self.root.after(0, self._toggle_panel)

    def _hk_pull(self) -> None:
        self.root.after(0, self._toggle_pull)

    # =====================================================================
    # Panel visibility
    # =====================================================================
    def _toggle_panel(self) -> None:
        self._hide_panel() if self._panel_visible else self._show_panel()

    def _show_panel(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self._panel_visible = True

    def _hide_panel(self) -> None:
        self.root.withdraw()
        self._panel_visible = False

    # =====================================================================
    # Persistence
    # =====================================================================
    def _schedule_autosave(self) -> None:
        if self._autosave_job is not None:
            self.root.after_cancel(self._autosave_job)
        self._autosave_job = self.root.after(800, self._save_now)

    def _save_now(self) -> None:
        self._autosave_job = None
        try:
            persistence.save(self.state)
        except OSError as exc:
            self._flash_status(f"save failed: {exc}", OFF)

    def _reset_defaults(self) -> None:
        fresh = AppState()
        persistence.apply_dict(self.state, persistence.to_dict(fresh))
        self._save_now()
        self._clear_hotkeys()
        for w in self.root.winfo_children():
            w.destroy()
        self._region_buttons.clear()
        self._source_buttons.clear()
        self._build_ui()
        self._apply_sensitivity(self.state.get("sensitivity"))
        self._register_hotkeys()
        self._refresh_toggle()

    # =====================================================================
    # Cues + status
    # =====================================================================
    def _beep(self) -> None:
        try:
            import winsound
            winsound.Beep(880, 60)
        except Exception:
            pass

    def _on_dwell_start(self) -> None:
        self.root.after(0, self._beep)

    def _on_click(self) -> None:
        self.root.after(0, self._beep)

    def _on_error(self, exc: Exception) -> None:
        self.root.after(0, lambda: self._flash_status(f"error: {exc}", OFF))

    def _flash_status(self, text: str, color: str) -> None:
        self.status_lbl.config(text=text, fg=color)

    def _poll_status(self) -> None:
        if not self._eyedrop_active:
            found = self.state.get("last_target_found")
            fps = self.state.get("loop_fps")
            self.status_lbl.config(
                text=f"target: {'yes' if found else '--'}    fps: {fps}",
                fg=ON if found else MUTED)
        self._refresh_toggle()
        self.root.after(150, self._poll_status)

    # =====================================================================
    # Lifecycle
    # =====================================================================
    def _quit(self) -> None:
        self._save_now()
        try:
            self.controller.stop()
        finally:
            self._clear_hotkeys()
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def wintypes_point():
    from ctypes import wintypes
    return wintypes.POINT()
