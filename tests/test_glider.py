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
