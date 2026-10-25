"""Chirp sequences the boards play.

A sequence is a lead silence and a list of [symbol, gap after it in ms]. Every
chirp lasts 360 ms (beacon_voice.h). Symbol -1 is the 18.2 kHz sync chirp,
0-25 are A-Z and 26 is space. Only intelligent messages are framed by sync
chirps; a phone treats any unframed chirp as noise or a clock.
"""
from __future__ import annotations

import random

CHIRP_MS = 360
SYNC = -1
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
# The firmware's chirp buffer. A 40-character message needs 43 chirps.
MAX_CHIRPS = 128
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
