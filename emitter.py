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

from audio_message import (
    LoopingMessagePlayer,
    VALID_MODES,
    VALID_SIGNAL_TYPES,
    sanitize_message,
)
from reply_engine import MAX_REPLY_CHARS, ReplyUnavailableError, generate_reply, normalize_reply


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


class SerialMessageTransport:
    """Send a single play request to the USB-connected ESP32."""

    def __init__(self, port_name: str) -> None:
        self.port_name = port_name
        self._port = None
        self._lock = threading.Lock()

    def play(self, message: str) -> None:
        import serial

        with self._lock:
            if self._port is None or not self._port.is_open:
                self._port = serial.Serial(self.port_name, 115200, timeout=0.2, write_timeout=2)
                # Opening USB serial can reset the ESP32; wait until its receiver is ready.
                time.sleep(1.5)
                self._port.reset_input_buffer()
            self._port.write(f"PLAY {message}\n".encode("ascii"))
            self._port.flush()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                line = self._port.readline().decode("ascii", errors="replace").strip()
                if line == f"START {message}":
                    return
            raise TimeoutError("ESP32 did not start the play request")

    def close(self) -> None:
        if self._port is not None:
            self._port.close()


class DemoState:
    def __init__(
        self,
        player: LoopingMessagePlayer,
        device_output: bool = False,
        serial_device: SerialMessageTransport | None = None,
        state_file: Path | None = None,
    ) -> None:
        self.player = player
        self.device_output = device_output
        self.serial_device = serial_device
        self.running = True
        self.latest_reply = normalize_reply(player.message) or "ALIVE"
        self.reply_revision = 0
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
                self.player.configure(message=self.latest_reply, signal_type="language")

    def _save_state(self) -> None:
        if self.state_file is None:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"message": self.latest_reply, "revision": self.reply_revision}),
                             encoding="utf-8")
        os.replace(temporary, self.state_file)

    def snapshot(self) -> dict[str, object]:
        return self.player.snapshot()

    def note_device_poll(self) -> None:
        with self._lock:
            self._device_last_seen_at = time.monotonic()

    def reserve_public_message(self) -> int:
        """Bound public LLM usage even when callers bypass the browser UI."""
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

    def reserve_public_play(self) -> int:
        duration = float(self.player.public_snapshot()["duration"])
        with self._lock:
            now = time.monotonic()
            wait = self._public_play_ready_at - now
            if wait > 0:
                return max(1, int(wait + 0.999))
            self._public_play_ready_at = now + max(2.0, duration + 1.0)
            return 0

    def public_snapshot(self) -> dict[str, object]:
        return self.player.public_snapshot()

    def current_emitter_message(self) -> dict[str, object]:
        player_state = self.player.public_snapshot()
        with self._lock:
            return {
                "emitterId": "main",
                "revision": self.reply_revision,
                "message": self.latest_reply,
                "mode": "language",
                "maxChars": MAX_REPLY_CHARS,
                "duration": player_state["duration"],
                "active": player_state["active"],
                "output": "esp32" if self.device_output else "laptop",
                "deviceOnline": bool(self.serial_device) or
                    (self.device_output and time.monotonic() - self._device_last_seen_at < 5),
            }

    def set_reply(self, reply: str) -> dict[str, object]:
        cleaned = normalize_reply(reply) or "ALIVE"
        self.player.configure(message=cleaned, signal_type="language")
        player_state = self.player.public_snapshot()
        with self._lock:
            self.latest_reply = cleaned
            self._save_state()
            return {
                "emitterId": "main",
                "revision": self.reply_revision,
                "message": self.latest_reply,
                "mode": "language",
                "maxChars": MAX_REPLY_CHARS,
                "duration": player_state["duration"],
                "active": player_state["active"],
                "output": "esp32" if self.device_output else "laptop",
            }

    def play_current_once(self) -> dict[str, object]:
        with self._lock:
            if self.device_output and self.serial_device is None and time.monotonic() - self._device_last_seen_at >= 5:
                raise TimeoutError("ESP32 is offline; check its Wi-Fi connection")
            message = self.latest_reply
        if self.serial_device is not None:
            self.serial_device.play(message)
        elif not self.device_output:
            self.player.play_once()
        with self._lock:
            self.reply_revision += 1
            self._save_state()
        return self.current_emitter_message()


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)


def make_handler(state: DemoState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVEEmitter/0.4"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/emitter/main/current":
                if self._authorized("ALIVE_DEVICE_TOKEN"):
                    state.note_device_poll()
                    self._send_json(state.current_emitter_message())
                return
            if (parsed.path.startswith("/api/") or parsed.path == "/events") and not self._authorized("ALIVE_WEB_TOKEN"):
                return
            if parsed.path in {"/", "/index.html"}:
                self._send_text(make_static_phone_html(), "text/html; charset=utf-8")
                return
            if parsed.path.startswith("/assets/"):
                self._send_static_asset(parsed.path)
                return
            if parsed.path == "/api/state":
                self._send_json(state.public_snapshot())
                return
            if parsed.path == "/api/configure":
                self._handle_configure(parsed.query)
                return
            if parsed.path == "/events":
                self._events()
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
            if parsed.path == "/api/emitter/main/play":
                try:
                    if public_action:
                        if not state.current_emitter_message()["deviceOnline"]:
                            raise TimeoutError("ESP32 is offline; check its Wi-Fi connection")
                        wait = state.reserve_public_play()
                        if wait:
                            self._send_json({"error": f"Wait {wait}s before replaying"}, HTTPStatus.TOO_MANY_REQUESTS)
                            return
                    self._send_json(state.play_current_once())
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

        def _handle_configure(self, query: str) -> None:
            params = parse_qs(query)
            message = params.get("message", [None])[0]
            mode = params.get("mode", [None])[0]
            signal_type = params.get("signal", [None])[0]
            if mode is not None and mode not in VALID_MODES:
                self.send_error(HTTPStatus.BAD_REQUEST, "mode must be laser, horn, or vocal")
                return
            if signal_type is not None and signal_type not in VALID_SIGNAL_TYPES:
                self.send_error(HTTPStatus.BAD_REQUEST, "signal must be language, clock, or burst")
                return
            state.player.configure(message=message, mode=mode, signal_type=signal_type)
            self._send_json(state.public_snapshot())

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

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "keep-alive")
            self.end_headers()
            while state.running:
                payload = json.dumps(state.public_snapshot()).encode("utf-8")
                try:
                    self.wfile.write(b"data: " + payload + b"\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(0.1)

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


def controller_loop(state: DemoState) -> None:
    print("\nLive controls:")
    print("  start                   start the current signal")
    print("  stop                    stop the current signal")
    print("  message <text>          prepare encoded message")
    print("  ask <text>              generate a max-12-char reply")
    print("  language / clock / burst  change signal type")
    print("  status                  show current sender state")
    print("  quit                    stop the server\n")
    while state.running:
        try:
            raw = input("alive> ").strip()
        except EOFError:
            time.sleep(0.2)
            continue
        except KeyboardInterrupt:
            print()
            state.running = False
            break
        if not raw:
            continue
        command, _, value = raw.partition(" ")
        command = command.lower()
        if command in {"quit", "exit"}:
            state.running = False
        elif command == "start":
            state.player.start()
        elif command == "stop":
            state.player.stop()
        elif command == "status":
            print(json.dumps(state.snapshot(), indent=2))
        elif command == "message" and value.strip():
            cleaned = sanitize_message(value)
            if cleaned:
                state.set_reply(cleaned)
            else:
                print("[error] message must contain A-Z or spaces")
        elif command == "ask" and value.strip():
            try:
                reply = generate_reply(value)
                current = state.set_reply(reply)
                print(f"[reply] {current['message']}")
            except ReplyUnavailableError as exc:
                print(f"[LLM] {exc}")
        elif command == "signal" and value.strip():
            signal_type = value.strip().lower()
            if signal_type in VALID_SIGNAL_TYPES:
                state.player.configure(signal_type=signal_type)
            else:
                print("[error] signal must be language, clock, or burst")
        elif command in VALID_SIGNAL_TYPES:
            state.player.configure(signal_type=command)
        else:
            print("Unknown command. Try: start, stop, message HELLO WORLD, ask ARE YOU THERE, language, clock, burst, status, quit")


def main() -> int:
    parser = argparse.ArgumentParser(description="ALIVE encoded-audio emitter")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    tone = parser.add_mutually_exclusive_group()
    tone.add_argument("--laser", dest="mode", action="store_const", const="laser", default="laser")
    tone.add_argument("--horn", dest="mode", action="store_const", const="horn")
    tone.add_argument("--vocal", dest="mode", action="store_const", const="vocal")
    parser.add_argument("--signal", choices=VALID_SIGNAL_TYPES, default="language")
    parser.add_argument("--http", action="store_true", help="Use HTTP instead of local HTTPS")
    parser.add_argument("--serve-only", action="store_true", help="Run the API without the terminal controls")
    parser.add_argument(
        "--device-output",
        action="store_true",
        help="Queue replies for the ESP32 I2S emitter instead of laptop audio",
    )
    parser.add_argument("--wifi-device", action="store_true",
                        help="Queue one-shot commands for the Wi-Fi ESP32 without laptop audio")
    parser.add_argument(
        "--serial-device",
        metavar="PORT",
        help="Send one-shot play requests to an ESP32 over USB serial (for example /dev/ttyACM0)",
    )
    args = parser.parse_args()

    player = LoopingMessagePlayer(normalize_reply(args.message) or "ALIVE", args.mode, args.signal)
    serial_device = SerialMessageTransport(args.serial_device) if args.serial_device else None
    state_path = os.environ.get("ALIVE_STATE_FILE")
    state = DemoState(player, device_output=args.device_output or args.wifi_device or bool(serial_device),
                      serial_device=serial_device, state_file=Path(state_path) if state_path else None)
    ip = local_ip()
    server = QuietThreadingHTTPServer((args.host, args.port), make_handler(state))
    https_active = False
    if not args.http:
        https_active = apply_https(server, ip)
    if not args.serve_only:
        threading.Thread(target=server.serve_forever, daemon=True).start()

    scheme = "https" if https_active else "http"
    url = f"{scheme}://{ip}:{args.port}/"
    print("=" * 56)
    print("ALIVE encoded-audio emitter")
    print("=" * 56)
    print(f"Phone URL: {url}")
    print(f"Encoded message: {player.message}")
    print(f"Sound style: {player.mode}")
    print(f"Signal type: {player.signal_type}")
    print(f"Audio output: {'ESP32 / MAX98357' if state.device_output else 'laptop'}")
    if args.wifi_device:
        print("Wi-Fi ESP32: waiting for one-shot play requests; no laptop audio")
    elif serial_device is not None:
        print(f"USB serial: {serial_device.port_name}; Play signal sends once")
    else:
        print("Audio loop: stopped; type start to play the current signal")
    if https_active:
        print("[HTTPS] The phone may show a certificate warning; accept it for the local demo.")
    else:
        print("[HTTPS] HTTP mode is active. Phone microphone access may be blocked.")
    print_qr_hint(url)

    try:
        if args.serve_only:
            server.serve_forever()
        else:
            controller_loop(state)
    finally:
        state.running = False
        player.stop()
        if serial_device is not None:
            serial_device.close()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
