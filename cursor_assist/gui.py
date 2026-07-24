"""Dark, sectioned, always-on-top settings panel.

A small black control panel, organised into labelled sections, exposing every
tunable in the app. Runs on the main thread; writes settings into
:class:`AppState`, which the background loop reads.

Two global hotkeys (both editable in the Hotkeys section):
  * **Right Shift** shows/hides this panel.
  * **Ctrl+Alt+Space** toggles the pull assist on/off.

Settings persist to a JSON file between runs (see :mod:`persistence`).
"""

from __future__ import annotations

import colorsys
import tkinter as tk
from tkinter import colorchooser
from typing import Callable, Optional

from . import persistence
from .config import REGIONS, AppState, ColorTarget
from .controller import AssistController

# --- Theme -----------------------------------------------------------------
BG = "#0b0b0d"          # window background
CARD = "#151519"        # section background
EDGE = "#26262d"        # section border / separators
FG = "#e8e8ec"          # primary text
MUTED = "#8a8a93"       # secondary text
FIELD = "#1d1d22"       # input backgrounds
ACCENT = "#3aa0ff"      # active / accent
ON = "#27c04a"          # pull-on green
OFF = "#c0392b"         # pull-off red
FONT = ("Segoe UI", 9)
FONT_B = ("Segoe UI", 9, "bold")
FONT_TITLE = ("Segoe UI", 11, "bold")


def _rgb_to_cv_hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return int(h * 179), int(s * 255), int(v * 255)


class ControlPanel:
    def __init__(self, state: AppState, load_settings: bool = True):
        self.state = state
        if load_settings:
            persistence.load(state)  # apply saved settings before building widgets

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

        self._build_ui()
        self._register_hotkeys()

        self.controller.start()
        self.root.protocol("WM_DELETE_WINDOW", self._hide_panel)  # X = hide, not quit
        self._poll_status()

    # =====================================================================
    # Small dark-styled widget builders
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
        val = tk.Label(row, textvariable=var, bg=CARD, fg=ACCENT, font=FONT_B,
                       width=5, anchor="e")
        val.pack(side="right")
        s = tk.Scale(
            row, variable=var, from_=lo, to=hi, resolution=res,
            orient="horizontal", showvalue=False, length=150,
            bg=CARD, fg=FG, troughcolor=FIELD, highlightthickness=0,
            bd=0, activebackground=ACCENT, sliderrelief="flat",
            command=lambda v: (cb(v), self._schedule_autosave()),
        )
        s.pack(side="right", padx=6)
        return s

    def _check(self, parent, label, initial, cb):
        var = tk.BooleanVar(value=initial)
        c = tk.Checkbutton(
            parent, text=label, variable=var, bg=CARD, fg=FG, font=FONT,
            activebackground=CARD, activeforeground=FG, selectcolor=FIELD,
            highlightthickness=0, bd=0, anchor="w",
            command=lambda: (cb(bool(var.get())), self._schedule_autosave()),
        )
        c.pack(fill="x", anchor="w", pady=1)
        return var

    def _entry(self, parent, width=6, value=""):
        e = tk.Entry(parent, width=width, bg=FIELD, fg=FG, font=FONT,
                     insertbackground=FG, relief="flat",
                     highlightthickness=1, highlightbackground=EDGE,
                     highlightcolor=ACCENT)
        e.insert(0, str(value))
        return e

    def _button(self, parent, text, cb, accent=False, **kw):
        b = tk.Button(
            parent, text=text, command=cb, font=FONT_B,
            bg=ACCENT if accent else FIELD, fg="#04121f" if accent else FG,
            activebackground=ACCENT, activeforeground="#04121f",
            relief="flat", bd=0, padx=8, pady=4, cursor="hand2", **kw,
        )
        return b

    # =====================================================================
    # UI layout
    # =====================================================================
    def _build_ui(self) -> None:
        st = self.state

        # --- Header ------------------------------------------------------
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=8, pady=(8, 6))
        tk.Label(header, text="⛶ Cursor Assist", bg=BG, fg=FG,
                 font=FONT_TITLE).pack(side="left")
        self._button(header, "Hide", self._hide_panel).pack(side="right")

        self.toggle_btn = tk.Button(
            self.root, text="PULL: OFF", command=self._toggle_pull,
            font=("Segoe UI", 12, "bold"), fg="white", bg=OFF,
            activebackground=OFF, activeforeground="white", relief="flat",
            bd=0, pady=8, cursor="hand2",
        )
        self.toggle_btn.pack(fill="x", padx=8, pady=(0, 6))

        self.status_lbl = tk.Label(self.root, text="target: --    fps: --",
                                   bg=BG, fg=MUTED, font=FONT)
        self.status_lbl.pack(anchor="w", padx=10, pady=(0, 6))

        # --- Assist ------------------------------------------------------
        sec = self._section("Assist")
        self.pull_var = tk.DoubleVar(value=round(st.get("pull_factor"), 2))
        self._slider(sec, "Pull strength", self.pull_var, 0.1, 0.5, 0.01,
                     lambda v: st.set("pull_factor", float(v)))
        self.maxpx_var = tk.IntVar(value=st.get("max_px_per_frame"))
        self._slider(sec, "Max px / frame", self.maxpx_var, 5, 120, 1,
                     lambda v: st.set("max_px_per_frame", int(float(v))))
        self.ema_var = tk.DoubleVar(value=round(st.get("target_ema"), 2))
        self._slider(sec, "Smoothing", self.ema_var, 0.05, 0.9, 0.05,
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

        # --- Color -------------------------------------------------------
        sec = self._section("Target color")
        row = tk.Frame(sec, bg=CARD)
        row.pack(fill="x", pady=2)
        self.color_swatch = tk.Label(row, text="   ", bg=self._swatch_hex(),
                                     width=6, relief="flat", bd=0)
        self.color_swatch.pack(side="left", padx=(0, 8))
        self._button(row, "Pick color…", self._pick_color,
                     accent=True).pack(side="left")
        self.tol_var = tk.IntVar(value=st.get("colors")[0].h_tol)
        self._slider(sec, "Tolerance", self.tol_var, 2, 40, 1, self._on_tolerance)
        self.minarea_var = tk.IntVar(value=st.get("min_contour_area"))
        self._slider(sec, "Min area (px²)", self.minarea_var, 5, 500, 5,
                     lambda v: st.set("min_contour_area", int(float(v))))
        self.thin_var = self._check(
            sec, "Detect thin outlines (not just fills)",
            st.get("detect_thin_border"),
            lambda b: st.set("detect_thin_border", b))

        # --- Region ------------------------------------------------------
        sec = self._section("Target region")
        grid = tk.Frame(sec, bg=CARD)
        grid.pack()
        for i, name in enumerate(REGIONS):
            b = tk.Button(
                grid, text=name, width=7, height=1, font=FONT_B,
                relief="flat", bd=0, cursor="hand2",
                command=lambda n=name: self._select_region(n),
            )
            b.grid(row=i // 3, column=i % 3, padx=3, pady=3)
            self._region_buttons[name] = b
        self._highlight_region(st.get("active_region"))

        # --- Capture -----------------------------------------------------
        sec = self._section("Capture source")
        row = tk.Frame(sec, bg=CARD)
        row.pack(fill="x", pady=(0, 4))
        for label, src in (("Screen", "screen"), ("OBS cam", "obs")):
            b = tk.Button(row, text=label, width=8, font=FONT_B, relief="flat",
                          bd=0, cursor="hand2",
                          command=lambda s=src: self._select_source(s))
            b.pack(side="left", padx=(0, 4))
            self._source_buttons[src] = b
        self._highlight_source(st.get("capture").source)

        grid = tk.Frame(sec, bg=CARD)
        grid.pack(fill="x", pady=2)
        cap = st.get("capture")
        tk.Label(grid, text="Monitor", bg=CARD, fg=MUTED, font=FONT,
                 width=8, anchor="w").grid(row=0, column=0, sticky="w")
        self.monitor_e = self._entry(grid, 4, cap.monitor)
        self.monitor_e.grid(row=0, column=1, sticky="w", padx=2)
        tk.Label(grid, text="OBS idx", bg=CARD, fg=MUTED, font=FONT,
                 width=8, anchor="w").grid(row=0, column=2, sticky="w")
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
        self._button(rrow, "Apply", self._apply_capture,
                     accent=True).pack(side="left", padx=6)

        # --- Hotkeys -----------------------------------------------------
        sec = self._section("Hotkeys")
        hrow = tk.Frame(sec, bg=CARD)
        hrow.pack(fill="x", pady=1)
        tk.Label(hrow, text="Show panel", bg=CARD, fg=FG, font=FONT, width=11,
                 anchor="w").pack(side="left")
        self.hk_show_e = self._entry(hrow, 16, st.get("hotkey_show_panel"))
        self.hk_show_e.pack(side="left", padx=2)
        hrow2 = tk.Frame(sec, bg=CARD)
        hrow2.pack(fill="x", pady=1)
        tk.Label(hrow2, text="Toggle pull", bg=CARD, fg=FG, font=FONT, width=11,
                 anchor="w").pack(side="left")
        self.hk_pull_e = self._entry(hrow2, 16, st.get("hotkey_toggle_pull"))
        self.hk_pull_e.pack(side="left", padx=2)
        self._button(sec, "Apply hotkeys", self._apply_hotkeys).pack(
            anchor="e", pady=(4, 0))

        # --- Footer ------------------------------------------------------
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=8, pady=(2, 8))
        self._button(foot, "Save settings", self._save_now).pack(side="left")
        self._button(foot, "Reset defaults", self._reset_defaults).pack(
            side="left", padx=6)
        self._button(foot, "Quit", self._quit).pack(side="right")

    # =====================================================================
    # Actions
    # =====================================================================
    def _toggle_pull(self) -> None:
        self.state.set("pull_enabled", not self.state.get("pull_enabled"))
        self._refresh_toggle()

    def _refresh_toggle(self) -> None:
        on = self.state.get("pull_enabled")
        self.toggle_btn.config(text=f"PULL: {'ON' if on else 'OFF'}",
                               bg=ON if on else OFF, activebackground=ON if on else OFF)

    def _select_region(self, name: str) -> None:
        self.state.set("active_region", name)
        self._highlight_region(name)
        self._schedule_autosave()

    def _highlight_region(self, active: str) -> None:
        for name, btn in self._region_buttons.items():
            on = name == active
            btn.config(bg=ACCENT if on else FIELD,
                       fg="#04121f" if on else FG,
                       activebackground=ACCENT if on else FIELD)

    def _select_source(self, src: str) -> None:
        with self.state.lock:
            self.state.capture.source = src
        self._highlight_source(src)
        self._schedule_autosave()

    def _highlight_source(self, active: str) -> None:
        for src, btn in self._source_buttons.items():
            on = src == active
            btn.config(bg=ACCENT if on else FIELD,
                       fg="#04121f" if on else FG,
                       activebackground=ACCENT if on else FIELD)

    def _on_tolerance(self, value) -> None:
        tol = int(float(value))
        with self.state.lock:
            for c in self.state.colors:
                c.h_tol = tol
                c.s_tol = min(255, tol * 8)
                c.v_tol = min(255, tol * 8)

    def _pick_color(self) -> None:
        rgb, _ = colorchooser.askcolor(title="Pick target color")
        if not rgb:
            return
        r, g, b = (int(c) for c in rgb)
        h, s, v = _rgb_to_cv_hsv(r, g, b)
        tol = int(self.tol_var.get())
        with self.state.lock:
            self.state.colors[:] = [ColorTarget(
                h=h, s=s, v=v, h_tol=tol,
                s_tol=min(255, tol * 8), v_tol=min(255, tol * 8))]
        self.color_swatch.config(bg=f"#{r:02x}{g:02x}{b:02x}")
        self._schedule_autosave()

    def _swatch_hex(self) -> str:
        c = self.state.get("colors")[0]
        rr, gg, bb = colorsys.hsv_to_rgb(c.h / 179.0, c.s / 255.0, c.v / 255.0)
        return f"#{int(rr*255):02x}{int(gg*255):02x}{int(bb*255):02x}"

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
            self._hotkey_handles.append(
                keyboard.add_hotkey(show, self._hotkey_show))
            self._hotkey_handles.append(
                keyboard.add_hotkey(pull, self._hotkey_pull))
            self._keyboard_ok = True
        except Exception:
            # Window-focused fallbacks (only work when the panel has focus).
            self._keyboard_ok = False
            self.root.bind("<KeyPress-Shift_R>", lambda e: self._hotkey_show())
            self.root.bind("<Control-Alt-space>", lambda e: self._hotkey_pull())

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
        pull = self.hk_pull_e.get().strip() or "ctrl+alt+space"
        self.state.set("hotkey_show_panel", show)
        self.state.set("hotkey_toggle_pull", pull)
        try:
            self._register_hotkeys()
            self._flash_status(f"hotkeys set: {show} / {pull}", ACCENT)
            self._save_now()
        except Exception as exc:
            self._flash_status(f"bad hotkey: {exc}", OFF)

    def _hotkey_show(self) -> None:
        self.root.after(0, self._toggle_panel)

    def _hotkey_pull(self) -> None:
        self.root.after(0, self._toggle_pull)

    # =====================================================================
    # Panel visibility
    # =====================================================================
    def _toggle_panel(self) -> None:
        if self._panel_visible:
            self._hide_panel()
        else:
            self._show_panel()

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
        with self.state.lock, fresh.lock:
            persistence.apply_dict(self.state, persistence.to_dict(fresh))
        self._save_now()
        # Rebuild the window so every widget reflects the defaults.
        self._clear_hotkeys()
        for w in self.root.winfo_children():
            w.destroy()
        self._region_buttons.clear()
        self._source_buttons.clear()
        self._build_ui()
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
