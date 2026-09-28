import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from reply_engine import (
    DEFAULT_MODEL,
    MAX_REPLY_CHARS,
    MAX_SIGNAL_SECONDS,
    ReplyUnavailableError,
    generate_reply,
    load_local_env,
    normalize_reply,
    sanitize_message,
    signal_duration_seconds,
)


def test_sanitize_message_keeps_firmware_characters():
    assert sanitize_message("test 123!") == "TEST"
    assert sanitize_message("hello world") == "HELLO WORLD"


def test_reply_duration_matches_wifi_firmware():
    assert signal_duration_seconds("HI") == 2.108
    assert signal_duration_seconds("A") == 1.49
    assert signal_duration_seconds("A A") == 3.19


def test_reply_is_short_and_transport_safe():
    assert normalize_reply("yes... but the air is running thin") == "YES BUT THE"
    assert len(normalize_reply("abcdefghijklmnopqrstuvwxyz")) <= MAX_REPLY_CHARS
    assert normalize_reply("STAY CLOSE NOW") == "STAY CLOSE"
    assert signal_duration_seconds(normalize_reply("Z" * 20)) <= MAX_SIGNAL_SECONDS


def test_local_env_loads_key_without_overriding_shell():
    with TemporaryDirectory() as directory:
        env_file = Path(directory) / ".env"
        env_file.write_text("OPENAI_API_KEY=local-test-key\nALIVE_OPENAI_MODEL=test-model\n", encoding="utf-8")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "shell-test-key"}, clear=True):
            load_local_env(env_file)
            assert os.environ["OPENAI_API_KEY"] == "shell-test-key"
            assert os.environ["ALIVE_OPENAI_MODEL"] == "test-model"


def test_reply_requires_api_key():
    with patch("reply_engine.load_local_env", return_value=None), patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ReplyUnavailableError, match="API key"):
            generate_reply("Can you hear me?")


def test_reply_calls_model_and_normalizes_output():
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
