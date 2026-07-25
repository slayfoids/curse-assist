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
        self._follow: Optional[dict] = None

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

    def set_follow(self, box: Optional[Tuple[int, int, int, int]]) -> None:
        """Grab only ``box`` (absolute desktop px) until cleared with ``None``.

        This is where the frame rate actually comes from. Grab cost scales with
        the captured area, so a full-screen grab is the hard ceiling on how
        often the engine can look at anything — on a 1920x1200 desktop it costs
        ~67 ms, capping the whole loop near 15 fps no matter how cheap
        detection is. Grabbing just the window around a locked target drops
        that to ~17 ms, i.e. the display's own refresh rate.
        """
        if box is None:
            self._follow = None
            return
        left, top, w, h = box
        base = self._region
        # Clamp into the configured capture region; an mss grab reaching past
        # the monitor returns black rows rather than failing loudly.
        x0 = max(base["left"], int(left))
        y0 = max(base["top"], int(top))
        x1 = min(base["left"] + base["width"], int(left) + int(w))
        y1 = min(base["top"] + base["height"], int(top) + int(h))
        if x1 - x0 < 16 or y1 - y0 < 16:
            self._follow = None
            return
        self._follow = {"left": x0, "top": y0,
                        "width": x1 - x0, "height": y1 - y0}

    @property
    def base_origin(self) -> Tuple[int, int]:
        """Top-left of the *configured* region, ignoring any follow window."""
        return self._region["left"], self._region["top"]

    @property
    def origin(self) -> Tuple[int, int]:
        """Top-left of the captured region in absolute desktop pixels."""
        r = self._follow or self._region
        return r["left"], r["top"]

    def grab(self) -> np.ndarray:
        shot = self._sct.grab(self._follow or self._region)
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
        self._follow: Optional[Tuple[int, int, int, int]] = None
        self._crop: Optional[Tuple[int, int]] = None

    def set_follow(self, box: Optional[Tuple[int, int, int, int]]) -> None:
        """Crop delivered frames to ``box`` (same absolute coordinates as the
        screen backend — the OBS canvas maps 1:1 onto the desktop, so its
        origin is (0, 0) and the two spaces coincide).

        Unlike the screen backend this cannot make the *capture* cheaper — a
        camera hands over whole frames whatever we do, and its frame rate is
        fixed by OBS. It still cuts the detection work and keeps the aim point
        free of downscale rounding.
        """
        self._follow = box
        self._crop = None

    @property
    def base_origin(self) -> Tuple[int, int]:
        return self._origin

    @property
    def origin(self) -> Tuple[int, int]:
        if self._crop is None:
            return self._origin
        return self._origin[0] + self._crop[0], self._origin[1] + self._crop[1]

    def grab(self) -> Optional[np.ndarray]:
        ok, frame = self._cap.read()
        if not ok:
            return None
        self._crop = None
        if self._follow is not None:
            fh, fw = frame.shape[:2]
            x, y, w, h = (int(v) for v in self._follow)
            x0, y0 = max(0, x - self._origin[0]), max(0, y - self._origin[1])
            x1, y1 = min(fw, x0 + w), min(fh, y0 + h)
            if x1 - x0 >= 16 and y1 - y0 >= 16:
                self._crop = (x0, y0)
                return frame[y0:y1, x0:x1]
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
