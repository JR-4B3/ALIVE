from __future__ import annotations

import argparse
import io
import hmac
import http.client
import json
import math
import mimetypes
import os
import random
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import wave
from collections import deque
from difflib import SequenceMatcher
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from reply_engine import ReplyUnavailableError, generate_reply, normalize_reply, sanitize_message
from signals import clock_score, clock_settings, message_score, noise_score, score_seconds


STATIC_PHONE_APP = Path(__file__).parent / "docs" / "index.html"
RECEIVER_CAPTURES = Path.home() / ".local" / "state" / "alive" / "receiver-captures"
# Boards stop polling while they play, and a reply lasts up to 25 seconds.
DEVICE_LEASE_SECONDS = 60
# Silence between two transmissions, so a phone logs them as separate signals.
AIR_GAP_SECONDS = 3.0
# Random pause before the next unprompted signal.
SIGNAL_PAUSE_SECONDS = (6.0, 20.0)
# Share of unprompted signals that are noise, a clock, or an intelligent beacon.
SIGNAL_WEIGHTS = {"noise": 0.45, "clock": 0.3, "intelligent": 0.25}
# What the intelligent board sends when nobody is talking to it.
BEACON_LINES = ("IS ANYONE THERE", "WE ARE HERE", "THIS IS LANTERN", "AURORA CALLING",
                "CAN YOU HEAR US", "ANSWER IF YOU HEAR")
# Boards get new random roles this often, unless a conversation is running.
ROLE_SECONDS = 600
CONVERSATION_HOLD_SECONDS = 180
# A visitor keeps contact this long after their phone decoded a message.
CONTACT_SECONDS = 1800
# How closely the text a phone decoded must match a transmission (0 to 1).
HEARD_MATCH = 0.6
CONVERSATION_TURNS = 6
REPLY_QUEUE_LIMIT = 3
REPLY_EXPIRY_SECONDS = 120
SESSION_MESSAGE_SECONDS = 8
PUBLIC_MESSAGES_PER_DAY = 600
# Per-board poll rows, one file per UTC day, used to time battery runtime.
POLL_LOG_DAYS = 14
# A board quiet this long while others poll has most likely lost power. Wi-Fi
# outages make boards change networks after a minute and return soon after.
BOARD_QUIET_SECONDS = 300


def save_receiver_capture(data: bytes, message: str) -> str:
    with wave.open(io.BytesIO(data), "rb") as recording:
        rate = recording.getframerate()
        frames = recording.getnframes()
        if (recording.getnchannels() != 1 or recording.getsampwidth() != 2 or
                not 8000 <= rate <= 96000 or not 0 < frames <= rate * 30):
            raise ValueError("Expected up to 30 seconds of mono PCM audio")
        if len(recording.readframes(frames)) != frames * 2:
            raise ValueError("Incomplete WAV recording")
    RECEIVER_CAPTURES.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = f"receiver-{time.time_ns()}"
    path = RECEIVER_CAPTURES / f"{name}.wav"
    path.touch(mode=0o600, exist_ok=False)
    path.write_bytes(data)
    metadata = RECEIVER_CAPTURES / f"{name}.json"
    metadata.touch(mode=0o600, exist_ok=False)
    metadata.write_text(json.dumps({"message": sanitize_message(message)[:40], "sampleRate": rate,
                                    "seconds": frames / rate}), encoding="utf-8")
    return name


class ApiState:
    """Board roles, the shared air, queued replies, and visitor conversations.

    Each board polls with its MAC address. A poll either gets nothing or a
    one-time chirp sequence to play right away. Only one board is on the air
    at a time, so signals never overlap.
    """

    def __init__(self, state_file: Path | None = None, rng: random.Random | None = None) -> None:
        self.state_file = state_file
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._device_last_seen_at = 0.0
        # Per-board monotonic poll times and battery start times for alerts.
        self._board_seen: dict[str, float] = {}
        self._board_power_on: dict[str, float] = {}
        self._quiet_alerted: set[str] = set()
        self._all_quiet_alerted = False
        self._roles: dict[str, str] = {}
        self._clocks: dict[str, tuple[int, int, int]] = {}
        self._roles_at = -math.inf
        self._air_free_at = 0.0
        self._next_signal_at = 0.0
        # The first unprompted signal after a start is a beacon, so a test
        # visit hears an intelligent message quickly.
        self._next_kind = "intelligent"
        self._replies: deque[tuple[float, str]] = deque()
        # Intelligent texts that went on the air. Repeating one back proves a
        # visitor's phone heard it.
        self._transmitted: deque[tuple[float, str]] = deque()
        self._sessions: dict[str, dict[str, object]] = {}
        self._conversation_at = -math.inf
        self._public_message_window_at = time.monotonic()
        self._public_message_count = 0

    def device_command(self, board: str = "", uptime_ms: str = "", reset: str = "") -> dict[str, object]:
        with self._lock:
            now = time.monotonic()
            self._device_last_seen_at = now
            if not (re.fullmatch(r"[0-9A-F]{2}(:[0-9A-F]{2}){5}", board) and uptime_ms.isdigit() and reset.isdigit()):
                return {"role": "dead", "play": None}
            self._log_poll(f"{board},{uptime_ms},{reset}")
            self._board_seen[board] = now
            if reset == "1":  # Power-on, e.g. a fresh battery
                self._board_power_on[board] = now - int(uptime_ms) / 1000
            self._assign_roles(now)
            return {"role": self._roles[board], "play": self._grant(board, now)}

    def _online(self, now: float) -> list[str]:
        return [board for board, seen in self._board_seen.items() if now - seen < DEVICE_LEASE_SECONDS]

    def _assign_roles(self, now: float) -> None:
        """Deal new random roles every ROLE_SECONDS and when a board joins, but
        never mid-conversation. Then a joining board gets only its own role."""
        online = self._online(now)
        conversing = bool(self._replies) or now - self._conversation_at < CONVERSATION_HOLD_SECONDS
        joined = any(board not in self._roles for board in online)
        if (joined or now - self._roles_at >= ROLE_SECONDS) and not conversing:
            self._roles_at = now
            boards = self._rng.sample(online, len(online))
            roles = ["intelligent", "clock", "noise"][:len(boards)]
            while len(roles) < len(boards):
                roles.append(self._rng.choice(["noise", "clock"] if "dead" in roles else ["noise", "clock", "dead"]))
            self._roles = dict(zip(boards, roles))
            self._clocks = {board: clock_settings(self._rng) for board in boards}
            return
        self._roles = {board: role for board, role in self._roles.items() if board in online}
        for board in online:
            if board not in self._roles:
                self._roles[board] = self._rng.choice(["noise", "clock"])
                self._clocks[board] = clock_settings(self._rng)
        if online and "intelligent" not in self._roles.values():
            self._roles[self._rng.choice(online)] = "intelligent"

    def _grant(self, board: str, now: float) -> dict[str, object] | None:
        if now < self._air_free_at:
            return None
        while self._replies and now - self._replies[0][0] > REPLY_EXPIRY_SECONDS:
            self._replies.popleft()
        role = self._roles[board]
        if self._replies:
            # Replies wait for the intelligent board; nothing else may take the air.
            if role != "intelligent":
                return None
            score = message_score(self._replies.popleft()[1])
        elif now >= self._next_signal_at:
            # A kind without a board of that role (e.g. a single board) falls
            # to any board that is not dead.
            kind = self._next_kind
            if kind in self._roles.values() and role != kind or role == "dead":
                return None
            if kind == "intelligent":
                score = message_score(self._rng.choice(BEACON_LINES))
            elif kind == "clock":
                score = clock_score(*self._clocks.setdefault(board, clock_settings(self._rng)))
            else:
                score = noise_score(self._rng)
            self._next_kind = self._rng.choices(list(SIGNAL_WEIGHTS), list(SIGNAL_WEIGHTS.values()))[0]
        else:
            return None
        if score["kind"] == "intelligent":
            self._transmitted.append((now, str(score["text"])))
            while now - self._transmitted[0][0] > CONTACT_SECONDS:
                self._transmitted.popleft()
        self._air_free_at = now + score_seconds(score) + AIR_GAP_SECONDS
        self._next_signal_at = self._air_free_at + self._rng.uniform(*SIGNAL_PAUSE_SECONDS)
        return score

    def reserve_public_message(self, session: str) -> int:
        """Bound public model usage even when callers bypass the browser UI."""
        with self._lock:
            now = time.monotonic()
            if now - self._public_message_window_at >= 86400:
                self._public_message_window_at = now
                self._public_message_count = 0
            if self._public_message_count >= PUBLIC_MESSAGES_PER_DAY:
                return -1
            wait = SESSION_MESSAGE_SECONDS - (now - float(self._sessions.get(session, {}).get("sentAt", -math.inf)))
            if wait > 0:
                return max(1, int(wait + 0.999))
            self._public_message_count += 1
            # Callers without a session share one entry, and so one limit.
            self._session(session, now)["sentAt"] = now
            return 0

    def _session(self, session: str, now: float) -> dict[str, object]:
        for key in [key for key, value in self._sessions.items() if now - float(value["at"]) > CONTACT_SECONDS]:
            del self._sessions[key]
        entry = self._sessions.setdefault(session, {"contact": False, "history": []})
        entry["at"] = now
        return entry

    def has_contact(self, session: str, heard: str) -> bool:
        """True once this visitor's phone decoded something an intelligent
        board sent. Phones may miss letters, so a close match counts."""
        heard = re.sub(r"\s+", " ", sanitize_message(heard))
        with self._lock:
            now = time.monotonic()
            entry = self._session(session, now) if session else {"contact": False}
            if not entry["contact"] and len(heard) >= 3:
                entry["contact"] = any(now - at < CONTACT_SECONDS and
                                       SequenceMatcher(None, heard, text).ratio() >= HEARD_MATCH
                                       for at, text in self._transmitted)
            return bool(entry["contact"])

    def conversation(self, session: str) -> list[tuple[str, str]]:
        with self._lock:
            history = self._sessions.get(session, {}).get("history", [])
            assert isinstance(history, list)
            return list(history)

    def reply_unavailable(self) -> str:
        """Why a reply could not be queued now, or an empty string."""
        with self._lock:
            now = time.monotonic()
            if not self._online(now):
                return "No unit is listening. Try again in a minute."
            if len(self._replies) >= REPLY_QUEUE_LIMIT:
                return "The channel is busy. Try again in a moment."
            return ""

    def queue_reply(self, session: str, message: str, reply: str) -> int:
        """Queue a reply for the intelligent board and return its place in line."""
        with self._lock:
            now = time.monotonic()
            self._replies.append((now, reply))
            self._conversation_at = now
            if session:
                history = self._session(session, now)["history"]
                assert isinstance(history, list)
                history.append((message, reply))
                del history[:-CONVERSATION_TURNS]
            return len(self._replies)

    def play_now(self, message: str = "") -> dict[str, object]:
        """Operator test: queue a given message, or make the next signal a beacon."""
        with self._lock:
            now = time.monotonic()
            if message:
                self._replies.append((now, message))
            else:
                self._next_kind = "intelligent"
                self._next_signal_at = now
            return self._status(now)

    def reset(self) -> dict[str, object]:
        """Operator reset: drop replies and conversations, deal new roles."""
        with self._lock:
            self._replies.clear()
            self._sessions.clear()
            self._transmitted.clear()
            self._conversation_at = self._roles_at = -math.inf
            now = time.monotonic()
            self._assign_roles(now)
            return self._status(now)

    def status(self) -> dict[str, object]:
        with self._lock:
            return self._status(time.monotonic())

    def _status(self, now: float) -> dict[str, object]:
        return {
            "deviceOnline": now - self._device_last_seen_at < DEVICE_LEASE_SECONDS,
            "boards": [{"board": board, "role": self._roles.get(board, "offline"),
                        "lastPollSeconds": round(now - seen, 1)}
                       for board, seen in sorted(self._board_seen.items())],
            "queuedReplies": len(self._replies),
            "airFreeInSeconds": max(0.0, round(self._air_free_at - now, 1)),
            "nextSignal": self._next_kind,
            "nextSignalInSeconds": max(0.0, round(self._next_signal_at - now, 1)),
        }

    def quiet_board_alerts(self) -> list[str]:
        """Return one message per newly quiet or returning board."""
        with self._lock:
            now = time.monotonic()
            alerts = []
            for board in sorted(self._quiet_alerted):
                if now - self._board_seen[board] < BOARD_QUIET_SECONDS:
                    self._quiet_alerted.discard(board)
                    alerts.append(f"ALIVE board {board} is polling again.")
            quiet = [board for board, seen in self._board_seen.items()
                     if now - seen >= BOARD_QUIET_SECONDS and board not in self._quiet_alerted]
            # When every board is quiet, blame Wi-Fi once and judge each board
            # again after the others return.
            if all(now - seen >= 60 for seen in self._board_seen.values()):
                if quiet and not self._all_quiet_alerted:
                    self._all_quiet_alerted = True
                    alerts.append(f"ALIVE: no board has polled for {BOARD_QUIET_SECONDS // 60} minutes. "
                                  "Check the Wi-Fi and the API before the batteries.")
                return alerts
            if self._all_quiet_alerted:
                self._all_quiet_alerted = False
                alerts.append("ALIVE boards are polling again.")
            self._quiet_alerted.update(quiet)
            for board in sorted(quiet):
                text = f"ALIVE board {board} stopped polling; its battery is probably empty."
                if board in self._board_power_on:
                    hours, rest = divmod(round(self._board_seen[board] - self._board_power_on[board]), 3600)
                    text += f" It ran {hours} h {rest // 60:02d} min since power-on."
                alerts.append(text)
            return alerts

    def _log_poll(self, row: str) -> None:
        """A board's last row is the moment it went quiet, e.g. its battery ran out."""
        if self.state_file is None:
            return
        now = time.time()
        folder = self.state_file.parent / "device-polls"
        path = folder / time.strftime("%Y-%m-%d.csv", time.gmtime(now))
        try:
            if not path.exists():
                folder.mkdir(parents=True, exist_ok=True)
                oldest = time.strftime("%Y-%m-%d.csv", time.gmtime(now - POLL_LOG_DAYS * 86400))
                for old in folder.glob("*.csv"):
                    if old.name < oldest:
                        old.unlink()
                path.write_text("received_utc,board,uptime_ms,reset_reason\n", encoding="utf-8")
            with path.open("a", encoding="utf-8") as file:
                file.write(time.strftime("%Y-%m-%dT%H:%M:%SZ,", time.gmtime(now)) + row + "\n")
        except OSError as exc:
            # Polling must keep working even when the log cannot be written.
            print(f"Could not log device poll: {exc}", flush=True)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)


def make_handler(state: ApiState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVEEmitter/0.4"
        # Drop clients that stall mid-request instead of holding a thread forever.
        timeout = 30

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/emitter/main/current":
                if self._authorized("ALIVE_DEVICE_TOKEN"):
                    self._send_json(state.device_command(
                        self.headers.get("x-alive-board", ""), self.headers.get("x-alive-uptime-ms", ""),
                        self.headers.get("x-alive-reset", "")))
                return
            if parsed.path == "/healthz":
                # Taking the state lock proves request handling is not wedged.
                state.status()
                self._send_json({"status": "ok"})
                return
            if parsed.path.startswith("/api/") and not self._authorized("ALIVE_WEB_TOKEN"):
                return
            if parsed.path == "/api/status":
                self._send_json(state.status())
                return
            if parsed.path in {"/", "/index.html"}:
                self._send_text(make_static_phone_html(), "text/html; charset=utf-8")
                return
            if parsed.path.startswith("/assets/"):
                self._send_static_asset(parsed.path)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type, authorization")
            self.end_headers()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            public_action = parsed.path == "/api/message" and os.environ.get("ALIVE_PUBLIC_DEMO") == "1"
            if parsed.path.startswith("/api/") and not public_action and not self._authorized("ALIVE_WEB_TOKEN"):
                return
            if parsed.path == "/api/receiver/capture":
                try:
                    length = int(self.headers.get("content-length", "0"))
                    if not 44 <= length <= 6_000_000:
                        self.close_connection = True
                        self._send_json({"error": "Recording size is invalid"}, HTTPStatus.BAD_REQUEST)
                        return
                    message = parse_qs(parsed.query).get("message", [""])[0]
                    name = save_receiver_capture(self.rfile.read(length), message)
                    self._send_json({"saved": name})
                except (ValueError, wave.Error, EOFError) as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except OSError:
                    self._send_json({"error": "Could not save recording"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/message":
                self._handle_message_post(public_action)
                return
            if parsed.path == "/api/emitter/main/reset":
                self._send_json(state.reset())
                return
            if parsed.path == "/api/emitter/main/play":
                try:
                    payload = self._read_json()
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    return
                if not state.status()["deviceOnline"]:
                    self._send_json({"error": "No unit is polling; check its Wi-Fi connection"},
                                    HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._send_json(state.play_now(normalize_reply(str(payload.get("message") or ""))))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _has_token(self, token_name: str) -> bool:
            expected = os.environ.get(token_name, "")
            supplied = self.headers.get("authorization", "").removeprefix("Bearer ")
            return not expected or hmac.compare_digest(supplied, expected)

        def _authorized(self, token_name: str) -> bool:
            if self._has_token(token_name):
                return True
            self._send_json({"error": "Invalid API access token"}, HTTPStatus.UNAUTHORIZED)
            return False

        def _handle_message_post(self, public_action: bool = False) -> None:
            try:
                payload = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            player_text = str(payload.get("message") or payload.get("playerText") or "")
            if not player_text.strip():
                self.send_error(HTTPStatus.BAD_REQUEST, "message is required")
                return
            if len(player_text) > 120:
                self._send_json({"error": "Message must be at most 120 characters"}, HTTPStatus.BAD_REQUEST)
                return
            session = str(payload.get("session") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", session):
                session = ""
            if public_action:
                wait = state.reserve_public_message(session)
                if wait:
                    message = "Daily message limit reached" if wait < 0 else f"Wait {wait}s before sending again"
                    self._send_json({"error": message}, HTTPStatus.TOO_MANY_REQUESTS)
                    return
            # Until the visitor's phone has decoded an intelligent message, a
            # message goes nowhere: no model call and no reply.
            if not state.has_contact(session, str(payload.get("heard") or "")):
                self._send_json({"contact": False})
                return
            unavailable = state.reply_unavailable()
            if unavailable:
                self._send_json({"error": unavailable}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                reply = generate_reply(player_text, state.conversation(session))
            except ReplyUnavailableError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            position = state.queue_reply(session, player_text.strip(), reply)
            result: dict[str, object] = {"contact": True, "queued": position}
            # Visitors must decode the reply from sound; only operators see it here.
            if self._has_token("ALIVE_WEB_TOKEN"):
                result["reply"] = reply
            self._send_json(result)

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("content-length", "0") or "0")
            if length <= 0:
                return {}
            if length > 4096:
                self.close_connection = True
                raise ValueError("Message request is too large")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}

        def _send_cors_headers(self) -> None:
            origin = os.environ.get("ALIVE_WEB_ORIGIN", "")
            if not origin:
                self.send_header("access-control-allow-origin", "*")
            elif self.headers.get("origin") == origin:
                self.send_header("access-control-allow-origin", origin)
                self.send_header("vary", "Origin")
            self.send_header("access-control-allow-private-network", "true")

        def _send_text(self, text: str, content_type: str) -> None:
            self._send_bytes(text.encode("utf-8"), content_type)

        def _send_bytes(self, data: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers()
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_static_asset(self, request_path: str) -> None:
            root = STATIC_PHONE_APP.parent.resolve()
            target = (root / request_path.lstrip("/")).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send_bytes(target.read_bytes(), content_type)

    return Handler


def make_static_phone_html() -> str:
    if STATIC_PHONE_APP.exists():
        return STATIC_PHONE_APP.read_text(encoding="utf-8")
    return "<!doctype html><title>ALIVE</title><p>Build the phone app with: cd web && bun run build</p>"


def local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def ensure_self_signed_cert(ip_address: str) -> tuple[Path, Path] | None:
    cert = Path(".alive-demo-cert.pem")
    key = Path(".alive-demo-key.pem")
    if cert.exists() and key.exists():
        return cert, key

    config = Path(".alive-demo-openssl.cnf")
    config.write_text(
        "\n".join(
            [
                "[req]",
                "distinguished_name=req_distinguished_name",
                "x509_extensions=v3_req",
                "prompt=no",
                "[req_distinguished_name]",
                "CN=ALIVE local demo",
                "[v3_req]",
                f"subjectAltName=IP:{ip_address},DNS:localhost,IP:127.0.0.1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "7",
                "-nodes",
                "-config",
                str(config),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[HTTPS] Could not generate local HTTPS certificate: {exc}")
        return None
    return cert, key


def apply_https(server: ThreadingHTTPServer, ip_address: str) -> bool:
    cert_pair = ensure_self_signed_cert(ip_address)
    if cert_pair is None:
        return False
    cert, key = cert_pair
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return True


def print_qr_hint(url: str) -> None:
    try:
        from simple_qr import terminal_qr
    except Exception:
        print(f"[QR] {url}")
        return
    print(terminal_qr(url))


def notify_systemd(message: str) -> None:
    address = os.environ.get("NOTIFY_SOCKET", "")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.sendto(message.encode(), address)


def feed_systemd_watchdog(port: int, interval: float) -> None:
    """Pet systemd's watchdog only while this process still answers HTTP."""
    while True:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/healthz")
            if connection.getresponse().status == HTTPStatus.OK:
                notify_systemd("WATCHDOG=1")
        except OSError:
            pass
        finally:
            connection.close()
        time.sleep(interval)


def send_notification(url: str, text: str) -> None:
    """Post to a Discord webhook as JSON, or to any other URL (e.g. ntfy) as plain text."""
    if "discord.com/api/webhooks/" in url:
        body, content_type = json.dumps({"content": text}).encode(), "application/json"
    else:
        body, content_type = text.encode(), "text/plain; charset=utf-8"
    request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except OSError as exc:
        print(f"Could not send notification ({exc}): {text}", flush=True)
    else:
        print(f"Notification: {text}", flush=True)


def watch_boards(state: ApiState, url: str) -> None:
    while True:
        time.sleep(30)
        for text in state.quiet_board_alerts():
            send_notification(url, text)


def main() -> int:
    parser = argparse.ArgumentParser(description="ALIVE Wi-Fi emitter API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--http", action="store_true", help="Use HTTP behind a trusted HTTPS proxy")
    args = parser.parse_args()

    state_path = os.environ.get("ALIVE_STATE_FILE")
    state = ApiState(state_file=Path(state_path) if state_path else None)
    ip = local_ip()
    server = QuietThreadingHTTPServer((args.host, args.port), make_handler(state))
    https_active = not args.http and apply_https(server, ip)
    scheme = "https" if https_active else "http"
    url = f"{scheme}://{ip}:{args.port}/"
    print(f"ALIVE Wi-Fi emitter API: {url}")
    print("Operator token: configured" if os.environ.get("ALIVE_WEB_TOKEN") else
          "Operator token: not configured")
    if https_active:
        print("[HTTPS] A phone may need to trust the local test certificate")
    elif not args.http:
        print("[HTTPS] Local certificate unavailable; serving HTTP")
    print_qr_hint(url)
    notify_systemd("READY=1")
    watchdog_usec = int(os.environ.get("WATCHDOG_USEC", "0"))
    if watchdog_usec and not https_active:
        threading.Thread(target=feed_systemd_watchdog, args=(args.port, watchdog_usec / 3e6),
                         daemon=True).start()

    notify_url = os.environ.get("ALIVE_NOTIFY_URL", "")
    if notify_url:
        threading.Thread(target=watch_boards, args=(state, notify_url), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[stopped]")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
