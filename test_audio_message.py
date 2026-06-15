import numpy as np

from audio_message import (
    LoopingMessagePlayer,
    encode_burst_signal,
    encode_clock_signal,
    encode_message,
    encoded_gap_ms,
    sanitize_message,
)


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


def run_tests():
    tests = [
        test_sanitize_message_keeps_codebook_chars,
        test_encoded_gap_uses_transmission_scale,
        test_language_signal_contains_bursts_and_gaps,
        test_clock_and_burst_signals_are_distinct,
        test_player_configures_without_audio_device,
    ]
    for test in tests:
        test()
        print(f"{test.__name__}: OK")
    print(f"Result: {len(tests)} passed, 0 failed")


if __name__ == "__main__":
    run_tests()
