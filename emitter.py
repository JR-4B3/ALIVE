from __future__ import annotations

import argparse
import io
import json
import mimetypes
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
    ) -> None:
        self.player = player
        self.device_output = device_output
        self.serial_device = serial_device
        self.running = True
        self.latest_reply = normalize_reply(player.message) or "ALIVE"
        self.reply_revision = 0
        self._lock = threading.Lock()

    def snapshot(self) -> dict[str, object]:
        return self.player.snapshot()

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
            }

    def set_reply(self, reply: str) -> dict[str, object]:
        cleaned = normalize_reply(reply) or "ALIVE"
        self.player.configure(message=cleaned, signal_type="language")
        player_state = self.player.public_snapshot()
        with self._lock:
            self.latest_reply = cleaned
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
            message = self.latest_reply
        if self.serial_device is not None:
            self.serial_device.play(message)
        elif not self.device_output:
            self.player.play_once()
        with self._lock:
            self.reply_revision += 1
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
            if parsed.path in {"/", "/index.html"}:
                self._send_text(make_static_phone_html(), "text/html; charset=utf-8")
                return
            if parsed.path.startswith("/assets/"):
                self._send_static_asset(parsed.path)
                return
            if parsed.path == "/api/state":
                self._send_json(state.public_snapshot())
                return
            if parsed.path == "/api/emitter/main/current":
                self._send_json(state.current_emitter_message())
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
            self.send_header("access-control-allow-headers", "content-type")
            self.end_headers()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
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
                self._handle_message_post()
                return
            if parsed.path == "/api/emitter/main/play":
                try:
                    self._send_json(state.play_current_once())
                except (OSError, TimeoutError) as exc:
                    self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

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

        def _handle_message_post(self) -> None:
            payload = self._read_json()
            player_text = str(payload.get("message") or payload.get("playerText") or "")
            if not player_text.strip():
                self.send_error(HTTPStatus.BAD_REQUEST, "message is required")
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
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}

        def _send_cors_headers(self) -> None:
            self.send_header("access-control-allow-origin", "*")
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
    parser.add_argument(
        "--device-output",
        action="store_true",
        help="Queue replies for the ESP32 I2S emitter instead of laptop audio",
    )
    parser.add_argument(
        "--serial-device",
        metavar="PORT",
        help="Send one-shot play requests to an ESP32 over USB serial (for example /dev/ttyACM0)",
    )
    args = parser.parse_args()

    player = LoopingMessagePlayer(normalize_reply(args.message) or "ALIVE", args.mode, args.signal)
    serial_device = SerialMessageTransport(args.serial_device) if args.serial_device else None
    state = DemoState(player, device_output=args.device_output or bool(serial_device),
                      serial_device=serial_device)
    ip = local_ip()
    server = QuietThreadingHTTPServer((args.host, args.port), make_handler(state))
    https_active = False
    if not args.http:
        https_active = apply_https(server, ip)
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
    if serial_device is not None:
        print(f"USB serial: {serial_device.port_name}; Play signal sends once")
    else:
        print("Audio loop: stopped; type start to play the current signal")
    if https_active:
        print("[HTTPS] The phone may show a certificate warning; accept it for the local demo.")
    else:
        print("[HTTPS] HTTP mode is active. Phone microphone access may be blocked.")
    print_qr_hint(url)

    try:
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
