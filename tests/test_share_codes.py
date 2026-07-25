"""Share codes: a whole setup carried inside one pasteable string.

A saved config used to be a file on one machine plus a code that only meant
something to the machine that wrote it, so there was no way to hand a setup to
somebody else. These carry the settings themselves, which means they cross
machines — and also that they arrive from outside and cannot be trusted.
"""

import pytest

from cursor_assist import persistence
from cursor_assist.config import AppState, ColorTarget


def _tuned():
    """A state with a spread of non-default settings."""
    s = AppState()
    with s.lock:
        s.smoothness = 0.61
        s.max_speed = 41000
        s.pull_radius = 380
        s.snap_radius = 26
        s.snap_after_ms = 0
        s.sensitivity = 19
        s.click_mode = "trigger"
        s.hotkey_trigger = "MB5"
        s.activation_mode = "hold"
        s.hotkey_hold = "MB4"
        s.body_part_detection = True
        s.active_region = "Head"
        s.precision_px = 90
        s.colors[:] = [ColorTarget(h=5, s=240, v=230, h_tol=9, s_tol=70,
                                   v_tol=60),
                       ColorTarget(h=95, s=200, v=180, h_tol=12, s_tol=80,
                                   v_tol=70)]
        s.capture.left, s.capture.top = 120, 60
        s.capture.width, s.capture.height = 1280, 720
    return s


def test_round_trips_every_setting():
    src = _tuned()
    code = persistence.encode_share(src, "nephew setup")
    dst = AppState()
    assert persistence.apply_share(dst, code) == "nephew setup"
    for f in persistence._SCALAR_FIELDS:
        assert getattr(dst, f) == getattr(src, f), f
    assert len(dst.colors) == 2
    assert (dst.colors[0].h, dst.colors[0].s, dst.colors[0].v) == (5, 240, 230)
    assert dst.colors[1].h_tol == 12
    assert (dst.capture.left, dst.capture.width) == (120, 1280)


def test_import_reproduces_the_sender_not_a_mixture():
    """The receiver's own settings must not survive underneath.

    Only differences from the defaults travel, so anything the receiver had
    changed and the sender had not would otherwise linger and quietly make the
    two setups behave differently.
    """
    src = AppState()
    with src.lock:
        src.smoothness = 0.8          # the only thing the sender changed
    code = persistence.encode_share(src)

    dst = AppState()
    with dst.lock:
        dst.max_speed = 999           # receiver's own tweak, not the sender's
        dst.pull_radius = 42
    assert persistence.apply_share(dst, code) is not None
    assert dst.smoothness == 0.8
    assert dst.max_speed == AppState().max_speed
    assert dst.pull_radius == AppState().pull_radius


def test_code_is_short_enough_to_paste_in_a_chat_message():
    code = persistence.encode_share(_tuned(), "nephew setup")
    assert code.startswith(persistence.SHARE_PREFIX)
    assert len(code) < 700, len(code)
    # A near-default setup should be markedly shorter still.
    assert len(persistence.encode_share(AppState())) < 120


def test_code_survives_whitespace_and_case_from_a_chat_paste():
    code = persistence.encode_share(_tuned())
    mangled = "  " + code[:40] + "\n" + code[40:] + "  \n"
    dst = AppState()
    assert persistence.apply_share(dst, mangled) is not None


def test_truncated_code_is_rejected_not_half_applied():
    """Chat clients wrap and people miss the tail; that must not half-load."""
    code = persistence.encode_share(_tuned())
    dst = AppState()
    before = dst.smoothness
    assert persistence.apply_share(dst, code[:len(code) - 12]) is None
    assert dst.smoothness == before


def test_tampered_code_is_rejected():
    code = persistence.encode_share(_tuned())
    flipped = code[:-6] + ("A" if code[-6] != "A" else "B") + code[-5:]
    assert persistence.decode_share(flipped) is None


@pytest.mark.parametrize("junk", [
    "", "   ", "hello", "CRS-7KQ2XN", "CURSE1-", "CURSE1-!!!!",
    "CURSE1-" + "A" * 40, "not even close",
])
def test_junk_is_rejected_cleanly(junk):
    assert persistence.decode_share(junk) is None
    dst = AppState()
    assert persistence.apply_share(dst, junk) is None


def test_a_local_code_is_not_mistaken_for_a_share_code():
    assert persistence.decode_share("CRS-7KQ2XN") is None


def test_hostile_values_cannot_poison_the_state():
    """These arrive from other people. Wrong types must not reach the loop."""
    dst = AppState()
    good_speed = dst.max_speed
    persistence.apply_dict(dst, {
        "smoothness": "not a number",
        "max_speed": None,
        "pull_radius": [1, 2, 3],
        "click_mode": 12345,           # coerces to a string, harmlessly
        "sensitivity": 21,             # this one is fine and should land
    })
    assert isinstance(dst.smoothness, float)
    assert dst.max_speed == good_speed
    assert isinstance(dst.pull_radius, int)
    assert dst.sensitivity == 21


def test_decompression_is_bounded():
    """A few hundred pasted bytes must not be able to expand into all of RAM."""
    import base64
    import zlib
    bomb = zlib.compress(b"\0" * (4 * 1024 * 1024), 9)
    body = zlib.crc32(b"x").to_bytes(4, "big") + bomb
    code = persistence.SHARE_PREFIX + base64.urlsafe_b64encode(body).decode()
    assert len(code) < 20_000                      # small on the wire
    assert persistence.decode_share(code) is None  # refused, not expanded


def test_share_then_local_save_keeps_the_imported_setup(tmp_path):
    """Importing also stores it locally, so it can be returned to later."""
    src = _tuned()
    code = persistence.encode_share(src, "range setup")
    dst = AppState()
    persistence.apply_share(dst, code)
    saved = persistence.save_config(dst, "range setup", base=tmp_path)
    back = AppState()
    assert persistence.load_config(back, saved, base=tmp_path)
    assert back.pull_radius == src.pull_radius
    assert back.snap_radius == src.snap_radius


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
