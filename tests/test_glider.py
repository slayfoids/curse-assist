"""Fast, deterministic convergence tests for CursorGlider.

Guards the regression where a gentle easing setting stalled several pixels short
of the target (sub-pixel steps rounded to zero). No threads, no real cursor.
"""

import math

import cursor_assist.cursor as cur


def _drive(target, tau, start=(0.0, 0.0), max_speed=6000, hz=240, seconds=3.0):
    pos = [float(start[0]), float(start[1])]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))

    def mv(dx, dy):
        pos[0] += dx
        pos[1] += dy

    cur.move_relative = mv
    g = cur.CursorGlider()
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


def _drive_gain(target, os_gain, tau=0.06, hz=240, seconds=3.0, **kw):
    """Drive the glider through an OS that scales every move by ``os_gain``.

    Mimics the Windows pointer-speed slider / "enhance pointer precision",
    which is why a low-sensitivity setup under-reaches: a requested 10 px move
    lands 10*gain px.
    """
    pos = [0.0, 0.0]
    cur.get_cursor_pos = lambda: (int(round(pos[0])), int(round(pos[1])))

    def mv(dx, dy):
        pos[0] += dx * os_gain
        pos[1] += dy * os_gain

    cur.move_relative = mv
    g = cur.CursorGlider()
    dt = 1.0 / hz
    for _ in range(int(hz * seconds)):
        g.step(target, dt, tau, 6000, **kw)
    return math.hypot(target[0] - pos[0], target[1] - pos[1]), g


def test_reaches_target_on_a_low_sensitivity_mouse():
    """A low OS pointer gain must not stop the pull reaching the target."""
    err, g = _drive_gain((700, 0), os_gain=0.35)
    assert err <= 2.0
    # ...and the gain was actually learned, not just brute-forced by retrying.
    assert 0.25 <= g.gain <= 0.5


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
        g = cur.CursorGlider()
        for _ in range(int(240 * seconds)):
            g.step((900, 0), 1 / 240, 0.06, 6000)
        return pos[0]

    normal = travel_after(1.0, 0.35)
    low = travel_after(0.35, 0.35)
    assert low >= 0.7 * normal


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
        cur.CursorGlider().step((600, 0), 1 / 240, 0.06, 6000,
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
    g = cur.CursorGlider()
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
    cur.CursorGlider().step((200, 200), 1 / 240, 0.1, 6000)
    # Already within lock distance: at most a zero move.
    assert all(m == (0, 0) for m in moves)
