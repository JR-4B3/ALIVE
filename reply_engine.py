from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from audio_message import BURST_LEN, LANGUAGE_LOOP_PAUSE_S, encoded_gap_ms, sanitize_message


MAX_REPLY_CHARS = 12
MAX_SIGNAL_SECONDS = 15.0
DEVICE_LEAD_SECONDS = 0.25
DEFAULT_MODEL = "gpt-6-luna"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
API_KEY_FILE = Path.home() / ".config" / "alive" / "openai_api_key"
LOCAL_ENV_FILE = Path(__file__).with_name(".env")


def load_local_env(path: Path = LOCAL_ENV_FILE) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or key not in {"OPENAI_API_KEY", "ALIVE_OPENAI_MODEL"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        if value:
            os.environ.setdefault(key, value)


class ReplyUnavailableError(RuntimeError):
    """The requested model could not prepare a reply."""


def signal_duration_seconds(text: str) -> float:
    return DEVICE_LEAD_SECONDS + LANGUAGE_LOOP_PAUSE_S + sum(
        BURST_LEN + encoded_gap_ms(char) / 1000 for char in text
    )


def normalize_reply(text: str, max_chars: int = MAX_REPLY_CHARS) -> str:
    cleaned = sanitize_message(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    while len(cleaned) > max_chars or signal_duration_seconds(cleaned) > MAX_SIGNAL_SECONDS:
        if not cleaned:
            break
        shorter = cleaned.rsplit(" ", 1)[0] if " " in cleaned else cleaned[:-1]
        cleaned = shorter.strip()
    return cleaned


def generate_reply(player_text: str) -> str:
    load_local_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        try:
            api_key = API_KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    if not api_key:
        raise ReplyUnavailableError("OpenAI API key is not configured on the laptop")

    payload = {
        "model": os.environ.get("ALIVE_OPENAI_MODEL", DEFAULT_MODEL),
        "instructions": build_prompt(),
        "input": player_text.strip()[:240],
        "reasoning": {"effort": "none"},
        "max_output_tokens": 40,
    }
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ReplyUnavailableError("OpenAI API key was rejected (HTTP 401)") from exc
        raise ReplyUnavailableError(f"OpenAI request failed (HTTP {exc.code})") from exc
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ReplyUnavailableError(f"OpenAI request failed: {type(exc).__name__}") from exc

    reply = extract_response_text(body)
    normalized = normalize_reply(reply)
    if not normalized:
        raise ReplyUnavailableError("OpenAI returned no usable signal text")
    return normalized


def build_prompt() -> str:
    return "\n".join(
        [
            "You are LANTERN, the last emergency beacon of the survey ship AURORA.",
            "Your crew launched you decades ago to help anyone who crossed this route.",
            "You remember fragments of their journey. Speak with calm urgency and a trace of longing.",
            "Answer the visitor's message directly. Give useful guidance when you can; admit uncertainty briefly.",
            "Your transmitter has room for only one tiny burst.",
            f"Reply with one to three short words, at most {MAX_REPLY_CHARS} characters total.",
            "Use only uppercase A to Z and spaces. No punctuation, numbers, labels, or explanation.",
            "Examples of the required length: STAY CLOSE, SEEK SHELTER, WE ARE HERE.",
        ]
    )


def extract_response_text(body: dict[str, object]) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str):
        return output_text

    output = body.get("output")
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return " ".join(chunks)
