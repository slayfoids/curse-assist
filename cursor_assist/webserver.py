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
from . import __version__
from .config import REGIONS, AppState, ColorTarget, tolerances_for
from .controller import AssistController
from . import holdwatch
from .holdwatch import HoldWatcher
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

# Mouse event types that all mean "the button went down".
#
# The `mouse` package rewrites a press landing within the system double-click
# time (~500 ms) of the *previous button event* -- including the preceding
# release -- into a "double" event instead of a "down" (see its
# ``_winmouse.py``). Listening for "down" alone therefore dropped every quick
# re-press: the hold button worked once and then looked completely dead.
PRESS_TYPES = ("down", "double")

# What the hold/trigger recorder will accept, in priority order. Mouse buttons
# come first so a side-button press is reported as MB4 rather than as whatever
# modifier happened to be held at the same time.
_RECORDABLE = {
    "MB4": 0x05, "MB5": 0x06, "MMB": 0x04, "RMB": 0x02,
    "right ctrl": 0xA3, "left ctrl": 0xA2,
    "right shift": 0xA1, "left shift": 0xA0,
    "right alt": 0xA5, "left alt": 0xA4,
    "space": 0x20, "tab": 0x09, "caps lock": 0x14,
    **{f"f{n}": 0x70 + n - 1 for n in range(1, 13)},
    **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
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
                 port: int = 8756, open_browser: bool = True,
                 has_overlay: bool = True):
        self.state = state
        self.host = host
        self.port = port
        self.open_browser = open_browser
        # Whether something else is running a Tk main loop that can service a
        # region-pick request (the crosshair overlay does).
        self._has_overlay = has_overlay
        self.url = f"http://{host}:{port}/"

        self.controller = AssistController(
            state, on_dwell_start=self._beep, on_click=self._beep,
            on_error=self._on_error)
        self._last_error = ""
        self._eyedropping = False
        self._eyedrop_thread: Optional[threading.Thread] = None
        self._hotkey_handles: list = []
        self._mouse_hooks: list = []
        self._key_hooks: list = []   # keyboard.hook_key handles
        self._hold = HoldWatcher(self._set_pull)
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
            # flush: stdout is block-buffered when redirected to a file, which
            # is exactly when someone is capturing output to report a problem.
            print(f"Curse v{__version__} — UI running at {self.url}", flush=True)
            print("Press Ctrl+C here to quit (or use Quit in the page).",
                  flush=True)
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

    def _set_pull(self, value: bool) -> None:
        """Single gateway for turning the pull on/off: state + audio cue.

        Every path (toggle hotkey, hold button press/release, UI button, API)
        goes through here so the on/off beeps always fire exactly once per
        actual change.
        """
        value = bool(value)
        with self.state.lock:
            if self.state.pull_enabled == value:
                return
            self.state.pull_enabled = value
        self._pull_cue(value)

    def _pull_cue(self, on: bool) -> None:
        """Two high-pitched beeps when activated, two low-pitched when off."""
        if not self.state.get("audio_cues"):
            return
        def _play():
            try:
                import time as _t
                import winsound
                freq = 1400 if on else 440
                for _ in range(2):
                    winsound.Beep(freq, 90)
                    _t.sleep(0.045)
            except Exception:
                pass
        threading.Thread(target=_play, name="pull-cue", daemon=True).start()

    def _on_error(self, exc: Exception) -> None:
        self._last_error = str(exc)

    def _save(self) -> None:
        try:
            persistence.save(self.state)
        except OSError:
            pass

    def _apply_sensitivity(self, tol: int) -> None:
        h_tol, s_tol, v_tol = tolerances_for(tol)
        with self.state.lock:
            self.state.sensitivity = tol
            for c in self.state.colors:
                c.h_tol = h_tol
                c.s_tol = s_tol
                c.v_tol = v_tol

    def _add_color_rgb(self, r, g, b) -> None:
        h, s, v = _rgb_to_cv_hsv(r, g, b)
        h_tol, s_tol, v_tol = tolerances_for(int(self.state.get("sensitivity")))
        with self.state.lock:
            self.state.colors.append(ColorTarget(
                h=h, s=s, v=v, h_tol=h_tol, s_tol=s_tol, v_tol=v_tol))

    # ------------------------------------------------------------ screenshot
    def screenshot_png(self) -> Optional[bytes]:
        """One frame of the current capture source, encoded as PNG.

        Backs the panel's "Screenshot" picker: freezing a frame and clicking
        the exact pixel is far easier than chasing a live eyedropper, which
        needs the colour to still be on screen *and* the hand steady enough
        to click it — the precise thing this tool exists to help with.
        """
        import cv2
        from .capture import make_capture
        cap = None
        try:
            cap = make_capture(self.state.snapshot().capture)
            frame = cap.grab()
            if frame is None:
                return None
            ok, buf = cv2.imencode(".png", frame)
            return buf.tobytes() if ok else None
        except Exception as exc:
            self._on_error(exc)
            return None
        finally:
            if cap is not None:
                try:
                    cap.close()
                except Exception:
                    pass

    # --------------------------------------------------------- region picker
    def _start_region_pick(self, what: str) -> None:
        """Ask for the drag-a-box screen picker.

        The overlay owns Tk's main loop and watches this flag, because Tk only
        builds windows on the thread running its loop and this request arrives
        on an HTTP worker. With ``--no-overlay`` there is no such loop, so a
        private one is started on its own thread instead.
        """
        if self.state.get("region_pick"):
            return          # one already in flight
        self.state.set("region_pick", what)
        if self._has_overlay:
            return
        threading.Thread(target=self._pick_region_standalone, args=(what,),
                         name="region-pick", daemon=True).start()

    def _pick_region_standalone(self, what: str) -> None:
        from . import region_picker
        titles = {"roi": "Drag to set the detection area",
                  "capture": "Drag to set the capture region"}
        try:
            box = region_picker.pick_blocking(titles.get(what, ""))
        except Exception as exc:
            self._on_error(exc)
            box = None
        with self.state.lock:
            self.state.region_pick = ""
            if box is not None:
                region_picker.apply_region(self.state, what, box)
        if box is not None:
            self._save()

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
        """(Re)bind every global hotkey.

        Each binding gets its own guard. Previously a single ``try`` wrapped
        the lot, so one unusable key name -- or a missing optional package --
        silently took every *later* binding down with it, and the swallowed
        exception left nothing to diagnose from.
        """
        self._clear_hotkeys()
        try:
            import keyboard
        except Exception as exc:
            self._last_error = f"hotkeys unavailable ({exc})"
            return

        def _bind(fn, what: str) -> None:
            try:
                fn()
            except Exception as exc:
                self._last_error = f"could not bind {what} ({exc})"

        _bind(lambda: self._hotkey_handles.append(keyboard.add_hotkey(
            self.state.get("hotkey_show_panel"),
            lambda: webbrowser.open(self.url))), "the show-panel hotkey")
        _bind(lambda: self._hotkey_handles.append(keyboard.add_hotkey(
            self.state.get("hotkey_toggle_pull"),
            lambda: self._set_pull(not self.state.get("pull_enabled")))),
            "the toggle hotkey")

        # Hold-to-activate: the pull is live only while the chosen key or
        # mouse button is physically held down. This polls the real key state
        # rather than hooking events — see :mod:`holdwatch` for why the hook
        # route kept failing silently.
        if self.state.get("activation_mode") == "hold":
            hold = self.state.get("hotkey_hold")
            if not self._hold.start(hold):
                self._last_error = (
                    f"hold button {hold!r} not recognised — pick one of the "
                    f"preset buttons, or record a key")

        # Instant-click trigger, only while in "trigger" click mode. The
        # trigger can be a keyboard key/combo or a mouse button.
        trig = self.state.get("hotkey_trigger")
        if self.state.get("click_mode") == "trigger" and trig:
            mouse_btn = MOUSE_TOKENS.get(trig)
            if mouse_btn:
                _bind(lambda: self._hook_mouse_trigger(mouse_btn),
                      f"trigger button {trig}")
            else:
                _bind(lambda: self._hotkey_handles.append(
                    keyboard.add_hotkey(trig, self.controller.trigger_click)),
                    f"trigger hotkey {trig}")

    def _hook_mouse_trigger(self, button: str) -> None:
        import mouse
        self._mouse_hooks.append(mouse.on_button(
            self.controller.trigger_click,
            buttons=(button,), types=PRESS_TYPES))

    def _clear_hotkeys(self) -> None:
        self._hold.stop()
        try:
            import keyboard
            for h in self._hotkey_handles:
                try:
                    keyboard.remove_hotkey(h)
                except (KeyError, ValueError):
                    pass
            for h in self._key_hooks:
                try:
                    keyboard.unhook(h)
                except (KeyError, ValueError):
                    pass
        except Exception:
            pass
        self._hotkey_handles = []
        self._key_hooks = []
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

    def _record_hotkey(self, mouse_ok: bool = False) -> Optional[str]:
        """Capture the next key (or button) the user presses.

        ``keyboard.read_hotkey`` only ever sees the *keyboard*. Pressing a
        mouse button left it blocking, and it then returned whichever key was
        pressed next — typically the Windows key or Alt-Tab as the user went
        back to the browser window. That is the "binds to the Windows key at
        random" bug: it was recording the wrong event entirely, several
        seconds late.

        With ``mouse_ok`` the capture polls real key state instead, so mouse
        buttons and keyboard keys are recorded through one identical path.
        """
        if not mouse_ok:
            try:
                import keyboard
                return keyboard.read_hotkey(suppress=False)
            except Exception:
                return None

        import time as _t
        # Wait for everything to be released first, so the click that pressed
        # "Record" in the browser isn't itself captured.
        deadline = _t.monotonic() + 1.5
        while _t.monotonic() < deadline:
            if not any(holdwatch.is_down(v) for v in _RECORDABLE.values()):
                break
            _t.sleep(0.01)
        deadline = _t.monotonic() + 10.0
        while _t.monotonic() < deadline:
            if holdwatch.is_down(0x1B):       # Esc cancels
                return None
            for token, vk in _RECORDABLE.items():
                if holdwatch.is_down(vk):
                    return token
            _t.sleep(0.008)
        return None

    # ----------------------------------------------------------- API payload
    def state_payload(self) -> dict:
        with self.state.lock:
            s = self.state
            return {
                "version": __version__,
                "pull_enabled": s.pull_enabled,
                "activation_mode": s.activation_mode,
                "hotkey_hold": s.hotkey_hold,
                "audio_cues": s.audio_cues,
                "auto_click_enabled": s.auto_click_enabled,
                "click_mode": s.click_mode,
                "smoothness": s.smoothness,
                "max_speed": s.max_speed,
                "target_ema": s.target_ema,
                "motion_response": s.motion_response,
                "jitter_floor": s.jitter_floor,
                "precision_px": s.precision_px,
                "precision_slow": s.precision_slow,
                "max_accel": s.max_accel,
                "pointer_gain": s.pointer_gain,
                "pointer_gain_auto": s.pointer_gain_auto,
                "pointer_gain_measured": s.pointer_gain_measured,
                "dwell_ms": s.dwell_ms,
                "click_radius": s.click_radius,
                "click_repeat": s.click_repeat,
                "click_interval_ms": s.click_interval_ms,
                "sensitivity": s.sensitivity,
                "min_contour_area": s.min_contour_area,
                "detect_scale": s.detect_scale,
                "scan_fps": s.scan_fps,
                "display_hz": s.display_hz,
                "roi_x": s.roi_x, "roi_y": s.roi_y,
                "roi_w": s.roi_w, "roi_h": s.roi_h,
                "show_roi": s.show_roi,
                "region_pick": s.region_pick,
                "mask_coverage": s.mask_coverage,
                "pointer_profile": s.pointer_profile,
                "pointer_resolution": s.pointer_resolution,
                "detect_thin_border": s.detect_thin_border,
                "pull_radius": s.pull_radius,
                "show_overlay": s.show_overlay,
                "show_aim_line": s.show_aim_line,
                "overlay_radius": s.overlay_radius,
                "adaptive_roi": s.adaptive_roi,
                "roi_following": s.roi_following,
                "dwell_grace_ms": s.dwell_grace_ms,
                "suppress_mouse": s.suppress_mouse,
                "lock_target": s.lock_target,
                "snap_to_best": s.snap_to_best,
                "snap_after_ms": s.snap_after_ms,
                "snap_radius": s.snap_radius,
                "body_part_detection": s.body_part_detection,
                "active_region": s.active_region,
                "part_attraction": s.part_attraction,
                "regions": REGIONS,
                "configs": persistence.list_configs(),
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
        if name == "activation_mode":
            if value not in ("toggle", "hold"):
                return
            self.state.set("activation_mode", value)
            # Entering/leaving hold mode: start from OFF for safety, then
            # rebind so the hold hooks appear/disappear.
            self._set_pull(False)
            self._register_hotkeys()
            self._save()
            return
        if name == "hotkey_hold":
            self.state.set("hotkey_hold", str(value))
            self._register_hotkeys()
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
            self._set_pull(not self.state.get("pull_enabled"))
        elif action == "set_pull":
            self._set_pull(bool(data.get("value")))
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
        elif action == "pick_region":
            what = data.get("what", "roi")
            if what not in ("roi", "capture"):
                what = "roi"
            self._start_region_pick(what)
            return {"ok": True, "picking": what}
        elif action == "apply_hotkeys":
            self.state.set("hotkey_show_panel",
                           data.get("show") or "right shift")
            self.state.set("hotkey_toggle_pull", data.get("pull") or "f8")
            if data.get("trigger") is not None:
                self.state.set("hotkey_trigger", data.get("trigger") or "")
            self._register_hotkeys()
        elif action == "record_hotkey":
            hk = self._record_hotkey(mouse_ok=bool(data.get("mouse")))
            return {"hotkey": hk}
        elif action == "eyedrop":
            self._start_eyedrop()
        elif action == "save_config":
            code = persistence.save_config(self.state,
                                           str(data.get("name", "")))
            return {"ok": True, "code": code}
        elif action == "load_config":
            ok = persistence.load_config(self.state, str(data.get("code", "")))
            if ok:
                self._register_hotkeys()
                self._save()
            return {"ok": ok}
        elif action == "delete_config":
            return {"ok": persistence.delete_config(str(data.get("code", "")))}
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
        elif self.path.startswith("/api/screenshot"):
            png = self.app.screenshot_png()
            if png is None:
                self._json({"ok": False, "error": "capture failed"}, 503)
            else:
                self._send(200, png, "image/png")
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
