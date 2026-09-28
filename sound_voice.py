"""Experimental, sample-based acoustic alphabets. No legacy carrier dependency.

The JSON package contains PCM for playback and spectral trajectories for recognition.
Keep this feature format in sync with web/src/sensing/soundVoice.ts.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

RATE = 16000
FRAME = 512
HOP = 160
BANDS = 40
STEPS = 24
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
GAP = 0.22
MAX_SECONDS = 1.2


def read_audio(path: Path) -> np.ndarray:
    rate, data = wavfile.read(path)
    if data.dtype.kind in "iu":
        if data.dtype == np.uint8:
            data = (data.astype(float) - 128) / 128
        else:
            data = data.astype(float) / (2 ** (data.dtype.itemsize * 8 - 1))
    else:
        data = data.astype(float)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if not np.isfinite(data).all() or not len(data):
        raise ValueError("Audio must contain finite samples")
    if rate != RATE:
        from math import gcd
        divisor = gcd(rate, RATE)
        data = signal.resample_poly(data, RATE // divisor, rate // divisor)
    return data


def prepare(data: np.ndarray) -> np.ndarray:
    data = np.asarray(data, dtype=float)
    if not np.isfinite(data).all() or not len(data):
        raise ValueError("Empty or invalid sound")
    data = data - np.mean(data)
    peak = np.max(np.abs(data))
    if peak < 1e-5:
        raise ValueError("Sound is silent")
    active = np.flatnonzero(np.abs(data) > peak * 0.015)
    data = data[max(0, active[0] - 160):min(len(data), active[-1] + 161)]
    if not 0.12 <= len(data) / RATE <= MAX_SECONDS:
        raise ValueError(f"Each trimmed sound must be 0.12–{MAX_SECONDS} seconds")
    edge = min(160, len(data) // 10)
    data[:edge] *= np.linspace(0, 1, edge)
    data[-edge:] *= np.linspace(1, 0, edge)
    return data / max(np.max(np.abs(data)), 1e-9) * 0.7


def filterbank() -> np.ndarray:
    edges = np.geomspace(180, 6500, BANDS + 2)
    bins = np.arange(FRAME // 2 + 1) * RATE / FRAME
    return np.array([np.maximum(0, np.minimum((bins - a) / (b - a), (c - bins) / (c - b)))
                     for a, b, c in zip(edges, edges[1:], edges[2:])])


BANK = filterbank()
WINDOW = np.hanning(FRAME)


def features(data: np.ndarray) -> list[list[float]]:
    padded = np.pad(data, (0, max(0, FRAME - len(data))))
    frames = np.lib.stride_tricks.sliding_window_view(padded, FRAME)[::HOP]
    powers = np.abs(np.fft.rfft(frames * WINDOW)) ** 2
    bands = np.sqrt(powers @ BANK.T)
    # Suppress weak spectral tails; normalize away playback/microphone gain.
    bands = np.maximum(0, bands - np.max(bands, axis=1, keepdims=True) * 0.04)
    bands /= np.maximum(np.linalg.norm(bands, axis=1, keepdims=True), 1e-9)
    positions = np.linspace(0, len(bands) - 1, STEPS)
    result = np.array([np.interp(positions, np.arange(len(bands)), bands[:, b]) for b in range(BANDS)]).T
    result /= np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-9)
    return result.round(6).tolist()


def distance(a: list, b: list) -> float:
    """Band-constrained DTW with cosine cost; match the browser implementation."""
    x, y = np.array(a), np.array(b)
    costs = np.maximum(0, 1 - x @ y.T)
    grid = np.full((len(x) + 1, len(y) + 1), np.inf)
    grid[0, 0] = 0
    for i in range(1, len(x) + 1):
        for j in range(max(1, i - 3), min(len(y), i + 3) + 1):
            grid[i, j] = costs[i - 1, j - 1] + min(grid[i - 1, j - 1], grid[i - 1, j] + .025, grid[i, j - 1] + .025)
    return float(grid[-1, -1] / max(len(x), len(y)))


def identify(trajectory: list, voice: dict) -> dict:
    ranked = sorted((min(distance(trajectory, t) for t in entry["templates"]), ch)
                    for ch, entry in voice["symbols"].items())
    score, ch = ranked[0]
    margin = ranked[1][0] - score
    accepted = score <= voice["maxDistance"] and margin >= voice["minMargin"]
    return {"symbol": ch if accepted else "?", "nearest": ch, "distance": score, "margin": margin}


def stamp(voice: dict) -> dict:
    voice.pop("id", None)
    def canonical(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"{value:.6f}"
        if isinstance(value, list):
            return [canonical(x) for x in value]
        if isinstance(value, dict):
            return {k: canonical(v) for k, v in value.items()}
        return value
    voice["id"] = hashlib.sha256(json.dumps(canonical(voice), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return voice


def compile_voice(sounds: dict[str, np.ndarray], name: str) -> dict:
    if set(sounds) != set(LETTERS):
        raise ValueError("Provide all A–Z sounds and SPACE.wav")
    symbols = {}
    for ch in LETTERS:
        audio = prepare(sounds[ch])
        pcm = np.round(audio * 32767).astype("<i2")
        # Templates describe the actual quantized samples used for playback.
        symbols[ch] = {"pcm": base64.b64encode(pcm.tobytes()).decode(),
                       "samples": len(pcm), "templates": [features(pcm.astype(float) / 32768)]}
    voice = {"format": "alive-sound-voice", "version": 1, "name": name[:80], "sampleRate": RATE,
             "gapSeconds": GAP, "maxDistance": .24, "minMargin": .045, "symbols": symbols,
             "calibration": []}
    return stamp(voice)


def validate_voice(voice: dict) -> dict:
    if (voice.get("format") != "alive-sound-voice" or voice.get("version") != 1 or
            voice.get("sampleRate") != RATE or set(voice.get("symbols", {})) != set(LETTERS)):
        raise ValueError("Unsupported voice package")
    if not .12 <= voice.get("gapSeconds", 0) <= .6:
        raise ValueError("Invalid symbol gap")
    if not 0 < voice.get("maxDistance", 0) <= .5 or not .01 <= voice.get("minMargin", 0) <= .3:
        raise ValueError("Invalid recognition thresholds")
    if not isinstance(voice.get("name"), str) or len(voice["name"]) > 80:
        raise ValueError("Invalid voice name")
    history = voice.get("calibration")
    if not isinstance(history, list) or len(history) > 500:
        raise ValueError("Invalid calibration history")
    import re
    for example in history:
        if (not isinstance(example, dict) or not isinstance(example.get("recordingId"), str) or
                not re.fullmatch(r"[a-f0-9]{64}", example["recordingId"]) or
                not isinstance(example.get("label"), str) or len(example["label"]) > 80 or
                example.get("symbol") not in list(LETTERS)):
            raise ValueError("Invalid calibration history")
    for entry in voice["symbols"].values():
        pcm = base64.b64decode(entry["pcm"], validate=True)
        if len(pcm) != entry["samples"] * 2 or not RATE * .12 <= entry["samples"] <= RATE * MAX_SECONDS:
            raise ValueError("Invalid PCM sound")
        templates = np.asarray(entry["templates"], dtype=float)
        if (templates.ndim != 3 or templates.shape[1:] != (STEPS, BANDS) or
                not 1 <= len(templates) <= 8 or not np.isfinite(templates).all() or
                np.min(templates) < 0 or np.max(templates) > 1.001):
            raise ValueError("Invalid recognition templates")
    if not isinstance(voice.get("id"), str) or len(voice["id"]) != 24:
        raise ValueError("Missing voice version ID")
    expected = voice["id"]
    if stamp(dict(voice))["id"] != expected:
        raise ValueError("Voice contents do not match version ID")
    return voice


def load_voice(path: Path) -> dict:
    if path.stat().st_size > 4_000_000:
        raise ValueError("Voice package exceeds 4 MB")
    return validate_voice(json.loads(path.read_text()))


def pcm_for(voice: dict, ch: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(voice["symbols"][ch]["pcm"]), dtype="<i2").astype(float) / 32768


def render_message(voice: dict, message: str) -> np.ndarray:
    if not message or len(message) > 20 or any(ch not in LETTERS for ch in message):
        raise ValueError("Message must contain 1–20 uppercase letters/spaces")
    pieces = [np.zeros(RATE // 2)]
    for ch in message:
        pieces.extend((pcm_for(voice, ch), np.zeros(round(voice["gapSeconds"] * RATE))))
    pieces.append(np.zeros(RATE))
    audio = np.concatenate(pieces)
    if len(audio) > RATE * 30:
        raise ValueError("Message exceeds 30 seconds")
    return audio


def confusion_report(voice: dict) -> dict:
    pairs = []
    for i, a in enumerate(LETTERS):
        for b in LETTERS[i + 1:]:
            d = min(distance(x, y) for x in voice["symbols"][a]["templates"]
                    for y in voice["symbols"][b]["templates"])
            pairs.append({"a": a, "b": b, "distance": round(d, 4)})
    pairs.sort(key=lambda p: p["distance"])
    failed = [ch for ch in LETTERS if identify(features(pcm_for(voice, ch)), voice)["symbol"] != ch]
    return {"voiceId": voice["id"], "selfRecognitionFailures": failed,
            "closestPairs": pairs[:20], "readyForAcousticTesting": not failed,
            "note": "Digital separation only. Not proof of speaker-to-phone reliability."}


def generated_sounds(source: np.ndarray) -> dict[str, np.ndarray]:
    """Create 27 continuous variations from the whole source sound."""
    source = prepare(source)
    source_length = round(max(.24 * RATE, min(.62 * RATE, len(source))))
    seed = np.interp(np.linspace(0, len(source) - 1, source_length),
                     np.arange(len(source)), source)
    result = {}
    for index, ch in enumerate(LETTERS):
        rate = .64 * 1.12 ** (index // 3)
        sweep = (-.4, 0, .4)[index % 3]
        length = round(source_length / rate)
        progress = np.linspace(0, 1, length)
        warped = progress + sweep * (progress * progress - progress)
        positions = warped * (source_length - 1)
        gesture = np.interp(positions, np.arange(source_length), seed)
        result[ch] = gesture * np.sin(np.pi * progress) ** .35
    return result
