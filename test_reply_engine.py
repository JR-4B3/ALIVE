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
    STAGE_AURORA,
    Reply,
    ReplyUnavailableError,
    build_prompt,
    generate_reply,
    load_local_env,
    normalize_reply,
    sanitize_message,
    signal_duration_seconds,
)


def test_sanitize_message_keeps_firmware_characters():
    assert sanitize_message("test 123!") == "TEST"
    assert sanitize_message("hello world") == "HELLO WORLD"


def test_reply_duration_matches_ultrasound_firmware():
    # 150 ms lead, two sync chirps, 540 ms per character, closing chirp and tail.
    assert signal_duration_seconds("HI") == 3.53
    assert signal_duration_seconds("A") == 2.99
    assert signal_duration_seconds("A A") == 4.07


def test_reply_is_short_and_transport_safe():
    assert normalize_reply("yes... but the air is running thin") == "YES BUT THE AIR IS RUNNING THIN"
    assert normalize_reply("we are the last light of aurora and we are listening") == \
        "WE ARE THE LAST LIGHT OF AURORA AND WE"
    assert len(normalize_reply("abcdefghijklmnopqrstuvwxyz" * 2)) <= MAX_REPLY_CHARS
    assert signal_duration_seconds(normalize_reply("Z" * 60)) <= MAX_SIGNAL_SECONDS


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
            "output": [{"content": [{"text": '{"reply": "stay close", "trusted": false}'}]}]
        }).encode())

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
        with patch("urllib.request.urlopen", fake_urlopen):
            assert generate_reply("Can you hear me?") == Reply("STAY CLOSE")
    assert captured["payload"]["model"] == DEFAULT_MODEL == "gpt-6-luna"
    assert captured["payload"]["reasoning"] == {"effort": "none"}
    assert captured["payload"]["input"] == [{"role": "user", "content": "Can you hear me?"}]
    assert "LANTERN" in captured["payload"]["instructions"]
    assert captured["payload"]["text"]["format"]["type"] == "json_schema"


def test_reply_sends_the_conversation_so_far():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return io.BytesIO(json.dumps({"output_text": "WE ARE LANTERN"}).encode())

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
        with patch("urllib.request.urlopen", fake_urlopen):
            assert generate_reply("Who are you?", [("Hello", "WE ARE HERE")]) == Reply("WE ARE LANTERN")
    assert captured["payload"]["input"] == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "WE ARE HERE"},
        {"role": "user", "content": "Who are you?"},
    ]


def test_only_lantern_can_grant_trust():
    def answer(stage):
        def fake_urlopen(request, timeout):
            return io.BytesIO(json.dumps({"output_text": '{"reply": "YOU CARE", "trusted": true}'}).encode())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch("urllib.request.urlopen", fake_urlopen):
                return generate_reply("Are you alright?", stage=stage)

    assert answer("beacon") == Reply("YOU CARE", trusted=True)
    assert answer(STAGE_AURORA).trusted is False


def test_lantern_hints_only_once_the_visitor_seems_stuck():
    assert "seems stuck" not in build_prompt(turns=0)
    assert "seems stuck" in build_prompt(turns=3)
    assert "AURORA" not in build_prompt()
    assert "never launched" in build_prompt(STAGE_AURORA)
