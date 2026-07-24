"""Local web UI backend.

Serves a sleek dark control panel at ``http://127.0.0.1:<port>`` and exposes a
tiny JSON API the page uses to read status and change settings. The vision/pull
engine (:class:`AssistController`) runs in this same process; the browser tab is
just the front end.

Bound to loopback only -- it is never exposed on the network.
"""

from __future__ import annotations

import colorsys
import ctypes
import json
import threading
import webbrowser
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from . import persistence
from .config import REGIONS, AppState, ColorTarget
from .controller import AssistController
from .webpage import PAGE

VK_LBUTTON = 0x01
VK_ESCAPE = 0x1B

# Click-trigger tokens that mean a mouse button (mapped to `mouse` lib names).
# Anything not in here is treated as a keyboard key/combo.
MOUSE_TOKENS = {
    "LMB": "left",
    "RMB": "right",
    "MMB": "middle",
    "MB4": "x",
    "MB5": "x2",
}


def _hsv_to_hex(c: ColorTarget) -> str:
    r, g, b = colorsys.hsv_to_rgb(c.h / 179.0, c.s / 255.0, c.v / 255.0)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _hex_to_rgb(s: str):
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def _rgb_to_cv_hsv(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return int(h * 179), int(s * 255), int(v * 255)


class WebApp:
    def __init__(self, state: AppState, host: str = "127.0.0.1",
                 port: int = 8756, open_browser: bool = True):
        self.state = state
        self.host = host
        self.port = port
        self.open_browser = open_browser
        self.url = f"http://{host}:{port}/"

        self.controller = AssistController(
            state, on_dwell_start=self._beep, on_click=self._beep,
            on_error=self._on_error)
        self._last_error = ""
        self._eyedropping = False
        self._eyedrop_thread: Optional[threading.Thread] = None
        self._hotkey_handles: list = []
        self._mouse_hooks: list = []
        self._httpd: Optional[ThreadingHTTPServer] = None
        self.quit_event = threading.Event()  # set when the app is shutting down
        self._stopped = False

    # ------------------------------------------------------------------ run
    def start(self) -> None:
        self.controller.start()
        self._register_hotkeys()
        self._httpd = _make_server(self)
        self.port = self._httpd.server_address[1]
        self.url = f"http://{self.host}:{self.port}/"
        threading.Thread(target=self._httpd.serve_forever,
                         name="web-ui", daemon=True).start()
        if self.open_browser:
            threading.Timer(0.4, lambda: webbrowser.open(self.url)).start()

    def serve_blocking(self) -> None:
        import sys
        self.start()
        if sys.stdout:  # None under pythonw (background/windowless mode)
            print(f"Cursor Assist UI running at {self.url}")
            print("Press Ctrl+C here to quit (or use Quit in the page).")
        self._shutdown = threading.Event()
        try:
            self._shutdown.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.quit_event.set()  # lets the overlay/main thread exit
        try:
            self.controller.stop()
        finally:
            self._clear_hotkeys()
            if self._httpd:
                threading.Thread(target=self._httpd.shutdown, daemon=True).start()
            if getattr(self, "_shutdown", None):
                self._shutdown.set()

    # -------------------------------------------------------------- helpers
    def _beep(self) -> None:
        try:
            import winsound
            winsound.Beep(880, 60)
        except Exception:
            pass

    def _on_error(self, exc: Exception) -> None:
        self._last_error = str(exc)

    def _save(self) -> None:
        try:
            persistence.save(self.state)
        except OSError:
            pass

    def _apply_sensitivity(self, tol: int) -> None:
        with self.state.lock:
            self.state.sensitivity = tol
            for c in self.state.colors:
                c.h_tol = tol
                c.s_tol = min(255, tol * 8)
                c.v_tol = min(255, tol * 8)

    def _add_color_rgb(self, r, g, b) -> None:
        h, s, v = _rgb_to_cv_hsv(r, g, b)
        tol = int(self.state.get("sensitivity"))
        with self.state.lock:
            self.state.colors.append(ColorTarget(
                h=h, s=s, v=v, h_tol=tol,
                s_tol=min(255, tol * 8), v_tol=min(255, tol * 8)))

    # ------------------------------------------------------------ eyedropper
    def _start_eyedrop(self) -> None:
        if self._eyedropping:
            return
        self._eyedropping = True
        self._eyedrop_thread = threading.Thread(
            target=self._eyedrop_loop, name="eyedrop", daemon=True)
        self._eyedrop_thread.start()

    def _eyedrop_loop(self) -> None:
        import time
        u = ctypes.windll.user32
        gdi = ctypes.windll.gdi32
        was_down = bool(u.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        deadline = time.monotonic() + 20.0
        while self._eyedropping and time.monotonic() < deadline:
            if u.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
                break
            down = bool(u.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            if down and not was_down:
                pt = wintypes.POINT()
                u.GetCursorPos(ctypes.byref(pt))
                hdc = u.GetDC(0)
                col = gdi.GetPixel(hdc, pt.x, pt.y)
                u.ReleaseDC(0, hdc)
                if 0 <= col != 0xFFFFFFFF:
                    self._add_color_rgb(col & 0xFF, (col >> 8) & 0xFF,
                                        (col >> 16) & 0xFF)
                    self._save()
                break
            was_down = down
            time.sleep(0.02)
        self._eyedropping = False

    # --------------------------------------------------------------- hotkeys
    def _register_hotkeys(self) -> None:
        self._clear_hotkeys()
        try:
            import keyboard
            self._hotkey_handles.append(keyboard.add_hotkey(
                self.state.get("hotkey_show_panel"),
                lambda: webbrowser.open(self.url)))
            self._hotkey_handles.append(keyboard.add_hotkey(
                self.state.get("hotkey_toggle_pull"),
                lambda: self.state.set("pull_enabled",
                                       not self.state.get("pull_enabled"))))
            # Instant-click trigger, only while in "trigger" click mode. The
            # trigger can be a keyboard key/combo or a mouse button.
            trig = self.state.get("hotkey_trigger")
            if self.state.get("click_mode") == "trigger" and trig:
                mouse_btn = MOUSE_TOKENS.get(trig)
                if mouse_btn:
                    import mouse
                    self._mouse_hooks.append(mouse.on_button(
                        self.controller.trigger_click,
                        buttons=(mouse_btn,), types=("down",)))
                else:
                    self._hotkey_handles.append(keyboard.add_hotkey(
                        trig, self.controller.trigger_click))
        except Exception:
            pass

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
        try:
            import mouse
            for h in self._mouse_hooks:
                try:
                    mouse.unhook(h)
                except (KeyError, ValueError):
                    pass
        except Exception:
            pass
        self._mouse_hooks = []

    def _record_hotkey(self) -> Optional[str]:
        try:
            import keyboard
            return keyboard.read_hotkey(suppress=False)
        except Exception:
            return None

    # ----------------------------------------------------------- API payload
    def state_payload(self) -> dict:
        with self.state.lock:
            s = self.state
            return {
                "pull_enabled": s.pull_enabled,
                "auto_click_enabled": s.auto_click_enabled,
                "click_mode": s.click_mode,
                "smoothness": s.smoothness,
                "max_speed": s.max_speed,
                "target_ema": s.target_ema,
                "dwell_ms": s.dwell_ms,
                "click_radius": s.click_radius,
                "click_repeat": s.click_repeat,
                "click_interval_ms": s.click_interval_ms,
                "sensitivity": s.sensitivity,
                "min_contour_area": s.min_contour_area,
                "detect_scale": s.detect_scale,
                "roi_x": s.roi_x, "roi_y": s.roi_y,
                "roi_w": s.roi_w, "roi_h": s.roi_h,
                "detect_thin_border": s.detect_thin_border,
                "pull_radius": s.pull_radius,
                "show_overlay": s.show_overlay,
                "overlay_radius": s.overlay_radius,
                "suppress_mouse": s.suppress_mouse,
                "lock_target": s.lock_target,
                "snap_to_best": s.snap_to_best,
                "snap_after_ms": s.snap_after_ms,
                "body_part_detection": s.body_part_detection,
                "active_region": s.active_region,
                "regions": REGIONS,
                "colors": [_hsv_to_hex(c) for c in s.colors],
                "capture": {
                    "source": s.capture.source,
                    "monitor": s.capture.monitor,
                    "obs_device_index": s.capture.obs_device_index,
                    "left": s.capture.left, "top": s.capture.top,
                    "width": s.capture.width, "height": s.capture.height,
                },
                "hotkey_show_panel": s.hotkey_show_panel,
                "hotkey_toggle_pull": s.hotkey_toggle_pull,
                "hotkey_trigger": s.hotkey_trigger,
                "fps": s.loop_fps,
                "target_found": s.last_target_found,
                "eyedropping": self._eyedropping,
                "error": self._last_error,
            }

    # Coerce an incoming value to the type of the current field.
    def set_scalar(self, name: str, value) -> None:
        if name == "sensitivity":
            self._apply_sensitivity(int(value))
            self._save()
            return
        with self.state.lock:
            if not hasattr(self.state, name):
                return
            cur = getattr(self.state, name)
            try:
                if isinstance(cur, bool):
                    value = bool(value)
                elif isinstance(cur, int):
                    value = int(value)
                elif isinstance(cur, float):
                    value = float(value)
            except (TypeError, ValueError):
                return
            setattr(self.state, name, value)
        # Changing the click mode changes whether the trigger key is bound.
        if name == "click_mode":
            self._register_hotkeys()
        self._save()

    def do_action(self, data: dict):
        action = data.get("action")
        if action == "toggle_pull":
            self.state.set("pull_enabled", not self.state.get("pull_enabled"))
        elif action == "set_pull":
            self.state.set("pull_enabled", bool(data.get("value")))
        elif action == "set_region":
            r = data.get("region")
            if r in REGIONS:
                self.state.set("active_region", r)
        elif action == "set_source":
            src = data.get("source")
            if src in ("obs", "screen"):
                with self.state.lock:
                    self.state.capture.source = src
        elif action == "add_color":
            rgb = _hex_to_rgb(data.get("hex", ""))
            if rgb:
                self._add_color_rgb(*rgb)
        elif action == "remove_color":
            idx = int(data.get("index", -1))
            with self.state.lock:
                if 0 <= idx < len(self.state.colors):
                    self.state.colors.pop(idx)
        elif action == "clear_colors":
            with self.state.lock:
                self.state.colors.clear()
        elif action == "apply_capture":
            with self.state.lock:
                cap = self.state.capture
                for k in ("monitor", "obs_device_index", "left", "top",
                          "width", "height"):
                    if k in data:
                        try:
                            setattr(cap, k, int(data[k]))
                        except (TypeError, ValueError):
                            pass
        elif action == "apply_roi":
            with self.state.lock:
                for k in ("roi_x", "roi_y", "roi_w", "roi_h"):
                    if k in data:
                        try:
                            setattr(self.state, k, max(0, int(data[k])))
                        except (TypeError, ValueError):
                            pass
        elif action == "apply_hotkeys":
            self.state.set("hotkey_show_panel",
                           data.get("show") or "right shift")
            self.state.set("hotkey_toggle_pull", data.get("pull") or "f8")
            if data.get("trigger") is not None:
                self.state.set("hotkey_trigger", data.get("trigger") or "")
            self._register_hotkeys()
        elif action == "record_hotkey":
            hk = self._record_hotkey()
            return {"hotkey": hk}
        elif action == "eyedrop":
            self._start_eyedrop()
        elif action == "reset_defaults":
            persistence.apply_dict(self.state, persistence.to_dict(AppState()))
            self._register_hotkeys()
        elif action == "quit":
            threading.Timer(0.2, self.stop).start()
            return {"ok": True, "quitting": True}
        self._save()
        return {"ok": True}


# ----------------------------------------------------------------- HTTP glue
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence default stderr logging
        pass

    @property
    def app(self) -> WebApp:
        return self.server.app  # type: ignore[attr-defined]

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(self.app.state_payload())
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            self._json({"ok": False, "error": "bad json"}, 400)
            return
        if self.path == "/api/set":
            self.app.set_scalar(data.get("name"), data.get("value"))
            self._json({"ok": True})
        elif self.path == "/api/action":
            self._json(self.app.do_action(data) or {"ok": True})
        else:
            self._json({"ok": False, "error": "unknown"}, 404)


def _make_server(app: WebApp) -> ThreadingHTTPServer:
    last_err = None
    for port in range(app.port, app.port + 20):
        try:
            httpd = ThreadingHTTPServer((app.host, port), _Handler)
            httpd.app = app  # type: ignore[attr-defined]
            return httpd
        except OSError as exc:
            last_err = exc
            continue
    raise RuntimeError(f"No free port near {app.port}: {last_err}")
