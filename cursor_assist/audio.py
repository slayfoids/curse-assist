"""Audio cues with a volume control.

``winsound.Beep`` is the obvious way to make a tone on Windows and the one this
used before, but it has no volume: it drives the tone at whatever level the
system decides, so "audio cues on" was all-or-nothing and, on some machines,
startlingly loud. Since the cues fire on every activation and every click, that
matters more here than it would elsewhere.

So the tone is synthesised into a WAV in memory instead and handed to
``PlaySound``, which means amplitude — and therefore volume — is just a
multiplier on the samples. Nothing is written to disk and nothing is installed.

Playback is fire-and-forget on a worker thread: a cue must never hold up the
movement loop, and a dropped cue is far better than a stutter in the pointer.
"""

from __future__ import annotations

import array
import io
import math
import struct
import threading
import wave

SAMPLE_RATE = 22050
FADE_MS = 6.0          # tiny fade in/out; a square-edged tone clicks audibly


def _tone_wav(freq: float, ms: float, volume: float) -> bytes:
    """A mono 16-bit WAV of a sine tone, as bytes."""
    vol = max(0.0, min(1.0, volume))
    n = max(1, int(SAMPLE_RATE * ms / 1000.0))
    fade = max(1, int(SAMPLE_RATE * FADE_MS / 1000.0))
    samples = array.array("h", bytes(2 * n))
    amp = 32767.0 * vol * 0.85      # headroom, so the fades never clip
    step = 2.0 * math.pi * freq / SAMPLE_RATE
    for i in range(n):
        env = 1.0
        if i < fade:
            env = i / fade
        elif i > n - fade:
            env = max(0.0, (n - i) / fade)
        samples[i] = int(amp * env * math.sin(step * i))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


_cache: dict = {}
_cache_lock = threading.Lock()


def _cached(freq: float, ms: float, volume: float) -> bytes:
    # Volume is quantised for the cache key: rendering a fresh WAV for every
    # pixel of slider travel would be wasted work nobody can hear.
    key = (round(freq), round(ms), round(volume, 2))
    with _cache_lock:
        wav = _cache.get(key)
        if wav is None:
            wav = _tone_wav(freq, ms, volume)
            if len(_cache) > 24:
                _cache.clear()
            _cache[key] = wav
    return wav


def _play_blocking(chunks) -> None:
    try:
        import time
        import winsound
        for freq, ms, volume, gap in chunks:
            if volume <= 0.0:
                continue
            winsound.PlaySound(_cached(freq, ms, volume),
                               winsound.SND_MEMORY | winsound.SND_NODEFAULT)
            if gap:
                time.sleep(gap)
    except Exception:
        pass        # a machine with no audio device must not break the assist


def play(chunks) -> None:
    """Play ``[(freq_hz, ms, volume 0..1, gap_s), ...]`` without blocking."""
    threading.Thread(target=_play_blocking, args=(list(chunks),),
                     name="cue", daemon=True).start()


def cue_pull(on: bool, volume: float) -> None:
    """Two high beeps when guidance goes on, two low ones when it goes off."""
    freq = 1400 if on else 440
    play([(freq, 90, volume, 0.045), (freq, 90, volume, 0.0)])


def cue_click(volume: float) -> None:
    play([(880, 60, volume, 0.0)])


def preview(volume: float) -> None:
    """One beep at the current setting, so the slider can be heard."""
    play([(1100, 120, volume, 0.0)])
