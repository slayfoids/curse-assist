"""Always-on-top Tkinter control panel.

Runs on the main thread. Writes user settings into :class:`AppState`; the
background :class:`AssistController` reads them. Also registers a global hotkey
(via ``keyboard`` if available) so pull mode can be toggled without focusing the
window -- important for a user with limited hand precision.
"""

from __future__ import annotations

import colorsys
import tkinter as tk
from tkinter import colorchooser, ttk
from typing import Optional

from .config import REGIONS, AppState, ColorTarget
from .controller import AssistController

DEFAULT_HOTKEY = "ctrl+alt+space"


def _rgb_to_cv_hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Convert 0-255 RGB to OpenCV HSV (H 0-179, S/V 0-255)."""
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return int(h * 179), int(s * 255), int(v * 255)


class ControlPanel:
    def __init__(self, state: AppState):
        self.state = state
        self.root = tk.Tk()
        self.root.title("Cursor Assist")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        self.controller = AssistController(
            state,
            on_dwell_start=self._on_dwell_start,
            on_click=self._on_click,
            on_error=self._on_error,
        )

        self._region_buttons: dict[str, tk.Button] = {}
        self._hotkey_handle = None

        self._build_ui()
        self._register_hotkey()

        self.controller.start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_status()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        row = 0

        # --- master toggle + hotkey display ---
        self.toggle_btn = tk.Button(
            self.root, text="Pull: OFF", width=24, height=2,
            bg="#b33", fg="white", font=("Segoe UI", 12, "bold"),
            command=self._toggle_pull,
        )
        self.toggle_btn.grid(row=row, column=0, columnspan=2, **pad)
        row += 1

        tk.Label(self.root, text=f"Global hotkey: {DEFAULT_HOTKEY}",
                 fg="#555").grid(row=row, column=0, columnspan=2, sticky="w",
                                 padx=8)
        row += 1

        self.status_lbl = tk.Label(self.root, text="target: --   fps: --",
                                   fg="#777")
        self.status_lbl.grid(row=row, column=0, columnspan=2, sticky="w",
                             padx=8)
        row += 1

        ttk.Separator(self.root, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        # --- sliders ---
        self.pull_var = tk.DoubleVar(value=self.state.get("pull_factor"))
        row = self._slider(row, "Pull strength", self.pull_var, 0.1, 0.5, 0.01,
                            lambda v: self.state.set("pull_factor", float(v)))

        self.dwell_var = tk.IntVar(value=self.state.get("dwell_ms"))
        row = self._slider(row, "Dwell time (ms)", self.dwell_var, 200, 1500, 50,
                           lambda v: self.state.set("dwell_ms", int(float(v))))

        self.radius_var = tk.IntVar(value=self.state.get("click_radius"))
        row = self._slider(row, "Click radius (px)", self.radius_var, 5, 80, 1,
                           lambda v: self.state.set("click_radius", int(float(v))))

        self.tol_var = tk.IntVar(value=self.state.get("colors")[0].h_tol)
        row = self._slider(row, "Color tolerance", self.tol_var, 2, 40, 1,
                           self._on_tolerance)

        ttk.Separator(self.root, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        # --- color ---
        self.color_swatch = tk.Label(self.root, text="  target color  ",
                                     bg=self._current_swatch_hex(), width=16)
        self.color_swatch.grid(row=row, column=0, padx=8, pady=4)
        tk.Button(self.root, text="Pick color…",
                  command=self._pick_color).grid(row=row, column=1, padx=8)
        row += 1

        ttk.Separator(self.root, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        # --- big region buttons (2 columns x 3 rows) ---
        tk.Label(self.root, text="Target region",
                 font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8)
        row += 1

        grid = tk.Frame(self.root)
        grid.grid(row=row, column=0, columnspan=2, padx=8, pady=4)
        for i, name in enumerate(REGIONS):
            b = tk.Button(grid, text=name, width=8, height=2,
                          font=("Segoe UI", 12, "bold"),
                          command=lambda n=name: self._select_region(n))
            b.grid(row=i // 2, column=i % 2, padx=4, pady=4)
            self._region_buttons[name] = b
        self._highlight_region(self.state.get("active_region"))
        row += 1

        ttk.Separator(self.root, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        # --- auto-click master enable ---
        self.autoclick_var = tk.BooleanVar(
            value=self.state.get("auto_click_enabled"))
        tk.Checkbutton(
            self.root, text="Auto dwell-click (off = manual click only)",
            variable=self.autoclick_var,
            command=lambda: self.state.set(
                "auto_click_enabled", bool(self.autoclick_var.get())),
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        row += 1

        self.thin_var = tk.BooleanVar(value=self.state.get("detect_thin_border"))
        tk.Checkbutton(
            self.root, text="Detect thin outlines (not just filled color)",
            variable=self.thin_var,
            command=lambda: self.state.set(
                "detect_thin_border", bool(self.thin_var.get())),
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

    def _slider(self, row, label, var, lo, hi, res, cb):
        tk.Label(self.root, text=label).grid(row=row, column=0, sticky="w",
                                             padx=8)
        s = tk.Scale(self.root, variable=var, from_=lo, to=hi, resolution=res,
                     orient="horizontal", length=180, command=cb)
        s.grid(row=row, column=1, padx=8, sticky="e")
        return row + 1

    # -------------------------------------------------------------- actions
    def _toggle_pull(self) -> None:
        new = not self.state.get("pull_enabled")
        self.state.set("pull_enabled", new)
        self._refresh_toggle()

    def _refresh_toggle(self) -> None:
        on = self.state.get("pull_enabled")
        self.toggle_btn.config(
            text=f"Pull: {'ON' if on else 'OFF'}",
            bg="#2a2" if on else "#b33",
        )

    def _select_region(self, name: str) -> None:
        self.state.set("active_region", name)
        self._highlight_region(name)

    def _highlight_region(self, active: str) -> None:
        for name, btn in self._region_buttons.items():
            if name == active:
                btn.config(bg="#248", fg="white")
            else:
                btn.config(bg="SystemButtonFace", fg="black")

    def _on_tolerance(self, value) -> None:
        tol = int(float(value))
        with self.state.lock:
            for c in self.state.colors:
                c.h_tol = tol
                # Scale S/V tolerance with H tolerance for a sensible feel.
                c.s_tol = min(255, tol * 8)
                c.v_tol = min(255, tol * 8)

    def _pick_color(self) -> None:
        rgb, _hexv = colorchooser.askcolor(title="Pick target color")
        if not rgb:
            return
        r, g, b = (int(c) for c in rgb)
        h, s, v = _rgb_to_cv_hsv(r, g, b)
        tol = int(self.tol_var.get())
        with self.state.lock:
            self.state.colors[:] = [ColorTarget(
                h=h, s=s, v=v, h_tol=tol,
                s_tol=min(255, tol * 8), v_tol=min(255, tol * 8),
            )]
        self.color_swatch.config(bg=f"#{r:02x}{g:02x}{b:02x}")

    def _current_swatch_hex(self) -> str:
        c = self.state.get("colors")[0]
        rr, gg, bb = colorsys.hsv_to_rgb(c.h / 179.0, c.s / 255.0, c.v / 255.0)
        return f"#{int(rr*255):02x}{int(gg*255):02x}{int(bb*255):02x}"

    # -------------------------------------------------------------- hotkey
    def _register_hotkey(self) -> None:
        try:
            import keyboard  # optional; global even when unfocused
            self._hotkey_handle = keyboard.add_hotkey(
                DEFAULT_HOTKEY, self._hotkey_toggle)
        except Exception:
            # Fall back to a window-focused binding.
            self.root.bind("<Control-Alt-space>",
                           lambda e: self._hotkey_toggle())

    def _hotkey_toggle(self) -> None:
        # Called from the keyboard hook thread -> marshal onto the Tk thread.
        self.root.after(0, self._toggle_pull)

    # -------------------------------------------------------------- cues
    def _beep(self) -> None:
        try:
            import winsound
            winsound.Beep(880, 60)
        except Exception:
            pass

    def _on_dwell_start(self) -> None:
        self.root.after(0, self._beep)

    def _on_click(self) -> None:
        self.root.after(0, lambda: self._beep())

    def _on_error(self, exc: Exception) -> None:
        self.root.after(0, lambda: self.status_lbl.config(
            text=f"error: {exc}", fg="#b33"))

    # -------------------------------------------------------------- status
    def _poll_status(self) -> None:
        found = self.state.get("last_target_found")
        fps = self.state.get("loop_fps")
        self.status_lbl.config(
            text=f"target: {'yes' if found else '--'}   fps: {fps}",
            fg="#2a2" if found else "#777",
        )
        self._refresh_toggle()
        self.root.after(120, self._poll_status)

    # -------------------------------------------------------------- run
    def _on_close(self) -> None:
        try:
            self.controller.stop()
        finally:
            if self._hotkey_handle is not None:
                try:
                    import keyboard
                    keyboard.remove_hotkey(self._hotkey_handle)
                except Exception:
                    pass
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
