from __future__ import annotations

import threading

import numpy as np

from codebook import FREQ_MAP, GAP_MAP


SAMPLE_RATE = 44100
BURST_LEN = 0.22
BURST_AMP = 0.6
VALID_MODES = ("laser", "horn", "vocal")
VALID_SIGNAL_TYPES = ("language", "clock", "dead")
END_FREQS = (1000, 2900)


def make_burst(letter: str, mode: str = "laser") -> np.ndarray:
    if letter == "<END>":
        low_f, high_f = END_FREQS
    elif letter in FREQ_MAP:
        low_f, high_f = FREQ_MAP[letter]
    else:
        return np.zeros(0, dtype=np.float32)

    t = np.linspace(0, BURST_LEN, int(SAMPLE_RATE * BURST_LEN), endpoint=False)

    if mode == "laser":
        carrier = np.sin(2 * np.pi * 4200 * t)
        sweep = np.sin(2 * np.pi * (4800 - 600 * t / BURST_LEN) * t)
        noise = np.random.normal(0, 0.08, size=t.shape)
        texture = (carrier * 0.4 + sweep * 0.35 + noise) * 0.35
        envelope = np.ones_like(t)
        attack = int(0.001 * SAMPLE_RATE)
        decay = int(0.008 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        texture = texture * envelope

    elif mode == "vocal":
        f_start, f_end = 180, 140
        freq = f_start + (f_end - f_start) * (t / BURST_LEN)
        phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
        body = np.sin(phase)
        body += 0.35 * np.sin(3 * phase)
        body += 0.18 * np.sin(5 * phase)
        shimmer = np.sin(2 * np.pi * 251 * t) * 0.25
        sub_env = np.exp(-t * 20)
        sub = np.sin(2 * np.pi * 55 * t) * sub_env * 0.6
        noise = np.random.normal(0, 0.12, size=t.shape)
        texture = body * 0.6 + shimmer * 0.3 + sub + noise * 0.2
        envelope = np.ones_like(t)
        attack = int(0.015 * SAMPLE_RATE)
        decay = int(0.030 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        tremolo = 1.0 + 0.15 * np.sin(2 * np.pi * 7 * t)
        texture = np.clip(texture * envelope * tremolo, -0.95, 0.95)

    else:
        fundamental = np.sin(2 * np.pi * 100 * t)
        overtones = 0.40 * np.sin(2 * np.pi * 300 * t)
        overtones += 0.25 * np.sin(2 * np.pi * 500 * t)
        overtones += 0.15 * np.sin(2 * np.pi * 700 * t)
        high = 0.35 * np.sin(2 * np.pi * 1120 * t)
        click_env = np.exp(-t * 60)
        click = 0.5 * np.sin(2 * np.pi * 1600 * t) * click_env
        noise = np.random.normal(0, 0.18, size=t.shape)
        texture = fundamental * 0.55 + overtones + high * 0.6 + click + noise * 0.25
        texture = np.clip(texture * 2.2, -0.88, 0.88)
        envelope = np.ones_like(t)
        attack = int(0.003 * SAMPLE_RATE)
        decay = int(0.015 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        texture = texture * envelope

    carrier_low = np.sin(2 * np.pi * low_f * t) * 0.78
    carrier_high = np.sin(2 * np.pi * high_f * t) * 0.68
    burst = np.clip(texture * 0.28 + carrier_low + carrier_high, -0.95, 0.95)
    burst = burst / (np.max(np.abs(burst)) + 1e-9) * BURST_AMP
    return burst.astype(np.float32)


def sanitize_message(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch in FREQ_MAP).strip()


def encode_message(text: str, mode: str = "laser", loop_pause_s: float = 1.0) -> np.ndarray:
    message = sanitize_message(text) or "ALIVE"
    signal: list[float] = []
    for ch in message:
        signal.extend(make_burst(ch, mode=mode))
        signal.extend(np.zeros(int(SAMPLE_RATE * (GAP_MAP[ch] / 1000.0)), dtype=np.float32))
    signal.extend(make_burst("<END>", mode=mode))
    signal.extend(np.zeros(int(SAMPLE_RATE * loop_pause_s), dtype=np.float32))
    return np.asarray(signal, dtype=np.float32)


def encode_clock_signal(mode: str = "laser", pulses: int = 6, gap_s: float = 0.5) -> np.ndarray:
    signal: list[float] = []
    for _ in range(pulses):
        signal.extend(make_burst("A", mode=mode))
        signal.extend(np.zeros(int(SAMPLE_RATE * gap_s), dtype=np.float32))
    signal.extend(make_burst("<END>", mode=mode))
    signal.extend(np.zeros(int(SAMPLE_RATE * 1.0), dtype=np.float32))
    return np.asarray(signal, dtype=np.float32)


def encode_dead_signal(duration_s: float = 2.0) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * duration_s), dtype=np.float32)


class LoopingMessagePlayer:
    def __init__(
        self,
        message: str,
        mode: str = "laser",
        signal_type: str = "language",
    ) -> None:
        self.message = sanitize_message(message) or "ALIVE"
        self.mode = mode if mode in VALID_MODES else "laser"
        self.signal_type = signal_type if signal_type in VALID_SIGNAL_TYPES else "language"
        self._audio = self._encode_current()
        self._cursor = 0
        self._lock = threading.Lock()
        self._stream = None

    def _encode_current(self) -> np.ndarray:
        if self.signal_type == "dead":
            return encode_dead_signal()
        if self.signal_type == "clock":
            return encode_clock_signal(self.mode)
        return encode_message(self.message, self.mode)

    def start(self) -> bool:
        try:
            import sounddevice as sd
        except Exception as exc:
            print(f"[SENDER] Audio output unavailable: {exc}")
            return False
        try:
            self._stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=1024,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            print(f"[SENDER] Could not start encoded message loop: {exc}")
            self._stream = None
            return False
        print(f"[SENDER] Looping {self._description()}")
        return True

    def stop(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None

    def configure(
        self,
        message: str | None = None,
        mode: str | None = None,
        signal_type: str | None = None,
    ) -> None:
        with self._lock:
            if message is not None:
                self.message = sanitize_message(message) or self.message
            if mode is not None and mode in VALID_MODES:
                self.mode = mode
            if signal_type is not None and signal_type in VALID_SIGNAL_TYPES:
                self.signal_type = signal_type
            self._audio = self._encode_current()
            self._cursor = 0
        print(f"[SENDER] Looping {self._description()}")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "message": self.message,
                "mode": self.mode,
                "signal": self.signal_type,
                "duration": round(len(self._audio) / SAMPLE_RATE, 2),
            }

    def public_snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "signal": self.signal_type,
                "duration": round(len(self._audio) / SAMPLE_RATE, 2),
            }

    def _description(self) -> str:
        if self.signal_type == "language":
            return f"language signal as {self.mode}"
        return f"{self.signal_type} signal as {self.mode}"

    def _callback(self, outdata, frames: int, time, status) -> None:
        del time, status
        with self._lock:
            audio = self._audio
            cursor = self._cursor
            if len(audio) == 0:
                out = np.zeros(frames, dtype=np.float32)
            else:
                idx = (np.arange(frames) + cursor) % len(audio)
                out = audio[idx]
                self._cursor = (cursor + frames) % len(audio)
        outdata[:, 0] = out
