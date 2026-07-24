"""Screen / OBS capture.

Two interchangeable sources, both returning frames as BGR ``numpy`` arrays:

* ``ScreenCapture`` grabs a desktop region with ``mss`` (fast, no compositor).
* ``OBSCapture`` reads the OBS Virtual Camera through ``cv2.VideoCapture``.

Only screen-pixel input is used; nothing reads process memory or hooks OBS
beyond consuming its virtual-camera video output.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from .config import CaptureConfig


class ScreenCapture:
    """Region/full-screen capture backed by ``mss``."""

    def __init__(self, cfg: CaptureConfig):
        import mss  # imported lazily so OBS-only users need not install extras

        self._sct = mss.mss()
        self._cfg = cfg
        self._region = self._resolve_region(cfg)

    def _resolve_region(self, cfg: CaptureConfig) -> dict:
        if cfg.width > 0 and cfg.height > 0:
            return {
                "left": cfg.left,
                "top": cfg.top,
                "width": cfg.width,
                "height": cfg.height,
            }
        # Fall back to a whole monitor.
        mon = self._sct.monitors[cfg.monitor]
        return {
            "left": mon["left"],
            "top": mon["top"],
            "width": mon["width"],
            "height": mon["height"],
        }

    @property
    def origin(self) -> Tuple[int, int]:
        """Top-left of the captured region in absolute desktop pixels."""
        return self._region["left"], self._region["top"]

    def grab(self) -> np.ndarray:
        shot = self._sct.grab(self._region)
        # mss gives BGRA; drop alpha to BGR for OpenCV.
        frame = np.asarray(shot)[:, :, :3]
        return np.ascontiguousarray(frame)

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass


class OBSCapture:
    """Reads the OBS Virtual Camera as an ordinary video device."""

    def __init__(self, cfg: CaptureConfig):
        import cv2

        self._cap = cv2.VideoCapture(cfg.obs_device_index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Could not open OBS virtual camera at index "
                f"{cfg.obs_device_index}. Is 'Start Virtual Camera' running in OBS?"
            )
        # OBS output is composited at desktop scale; capture maps 1:1 to that
        # composited canvas, not the raw desktop, so origin is (0, 0).
        self._origin = (0, 0)

    @property
    def origin(self) -> Tuple[int, int]:
        return self._origin

    def grab(self) -> Optional[np.ndarray]:
        ok, frame = self._cap.read()
        if not ok:
            return None
        return frame  # already BGR

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass


def make_capture(cfg: CaptureConfig):
    """Factory that returns the capture backend named by ``cfg.source``."""
    if cfg.source == "obs":
        return OBSCapture(cfg)
    return ScreenCapture(cfg)
