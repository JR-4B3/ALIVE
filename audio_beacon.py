from __future__ import annotations

import math
import threading

import numpy as np


BEACON_FREQS = (1720.0, 2290.0)
BEACON_SAMPLE_RATE = 44100


class AudioBeacon:
    def __init__(
        self,
        sample_rate: int = BEACON_SAMPLE_RATE,
        frequencies: tuple[float, float] = BEACON_FREQS,
        amplitude: float = 0.16,
        pulse_hz: float = 0.8,
    ) -> None:
        self.sample_rate = sample_rate
        self.frequencies = frequencies
        self.amplitude = amplitude
        self.pulse_hz = pulse_hz
        self._sample_cursor = 0
        self._stream = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        try:
            import sounddevice as sd
        except Exception as exc:
            print(f"[EMITTER] Audio beacon unavailable: {exc}")
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
            print(f"[EMITTER] Could not start audio beacon: {exc}")
            self._stream = None
            return False

        f1, f2 = self.frequencies
        print(f"[EMITTER] Audio beacon active: {f1:.0f} Hz + {f2:.0f} Hz")
        return True

    def stop(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None

    def _callback(self, outdata, frames: int, time, status) -> None:
        del time
        if status:
            pass
        with self._lock:
            start = self._sample_cursor
            self._sample_cursor += frames

        indices = np.arange(start, start + frames, dtype=np.float64)
        seconds = indices / self.sample_rate
        f1, f2 = self.frequencies

        carrier = np.sin(2.0 * math.pi * f1 * seconds)
        carrier += 0.72 * np.sin(2.0 * math.pi * f2 * seconds)
        envelope = 0.66 + 0.34 * np.sin(2.0 * math.pi * self.pulse_hz * seconds)
        signal = carrier * envelope * self.amplitude
        outdata[:, 0] = signal.astype(np.float32)
