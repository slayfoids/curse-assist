"""Target selection, locking, and jitter smoothing.

Turns a frame's detected contours + the active region into a single screen-space
target point. Three layers of stability:

* **Target lock** — once a blob is chosen it stays the target until it actually
  disappears (with a short grace period), instead of re-picking the nearest blob
  every frame. Without this, several same-color blobs made the nearest-pick
  flip-flop each frame: the smoothed point averaged out to the middle of the
  group ("equal pull") and the velocity estimator saw the flips as violent
  motion, flinging the cursor around (the random "spasms").
* **Teleport guard + deadband** — a raw target jump too fast to be physical
  resets velocity/smoothing instead of feeding the lead predictor; sub-2px
  detection noise is ignored entirely so a still target is rock steady.
* **Max-coverage snap** — after the cursor has been on the target color for a
  while, aim at the pixel where a circle of the configured size covers the most
  target color, instead of the blob's bbox center.

An exponential moving average is applied to the *target* (not the cursor) so
noisy detection doesn't make the pull twitch frame to frame.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

import cv2

from .detection import DetectedShape
from .segmentation import contour_points_in_region, segment_regions

# Motion prediction. A moving target is only *known* as of the last detection
# frame, so the pointer trails by roughly the detection interval plus smoothing.
# We predict ahead by (LEAD_FRAMES x measured detection interval), which
# auto-scales with frame rate: more lead when detection is slow, less when fast.
# A static target is below LEAD_DEADZONE and gets zero prediction, so precision
# on a still target is never affected.
LEAD_BASE = 0.02
LEAD_FRAMES = 1.8
LEAD_MIN_S = 0.02
LEAD_MAX_S = 0.14
LEAD_DEADZONE = 60.0
LEAD_MAX = 140.0      # absolute cap (px) so a fast flick can't overshoot wildly
LEAD_WARMUP = 6       # frames of continuous tracking before lead kicks in

# --- Adaptive smoothing (one-euro) ------------------------------------------
# Jitter and lag pull in opposite directions: smoothing hard kills detection
# noise on a resting target but drags behind a moving one, and a single fixed
# blend has to pick one of those to be bad at. The one-euro filter (Casiez et
# al. 2012) varies its cutoff with the target's own speed, so a still target is
# filtered heavily and a fast one is barely filtered at all.
#
# It is also derived from *elapsed time* rather than applied once per frame.
# The old fixed per-frame blend was frame-rate dependent: identical settings
# smoothed roughly twice as hard at 30 fps as at 60, so the feel drifted with
# whatever the capture source and CPU were doing.
MIN_CUTOFF_BASE = 0.8    # Hz at steadiness 0 — very calm when still
MIN_CUTOFF_SPAN = 4.5    # extra Hz at steadiness 1
CUTOFF_BETA = 0.013      # Hz gained per px/s of target speed
VEL_CUTOFF_HZ = 6.0      # cutoff of the velocity estimator itself

# Stability guards.
#
# A raw jump can mean two very different things: a genuinely fast target, or a
# blob re-identification error / scene cut. Speed alone can't tell them apart —
# judging on speed alone made a target crossing the screen quickly look like a
# teleport, and tracking reset itself mid-flight, every frame. So a jump only
# counts as a teleport if it is *also* somewhere the current velocity did not
# predict: real motion stays consistent with its own velocity, a re-id error
# lands somewhere unrelated.
TELEPORT_SPEED = 3000.0       # px/s; above this a jump becomes suspicious...
TELEPORT_RESIDUAL_PX = 160.0  # ...and a teleport only if it also misses the
                              # velocity-predicted position by this much
TELEPORT_HARD_PX = 400.0      # a single-frame jump this big is always a cut
DEADBAND_PX = 2.0        # ignore raw wiggle below this on a static target


def _alpha(dt: float, cutoff_hz: float) -> float:
    """One-euro blend factor for an elapsed time and a cutoff frequency.

    Because it is built from ``dt``, the resulting smoothing is the same at any
    frame rate — the thing the old fixed-alpha blend got wrong.
    """
    tau = 1.0 / (2.0 * math.pi * max(cutoff_hz, 1e-3))
    return 1.0 / (1.0 + tau / max(dt, 1e-6))

# Target lock.
LOCK_MATCH_MIN = 70.0    # screen px; base radius for re-identifying the lock
LOCK_GRACE_S = 0.40      # keep aiming at a vanished target this long before
                         # releasing the lock and picking a new one

# Max-coverage snap.
SNAP_OFF_GRACE_S = 0.30  # brief mask flicker doesn't reset the on-color timer
SNAP_MAX_KERNEL_R = 16   # downscale the search so the kernel stays this small

# The snap circle is sized from the target itself when left on "auto". Its job
# is to find the meatiest part *of the thing being aimed at* — a torso rather
# than a trailing limb — so it scales with the blob's narrow dimension. A circle
# any larger stops measuring the target and starts measuring the neighbourhood.
SNAP_AUTO_FRAC = 0.32    # of the blob's shorter side
SNAP_AUTO_MIN = 7        # px, screen space
SNAP_AUTO_MAX = 70

# How far outside the locked blob the snap may look and land. The search needs a
# little margin so a circle can sit over an edge, but the *result* is clamped
# into the blob: refining the aim within the current target is the entire point,
# and any answer outside it is a re-target the lock explicitly forbids.
SNAP_SEARCH_MARGIN = 1.0   # x radius
SNAP_BOUND_MARGIN = 0.35   # x radius

# A snap only means something if some placements are better than others. When
# the circle swallows the whole search region every position scores alike, the
# arg-max is decided by floating-point noise, and the "best" spot it reports is
# an artefact — measured as a constant ~8 px diagonal bias while target-follow
# was on. Below this spread the snap declines to move the aim at all.
SNAP_MIN_CONTRAST = 0.06   # (max - min) / max of the coverage score

_kernel_cache: Dict[int, np.ndarray] = {}


def _circle_kernel(r: int) -> np.ndarray:
    k = _kernel_cache.get(r)
    if k is None:
        d = 2 * r + 1
        k = np.zeros((d, d), dtype=np.float32)
        cv2.circle(k, (r, r), r, 1.0, -1)
        _kernel_cache[r] = k
    return k


def best_circle_center(
    mask: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    bounds: Optional[Tuple[float, float, float, float]] = None,
) -> Optional[Tuple[float, float]]:
    """Center of the ``radius`` circle that covers the most mask pixels.

    Searches a window around ``(cx, cy)`` (all in mask/detection coordinates).
    The search runs on a downscaled crop so even large circles stay cheap. Ties
    and near-ties are broken toward the current position so the snap point
    doesn't oscillate between equally-good centers.

    ``bounds`` is an optional ``(x, y, w, h)`` box the search and the answer are
    both confined to — normally the locked blob. Without it the coverage
    optimum is free to be a *different* target: with the shipped default the
    circle was as wide as the whole field of view, so on two figures 220 px
    apart the aim settled 47 px off the locked one, and on some spacings landed
    between the two, on neither. Confining it makes the snap what it claims to
    be, a refinement of the aim inside the current target.
    """
    h, w = mask.shape[:2]
    if h == 0 or w == 0 or radius <= 0:
        return None
    search = radius * SNAP_SEARCH_MARGIN + 4
    x0 = max(0, int(cx - search))
    x1 = min(w, int(cx + search) + 1)
    y0 = max(0, int(cy - search))
    y1 = min(h, int(cy + search) + 1)
    if bounds is not None:
        bx0, by0, bw, bh = bounds
        m = radius * SNAP_BOUND_MARGIN
        x0 = max(x0, int(bx0 - m))
        y0 = max(y0, int(by0 - m))
        x1 = min(x1, int(bx0 + bw + m) + 1)
        y1 = min(y1, int(by0 + bh + m) + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = mask[y0:y1, x0:x1]

    ds = max(1.0, radius / SNAP_MAX_KERNEL_R)
    sw = max(2, int(round((x1 - x0) / ds)))
    sh = max(2, int(round((y1 - y0) / ds)))
    small = cv2.resize(crop, (sw, sh), interpolation=cv2.INTER_AREA)
    rr = max(1, int(round(radius / ds)))
    # A kernel that covers the whole search region can only produce a flat
    # score, so there is no "best" position to find — just noise to follow.
    if 2 * rr + 1 >= min(sw, sh) * 2:
        return None
    score = cv2.filter2D((small > 0).astype(np.float32), -1, _circle_kernel(rr),
                         borderType=cv2.BORDER_CONSTANT)
    peak = float(score.max())
    if peak <= 0.0:
        return None
    if (peak - float(score.min())) / peak < SNAP_MIN_CONTRAST:
        return None

    fx = (x1 - x0) / float(sw)
    fy = (y1 - y0) / float(sh)
    px = (cx - x0) / fx
    py = (cy - y0) / fy
    # Hysteresis toward where we already are, expressed as a fraction of the
    # peak per squared cell of distance. The old fixed 0.02 was scored against
    # a coverage peak that grows with the kernel area, so on a large circle the
    # penalty was thousands of times too small to break a tie and the snap
    # point wandered between equally good centers.
    yy, xx = np.mgrid[0:sh, 0:sw]
    reach = max(1.0, float(rr))
    score = score - (0.05 * peak / (reach * reach)) * (
        (xx - px) ** 2 + (yy - py) ** 2)

    by, bx = divmod(int(np.argmax(score)), sw)
    ox = x0 + (bx + 0.5) * fx
    oy = y0 + (by + 0.5) * fy
    if bounds is not None:
        bx0, by0, bw, bh = bounds
        m = radius * SNAP_BOUND_MARGIN
        ox = min(max(ox, bx0 - m), bx0 + bw + m)
        oy = min(max(oy, by0 - m), by0 + bh + m)
    return (ox, oy)


class TargetTracker:
    """Chooses, locks onto, and smooths the point the cursor is pulled toward."""

    def __init__(self, ema: float = 0.35):
        self._ema = ema
        # Multipliers on the two halves of the adaptive cutoff, exposed in the
        # panel so following and steadiness can be traded off independently
        # instead of both riding on one slider.
        self._response = 1.0   # how far the cutoff opens with target speed
        self._floor = 1.0      # how hard a *resting* target is filtered
        self._smoothed: Optional[np.ndarray] = None  # screen-space (x, y) float
        self._vel = np.zeros(2)                       # smoothed velocity px/s
        self._prev_raw: Optional[np.ndarray] = None
        self._prev_t: Optional[float] = None
        self._dt = 1.0 / 60.0                         # smoothed detection interval
        self._track_frames = 0                        # frames on the same target
        # Target lock (screen space so it survives detect-scale changes).
        self._lock: Optional[Tuple[float, float]] = None
        self._lock_seen = 0.0                         # last time the lock matched
        # Bounding box of the blob matched *this* frame, in detection coords.
        # The snap is confined to it, so it can never re-aim onto a neighbour.
        self._lock_box: Optional[Tuple[int, int, int, int]] = None
        # Max-coverage snap.
        self._on_color_since: Optional[float] = None
        self._off_color_at: Optional[float] = None
        self._snap_radius_used = 0.0                  # last radius, for the UI

    def set_ema(self, ema: float) -> None:
        self._ema = max(0.0, min(1.0, ema))

    def set_tuning(self, response: float = 1.0, floor: float = 1.0) -> None:
        self._response = max(0.05, min(4.0, response))
        self._floor = max(0.05, min(4.0, floor))

    def speed(self) -> float:
        """Current estimated target speed in px/s (0 when static)."""
        return float(np.hypot(self._vel[0], self._vel[1]))

    def reset(self) -> None:
        self._smoothed = None
        self._vel = np.zeros(2)
        self._prev_raw = None
        self._prev_t = None
        self._track_frames = 0
        self._lock = None
        self._lock_box = None
        self._on_color_since = None
        self._off_color_at = None

    # ------------------------------------------------------------------ pick
    def pick(
        self,
        shapes: List[DetectedShape],
        figure: Optional[DetectedShape],
        active_region: str,
        cursor_screen: Tuple[int, int],
        capture_origin: Tuple[int, int],
        scale: float = 1.0,
        use_regions: bool = False,
        pull_radius: int = 0,
        mask: Optional[np.ndarray] = None,
        lock_enabled: bool = True,
        snap_enabled: bool = False,
        snap_radius: int = 0,
        snap_after_ms: int = 1000,
        part_attraction: float = 1.0,
    ) -> Optional[Tuple[int, int]]:
        """Return a smoothed screen-space target, or ``None`` if none found.

        Two modes:
        * ``use_regions=False`` (default) — **track one color blob**: lock onto
          the blob nearest the cursor and keep pulling toward *that* blob until
          it disappears (plus a short grace), then re-acquire.
        * ``use_regions=True`` — split the largest figure into body regions and
          only target contour points inside the active region.

        With ``snap_enabled``, once the cursor has sat on the target color for
        ``snap_after_ms``, the aim point becomes the center of the
        ``snap_radius`` circle that covers the most target color.

        Coordinate spaces
        -----------------
        * Contours/mask are in *detection* coordinates, which may be downscaled
          by ``scale`` relative to the captured frame.
        * The cursor and returned target are in absolute *desktop* pixels.
        Mapping: ``detection = (screen - origin) * scale`` and
        ``screen = origin + detection / scale``.
        """
        now = time.perf_counter()
        ox, oy = capture_origin
        inv = 1.0 / scale if scale else 1.0
        # Cursor expressed in detection coordinates.
        cx = (cursor_screen[0] - ox) * scale
        cy = (cursor_screen[1] - oy) * scale
        # FOV radius in detection coordinates (0 = unlimited).
        r_det = pull_radius * scale if pull_radius and pull_radius > 0 else None

        if not shapes:
            # No blob this frame, so nothing for the snap to refine against —
            # a stale box from the previous frame would confine the search to
            # where the target used to be.
            self._lock_box = None
            target_det = self._hold_lock_det(now, ox, oy, scale)
            if target_det is None:
                self.reset()
                return None
            switched = False
        elif not use_regions:
            target_det, switched = self._pick_color(
                shapes, cx, cy, r_det, ox, oy, inv, scale, now, lock_enabled)
            if target_det is None:
                self.reset()
                return None
        else:
            self._lock_box = None      # region aiming does its own placement
            target_det = self._pick_region(
                shapes, figure, active_region, cx, cy, r_det, part_attraction)
            if target_det is None:
                self.reset()
                return None
            switched = False

        # Max-coverage snap: after dwelling on the color, aim at the circle
        # position with the most color instead of the blob center.
        #
        # It only ever runs against the blob picked above (``_lock_box``): a
        # coverage optimum computed over open screen is free to be a different
        # target, which is precisely the drift the lock exists to prevent.
        snap_det_r = 0.0
        if (mask is not None and snap_enabled and not use_regions
                and self._lock_box is not None):
            snap_det_r = self._snap_radius_det(snap_radius, scale)
        if snap_det_r > 0.0:
            if snap_after_ms <= 0:
                # Instant snap: skip the dwell gate entirely. The gate below
                # only starts its timer once the cursor is *resting on* the
                # color — a condition a moving target never lets it reach, so
                # a 0 ms delay would otherwise still never engage on exactly
                # the targets that need it most.
                self._on_color_since = now
                self._off_color_at = None
                engaged = True
            else:
                # "On color" also counts having arrived at the pulled target:
                # for concave shapes the aim point (centroid) can sit just off
                # the ink, and strict mask-under-cursor would then never let
                # the snap engage even though the cursor rests on its target.
                near = (math.hypot(target_det[0] - cx, target_det[1] - cy)
                        <= max(12.0 * scale, 2.0 * snap_det_r))
                self._update_on_color(mask, cx, cy, now, near)
                engaged = (
                    self._on_color_since is not None
                    and (now - self._on_color_since) * 1000.0 >= snap_after_ms)
            if engaged:
                best = best_circle_center(mask, target_det[0], target_det[1],
                                          snap_det_r, bounds=self._lock_box)
                if best is not None:
                    target_det = best

        # Back to screen space (undo the downscale), then smooth.
        raw = np.array([ox + target_det[0] * inv, oy + target_det[1] * inv],
                       dtype=np.float64)
        return self._smooth(raw, now, switched)

    # -------------------------------------------------------------- selection
    def _pick_color(self, shapes, cx, cy, r_det, ox, oy, inv, scale, now,
                    lock_enabled):
        """Blob-center picking with a sticky lock. Returns (target, switched).

        Also records the chosen blob's bounding box in ``_lock_box`` so the
        coverage snap can be confined to the target it is meant to refine.
        """
        cands = []
        for s in shapes:
            bw, bh = s.bbox[2], s.bbox[3]
            cands.append((s.center[0], s.center[1], math.hypot(bw, bh),
                          s.area, s.bbox))

        self._lock_box = None

        # 1) Try to re-identify the locked target among this frame's blobs.
        if lock_enabled and self._lock is not None:
            lx = (self._lock[0] - ox) * scale
            ly = (self._lock[1] - oy) * scale
            best = None
            best_d = None
            for (px, py, diag, _area, bbox) in cands:
                d = math.hypot(px - lx, py - ly)
                if best_d is None or d < best_d:
                    best_d, best = d, (px, py, diag, bbox)
            if best is not None:
                # Allow more drift for big blobs, fast targets, and stale locks.
                match_r = (max(LOCK_MATCH_MIN * scale, 0.8 * best[2])
                           + self.speed() * scale
                           * max(0.0, now - self._lock_seen) * 1.5)
                in_fov = (r_det is None or
                          math.hypot(best[0] - cx, best[1] - cy) <= 1.3 * r_det)
                if best_d <= match_r and in_fov:
                    self._lock = (ox + best[0] * inv, oy + best[1] * inv)
                    self._lock_seen = now
                    self._lock_box = best[3]
                    return (best[0], best[1]), False
            # Lock missed this frame: hold position briefly, then release.
            held = self._hold_lock_det(now, ox, oy, scale)
            if held is not None:
                return held, False
            self._lock = None

        # 2) No lock: acquire inside the FOV, scored by distance discounted by
        # blob size — between a speck and a real target at similar distance,
        # the real target wins, but a much closer blob still wins outright.
        best = None
        best_s = None
        for (px, py, diag, area, bbox) in cands:
            d = math.hypot(px - cx, py - cy)
            if r_det is not None and d > r_det:
                continue
            score = d / (max(area, 1.0) ** 0.15)
            if best_s is None or score < best_s:
                best_s, best = score, (px, py, bbox)
        if best is None:
            return None, False
        self._lock_box = best[2]
        if lock_enabled:
            self._lock = (ox + best[0] * inv, oy + best[1] * inv)
            self._lock_seen = now
        return (best[0], best[1]), True

    def _hold_lock_det(self, now, ox, oy, scale):
        """Last known lock position (detection coords) while within grace."""
        if self._lock is None or (now - self._lock_seen) > LOCK_GRACE_S:
            return None
        return ((self._lock[0] - ox) * scale, (self._lock[1] - oy) * scale)

    def _pick_region(self, shapes, figure, active_region, cx, cy, r_det,
                     attraction=1.0):
        if figure is None:
            return None
        fcx, fcy = figure.center
        # Respect the FOV: ignore a figure whose center is out of range.
        if r_det is not None:
            if (fcx - cx) ** 2 + (fcy - cy) ** 2 > r_det * r_det:
                return None
        region_rect = segment_regions(figure.bbox).get(active_region)
        if region_rect is None:
            return None
        candidates: List[np.ndarray] = []
        for s in shapes:
            pts = contour_points_in_region(s.contour, region_rect)
            if len(pts):
                candidates.append(pts)
        if candidates:
            # Outline strokes cross the region: aim at the centroid of the
            # strokes inside the band (steadier than the single nearest point,
            # which used to hop along the outline as the cursor moved).
            pts = np.vstack(candidates).astype(np.float64)
            part = (float(pts[:, 0].mean()), float(pts[:, 1].mean()))
        else:
            # Filled figure (no edge points inside the region): aim at the
            # center of the region box so the pull still heads to that area.
            rx, ry, rw, rh = region_rect
            part = (rx + rw / 2.0, ry + rh / 2.0)
        # Attraction: 1 = aim exactly at the part; lower blends toward the
        # figure's center of mass for extra steadiness.
        a = max(0.0, min(1.0, attraction))
        return (a * part[0] + (1.0 - a) * fcx,
                a * part[1] + (1.0 - a) * fcy)

    # -------------------------------------------------------- snap geometry
    def _snap_radius_det(self, snap_radius: int, scale: float) -> float:
        """Coverage-circle radius in detection px, ``<= 0`` meaning don't snap.

        ``snap_radius <= 0`` sizes the circle from the locked blob instead of
        from a fixed number. That is the useful default because the right size
        is a property of the target, not of the user's field of view — the
        setting used to borrow the FOV circle (250 px by default), which made
        the "best coverage" position a statement about everything on that part
        of the screen rather than about the target.
        """
        box = self._lock_box
        if box is None:
            return 0.0
        if snap_radius > 0:
            r_screen = float(snap_radius)
        else:
            short_det = max(1.0, float(min(box[2], box[3])))
            r_screen = SNAP_AUTO_FRAC * short_det / max(scale, 1e-6)
            r_screen = max(SNAP_AUTO_MIN, min(SNAP_AUTO_MAX, r_screen))
        self._snap_radius_used = r_screen
        return r_screen * scale

    # ------------------------------------------------------------- snap timer
    def _update_on_color(self, mask, cx, cy, now,
                         near_target: bool = False) -> None:
        h, w = mask.shape[:2]
        ix, iy = int(round(cx)), int(round(cy))
        on = near_target
        if not on and 0 <= ix < w and 0 <= iy < h:
            x0, x1 = max(0, ix - 2), min(w, ix + 3)
            y0, y1 = max(0, iy - 2), min(h, iy + 3)
            on = bool(mask[y0:y1, x0:x1].any())
        if on:
            if self._on_color_since is None:
                self._on_color_since = now
            self._off_color_at = None
        else:
            if self._off_color_at is None:
                self._off_color_at = now
            elif (now - self._off_color_at) > SNAP_OFF_GRACE_S:
                self._on_color_since = None

    # -------------------------------------------------------------- smoothing
    def _smooth(self, raw: np.ndarray, now: float,
                switched: bool) -> Tuple[int, int]:
        # A fresh or switched target starts clean: snap the smoothing there and
        # zero the velocity so no cross-blob "movement" leaks into prediction.
        if (switched or self._smoothed is None or self._prev_raw is None
                or self._prev_t is None):
            self._smoothed = raw.copy()
            self._vel = np.zeros(2)
            self._prev_raw = raw
            self._prev_t = now
            self._track_frames = 0
            return int(round(raw[0])), int(round(raw[1]))

        dt = now - self._prev_t
        if dt > 1e-3:
            inst = (raw - self._prev_raw) / dt
            jump = float(np.hypot(raw[0] - self._prev_raw[0],
                                  raw[1] - self._prev_raw[1]))
            predicted = self._prev_raw + self._vel * dt
            residual = float(np.hypot(raw[0] - predicted[0],
                                      raw[1] - predicted[1]))
            if (jump > TELEPORT_HARD_PX
                    or (jump / dt > TELEPORT_SPEED
                        and residual > TELEPORT_RESIDUAL_PX)):
                # Discontinuity (blob re-id error, scene cut): restart tracking
                # there instead of poisoning the velocity.
                self._vel = np.zeros(2)
                self._smoothed = raw.copy()
                self._track_frames = 0
            else:
                # Time-based velocity estimate. The old fixed 0.85/0.15 blend
                # was a ~100 ms lag at 60 fps, which is a third of a cycle for
                # a target juking twice a second — so the lead it fed pointed
                # at where the target *had* been, and flung the pointer the
                # wrong way on every direction change.
                self._vel += _alpha(dt, VEL_CUTOFF_HZ) * (inst - self._vel)
            if dt < 0.5:  # ignore long stalls when estimating the interval
                self._dt = 0.8 * self._dt + 0.2 * dt
        self._prev_raw = raw
        self._prev_t = now
        self._track_frames += 1

        speed = self.speed()

        # Deadband: a static target that wiggles by a pixel of detection noise
        # holds perfectly still instead of trembling.
        delta = raw - self._smoothed
        if float(np.hypot(delta[0], delta[1])) <= DEADBAND_PX \
                and speed < LEAD_DEADZONE:
            self._vel *= 0.8
            return (int(round(self._smoothed[0])),
                    int(round(self._smoothed[1])))

        # One-euro follow: the cutoff rises with target speed, so a resting
        # target is smoothed hard (steady, precise) and a fast one is followed
        # almost immediately (little lag) — without the caller choosing.
        dt_f = dt if dt > 1e-3 else self._dt
        cutoff = ((MIN_CUTOFF_BASE + self._ema * MIN_CUTOFF_SPAN) / self._floor
                  + CUTOFF_BETA * speed * self._response)
        self._smoothed = self._smoothed + _alpha(dt_f, cutoff) * (
            raw - self._smoothed)

        # Lead the target when it's really moving — and only after the velocity
        # estimate has warmed up on this target, so a fresh lock never flings.
        # Unchanged in strength: the wrong-way lead that used to fling the
        # pointer on a direction change came from the stale velocity feeding
        # it, which is fixed above, not from the lead being too large. Gating
        # it on heading consistency was measured and made every case worse.
        out = self._smoothed
        if speed > LEAD_DEADZONE and self._track_frames >= LEAD_WARMUP:
            lead_time = min(LEAD_MAX_S,
                            max(LEAD_MIN_S, LEAD_BASE + LEAD_FRAMES * self._dt))
            lead = self._vel * lead_time
            n = float(np.hypot(lead[0], lead[1]))
            if n > LEAD_MAX:
                lead = lead * (LEAD_MAX / n)
            out = self._smoothed + lead

        return int(round(out[0])), int(round(out[1]))
