from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import numpy as np


SAMPLE_RATE = 44100
VALID_ZONES = ("far", "mid", "near", "close")


@dataclass(frozen=True)
class EmitterFingerprint:
    emitter_id: str
    label: str
    low_hz: float
    high_hz: float
    pulse_hz: float


EMITTER_FINGERPRINTS = (
    EmitterFingerprint("emitter-1", "Emitter 1", 1430.0, 2210.0, 1.05),
    EmitterFingerprint("emitter-2", "Emitter 2", 1510.0, 2330.0, 1.27),
    EmitterFingerprint("emitter-3", "Emitter 3", 1630.0, 2470.0, 1.51),
    EmitterFingerprint("emitter-4", "Emitter 4", 1760.0, 2590.0, 1.73),
    EmitterFingerprint("emitter-5", "Emitter 5", 1910.0, 2740.0, 1.93),
)


ZONE_SOUND = {
    "far": {"amplitude": 0.07, "pulse_depth": 0.32, "texture": 0.05},
    "mid": {"amplitude": 0.11, "pulse_depth": 0.42, "texture": 0.08},
    "near": {"amplitude": 0.16, "pulse_depth": 0.52, "texture": 0.11},
    "close": {"amplitude": 0.21, "pulse_depth": 0.62, "texture": 0.15},
}


def normalize_zone(value: str | None) -> str:
    if value is None:
        return "far"
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "f": "far",
        "far": "far",
        "m": "mid",
        "mid": "mid",
        "middle": "mid",
        "n": "near",
        "near": "near",
        "c": "close",
        "close": "close",
        "very-near": "close",
        "verynear": "close",
        "very": "close",
    }
    if normalized not in aliases:
        valid = ", ".join(VALID_ZONES)
        raise ValueError(f"unknown zone '{value}' (valid: {valid})")
    return aliases[normalized]


def fingerprint_for(emitter_id: str | None) -> EmitterFingerprint:
    if emitter_id:
        for fingerprint in EMITTER_FINGERPRINTS:
            if fingerprint.emitter_id == emitter_id:
                return fingerprint
    return EMITTER_FINGERPRINTS[0]


def synthesize_emitter_block(
    fingerprint: EmitterFingerprint,
    zone: str,
    start_frame: int,
    frames: int,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    zone = normalize_zone(zone)
    sound = ZONE_SOUND[zone]
    indices = np.arange(start_frame, start_frame + frames, dtype=np.float64)
    seconds = indices / sample_rate
    carrier = np.sin(2.0 * math.pi * fingerprint.low_hz * seconds)
    carrier += 0.82 * np.sin(2.0 * math.pi * fingerprint.high_hz * seconds)
    envelope = 1.0 - sound["pulse_depth"] / 2.0
    envelope += sound["pulse_depth"] / 2.0 * (1.0 + np.sin(2.0 * math.pi * fingerprint.pulse_hz * seconds))
    texture = sound["texture"] * np.sin(2.0 * math.pi * (fingerprint.low_hz + fingerprint.high_hz) / 3.0 * seconds)
    block = (carrier + texture) * envelope * sound["amplitude"]
    return np.clip(block, -0.95, 0.95).astype(np.float32)


class ZoneEmitterPlayer:
    def __init__(
        self,
        emitter_id: str = "emitter-1",
        zone: str = "far",
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self.sample_rate = sample_rate
        self.emitter = fingerprint_for(emitter_id)
        self.zone = normalize_zone(zone)
        self._sample_cursor = 0
        self._stream = None
        self._lock = threading.Lock()
        self._revision = 0
        self.last_phone_update: dict[str, object] | None = None

    def start(self) -> bool:
        if self._stream is not None:
            print(f"[EMITTER] Already playing {self.emitter.emitter_id} as {self.zone}")
            return True
        try:
            import sounddevice as sd
        except Exception as exc:
            print(f"[EMITTER] Audio output unavailable: {exc}")
            return False
        try:
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=1024,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            print(f"[EMITTER] Could not start zone emitter: {exc}")
            self._stream = None
            return False
        print(f"[EMITTER] Playing {self.emitter.emitter_id} as {self.zone}")
        return True

    def stop(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
            print("[EMITTER] Zone emitter stopped")

    def configure(self, emitter_id: str | None = None, zone: str | None = None) -> None:
        with self._lock:
            if emitter_id is not None:
                self.emitter = fingerprint_for(emitter_id)
            if zone is not None:
                self.zone = normalize_zone(zone)
            self._revision += 1
        print(f"[EMITTER] Ready {self.emitter.emitter_id} as {self.zone}")

    def apply_phone_zone(
        self,
        emitter_id: str,
        zone: str,
        confidence: float,
        levels: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            self.emitter = fingerprint_for(emitter_id)
            self.zone = normalize_zone(zone)
            self.last_phone_update = {
                "emitterId": self.emitter.emitter_id,
                "zone": self.zone,
                "confidence": float(confidence),
                "levels": levels or {},
            }
            self._revision += 1
        print(f"[CONTROL] Phone heard {self.emitter.emitter_id}: {self.zone} ({confidence:.0f}%)")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "mode": "zone",
                "emitterId": self.emitter.emitter_id,
                "label": self.emitter.label,
                "zone": self.zone,
                "frequencies": [self.emitter.low_hz, self.emitter.high_hz],
                "pulseHz": self.emitter.pulse_hz,
                "active": self._stream is not None,
                "revision": self._revision,
                "lastPhoneUpdate": self.last_phone_update,
                "emitters": [
                    {
                        "emitterId": item.emitter_id,
                        "label": item.label,
                        "frequencies": [item.low_hz, item.high_hz],
                        "pulseHz": item.pulse_hz,
                    }
                    for item in EMITTER_FINGERPRINTS
                ],
            }

    def _callback(self, outdata, frames: int, time, status) -> None:
        del time, status
        with self._lock:
            start = self._sample_cursor
            self._sample_cursor += frames
            emitter = self.emitter
            zone = self.zone
        outdata[:, 0] = synthesize_emitter_block(
            fingerprint=emitter,
            zone=zone,
            start_frame=start,
            frames=frames,
            sample_rate=self.sample_rate,
        )
