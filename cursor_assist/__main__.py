"""Entry point: ``python -m cursor_assist``.

Parses a few optional capture flags, builds the shared state, and launches the
control panel. The GUI owns the main thread; the detection/pull loop runs in a
background thread started by the panel.
"""

from __future__ import annotations

import argparse
import sys

from .config import AppState
from .gui import ControlPanel


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="cursor_assist",
        description="Color-based cursor assist accessibility tool (Windows).",
    )
    p.add_argument("--source", choices=["screen", "obs"], default="screen",
                   help="Capture from the desktop (mss) or the OBS virtual cam.")
    p.add_argument("--monitor", type=int, default=1,
                   help="mss monitor index for full-screen capture.")
    p.add_argument("--region", type=int, nargs=4,
                   metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"),
                   help="Capture only this desktop region (screen source).")
    p.add_argument("--obs-index", type=int, default=0,
                   help="cv2.VideoCapture index of the OBS virtual camera.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    if not sys.platform.startswith("win"):
        print("This tool uses the Windows SendInput API and only runs on "
              "Windows.", file=sys.stderr)
        return 2

    args = _parse_args(argv)
    state = AppState()
    with state.lock:
        state.capture.source = args.source
        state.capture.monitor = args.monitor
        state.capture.obs_device_index = args.obs_index
        if args.region:
            state.capture.left, state.capture.top, \
                state.capture.width, state.capture.height = args.region

    ControlPanel(state).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
