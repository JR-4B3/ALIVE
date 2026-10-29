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
    BEATS,
    GOODBYE,
    ReplyUnavailableError,
    build_prompt,
    fade,
    generate_reply,
    load_local_env,
    open_beats,
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
            "output": [{"content": [{"text": '{"reply": "stay close", "told": [0]}'}]}]
        }).encode())

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
        with patch("urllib.request.urlopen", fake_urlopen):
            assert generate_reply("Can you hear me?") == ("STAY CLOSE", frozenset({0}))
    assert captured["payload"]["model"] == DEFAULT_MODEL == "gpt-6-luna"
    assert captured["payload"]["reasoning"] == {"effort": "none"}
    assert captured["payload"]["input"] == [{"role": "user", "content": "Can you hear me?"}]
    assert "Stay vague" in captured["payload"]["instructions"]


def test_reply_sends_the_conversation_so_far():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return io.BytesIO(json.dumps({"output_text": "WHO LISTENS"}).encode())

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
        with patch("urllib.request.urlopen", fake_urlopen):
            assert generate_reply("Who are you?", [("Hello", "WE ARE HERE")]) == ("WHO LISTENS", frozenset())
    assert captured["payload"]["input"] == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "WE ARE HERE"},
        {"role": "user", "content": "Who are you?"},
    ]


def test_the_mystery_comes_first_the_goodbye_last_and_the_rest_in_any_order():
    middle = set(range(1, GOODBYE))
    assert open_beats() == [0]
    assert open_beats({0}) == sorted(middle)
    assert open_beats({0, 3, 5}) == sorted(middle - {3, 5})
    assert open_beats({0} | middle) == [GOODBYE]
    assert "Stay vague" in build_prompt() and BEATS[1] not in build_prompt()
    assert BEATS[1] in build_prompt({0}) and BEATS[GOODBYE] not in build_prompt({0})
    assert "says goodbye" in build_prompt({0} | middle)
    assert "Share one of these facts now" in build_prompt({0}, push=True)
    assert "Share one of these facts now" not in build_prompt({0})
    assert "power" not in build_prompt({0})


def test_a_fading_signal_keeps_each_words_first_letter():
    import random
    faded = fade("WE WERE LISTENING TOO", random.Random(1), rate=1.0)
    assert faded == "W W L T"


def test_a_reply_too_long_for_the_transmitter_is_asked_for_again():
    texts = iter(["EARTH SECRETLY SENT US TO SEARCH FOR LIFE BEYOND EARTH", "EARTH SENT US TO SEEK LIFE"])
    prompts = []

    def fake_urlopen(request, timeout):
        prompts.append(json.loads(request.data)["instructions"])
        return io.BytesIO(json.dumps({"output_text": json.dumps({"reply": next(texts), "told": [3]})}).encode())

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
        with patch("urllib.request.urlopen", fake_urlopen):
            assert generate_reply("Why?", told={0}) == ("EARTH SENT US TO SEEK LIFE", frozenset({3}))
    assert len(prompts) == 2 and "too long" in prompts[1]


def test_the_ship_beat_counts_only_when_the_reply_names_the_ship():
    def answer(text):
        def fake_urlopen(request, timeout):
            return io.BytesIO(json.dumps({"output_text": json.dumps({"reply": text, "told": [1, 2, 6, 9]})}).encode())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch("urllib.request.urlopen", fake_urlopen):
                return generate_reply("Where from?", told={0})

    # Beats not open yet, or unknown, never count.
    assert answer("WE CAME FROM EARTH") == ("WE CAME FROM EARTH", frozenset({1}))
    assert answer("OUR SHIP IS AURORA") == ("OUR SHIP IS AURORA", frozenset({1, 2}))
    assert answer("WE ARE THE CREW OF AURORA") == ("WE ARE THE CREW OF AURORA", frozenset({1, 2}))
