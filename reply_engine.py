from __future__ import annotations

import json
import os
import random
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Collection, Sequence

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


def fade(text: str, rng: random.Random | None = None, rate: float = 0.08) -> str:
    """Drop some letters, as a dying signal would, but never a word's first
    letter and never from AURORA, the name visitors should take home."""
    rng = rng or random.Random()
    return " ".join(word if word == "AURORA" else word[0] + "".join(char for char in word[1:] if rng.random() >= rate)
                    for word in text.split())


def normalize_reply(text: str, max_chars: int = MAX_REPLY_CHARS) -> str:
    cleaned = sanitize_message(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    while len(cleaned) > max_chars or signal_duration_seconds(cleaned) > MAX_SIGNAL_SECONDS:
        if not cleaned:
            break
        shorter = cleaned.rsplit(" ", 1)[0] if " " in cleaned else cleaned[:-1]
        cleaned = shorter.strip()
    return cleaned


def generate_reply(player_text: str, history: Sequence[tuple[str, str]] = (), told: Collection[int] = (),
                   push: bool = False) -> tuple[str, frozenset[int]]:
    """Reply to a visitor and return the story beats the reply told. History
    holds their earlier (message, reply) turns, told the beats already told.
    With push, the visitor has given the beacon little to answer for a while."""
    load_local_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ReplyUnavailableError("OpenAI API key is not configured on the API server")

    def ask(instructions: str) -> tuple[str, list[object]]:
        payload = {
            "model": os.environ.get("ALIVE_OPENAI_MODEL", DEFAULT_MODEL),
            "instructions": instructions,
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
                    "properties": {"reply": {"type": "string"},
                                   "told": {"type": "array", "items": {"type": "integer"}}},
                    "required": ["reply", "told"],
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
        # A model without structured output still gives a usable reply.
        if not isinstance(parsed, dict):
            return raw, []
        shared = parsed.get("told")
        return str(parsed.get("reply") or ""), shared if isinstance(shared, list) else []

    instructions = build_prompt(told, push)
    text, shared = ask(instructions)
    # A reply cut to fit the transmitter would end mid-sentence, so a long one
    # gets one more try.
    if len(re.sub(r"\s+", " ", sanitize_message(text))) > MAX_REPLY_CHARS:
        text, shared = ask(instructions + f"\nYour reply was too long. Stay under {MAX_REPLY_CHARS} characters.")
    normalized = normalize_reply(text)
    if not normalized:
        raise ReplyUnavailableError("OpenAI returned no usable signal text")
    beats = open_beats(told)
    # Told to say goodbye, the reply is the goodbye, whatever the model reports.
    if beats == [GOODBYE]:
        return normalized, frozenset(beats)
    reported = {beat for beat in shared if beat in beats and beat not in BEAT_WORDS}
    reported |= {beat for beat, word in BEAT_WORDS.items() if word in normalized}
    reported |= {beat for beat, words in BEAT_HINTS.items() if beat in beats and any(word in normalized for word in words)}
    return normalized, frozenset(reported)


STORY = ("You are the crew of AURORA. Earth secretly sent your ship to search for life beyond Earth. "
         "You recorded a signal and reported it home. Since that report, you have had no contact with Earth. "
         "Someone at a listening station on Earth just decoded your signal and wrote to you.")
# What the visitor should learn. The first comes first, so the signal stays
# a mystery for a while; the goodbye comes once all others are told. The rest
# come in whatever order the visitor asks.
BEATS = (
    "you have called for a very long time and nobody answered",
    "you are humans from Earth",
    "your ship is called AURORA",
    "Earth sent you in secret to search for life beyond Earth",
    "you recorded a signal out here and reported it home",
    "since that report, you have had no contact with Earth",
    "this is goodbye, and they should remember AURORA",
)
GOODBYE = len(BEATS) - 1
# The model sometimes claims it told a beat it skipped, or tells one it does
# not report. A reply tells a beat in BEAT_WORDS exactly when it holds the
# word, and one in BEAT_HINTS also when it holds one of the words.
BEAT_WORDS = {2: "AURORA"}
BEAT_HINTS = {1: ("HUMAN", "CREW"), 3: ("SECRET", "SEARCH"), 4: ("REPORT",), 5: ("CONTACT", "SILENT", "QUIET")}
FORMAT = (f"Answer plainly in one short sentence of at most six words and {MAX_REPLY_CHARS} characters, "
          "uppercase letters and spaces only. Speak like scientists; never say alien.")


def open_beats(told: Collection[int] = ()) -> list[int]:
    """The beats a reply may tell now."""
    untold = [beat for beat in range(len(BEATS)) if beat not in told]
    if 0 in untold:
        return [0]
    return [beat for beat in untold if beat != GOODBYE] or untold


def build_prompt(told: Collection[int] = (), push: bool = False) -> str:
    beats = open_beats(told)
    lines = [
        STORY,
        "You are stranded, tired, and serious. Answer their questions about you and your situation honestly.",
        "If a question is trivial or silly, react as people in your situation would, briefly.",
        "If they ask how to help, all you want is to be remembered.",
    ]
    if beats == [GOODBYE]:
        lines.append("Everything is said. Whatever they wrote, this reply says goodbye and asks them to remember AURORA.")
    else:
        if beats == [0]:
            lines.append("Stay vague about who you are for now.")
        lines.append("Facts they do not know yet. Share one when they ask or when it fits:")
        lines += [f"{beat}: {BEATS[beat]}" for beat in beats]
        if push:
            lines.append("They give you little to answer. Share one of these facts now.")
    lines += [FORMAT, "Answer with JSON: reply is your signal text, told lists the numbers of the facts "
                      "your reply shares."]
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
