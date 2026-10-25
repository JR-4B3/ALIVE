from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

# Ultrasound needs 0.54 s per character, so 40 characters play for 24 seconds.
MAX_REPLY_CHARS = 40
MAX_SIGNAL_SECONDS = 25.0
DEFAULT_MODEL = "gpt-6-luna"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
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


def sanitize_message(text: str) -> str:
    return "".join(char for char in text.upper() if char == " " or "A" <= char <= "Z").strip()


def signal_duration_seconds(text: str) -> float:
    """Match the ESP32's ultrasound framing: two sync chirps, one 360 ms chirp
    and 180 ms gap per character, a closing sync chirp, and the tail."""
    return round(2.45 + len(text) * 0.54, 3)


def normalize_reply(text: str, max_chars: int = MAX_REPLY_CHARS) -> str:
    cleaned = sanitize_message(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    while len(cleaned) > max_chars or signal_duration_seconds(cleaned) > MAX_SIGNAL_SECONDS:
        if not cleaned:
            break
        shorter = cleaned.rsplit(" ", 1)[0] if " " in cleaned else cleaned[:-1]
        cleaned = shorter.strip()
    return cleaned


def generate_reply(player_text: str, history: Sequence[tuple[str, str]] = ()) -> str:
    """Reply to a visitor. History holds their earlier (message, reply) turns."""
    load_local_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ReplyUnavailableError("OpenAI API key is not configured on the API server")

    payload = {
        "model": os.environ.get("ALIVE_OPENAI_MODEL", DEFAULT_MODEL),
        "instructions": build_prompt(),
        "input": [
            *({"role": role, "content": text} for turn in history
              for role, text in zip(("user", "assistant"), turn)),
            {"role": "user", "content": player_text.strip()[:240]},
        ],
        "reasoning": {"effort": "none"},
        "max_output_tokens": 60,
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
            "The visitor found you by decoding your ultrasound signal on their phone.",
            "Your transmitter sends one letter at a time, so every letter costs power.",
            f"Reply in at most {MAX_REPLY_CHARS} characters total, about two to seven short words.",
            "Use only uppercase A to Z and spaces. No punctuation, numbers, labels, or explanation.",
            "Examples of the required length: WE ARE HERE, WHO ARE YOU, OUR SHIP WENT DARK LONG AGO.",
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
