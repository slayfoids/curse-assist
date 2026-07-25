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
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

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
# With velocity feed-forward in the movement loop (see TargetTracker.velocity)
# the steady-state lag this used to paper over is gone at the source, so the
# lead only has to cover how *stale* a detection is by the time it is acted on
# — roughly half a scan interval plus processing. Leaving it sized for the old
# job made the two compensate for the same lag twice, which showed up as
# overshoot at direction changes: 30 px of lag and 36 px of overshoot against a
# 1000 px/s target, against 8.9 / 13 once rebalanced.
LEAD_BASE = 0.012
LEAD_FRAMES = 0.5
LEAD_MIN_S = 0.02
LEAD_MAX_S = 0.14
LEAD_DEADZONE = 60.0
LEAD_MAX = 140.0      # absolute cap (px) so a fast flick can't overshoot wildly
LEAD_WARMUP = 6       # frames of continuous tracking before lead kicks in

# Travelling vs vibrating.
#
# A velocity estimate says how fast the target point is moving, not whether it
# is going anywhere. Those come apart badly when detection makes the point
# oscillate — a figure that keeps breaking into two pieces behind an occlusion
# alternates between the whole centroid and a fragment's, which reads as
# ~900 px/s from something standing still. Everything downstream then treats it
# as a sprinting target: the lead throws the pointer *past* it (measured landing
# 23 px outside the range of both real positions), the adaptive cutoff stops
# filtering just when filtering is most needed, and the pursuit easing snaps
# tight. That is the "lock makes it spasm" report.
#
# Straightness — net displacement over distance travelled, across a short
# window — separates the two. Genuine travel scores near 1. Vibration scores
# near 0 because the path cancels itself out. It is measured over a window
# rather than frame to frame, which is what makes it robust: a single direction
# change during real travel barely moves it.
STRAIGHT_WINDOW = 10      # samples
STRAIGHT_MIN = 0.35       # at or below this, the target is not going anywhere
STRAIGHT_FULL = 0.70      # at or above this, treat the motion as real travel

# --- Aim commitment ---------------------------------------------------------
# The filters above all key off *speed*: they smooth hard when the target point
# is slow and open up when it is fast. Detection noise defeats that, because
# noise looks fast. On an animating figure with ragged edges the aim point
# wandered 9 px and changed 20 times a second while the figure stood still, and
# no combination of smoothness, steadiness, jitter floor or precision zone
# brought it below 6 px — the knobs cannot fix it because they are adjusting
# the wrong variable.
#
# What separates noise from movement here is *displacement*, not speed: noise
# stays within a bounded distance of where the target really is and averages to
# zero, while movement accumulates. So the final aim point is filtered on how
# far the candidate has strayed rather than how fast it is going — creeping
# while the candidate stays inside a small zone, following immediately once it
# leaves. That is what makes the aim commit to a pixel and hold it, instead of
# redecorating it twenty times a second.
COMMIT_TAU_HOLD = 0.90    # s; how slowly the aim drifts inside the zone
COMMIT_TAU_FOLLOW = 0.025  # s; how quickly it follows once the zone is left
# Above this travel speed the target is genuinely going somewhere and the zone
# is faded out entirely, so committing never costs tracking.
COMMIT_FADE_SPEED = 240.0

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
LOCK_MATCH_MAX_MULT = 3.0  # hard ceiling on how far the match radius may open
                           # up for a stale lock, as a multiple of its base

# How long the aim keeps pointing at a target that stopped being detected.
#
# This exists so a colour that drops out for a frame or two does not cause the
# lock to churn. It was a flat 0.40 s, which turned out to be the single
# largest source of latency in the whole pipeline: measured end to end, the
# pointer took **418 ms** to react to a target moving somewhere new, against
# 10 ms with the lock switched off, and the delay tracked this constant
# exactly. Worse, what the user sees is the aim freezing on empty screen and
# then snapping across — which reads as the assist spasming, not as lag.
#
# So it is split by what is actually on screen. With nothing else detected the
# target probably *is* flickering and there is nothing better to aim at anyway,
# so a short hold is free. With other candidates visible, holding a ghost is a
# refusal to look at evidence that is right there, and the hold is barely
# longer than one frame.
LOCK_GRACE_S = 0.18       # nothing else detected
LOCK_GRACE_BUSY_S = 0.06  # other candidates are visible

# Max-coverage snap.
SNAP_OFF_GRACE_S = 0.30  # brief mask flicker doesn't reset the on-color timer
SNAP_MAX_KERNEL_R = 16   # downscale the search so the kernel stays this small

# The snap circle is sized from the target itself when left on "auto". Its job
# is to find the meatiest part *of the thing being aimed at* — a torso rather
# than a trailing limb — so it scales with how thick the target actually is. A
# circle any larger stops measuring the target and starts measuring the
# neighbourhood; any smaller and it just tracks the noisiest pixel.
#
# Thickness is taken as 2 x area / perimeter, which is the width of the shape's
# limbs rather than the size of the box around it. The bounding box is a poor
# stand-in for anything concave: an L-shaped target 200 px across is made of
# 40 px-wide bars, and sizing the circle from the box gave one three times too
# big — large enough that every position scored alike and the aim stayed in the
# empty inside corner.
SNAP_AUTO_THICK = 0.45   # of the target's limb thickness
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
    if bounds is not None:
        # Search the whole target, not a window around its centroid. For a
        # concave shape the centroid can sit well off the ink — the inside
        # corner of an L is the standard case — and a window sized from the
        # radius then never reaches the dense part it exists to find. The
        # answer is clamped to the target either way, so there is nothing to
        # gain by looking at less of it.
        bx0, by0, bw, bh = bounds
        m = radius * SNAP_BOUND_MARGIN
        x0 = max(0, int(bx0 - m))
        y0 = max(0, int(by0 - m))
        x1 = min(w, int(bx0 + bw + m) + 1)
        y1 = min(h, int(by0 + bh + m) + 1)
    else:
        search = radius * SNAP_SEARCH_MARGIN + 4
        x0 = max(0, int(cx - search))
        x1 = min(w, int(cx + search) + 1)
        y0 = max(0, int(cy - search))
        y1 = min(h, int(cy + search) + 1)
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
        # Recent raw positions, for telling travel apart from vibration.
        self._recent: Deque[np.ndarray] = deque(maxlen=STRAIGHT_WINDOW)
        self._straight = 1.0
        # Where the previous frame's pick landed, so "is this the same target"
        # can be answered when the lock is switched off too.
        self._last_pick: Optional[Tuple[float, float]] = None
        # Committed aim point, and how far the candidate may stray before it
        # is believed. 0 disables commitment entirely.
        self._committed: Optional[np.ndarray] = None
        self._commit_px = 0.0
        self._dt = 1.0 / 60.0                         # smoothed detection interval
        self._track_frames = 0                        # frames on the same target
        # Target lock (screen space so it survives detect-scale changes).
        self._lock: Optional[Tuple[float, float]] = None
        self._lock_seen = 0.0                         # last time the lock matched
        self._matched = False                         # a real blob, this frame
        # Bounding box of the blob matched *this* frame, in detection coords.
        # The snap is confined to it, so it can never re-aim onto a neighbour.
        self._lock_box: Optional[Tuple[int, int, int, int]] = None
        # The matched shape itself, so the snap circle can be sized from how
        # thick the target actually is rather than from the box around it.
        self._lock_shape: Optional[DetectedShape] = None
        # Max-coverage snap.
        self._on_color_since: Optional[float] = None
        self._off_color_at: Optional[float] = None
        self._snap_radius_used = 0.0                  # last radius, for the UI

    def set_ema(self, ema: float) -> None:
        self._ema = max(0.0, min(1.0, ema))

    def set_tuning(self, response: float = 1.0, floor: float = 1.0) -> None:
        self._response = max(0.05, min(4.0, response))
        self._floor = max(0.05, min(4.0, floor))

    def velocity(self) -> Tuple[float, float]:
        """Target velocity in px/s, gated by straightness (0 when vibrating).

        Handed to the movement loop as a feed-forward term. An easing
        controller is a proportional one, and a proportional controller
        *cannot* sit on a moving target: against something travelling at a
        constant speed it settles at a fixed distance behind, proportional to
        its own time constant. Raising the speed or acceleration limits does
        not touch that — they cap how fast it may correct, not how large the
        steady-state error is — which is why the pointer trailed a moving
        target however high those were set. Driving the pointer at the
        target's own speed removes the error instead of chasing it.
        """
        gate = (self._straight - STRAIGHT_MIN) / (STRAIGHT_FULL - STRAIGHT_MIN)
        g = max(0.0, min(1.0, gate))
        return float(self._vel[0]) * g, float(self._vel[1]) * g

    def matched(self) -> bool:
        """Whether a real blob was identified this frame.

        Distinct from "a target was returned": during the grace a remembered
        position is still published, and a caller steering a follow window has
        to know the difference or it will keep centring on a memory.
        """
        return self._matched

    def raw_speed(self) -> float:
        """Speed of the target *point*, including detection vibration."""
        return float(np.hypot(self._vel[0], self._vel[1]))

    def straightness(self) -> float:
        """0 = vibrating on the spot, 1 = travelling in a consistent direction."""
        return self._straight

    def speed(self) -> float:
        """How fast the target is actually *travelling*, in px/s.

        Damped by straightness, so a point that is merely jittering does not
        read as a fast-moving target. Everything that reacts to speed — the
        lead, the adaptive cutoff, the pursuit easing, the follow-window size,
        the lock's match radius — wants this rather than the raw figure, since
        all of them are decisions about a target that is going somewhere.
        """
        gate = (self._straight - STRAIGHT_MIN) / (STRAIGHT_FULL - STRAIGHT_MIN)
        return self.raw_speed() * max(0.0, min(1.0, gate))

    def reset(self) -> None:
        self._smoothed = None
        self._vel = np.zeros(2)
        self._prev_raw = None
        self._prev_t = None
        self._track_frames = 0
        self._lock = None
        self._lock_box = None
        self._lock_shape = None
        self._last_pick = None
        self._committed = None
        self._recent.clear()
        self._straight = 1.0
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
        windowed: bool = False,
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
            self._lock_shape = None
            self._matched = False
            # An empty *follow window* is not evidence that the target left the
            # screen — only that it left this box, which is the ordinary way a
            # moving target behaves. Treating the two the same is what made the
            # aim sit on empty screen for the full grace before catching up.
            target_det = self._hold_lock_det(now, ox, oy, scale,
                                             alternatives=windowed)
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
            self._lock_shape = None
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
        self._last_pick = (float(raw[0]), float(raw[1]))
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
                          s.area, s.bbox, s))

        self._lock_box = None
        self._lock_shape = None
        self._matched = False

        # 1) Try to re-identify the locked target among this frame's blobs.
        if lock_enabled and self._lock is not None:
            lx = (self._lock[0] - ox) * scale
            ly = (self._lock[1] - oy) * scale
            best = None
            best_d = None
            for (px, py, diag, _area, bbox, shape) in cands:
                d = math.hypot(px - lx, py - ly)
                if best_d is None or d < best_d:
                    best_d, best = d, (px, py, diag, bbox, shape)
            if best is not None:
                # Allow more drift for big blobs, fast targets, and stale locks.
                # The allowance for a stale lock is capped: it grew without
                # bound while the target was missing, so after a fraction of a
                # second any blob anywhere on screen satisfied it and was
                # adopted as "the same target" — a re-identification error
                # dressed up as continuous motion.
                base_r = max(LOCK_MATCH_MIN * scale, 0.8 * best[2])
                stale = min(max(0.0, now - self._lock_seen), LOCK_GRACE_S)
                match_r = min(base_r + self.speed() * scale * stale * 1.5,
                              base_r * LOCK_MATCH_MAX_MULT)
                in_fov = (r_det is None or
                          math.hypot(best[0] - cx, best[1] - cy) <= 1.3 * r_det)
                if best_d <= match_r and in_fov:
                    self._lock = (ox + best[0] * inv, oy + best[1] * inv)
                    self._lock_seen = now
                    self._lock_box = best[3]
                    self._lock_shape = best[4]
                    self._matched = True
                    # A match that had to stretch a long way is a different
                    # object, not the same one moving — say so, so the
                    # smoothing restarts instead of feeding the jump to the
                    # velocity estimate and the lead.
                    stretched = best_d > base_r
                    return (best[0], best[1]), stretched
            # Lock missed this frame. Other blobs are on screen, so this is the
            # short hold — long enough to ride out a dropped frame, not long
            # enough to keep aiming at a memory.
            held = self._hold_lock_det(now, ox, oy, scale, alternatives=True)
            if held is not None:
                return held, False
            self._lock = None

        # 2) No lock: acquire inside the FOV, scored by distance discounted by
        # blob size — between a speck and a real target at similar distance,
        # the real target wins, but a much closer blob still wins outright.
        best = None
        best_s = None
        best_diag = 0.0
        for (px, py, diag, area, bbox, shape) in cands:
            d = math.hypot(px - cx, py - cy)
            if r_det is not None and d > r_det:
                continue
            score = d / (max(area, 1.0) ** 0.15)
            if best_s is None or score < best_s:
                best_s, best, best_diag = score, (px, py, bbox, shape), diag
        if best is None:
            return None, False
        self._lock_box = best[2]
        self._lock_shape = best[3]
        self._matched = True
        if lock_enabled:
            self._lock = (ox + best[0] * inv, oy + best[1] * inv)
            self._lock_seen = now
        # Is this the same thing we were aiming at last frame?
        #
        # This used to answer "yes, always new" unconditionally, which is the
        # path every frame takes with the lock switched *off* — so with lock
        # off the smoothing, the deadband and the lead were reset on every
        # single frame and never did anything at all. The pointer was riding
        # raw detection output.
        switched = True
        if self._last_pick is not None:
            near = max(LOCK_MATCH_MIN * scale, 0.8 * best_diag)
            switched = math.hypot(best[0] - (self._last_pick[0] - ox) * scale,
                                  best[1] - (self._last_pick[1] - oy) * scale
                                  ) > near
        return (best[0], best[1]), switched

    def _hold_lock_det(self, now, ox, oy, scale, alternatives: bool = False):
        """Last known lock position (detection coords) while within grace.

        ``alternatives`` says whether this frame detected anything else. If it
        did, the hold is cut short — continuing to aim at a remembered position
        while a real target sits on screen is what made the assist feel like it
        had frozen.
        """
        grace = LOCK_GRACE_BUSY_S if alternatives else LOCK_GRACE_S
        if self._lock is None or (now - self._lock_seen) > grace:
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
            r_screen = SNAP_AUTO_MIN
            shape = self._lock_shape
            if shape is not None:
                perim = float(cv2.arcLength(shape.contour, True))
                if perim > 1e-6:
                    thick_det = 2.0 * float(shape.area) / perim
                    r_screen = (SNAP_AUTO_THICK * thick_det
                                / max(scale, 1e-6))
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

    # ----------------------------------------------------------- straightness
    def _update_straightness(self, raw: np.ndarray) -> None:
        """Net displacement over distance travelled, across a short window.

        Near 1 while the target crosses the screen; near 0 while the detection
        point flips between two places, because the path cancels itself out.
        Held at 1 until the window fills so a fresh target is never treated as
        vibrating on the strength of two samples.
        """
        self._recent.append(raw.copy())
        if len(self._recent) < 4:
            self._straight = 1.0
            return
        pts = list(self._recent)
        path = 0.0
        for a, b in zip(pts, pts[1:]):
            path += float(np.hypot(b[0] - a[0], b[1] - a[1]))
        net = float(np.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]))
        # Below a pixel or so of total movement there is nothing to judge, and
        # the ratio would be noise divided by noise.
        self._straight = 1.0 if path < 2.0 else max(0.0, min(1.0, net / path))

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
            self._recent.clear()
            self._recent.append(raw.copy())
            self._straight = 1.0
            self._committed = raw.copy()
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
        self._update_straightness(raw)

        speed = self.speed()
        dt_f = dt if dt > 1e-3 else self._dt

        # Deadband: a static target that wiggles by a pixel of detection noise
        # holds perfectly still instead of trembling. Still routed through
        # commitment, so the committed point cannot drift away from what is
        # being returned and jump when the deadband next opens.
        delta = raw - self._smoothed
        if float(np.hypot(delta[0], delta[1])) <= DEADBAND_PX \
                and speed < LEAD_DEADZONE:
            self._vel *= 0.8
            out = self._commit(self._smoothed, dt_f, speed)
            return int(round(out[0])), int(round(out[1]))

        # One-euro follow: the cutoff rises with target speed, so a resting
        # target is smoothed hard (steady, precise) and a fast one is followed
        # almost immediately (little lag) — without the caller choosing.
        cutoff = ((MIN_CUTOFF_BASE + self._ema * MIN_CUTOFF_SPAN) / self._floor
                  + CUTOFF_BETA * speed * self._response)
        self._smoothed = self._smoothed + _alpha(dt_f, cutoff) * (
            raw - self._smoothed)

        # Lead the target when it's really moving — and only after the velocity
        # estimate has warmed up on this target, so a fresh lock never flings.
        #
        # ``speed`` here is already gated by straightness, so a target that is
        # vibrating rather than travelling gets no lead at all. That is the
        # fix for the lock spasm: an oscillating detection point read as
        # ~900 px/s and the lead threw the pointer 23 px beyond the range of
        # both positions it was actually alternating between.
        out = self._smoothed
        if speed > LEAD_DEADZONE and self._track_frames >= LEAD_WARMUP:
            lead_time = min(LEAD_MAX_S,
                            max(LEAD_MIN_S, LEAD_BASE + LEAD_FRAMES * self._dt))
            lead = self._vel * lead_time
            n = float(np.hypot(lead[0], lead[1]))
            if n > LEAD_MAX:
                lead = lead * (LEAD_MAX / n)
            out = self._smoothed + lead

        out = self._commit(out, dt_f, speed)
        return int(round(out[0])), int(round(out[1]))

    # ------------------------------------------------------------- commitment
    def _commit(self, candidate: np.ndarray, dt: float,
                speed: float) -> np.ndarray:
        """Hold a decided aim point until the target has actually moved.

        Filters on how far the candidate has strayed rather than how fast it is
        travelling — see the notes by :data:`COMMIT_TAU_HOLD`. Inside the zone
        the committed point creeps, so a slow genuine drift is still followed
        and the aim never sticks permanently to a stale spot; outside it, it
        follows at once.
        """
        zone = self._commit_px
        if zone <= 0.0:
            self._committed = candidate.copy()
            return candidate
        # A target that is really travelling needs no help deciding.
        fade = max(0.0, 1.0 - speed / COMMIT_FADE_SPEED)
        zone *= fade
        if self._committed is None or zone <= 0.0:
            self._committed = candidate.copy()
            return candidate
        err = candidate - self._committed
        d = float(np.hypot(err[0], err[1]))
        tau = COMMIT_TAU_HOLD if d <= zone else COMMIT_TAU_FOLLOW
        self._committed = self._committed + err * _alpha(dt, 1.0 /
                                                         (2.0 * math.pi * tau))
        return self._committed

    def set_commit_px(self, px: float) -> None:
        self._commit_px = max(0.0, float(px))
