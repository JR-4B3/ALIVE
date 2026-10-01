from __future__ import annotations

import argparse
import io
import hmac
import json
import mimetypes
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from reply_engine import (
    MAX_REPLY_CHARS, ReplyUnavailableError, generate_reply, normalize_reply,
    sanitize_message, signal_duration_seconds,
)


DEFAULT_MESSAGE = "WE ARE HERE"
STATIC_PHONE_APP = Path(__file__).parent / "docs" / "index.html"
RECEIVER_CAPTURES = Path.home() / ".local" / "state" / "alive" / "receiver-captures"


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
    metadata.write_text(json.dumps({"message": sanitize_message(message)[:20], "sampleRate": rate,
                                    "seconds": frames / rate}), encoding="utf-8")
    return name


class ApiState:
    """Prepared reply and one-time Wi-Fi play command state."""

    def __init__(self, message: str = DEFAULT_MESSAGE, state_file: Path | None = None) -> None:
        self.initial_message = normalize_reply(message) or "ALIVE"
        self.latest_reply = self.initial_message
        self.reply_revision = 0
        self.sound_direction = "original"
        self._lock = threading.Lock()
        self._device_last_seen_at = 0.0
        self._public_message_window_at = time.monotonic()
        self._public_message_count = 0
        self._public_message_last_at = 0.0
        self._public_play_ready_at = 0.0
        self.state_file = state_file
        if state_file and state_file.is_file():
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self.latest_reply = normalize_reply(str(saved.get("message", ""))) or self.latest_reply
                self.reply_revision = max(0, int(saved.get("revision", 0)))

    def _save_state(self) -> None:
        if self.state_file is None:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"message": self.latest_reply, "revision": self.reply_revision}),
                             encoding="utf-8")
        os.replace(temporary, self.state_file)

    def note_device_poll(self) -> None:
        with self._lock:
            self._device_last_seen_at = time.monotonic()

    def reserve_public_message(self) -> int:
        """Bound public model usage even when callers bypass the browser UI."""
        with self._lock:
            now = time.monotonic()
            if now - self._public_message_window_at >= 86400:
                self._public_message_window_at = now
                self._public_message_count = 0
            if self._public_message_count >= 300:
                return -1
            wait = 10 - (now - self._public_message_last_at)
            if self._public_message_count and wait > 0:
                return max(1, int(wait + 0.999))
            self._public_message_last_at = now
            self._public_message_count += 1
            return 0

    def reserve_public_play(self, sound_direction: str = "original") -> int:
        with self._lock:
            now = time.monotonic()
            wait = self._public_play_ready_at - now
            if wait > 0:
                return max(1, int(wait + 0.999))
            duration = signal_duration_seconds(self.latest_reply) + (3.95 if sound_direction != "original" else 0)
            self._public_play_ready_at = now + max(2.0, duration + 0.5)
            return 0

    def current_emitter_message(self) -> dict[str, object]:
        with self._lock:
            return self._current_message()

    def _current_message(self) -> dict[str, object]:
        """Build a response while holding the state lock."""
        return {
            "emitterId": "main",
            "revision": self.reply_revision,
            "message": self.latest_reply,
            "mode": "language",
            "maxChars": MAX_REPLY_CHARS,
            "duration": signal_duration_seconds(self.latest_reply) + (3.95 if self.sound_direction != "original" else 0),
            "soundDirection": self.sound_direction,
            "replayAfterSeconds": max(0, round(self._public_play_ready_at - time.monotonic(), 3)),
            "active": False,
            "output": "esp32",
            "deviceOnline": time.monotonic() - self._device_last_seen_at < 5,
        }

    def set_reply(self, reply: str) -> dict[str, object]:
        cleaned = normalize_reply(reply) or "ALIVE"
        with self._lock:
            self.latest_reply = cleaned
            self._save_state()
            return self._current_message()

    def reset_reply(self) -> dict[str, object]:
        return self.set_reply(self.initial_message)

    def play_current_once(self, sound_direction: str = "original") -> dict[str, object]:
        if sound_direction not in {"original", "drift", "beacon", "chorus"}:
            raise ValueError("Unknown sound direction")
        with self._lock:
            if time.monotonic() - self._device_last_seen_at >= 5:
                raise TimeoutError("ESP32 is offline; check its Wi-Fi connection")
            self.sound_direction = sound_direction
            self.reply_revision += 1
            self._save_state()
            return self._current_message()


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)


def make_handler(state: ApiState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVEEmitter/0.4"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/emitter/main/current":
                if self._authorized("ALIVE_DEVICE_TOKEN"):
                    state.note_device_poll()
                    self._send_json(state.current_emitter_message())
                return
            if parsed.path.startswith("/api/") and not self._authorized("ALIVE_WEB_TOKEN"):
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
            public_action = parsed.path in {"/api/message", "/api/emitter/main/play"} and \
                os.environ.get("ALIVE_PUBLIC_DEMO") == "1"
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
                self._send_json(state.reset_reply())
                return
            if parsed.path == "/api/emitter/main/play":
                try:
                    payload = self._read_json()
                    sound = str(payload.get("soundDirection", "original"))
                    if sound not in {"original", "drift", "beacon", "chorus"}:
                        raise ValueError("Unknown sound direction")
                    if public_action:
                        if not state.current_emitter_message()["deviceOnline"]:
                            raise TimeoutError("ESP32 is offline; check its Wi-Fi connection")
                        wait = state.reserve_public_play(sound)
                        if wait:
                            self._send_json({"error": f"Wait {wait}s before replaying"}, HTTPStatus.TOO_MANY_REQUESTS)
                            return
                    self._send_json(state.play_current_once(sound))
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except (OSError, TimeoutError) as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _authorized(self, token_name: str) -> bool:
            expected = os.environ.get(token_name, "")
            if not expected:
                return True
            supplied = self.headers.get("authorization", "").removeprefix("Bearer ")
            if hmac.compare_digest(supplied, expected):
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
            if public_action:
                wait = state.reserve_public_message()
                if wait:
                    message = "Daily message limit reached" if wait < 0 else f"Wait {wait}s before sending again"
                    self._send_json({"error": message}, HTTPStatus.TOO_MANY_REQUESTS)
                    return
            try:
                reply = generate_reply(player_text)
            except ReplyUnavailableError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            current = state.set_reply(reply)
            self._send_json({"reply": current["message"], **current})

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


def main() -> int:
    parser = argparse.ArgumentParser(description="ALIVE Wi-Fi emitter API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--message", default=DEFAULT_MESSAGE,
                        help="initial reply restored by the operator reset action")
    parser.add_argument("--http", action="store_true", help="Use HTTP behind a trusted HTTPS proxy")
    args = parser.parse_args()

    state_path = os.environ.get("ALIVE_STATE_FILE")
    state = ApiState(args.message, state_file=Path(state_path) if state_path else None)
    ip = local_ip()
    server = QuietThreadingHTTPServer((args.host, args.port), make_handler(state))
    https_active = not args.http and apply_https(server, ip)
    scheme = "https" if https_active else "http"
    url = f"{scheme}://{ip}:{args.port}/"
    print(f"ALIVE Wi-Fi emitter API: {url}")
    print(f"Prepared message: {state.current_emitter_message()['message']}")
    print("Operator token: configured" if os.environ.get("ALIVE_WEB_TOKEN") else
          "Operator token: not configured")
    if https_active:
        print("[HTTPS] A phone may need to trust the local test certificate")
    elif not args.http:
        print("[HTTPS] Local certificate unavailable; serving HTTP")
    print_qr_hint(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[stopped]")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
