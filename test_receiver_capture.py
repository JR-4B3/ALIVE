import io
import json
import wave
from unittest.mock import patch

import pytest

from emitter import save_receiver_capture


def test_receiver_capture_preserves_audio_and_expected_message(tmp_path):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\x00\x00" * 480)
    with patch("emitter.RECEIVER_CAPTURES", tmp_path):
        name = save_receiver_capture(output.getvalue(), "I AM HERE")
        assert (tmp_path / f"{name}.wav").read_bytes() == output.getvalue()
        metadata = json.loads((tmp_path / f"{name}.json").read_text())
        assert metadata == {"message": "I AM HERE", "sampleRate": 48000, "seconds": 0.01}
        assert (tmp_path / f"{name}.wav").stat().st_mode & 0o777 == 0o600


def test_receiver_capture_rejects_invalid_audio(tmp_path):
    with patch("emitter.RECEIVER_CAPTURES", tmp_path):
        with pytest.raises((wave.Error, EOFError)):
            save_receiver_capture(b"not audio", "TEST")
    assert not list(tmp_path.iterdir())
