import io
import json
import os
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from audio_message import (
    LoopingMessagePlayer,
    SAMPLE_RATE,
    encode_burst_signal,
    encode_clock_signal,
    encode_message,
    encoded_gap_ms,
    make_burst,
    sanitize_message,
)
from reply_engine import (
    API_KEY_FILE,
    DEFAULT_MODEL,
    MAX_REPLY_CHARS,
    MAX_SIGNAL_SECONDS,
    ReplyUnavailableError,
    generate_reply,
    load_local_env,
    normalize_reply,
    signal_duration_seconds,
)
from emitter import DemoState


def test_sanitize_message_keeps_codebook_chars():
    assert sanitize_message("test 123!") == "TEST"
    assert sanitize_message("hello world") == "HELLO WORLD"


def test_encoded_gap_uses_transmission_scale():
    assert encoded_gap_ms("A") == 90
    assert encoded_gap_ms("T") == 682


def test_language_signal_contains_bursts_and_gaps():
    audio = encode_message("TEST")
    assert audio.dtype == np.float32
    assert len(audio) > 44100
    assert np.max(np.abs(audio)) > 0.1
    assert np.min(np.abs(audio[-1000:])) == 0


def test_default_tone_has_smooth_edges_and_both_carriers():
    burst = make_burst("A")
    assert abs(burst[0]) < 1e-6
    assert abs(burst[-1]) < 1e-4
    assert np.max(np.abs(burst)) <= 0.5
    spectrum = np.abs(np.fft.rfft(burst * np.hanning(len(burst))))
    frequencies = np.fft.rfftfreq(len(burst), 1 / SAMPLE_RATE)
    for carrier in (400, 2000):
        assert np.max(spectrum[np.abs(frequencies - carrier) < 10]) > 100


def test_clock_and_burst_signals_are_distinct():
    clock = encode_clock_signal()
    burst = encode_burst_signal()
    assert len(clock) != len(burst)
    assert np.max(np.abs(clock)) > 0.1
    assert np.max(np.abs(burst)) > 0.1


def test_player_configures_without_audio_device():
    player = LoopingMessagePlayer("TEST")
    player.configure(message="HELLO", signal_type="clock")
    snapshot = player.snapshot()
    assert snapshot["message"] == "HELLO"
    assert snapshot["signal"] == "clock"
    assert snapshot["active"] is False


def test_local_env_loads_key_without_overriding_shell():
    with TemporaryDirectory() as directory:
        env_file = Path(directory) / ".env"
        env_file.write_text("OPENAI_API_KEY=local-test-key\nALIVE_OPENAI_MODEL=test-model\n", encoding="utf-8")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "shell-test-key"}, clear=True):
            load_local_env(env_file)
            assert os.environ["OPENAI_API_KEY"] == "shell-test-key"
            assert os.environ["ALIVE_OPENAI_MODEL"] == "test-model"


def test_reply_text_is_transport_safe():
    assert normalize_reply("yes... but the air is running thin") == "YES BUT THE"
    assert len(normalize_reply("abcdefghijklmnopqrstuvwxyz")) <= MAX_REPLY_CHARS
    assert normalize_reply("STAY CLOSE NOW") == "STAY CLOSE"
    assert signal_duration_seconds(normalize_reply("Z" * 20)) <= MAX_SIGNAL_SECONDS


def test_reply_requires_real_model_and_uses_luna():
    with patch("reply_engine.load_local_env", return_value=None):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch("reply_engine.API_KEY_FILE", API_KEY_FILE.with_name("absent_test_key")):
                try:
                    generate_reply("Can you hear me?")
                except ReplyUnavailableError as exc:
                    assert "API key" in str(exc)
                else:
                    raise AssertionError("missing API key must not return a fake LLM reply")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        assert timeout == 12
        return io.BytesIO(json.dumps({
            "output": [{"content": [{"text": "STAY CLOSE"}]}]
        }).encode())

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
        with patch("urllib.request.urlopen", fake_urlopen):
            assert generate_reply("Can you hear me?") == "STAY CLOSE"
    assert captured["payload"]["model"] == DEFAULT_MODEL == "gpt-6-luna"
    assert captured["payload"]["reasoning"] == {"effort": "none"}
    assert "emergency beacon" in captured["payload"]["instructions"]


def test_device_output_queues_each_play_without_laptop_audio():
    player = LoopingMessagePlayer("TEST")
    laptop_play_calls = []
    player.play_once = lambda: laptop_play_calls.append(True)  # type: ignore[method-assign]
    state = DemoState(player, device_output=True)

    first = state.set_reply("I AM HERE")
    state.note_device_poll()
    replay = state.play_current_once()

    assert first["revision"] == 0
    assert replay["revision"] == 1
    assert replay["message"] == "I AM HERE"
    assert replay["output"] == "esp32"
    assert laptop_play_calls == []


def test_serial_output_only_plays_when_requested():
    class FakeSerialDevice:
        def __init__(self):
            self.messages = []

        def play(self, message):
            self.messages.append(message)

    serial_device = FakeSerialDevice()
    state = DemoState(LoopingMessagePlayer("HELLO"), device_output=True,
                      serial_device=serial_device)

    prepared = state.set_reply("I AM HERE")
    assert prepared["revision"] == 0
    assert serial_device.messages == []

    played = state.play_current_once()
    assert played["revision"] == 1
    assert serial_device.messages == ["I AM HERE"]


def run_tests():
    tests = [
        test_sanitize_message_keeps_codebook_chars,
        test_encoded_gap_uses_transmission_scale,
        test_language_signal_contains_bursts_and_gaps,
        test_default_tone_has_smooth_edges_and_both_carriers,
        test_clock_and_burst_signals_are_distinct,
        test_player_configures_without_audio_device,
        test_reply_text_is_transport_safe,
        test_reply_requires_real_model_and_uses_luna,
        test_local_env_loads_key_without_overriding_shell,
        test_device_output_queues_each_play_without_laptop_audio,
        test_serial_output_only_plays_when_requested,
    ]
    for test in tests:
        test()
        print(f"{test.__name__}: OK")
    print(f"Result: {len(tests)} passed, 0 failed")


if __name__ == "__main__":
    run_tests()
