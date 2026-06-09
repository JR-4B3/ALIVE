from __future__ import annotations

import threading

import numpy as np

from codebook import FREQ_MAP, GAP_MAP


SAMPLE_RATE = 44100
BURST_LEN = 0.22
BURST_AMP = 0.5
TRANSMISSION_GAP_SCALE = 0.65
MIN_TRANSMISSION_GAP_MS = 90
LANGUAGE_LOOP_PAUSE_S = 3.0
CLOCK_LOOP_PAUSE_S = 1.2
BURST_TONE_S = 0.35
BURST_PAUSE_S = 4.5
RESET_NOTICE_LEAD_S = 0.6
START_LEAD_IN_S = 1.5
VALID_MODES = ("laser", "horn", "vocal")
VALID_SIGNAL_TYPES = ("language", "clock", "burst")


def make_burst(letter: str, mode: str = "laser") -> np.ndarray:
    if letter in FREQ_MAP:
        low_f, high_f = FREQ_MAP[letter]
    else:
        return np.zeros(0, dtype=np.float32)

    t = np.linspace(0, BURST_LEN, int(SAMPLE_RATE * BURST_LEN), endpoint=False)

    if mode == "laser":
        sweep_down = 6200 - 2600 * (t / BURST_LEN)
        sweep_up = 2700 + 1800 * (t / BURST_LEN)
        phase_down = 2 * np.pi * np.cumsum(sweep_down) / SAMPLE_RATE
        phase_up = 2 * np.pi * np.cumsum(sweep_up) / SAMPLE_RATE
        zap = np.sin(phase_down) * 0.55 + np.sin(phase_up) * 0.22
        bite = np.sign(np.sin(2 * np.pi * 95 * t)) * 0.12
        hiss = np.random.normal(0, 0.16, size=t.shape)
        ring_env = np.exp(-t * 9)
        texture = (zap + bite + hiss * 0.35) * ring_env
        attack = int(0.003 * SAMPLE_RATE)
        decay = int(0.045 * SAMPLE_RATE)
        envelope = np.ones_like(t)
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

    if mode == "laser":
        carrier_low = np.sin(2 * np.pi * low_f * t) * 0.50
        carrier_high = np.sin(2 * np.pi * high_f * t) * 0.44
        burst = texture * 0.62 + carrier_low + carrier_high
    else:
        carrier_low = np.sin(2 * np.pi * low_f * t) * 0.78
        carrier_high = np.sin(2 * np.pi * high_f * t) * 0.68
        burst = texture * 0.28 + carrier_low + carrier_high
    burst = np.clip(burst, -0.95, 0.95)
    burst = burst / (np.max(np.abs(burst)) + 1e-9) * BURST_AMP
    return burst.astype(np.float32)


def sanitize_message(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch in FREQ_MAP).strip()


def encoded_gap_ms(letter: str) -> int:
    return max(MIN_TRANSMISSION_GAP_MS, int(round(GAP_MAP[letter] * TRANSMISSION_GAP_SCALE)))


def encode_message(text: str, mode: str = "laser", loop_pause_s: float = LANGUAGE_LOOP_PAUSE_S) -> np.ndarray:
    message = sanitize_message(text) or "ALIVE"
    signal: list[float] = []
    for ch in message:
        signal.extend(make_burst(ch, mode=mode))
        signal.extend(np.zeros(int(SAMPLE_RATE * (encoded_gap_ms(ch) / 1000.0)), dtype=np.float32))
    signal.extend(np.zeros(int(SAMPLE_RATE * loop_pause_s), dtype=np.float32))
    return np.asarray(signal, dtype=np.float32)


def encode_clock_signal(mode: str = "laser", pulses: int = 6, gap_s: float = 0.5) -> np.ndarray:
    signal: list[float] = []
    for _ in range(pulses):
        signal.extend(make_burst("A", mode=mode))
        signal.extend(np.zeros(int(SAMPLE_RATE * gap_s), dtype=np.float32))
    signal.extend(np.zeros(int(SAMPLE_RATE * CLOCK_LOOP_PAUSE_S), dtype=np.float32))
    return np.asarray(signal, dtype=np.float32)


def encode_burst_signal(tone_s: float = BURST_TONE_S, pause_s: float = BURST_PAUSE_S) -> np.ndarray:
    t = np.linspace(0, tone_s, int(SAMPLE_RATE * tone_s), endpoint=False)
    tone = np.sin(2 * np.pi * 1500 * t)
    attack = int(0.010 * SAMPLE_RATE)
    decay = int(0.080 * SAMPLE_RATE)
    envelope = np.ones_like(t)
    envelope[:attack] = np.linspace(0, 1, attack)
    envelope[-decay:] = np.linspace(1, 0, decay)
    burst = (tone * envelope * 0.42).astype(np.float32)
    silence = np.zeros(int(SAMPLE_RATE * pause_s), dtype=np.float32)
    return np.concatenate([burst, silence])


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
        self._reset_frame = self._reset_frame_for_current(self._audio)
        self._cursor = 0
        self._revision = 0
        self._cycle = 0
        self._lock = threading.Lock()
        self._stream = None

    def _encode_current(self) -> np.ndarray:
        if self.signal_type == "burst":
            return encode_burst_signal()
        if self.signal_type == "clock":
            return encode_clock_signal(self.mode)
        return encode_message(self.message, self.mode)

    def _reset_frame_for_current(self, audio: np.ndarray) -> int:
        if self.signal_type == "burst":
            return int(SAMPLE_RATE * (BURST_TONE_S + 0.8))
        if self.signal_type == "clock":
            return max(0, len(audio) - int(SAMPLE_RATE * RESET_NOTICE_LEAD_S))
        return max(0, len(audio) - int(SAMPLE_RATE * RESET_NOTICE_LEAD_S))

    def start(self) -> bool:
        if self._stream is not None:
            print(f"[SENDER] Already looping {self._description()}")
            return True
        with self._lock:
            self._cursor = -int(SAMPLE_RATE * START_LEAD_IN_S)
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
            print("[SENDER] Signal stopped")

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
            self._reset_frame = self._reset_frame_for_current(self._audio)
            self._cursor = 0
            self._revision += 1
        prefix = "Looping" if self._stream is not None else "Ready"
        print(f"[SENDER] {prefix} {self._description()}")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "message": self.message,
                "mode": self.mode,
                "signal": self.signal_type,
                "duration": round(len(self._audio) / SAMPLE_RATE, 2),
                "revision": self._revision,
                "cycle": self._cycle,
                "active": self._stream is not None,
            }

    def public_snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "signal": self.signal_type,
                "duration": round(len(self._audio) / SAMPLE_RATE, 2),
                "revision": self._revision,
                "cycle": self._cycle,
                "active": self._stream is not None,
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
            elif cursor < 0:
                silent_frames = min(frames, -cursor)
                out = np.zeros(frames, dtype=np.float32)
                remaining_frames = frames - silent_frames
                if remaining_frames > 0:
                    audio_len = len(audio)
                    idx = np.arange(remaining_frames) % audio_len
                    out[silent_frames:] = audio[idx]
                    self._cursor = remaining_frames % audio_len
                else:
                    self._cursor = cursor + frames
            else:
                audio_len = len(audio)
                reset_frame = self._reset_frame
                next_cursor_abs = cursor + frames
                if cursor < reset_frame <= next_cursor_abs or next_cursor_abs >= audio_len + reset_frame:
                    self._cycle += 1
                idx = (np.arange(frames) + cursor) % audio_len
                out = audio[idx]
                self._cursor = next_cursor_abs % audio_len
        outdata[:, 0] = out
