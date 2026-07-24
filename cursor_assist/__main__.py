"""Entry point: ``python -m cursor_assist``.

Builds the shared state and launches the control UI. By default this is the
sleek local web panel (opens in your browser); ``--tk`` uses the legacy Tkinter
panel instead. The vision/pull engine runs in background threads either way.
"""

from __future__ import annotations

import argparse
import sys

from . import persistence
from .config import AppState


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="cursor_assist",
        description="Color-based cursor assist accessibility tool (Windows).",
    )
    p.add_argument("--tk", action="store_true",
                   help="Use the legacy Tkinter panel instead of the web UI.")
    p.add_argument("--port", type=int, default=8756,
                   help="Port for the local web UI (default 8756).")
    p.add_argument("--no-browser", action="store_true",
                   help="Don't auto-open the browser; just print the URL.")
    # Defaults are None so we can tell an explicit flag from an omitted one and
    # only override the persisted settings when the user actually passed it.
    p.add_argument("--source", choices=["screen", "obs"], default=None,
                   help="Capture from the desktop (mss) or the OBS virtual cam.")
    p.add_argument("--monitor", type=int, default=None,
                   help="mss monitor index for full-screen capture.")
    p.add_argument("--region", type=int, nargs=4, default=None,
                   metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"),
                   help="Capture only this desktop region (screen source).")
    p.add_argument("--obs-index", type=int, default=None,
                   help="cv2.VideoCapture index of the OBS virtual camera.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    if not sys.platform.startswith("win"):
        print("This tool uses the Windows SendInput API and only runs on "
              "Windows.", file=sys.stderr)
        return 2

    args = _parse_args(argv)
    state = AppState()
    persistence.load(state)  # saved settings first...

    with state.lock:  # ...then explicit CLI flags win over them
        if args.source is not None:
            state.capture.source = args.source
        if args.monitor is not None:
            state.capture.monitor = args.monitor
        if args.obs_index is not None:
            state.capture.obs_device_index = args.obs_index
        if args.region is not None:
            state.capture.left, state.capture.top, \
                state.capture.width, state.capture.height = args.region

    if args.tk:
        from .gui import ControlPanel
        ControlPanel(state, load_settings=False).run()
    else:
        from .webserver import WebApp
        WebApp(state, port=args.port,
               open_browser=not args.no_browser).serve_blocking()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
