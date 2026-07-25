"""Fast, deterministic convergence tests for CursorGlider.

Guards the regression where a gentle easing setting stalled several pixels short
of the target (sub-pixel steps rounded to zero). No threads, no real cursor.

Every glider here is built with an **explicit** gain curve. A bare
``CursorGlider()`` seeds itself from the machine's real Windows pointer
settings, so tests that used one silently measured whatever the developer's
mouse happened to be set to and would pass or fail depending on the machine.
"""

import math

import cursor_assist.cursor as cur
from cursor_assist.pointer import GainCurve, PointerSettings


def _glider(mult=1.0, enhance=False):
    """A glider whose curve is seeded for a known pointer speed."""
    speed = min(range(1, 21),
                key=lambda s: abs(PointerSettings(speed=s).multiplier - mult))
    return cur.CursorGlider(
        curve=GainCurve(PointerSettings(speed=speed, enhance=enhance)))


def _drive(target, tau, start=(0.0, 0.0), max_speed=6000, hz=240, seconds=3.0):
    pos = [float(start[0]), float(start[1])]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))

    def mv(dx, dy):
        pos[0] += dx
        pos[1] += dy

    cur.move_relative = mv
    g = _glider()
    dt = 1.0 / hz
    for _ in range(int(hz * seconds)):
        g.step(target, dt, tau, max_speed)
    return math.hypot(target[0] - pos[0], target[1] - pos[1])


def test_converges_on_smooth_setting():
    # smoothness 0.35 -> tau ~= 0.107; this setting used to stall ~13 px short.
    assert _drive((600, 0), tau=0.107) <= 1.5


def test_converges_on_max_smoothness():
    assert _drive((480, 300), tau=0.25) <= 1.5


def test_converges_on_snappy_setting():
    assert _drive((-350, 220), tau=0.03) <= 1.5


def test_speed_cap_still_reaches():
    # Tiny speed cap: must still fully arrive, just slower.
    assert _drive((900, 0), tau=0.05, max_speed=1500, seconds=4.0) <= 1.5


def _drive_gain(target, os_gain, tau=0.06, hz=240, seconds=3.0,
                seed=None, enhance=False, track=False, **kw):
    """Drive the glider through an OS that scales every move by ``os_gain``.

    Mimics the Windows pointer-speed slider, which is why a low-sensitivity
    setup under-reaches: a requested 10 px move lands 10*gain px. ``seed``
    is what the glider is *told* the setting is, defaulting to the truth —
    pass something else to test recovery from a wrong starting assumption.
    """
    pos = [0.0, 0.0]
    path = [0.0]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))

    def mv(dx, dy):
        path[0] += math.hypot(dx, dy) * os_gain
        pos[0] += dx * os_gain
        pos[1] += dy * os_gain

    cur.move_relative = mv
    g = _glider(os_gain if seed is None else seed, enhance)
    dt = 1.0 / hz
    for _ in range(int(hz * seconds)):
        g.step(target, dt, tau, 6000, **kw)
    err = math.hypot(target[0] - pos[0], target[1] - pos[1])
    if track:
        return err, g, path[0] / math.hypot(*target)
    return err, g


def test_reaches_target_on_a_low_sensitivity_mouse():
    """A low OS pointer gain must not stop the pull reaching the target."""
    err, g = _drive_gain((700, 0), os_gain=0.25)
    assert err <= 2.0
    assert 0.18 <= g.gain <= 0.35        # the real ratio, not a guess


def test_reaches_target_on_a_high_sensitivity_mouse():
    """The mirror case, which the scalar-gain version could not hold.

    At 3.5x one device unit is 3.5 px, so the pointer cannot be placed more
    precisely than that — but it must *settle* there rather than stepping back
    and forth across the target forever.
    """
    err, g, waste = _drive_gain((700, 300), os_gain=3.5, track=True)
    assert err <= 1.2 * g.resolution_px
    assert waste <= 1.10                 # almost no travel spent hunting


def test_high_sensitivity_does_not_oscillate_on_arrival():
    """Once arrived, nothing more should be emitted."""
    pos = [700.0, 300.0]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))
    moves = []

    def mv(dx, dy):
        moves.append((dx, dy))
        pos[0] += dx * 3.5
        pos[1] += dy * 3.5

    cur.move_relative = mv
    g = _glider(3.5)
    for _ in range(240):
        g.step((700, 300), 1 / 240, 0.06, 6000)
    assert not [m for m in moves if m != (0, 0)]


def test_sensitivity_is_seeded_from_the_os_not_learned_from_scratch():
    """The first move must already be the right size at either extreme.

    Learning from a fixed 1.0 start meant the opening moves were wrong by the
    full ratio — at 3.5x the first correction overshot by 250% — for as long as
    convergence took.
    """
    for mult in (0.25, 1.0, 3.5):
        g = _glider(mult)
        # 100 px wanted -> the units asked for must deliver about 100 px.
        ux, uy = g.curve.units_for(100.0), 0.0
        assert 80 <= ux * mult <= 125, (mult, ux)


def test_recovers_when_the_seeded_setting_is_wrong():
    """A wrong seed (shared PC, mouse DPI profile) must self-correct."""
    err, g = _drive_gain((700, 0), os_gain=0.25, seed=3.5, seconds=3.0)
    assert err <= 3.0
    assert g.gain <= 0.6                 # learned its way down from 3.5


def test_low_sensitivity_is_not_slower_than_normal():
    """Compensation must restore speed, not just eventual accuracy.

    Without it, every step lands short and the pull crawls — the "works but
    feels sluggish on low sensitivity" complaint.
    """
    def travel_after(os_gain, seconds):
        pos = [0.0, 0.0]
        cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))
        cur.move_relative = lambda dx, dy: (
            pos.__setitem__(0, pos[0] + dx * os_gain),
            pos.__setitem__(1, pos[1] + dy * os_gain))
        g = _glider(os_gain)
        for _ in range(int(240 * seconds)):
            g.step((900, 0), 1 / 240, 0.06, 6000)
        return pos[0]

    normal = travel_after(1.0, 0.35)
    for low in (0.25, 0.0625):
        assert travel_after(low, 0.35) >= 0.7 * normal


def test_manual_extra_gain_reaches_further_not_shorter():
    """The trim slider must move in the direction its label promises.

    It divided the requested distance instead of multiplying it, so turning up
    the control documented as "raise this if it still under-reaches" made it
    under-reach further.
    """
    def travel(gain_scale):
        pos = [0.0, 0.0]
        cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))
        cur.move_relative = lambda dx, dy: (pos.__setitem__(0, pos[0] + dx),
                                            pos.__setitem__(1, pos[1] + dy))
        g = _glider(1.0)
        for _ in range(24):              # a tenth of a second, still en route
            g.step((3000, 0), 1 / 240, 0.06, 60000, gain_scale=gain_scale)
        return pos[0]

    assert travel(2.0) > travel(1.0) > travel(0.5)


def test_precision_zone_slows_near_the_target_but_still_arrives():
    far, _ = _drive_gain((600, 0), os_gain=1.0, precision_px=0)
    near, _ = _drive_gain((600, 0), os_gain=1.0, precision_px=150,
                          precision_slow=0.2)
    assert far <= 2.0 and near <= 2.0        # both fully arrive

    # Within the zone the pointer must move more gently than without it.
    def speed_at(dist, precision_px):
        pos = [600.0 - dist, 0.0]
        cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))
        moved = []
        cur.move_relative = lambda dx, dy: (moved.append(dx),
                                            pos.__setitem__(0, pos[0] + dx))
        _glider().step((600, 0), 1 / 240, 0.06, 6000,
                                precision_px=precision_px, precision_slow=0.2)
        return sum(moved)

    assert speed_at(40, 150) < speed_at(40, 0)


def test_acceleration_limit_caps_a_sudden_fling():
    """One bad target frame must not produce an instant huge jump."""
    pos = [0.0, 0.0]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))
    steps = []
    cur.move_relative = lambda dx, dy: (steps.append(abs(dx)),
                                        pos.__setitem__(0, pos[0] + dx))
    g = _glider()
    dt = 1 / 240
    # Target 2000 px away, snappy tau: without a limit the first step is huge.
    g.step((2000, 0), dt, 0.02, 100000, max_accel_px_s2=50000)
    first = steps[0] if steps else 0
    assert first <= 50000 * dt * dt + 2      # bounded by the accel ceiling


def test_no_movement_when_already_on_target():
    pos = [200.0, 200.0]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))
    moves = []
    cur.move_relative = lambda dx, dy: (moves.append((dx, dy)),
                                        pos.__setitem__(0, pos[0] + dx),
                                        pos.__setitem__(1, pos[1] + dy))
    _glider().step((200, 200), 1 / 240, 0.1, 6000)
    # Already within lock distance: at most a zero move.
    assert all(m == (0, 0) for m in moves)
