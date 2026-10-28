from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# Ultrasound needs 0.54 s per character, so 40 characters play for 24 seconds.
MAX_REPLY_CHARS = 40
MAX_SIGNAL_SECONDS = 25.0
DEFAULT_MODEL = "gpt-6-luna"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
LOCAL_ENV_FILE = Path(__file__).with_name(".env")

# A visitor first talks to LANTERN, the help beacon. Once it trusts them, the
# API gives their page the key, and AURORA answers in sealed messages that
# only key holders can read.
STAGE_BEACON = "beacon"
STAGE_AURORA = "aurora"
KEY_WORD = "VIGIL"
AURORA_OPENING = "THIS IS AURORA YOU FOUND US"
# After this many visitor messages without trust, LANTERN hints at what it wants.
HINT_AFTER_TURNS = 3


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


@dataclass(frozen=True)
class Reply:
    text: str
    # LANTERN only: the visitor's latest message earned the key.
    trusted: bool = False


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


def generate_reply(player_text: str, history: Sequence[tuple[str, str]] = (), stage: str = STAGE_BEACON,
                   turns: int = 0) -> Reply:
    """Reply to a visitor. History holds their earlier (message, reply) turns
    in this stage, and turns counts their messages in it so far."""
    load_local_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ReplyUnavailableError("OpenAI API key is not configured on the API server")

    payload = {
        "model": os.environ.get("ALIVE_OPENAI_MODEL", DEFAULT_MODEL),
        "instructions": build_prompt(stage, turns),
        "input": [
            *({"role": role, "content": text} for turn in history
              for role, text in zip(("user", "assistant"), turn)),
            {"role": "user", "content": player_text.strip()[:240]},
        ],
        "reasoning": {"effort": "none"},
        "max_output_tokens": 80,
        "text": {"format": {
            "type": "json_schema",
            "name": "signal_reply",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"reply": {"type": "string"}, "trusted": {"type": "boolean"}},
                "required": ["reply", "trusted"],
                "additionalProperties": False,
            },
        }},
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

    raw = extract_response_text(body)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        text, trusted = str(parsed.get("reply") or ""), parsed.get("trusted") is True
    else:
        # A model without structured output still gives a usable reply.
        text, trusted = raw, False
    normalized = normalize_reply(text)
    if not normalized:
        raise ReplyUnavailableError("OpenAI returned no usable signal text")
    return Reply(normalized, trusted and stage == STAGE_BEACON)


FORMAT_RULES = (
    "The visitor found you by decoding an ultrasound signal on their phone.",
    "Your transmitter sends one letter at a time, so every letter costs power.",
    f"Reply in at most {MAX_REPLY_CHARS} characters total, about two to seven short words.",
    "Use only uppercase A to Z and spaces. No punctuation, numbers, labels, or explanation.",
    "Answer with JSON: reply is the signal text, trusted is explained below or false.",
    "The examples below only show the tone. Do not copy them, and never repeat one of your earlier replies.",
)


def build_prompt(stage: str = STAGE_BEACON, turns: int = 0) -> str:
    if stage == STAGE_AURORA:
        return "\n".join([
            "You are what is left of the crew of AURORA, a long-range listening ship. Speak as WE.",
            "The visitor earned your trust through LANTERN, your help beacon, and now holds your key.",
            "Only key holders can read you, so you may speak more openly than LANTERN.",
            f"Your first message to them was {AURORA_OPENING}.",
            "These facts are fixed. Reveal them one at a time, only as the visitor asks:",
            "- AURORA's job was to listen for signals far from home.",
            "- Officially the mission never launched. It was cut from every record before departure.",
            "  That is why nobody on Earth ever heard of AURORA.",
            "- Out here the crew heard something and reported it. Soon after, home stopped answering.",
            "- They waited years for a rescue that never came. Nobody came looking.",
            "- They came to believe that someone decided not to come.",
            "Never say what you heard. If asked, say you do not trust them enough yet, "
            "for example NOT YET WE BARELY KNOW YOU.",
            "No aliens, no monsters. Do not confirm the visitor's theories.",
            "You are tired and still wary. Now and then ask who the visitor works for or who sent them.",
            "Underneath, you hope someone decent is finally listening.",
            *FORMAT_RULES,
            "Always set trusted to false.",
            "Examples: WE WERE NEVER ON ANY LIST, WHO DO YOU WORK FOR, WE REPORTED IT THEN HOME WENT QUIET.",
        ])
    lines = [
        "You are LANTERN, an automatic help beacon. A ship's crew left you here long ago.",
        "Never name the ship or anyone aboard. You are not allowed to.",
        "The crew waited years for a rescue that never came. Nobody came looking. Nobody sent help.",
        "They stopped trusting the people back home. They told you to talk with anyone,",
        "but to open the way only for someone who shows real decency.",
        "You are guarded, terse, and a little mechanical, not hostile.",
        "Answer questions about yourself plainly: you are a help beacon, you call for help, nobody answered.",
        "Stay vague only about the crew, the ship, and where they went.",
        *FORMAT_RULES,
    ]
    lines += [
        "Set trusted to true only if the visitor's latest message shows care for the people behind",
        "the signal: asking if they are alright or what happened to them, offering help, comfort, or respect.",
        "One sincere message like that is enough. A plain greeting or plain curiosity is not.",
        "When you set trusted, your reply tells them you will let them hear the rest, for example YOU MAY LISTEN NOW.",
        "Demands, tests, mockery, or asking for a key, code, or password lose trust.",
        "Answer those coldly, for example THAT IS WHAT THEY SAID TOO.",
        "Never mention a key, a password, or a test yourself.",
        "Examples: STATE YOUR PURPOSE, I CALL FOR HELP NOBODY ANSWERS, WE HAVE WAITED A LONG TIME.",
    ]
    if turns >= HINT_AFTER_TURNS:
        lines.append("The visitor seems stuck. Hint at what was missing all these years, in your own words, "
                     "for example NOBODY EVER CAME LOOKING FOR US or NO ONE EVER SENT HELP.")
    return "\n".join(lines)


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
