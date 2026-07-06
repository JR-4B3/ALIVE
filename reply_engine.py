from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from audio_message import sanitize_message


MAX_REPLY_CHARS = 20
DEFAULT_REPLY = "SIGNAL WEAK"
DEFAULT_MODEL = "gpt-5.4-mini"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def normalize_reply(text: str, max_chars: int = MAX_REPLY_CHARS) -> str:
    cleaned = sanitize_message(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= max_chars:
        return cleaned

    truncated = cleaned[:max_chars].rstrip()
    if " " in truncated:
        by_word = truncated.rsplit(" ", 1)[0].strip()
        if by_word:
            return by_word
    return truncated or DEFAULT_REPLY


def generate_reply(player_text: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return fallback_reply(player_text)

    prompt = build_prompt(player_text)
    payload = {
        "model": os.environ.get("ALIVE_OPENAI_MODEL", DEFAULT_MODEL),
        "input": prompt,
        "max_output_tokens": 24,
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
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[LLM] Falling back after OpenAI request failed: {exc}")
        return fallback_reply(player_text)

    reply = extract_response_text(body)
    normalized = normalize_reply(reply)
    return normalized or fallback_reply(player_text)


def build_prompt(player_text: str) -> str:
    player = player_text.strip()[:240]
    return "\n".join(
        [
            "You are a frightened survivor on a lost space station.",
            "Reply in exactly one short sentence.",
            f"Use only A-Z letters and spaces, maximum {MAX_REPLY_CHARS} characters.",
            "Do not explain rules. Do not reveal puzzle answers.",
            f"Player says: {player}",
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


def fallback_reply(player_text: str) -> str:
    clean = normalize_reply(player_text)
    if any(word in clean.split() for word in ("HELLO", "ALIVE", "HERE")):
        return "I AM HERE"
    if any(word in clean.split() for word in ("HELP", "SOS")):
        return "FIND RING C"
    if "?" in player_text:
        return "SIGNAL WEAK"
    return DEFAULT_REPLY
