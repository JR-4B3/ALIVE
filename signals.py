"""Chirp sequences the boards play.

A sequence is a lead silence and a list of [symbol, gap after it in ms]. Every
chirp lasts 360 ms (beacon_voice.h). Symbol -1 is the 18.2 kHz sync chirp,
0-25 are A-Z and 26 is space. Only intelligent messages are framed by sync
chirps; a phone treats any unframed chirp as noise or a clock.
"""
from __future__ import annotations

import io
import math
import random
import wave
from array import array
from functools import lru_cache

CHIRP_MS = 360
SYNC = -1
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
# The phone needs 65 ms of silence between chirps, measured with its 85 ms
# analysis window, so a gap shorter than 150 ms merges two chirps into one.
MIN_GAP_MS = 180


def message_score(text: str) -> dict[str, object]:
    """Two sync chirps, one chirp per character, and a closing sync chirp.
    The timing matches reply_engine.signal_duration_seconds()."""
    chirps = [[SYNC, 180], [SYNC, 280]]
    chirps += [[ALPHABET.index(char), 180] for char in text if char in ALPHABET]
    chirps.append([SYNC, 760])
    return {"kind": "intelligent", "text": text, "leadMs": 150, "chirps": chirps}


def noise_score(rng: random.Random) -> dict[str, object]:
    """A few chirps on random channels at uneven intervals."""
    chirps = [[rng.randrange(len(ALPHABET)), rng.randint(MIN_GAP_MS, 900)]
              for _ in range(rng.randint(3, 10))]
    return {"kind": "noise", "leadMs": 0, "chirps": chirps}


def clock_settings(rng: random.Random) -> tuple[int, int, int]:
    """Channel, period in ms, and tick count for one board's clock."""
    return rng.randrange(len(ALPHABET)), rng.randint(900, 1600), rng.randint(6, 12)


def clock_score(symbol: int, period_ms: int, ticks: int) -> dict[str, object]:
    """One channel ticking at a fixed period, like a pulsar."""
    return {"kind": "clock", "leadMs": 0, "chirps": [[symbol, period_ms - CHIRP_MS] for _ in range(ticks)]}


def score_seconds(score: dict[str, object]) -> float:
    chirps = score["chirps"]
    assert isinstance(chirps, list)
    return round((int(score["leadMs"]) + sum(CHIRP_MS + gap for _, gap in chirps)) / 1000, 3)


# Chirp synthesis, the same integer oscillator as beacon_voice.h on the ESP32
# and beaconPulse() in web/src/audio/beacon.ts. The debug host uses it to play
# signals through a computer's speakers.
RATE = 48000
CHIRP_FRAMES = RATE * CHIRP_MS // 1000
SYNC_HZ = 18200
FIRST_LETTER_HZ = 18450
SPACING_HZ = 64
SWEEP_HZ = 24
_SINE = [int(32767 * math.sin(2 * math.pi * i / 1024)) for i in range(1025)]
_ENVELOPE = [int(32767 * math.sin(math.pi * i / 1024) ** 2) for i in range(1025)]


@lru_cache(maxsize=None)
def chirp_samples(symbol: int, amplitude: int = 6000) -> array:
    frequency = SYNC_HZ if symbol < 0 else FIRST_LETTER_HZ + symbol * SPACING_HZ
    step_delta = 2 * SWEEP_HZ * 2**32 // (CHIRP_FRAMES * RATE)
    step = (frequency + SWEEP_HZ) * 2**32 // RATE
    phase = 0
    samples = array("h")
    for frame in range(CHIRP_FRAMES):
        index, fraction = phase >> 22, (phase >> 12) & 1023
        wave_value = (_SINE[index] * (1024 - fraction) + _SINE[index + 1] * fraction) >> 10
        shaped = (wave_value * _ENVELOPE[frame * 1024 // CHIRP_FRAMES]) >> 15
        samples.append((shaped * amplitude) >> 15)
        phase = (phase + step) & 0xFFFFFFFF
        step -= step_delta
    return samples


def score_wav(score: dict[str, object], amplitude: int = 6000) -> bytes:
    """The score as a 48 kHz mono WAV file."""
    samples = array("h", bytes(2 * (RATE * int(score["leadMs"]) // 1000)))
    chirps = score["chirps"]
    assert isinstance(chirps, list)
    for symbol, gap_ms in chirps:
        samples += chirp_samples(int(symbol), amplitude)
        samples += array("h", bytes(2 * (RATE * int(gap_ms) // 1000)))
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(RATE)
        recording.writeframes(samples.tobytes())
    return output.getvalue()
