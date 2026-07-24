"""Live-motion simulations: every tracking feature against the real engine.

Each test drives the actual detection + movement threads against a synthetic
scene (see :mod:`simworld`): different shapes, sizes, distances, speeds, lock
stability with distractors, best-coverage snap, and body-part attraction on a
moving humanoid figure. These run in real time — the whole module takes ~30 s.
"""

import math
import statistics

import cv2
import numpy as np
import pytest

from simworld import RED, H, SimWorld, W, make_state


def mean_err(samples):
    return statistics.mean(samples)


def p95(samples):
    xs = sorted(samples)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))]


# ------------------------------------------------- static: shapes and sizes

SHAPES = [
    ("disc r=8",   lambda f, x, y: cv2.circle(f, (x, y), 8, RED, -1),   6.0),
    ("disc r=18",  lambda f, x, y: cv2.circle(f, (x, y), 18, RED, -1),  6.0),
    ("disc r=40",  lambda f, x, y: cv2.circle(f, (x, y), 40, RED, -1),  6.0),
    ("square 36",  lambda f, x, y: cv2.rectangle(f, (x - 18, y - 18),
                                                 (x + 18, y + 18), RED, -1), 6.0),
    ("triangle",   lambda f, x, y: cv2.fillPoly(
        f, [np.array([[x, y - 24], [x - 22, y + 14], [x + 22, y + 14]])], RED), 9.0),
    ("ring r=30",  lambda f, x, y: cv2.circle(f, (x, y), 30, RED, 4),   8.0),
]

@pytest.mark.parametrize("name,painter,tol", SHAPES,
                         ids=[s[0] for s in SHAPES])
def test_static_shape_lands_on_center(name, painter, tol):
    tx, ty = 700, 480
    def draw(f, t):
        painter(f, tx, ty)
    with SimWorld(draw) as world:
        world.x, world.y = 120.0, 120.0       # start far away
        st = make_state(detect_thin_border=("ring" in name))
        world.run(st, dur=1.3)
        # Triangle aim is its centroid, slightly below the bbox middle.
        cx, cy = (tx, ty + 1.3) if "triangle" in name else (tx, ty)
        err = math.hypot(world.x - cx, world.y - cy)
    assert err <= tol, f"{name}: final error {err:.1f}px > {tol}px"


def test_static_from_various_distances():
    """Close, medium, and across-the-screen starts must all converge."""
    tx, ty = 820, 560
    def draw(f, t):
        cv2.circle(f, (tx, ty), 18, RED, -1)
    for sx, sy in [(780, 540), (500, 300), (30, 30)]:
        with SimWorld(draw) as world:
            world.x, world.y = float(sx), float(sy)
            world.run(make_state(), dur=1.3)
            err = math.hypot(world.x - tx, world.y - ty)
        assert err <= 6.0, f"start ({sx},{sy}): error {err:.1f}px"


# --------------------------------------------------------- moving: speeds

@pytest.mark.parametrize("speed,bound_mean,bound_p95",
                         [(200, 20, 30), (500, 32, 48), (900, 60, 90)])
def test_linear_tracking_speeds(speed, bound_mean, bound_p95):
    y = H / 2
    def pos(t):
        # Bounce between x=180 and x=W-180 at constant speed.
        span = W - 360
        d = (speed * t) % (2 * span)
        return (180 + d, y) if d <= span else (180 + 2 * span - d, y)
    def draw(f, t):
        x, _ = pos(t)
        cv2.circle(f, (int(x), int(y)), 18, RED, -1)
    with SimWorld(draw) as world:
        world.x, world.y = pos(0)[0], y
        errs = world.run(
            make_state(), dur=3.4,
            sample=lambda now: math.hypot(world.x - pos(world.t())[0],
                                          world.y - y),
            warmup=1.0)
    assert mean_err(errs) <= bound_mean, f"mean {mean_err(errs):.1f}"
    assert p95(errs) <= bound_p95, f"p95 {p95(errs):.1f}"


def test_circular_tracking_fast():
    rx, ry, period = 240, 160, 2.5   # ~600 px/s at the fastest point
    def pos(t):
        return (W / 2 + rx * math.cos(2 * math.pi * t / period),
                H / 2 + ry * math.sin(2 * math.pi * t / period))
    def draw(f, t):
        x, y = pos(t)
        cv2.circle(f, (int(x), int(y)), 18, RED, -1)
    with SimWorld(draw) as world:
        world.x, world.y = W / 2, H / 2
        errs = world.run(
            make_state(), dur=4.0,
            sample=lambda now: math.hypot(world.x - pos(world.t())[0],
                                          world.y - pos(world.t())[1]),
            warmup=1.2)
    assert mean_err(errs) <= 30, f"mean {mean_err(errs):.1f}"


# ------------------------------------------- lock stability with distractor

def test_lock_stays_on_moving_target_near_distractor():
    """A second same-color blob nearby must not steal or split the aim."""
    dx, dy = 700, 350          # static distractor
    def pos(t):                # target orbits left of the distractor
        return (420 + 80 * math.cos(2 * math.pi * t / 5.0),
                350 + 80 * math.sin(2 * math.pi * t / 5.0))
    def draw(f, t):
        x, y = pos(t)
        cv2.circle(f, (int(x), int(y)), 18, RED, -1)
        cv2.circle(f, (dx, dy), 18, RED, -1)
    with SimWorld(draw) as world:
        world.x, world.y = 430.0, 350.0    # start near the target
        def sample(now):
            x, y = pos(world.t())
            return (math.hypot(world.x - x, world.y - y),
                    math.hypot(world.x - dx, world.y - dy))
        pairs = world.run(make_state(), dur=3.2, sample=sample, warmup=0.8)
    d_target = [p[0] for p in pairs]
    d_distr = [p[1] for p in pairs]
    assert mean_err(d_target) <= 30, f"target dist {mean_err(d_target):.1f}"
    # Never parks on (or between) the distractor: always clearly closer to
    # the locked target than to the decoy.
    assert min(d_distr) > 60, f"came {min(d_distr):.1f}px from distractor"


# ---------------------------------------------------- best-coverage snap

def test_snap_moves_aim_onto_ink_of_concave_shape():
    """L-shape: the centroid is off the ink; the snap must land the cursor
    on actual color once it has rested on target."""
    def draw(f, t):
        cv2.rectangle(f, (600, 200), (640, 400), RED, -1)   # vertical bar
        cv2.rectangle(f, (600, 360), (800, 400), RED, -1)   # horizontal bar
    with SimWorld(draw) as world:
        world.x, world.y = 620.0, 300.0     # start on the ink
        st = make_state(snap_to_best=True, snap_after_ms=400,
                        overlay_radius=40)
        world.run(st, dur=2.0)
        fx = world.frame_now()
        ix, iy = int(round(world.x)), int(round(world.y))
        on_ink = bool(fx[max(0, iy - 3):iy + 4, max(0, ix - 3):ix + 4, 2].any())
    assert on_ink, f"cursor settled off the ink at ({ix},{iy})"


# ------------------------------------------- body-part attraction, moving

def _humanoid(f, x, top):
    """Filled humanoid: head disc, torso, two legs. ~66 wide, ~185 tall."""
    cv2.circle(f, (int(x), int(top + 16)), 16, RED, -1)             # head
    cv2.rectangle(f, (int(x - 22), int(top + 28)),
                  (int(x + 22), int(top + 105)), RED, -1)           # torso
    cv2.rectangle(f, (int(x - 20), int(top + 105)),
                  (int(x - 4), int(top + 185)), RED, -1)            # L leg
    cv2.rectangle(f, (int(x + 4), int(top + 105)),
                  (int(x + 20), int(top + 185)), RED, -1)           # R leg

@pytest.mark.parametrize("region,y_lo,y_hi",
                         [("Head", 0, 55), ("Torso", 30, 115),
                          ("Feet", 140, 190)])
def test_body_attraction_on_moving_figure(region, y_lo, y_hi):
    top = 250.0
    def figx(t):
        span = 400.0
        d = (250.0 * t) % (2 * span)   # 250 px/s bounce
        return 300 + (d if d <= span else 2 * span - d)
    def draw(f, t):
        _humanoid(f, figx(t), top)
    with SimWorld(draw) as world:
        world.x, world.y = figx(0), top + 90
        st = make_state(body_part_detection=True, active_region=region,
                        part_attraction=1.0, min_contour_area=120)
        ys = world.run(
            st, dur=3.0,
            sample=lambda now: (world.y - top,
                                abs(world.x - figx(world.t()))),
            warmup=1.2)
    rel_y = [s[0] for s in ys]
    x_err = [s[1] for s in ys]
    assert y_lo <= mean_err(rel_y) <= y_hi, \
        f"{region}: aim rode at y={mean_err(rel_y):.0f} (want {y_lo}..{y_hi})"
    assert mean_err(x_err) <= 45, f"{region}: x lag {mean_err(x_err):.0f}px"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
