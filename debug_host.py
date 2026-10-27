#!/usr/bin/env python3
"""Start an ALIVE test from this computer, such as the MacBook at the venue.

    python3 debug_host.py         # your real units, through the API on the T480,
                                  # or on this computer when the T480 does not answer
    python3 debug_host.py -local # your real units, through an API on this computer
    python3 debug_host.py -sim   # no unit: this computer plays the signals
    python3 debug_host.py -kill   # stop every running debug host

Both modes serve the debug page over HTTPS for a phone on the same network and
print a QR code. The page's /api/* requests go through this script, which adds
the operator token, so nothing needs pasting. Run with --help for options.
"""
from __future__ import annotations

import argparse
import errno
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from simple_qr import terminal_qr

ROOT = Path(__file__).resolve().parent
DEBUG_APP_DIR = ROOT / "docs" / "debug"
DEBUG_APP = DEBUG_APP_DIR / "index.html"
SERVER_API = os.environ.get("ALIVE_API_URL", "https://t480.tail688a7b.ts.net")
VISITOR_PAGE = "https://jr-4b3.github.io/ALIVE/"
# The API on the T480 as seen from its own hotspot, ALIVE-T480.
HOTSPOT_API = "http://10.42.7.1:8765"
# The T480 runs the API, at the venue during the show. Secrets missing here are fetched from it once
# over SSH and kept in CONFIG_DIR, readable only by this user.
SERVER_SSH = os.environ.get("ALIVE_SERVER_SSH", "t480")
CONFIG_DIR = Path.home() / ".config" / "alive"
SECRETS_H = ROOT / "firmware" / "esp32_i2s_emitter" / "include" / "secrets.h"
MAX_REQUEST_BYTES = 12_000_000
# A locally administered MAC address, so it never matches a real board.
SPEAKER_BOARD = "02:A1:1E:00:00:02"
# Without the T480, boards on this computer's network poll the API here. They
# find it through this mDNS service, which the firmware looks up.
BOARD_API_PORT = 8765
BOARD_API_SERVICE = "_alive-api._tcp"


def running_debug_hosts() -> set[int]:
    """debug_host.py processes of this user, from any location."""
    listing = subprocess.run(["ps", "-U", str(os.getuid()), "-o", "pid=,command="],
                             capture_output=True, text=True, check=True).stdout
    hosts = set()
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        arguments = command.split()
        if (pid.isdecimal() and int(pid) != os.getpid() and "-kill" not in arguments
                and "--kill" not in arguments
                and any(Path(argument).name == "debug_host.py" for argument in arguments[1:])):
            hosts.add(int(pid))
    return hosts


def kill_debug_hosts() -> int:
    try:
        hosts = running_debug_hosts()
        if not hosts:
            print("No debug hosts are running.")
            return 0
        for sig, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
            for pid in hosts & running_debug_hosts():
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                if not hosts & running_debug_hosts():
                    print(f"Stopped {len(hosts)} debug host(s).")
                    return 0
                time.sleep(0.1)
        print("Some debug hosts could not be stopped.", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not stop debug hosts: {exc}", file=sys.stderr)
        return 1


def build_debug_app() -> bool:
    web_dir = ROOT / "web"
    runner = next((name for name in ("bun", "npm") if shutil.which(name)), None)
    if runner is None:
        print("[build] neither bun nor npm found; run: cd web && bun install && bun run build:debug")
        return False
    print(f"[build] building the debugging page with {runner}…")
    completed = subprocess.run([runner, "run", "build:debug"], cwd=web_dir)
    return completed.returncode == 0 and DEBUG_APP.exists()


def local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def ensure_self_signed_cert(ip_address: str) -> tuple[Path, Path] | None:
    # One certificate per address, since the computer moves between networks.
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    cert = CONFIG_DIR / f"debug-cert-{ip_address}.pem"
    key = CONFIG_DIR / f"debug-key-{ip_address}.pem"
    if cert.exists() and key.exists():
        return cert, key
    config = CONFIG_DIR / "debug-openssl.cnf"
    config.write_text("\n".join([
        "[req]", "distinguished_name=req_distinguished_name", "x509_extensions=v3_req", "prompt=no",
        "[req_distinguished_name]", "CN=ALIVE local demo",
        "[v3_req]", f"subjectAltName=IP:{ip_address},DNS:localhost,IP:127.0.0.1", "",
    ]), encoding="utf-8")
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", str(key),
                        "-out", str(cert), "-days", "30", "-nodes", "-config", str(config)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


def load_secret(env_name: str, file_name: str, remote_command: str) -> tuple[str, str]:
    """The secret and where it came from, or two empty strings. Never printed."""
    value = os.environ.get(env_name, "").strip()
    if value:
        return value, f"${env_name}"
    path = CONFIG_DIR / file_name
    if path.is_file() and path.read_text(encoding="utf-8").strip():
        return path.read_text(encoding="utf-8").strip(), f"~/.config/alive/{file_name}"
    # On the server itself the command runs here instead.
    command = (["sh", "-c", remote_command] if socket.gethostname().split(".")[0] == SERVER_SSH else
               ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", SERVER_SSH, remote_command])
    try:
        fetched = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return "", ""
    value = fetched.stdout.strip() if fetched.returncode == 0 else ""
    if not value or "\n" in value:
        return "", ""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.touch(mode=0o600)
    path.write_text(value + "\n", encoding="utf-8")
    return value, f"fetched from {SERVER_SSH}, saved in ~/.config/alive/{file_name}"


def firmware_networks() -> list[str]:
    """Wi-Fi names in this checkout's secrets.h, in the order units try them."""
    try:
        text = SECRETS_H.read_text(encoding="utf-8")
    except OSError:
        return []
    block = re.search(r"#define\s+ALIVE_WIFI_NETWORKS((?:.*\\\n)*.*)", text)
    if block:
        return re.findall(r'\{\s*"([^"]*)"\s*,', block.group(1))
    single = re.search(r'#define\s+ALIVE_WIFI_SSID\s+"([^"]*)"', text)
    return [single.group(1)] if single else []


def open_upstream(request: urllib.request.Request, timeout: float):
    """Open the upstream request, retrying without verification for self-signed
    local HTTPS APIs."""
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", error)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        return urllib.request.urlopen(request, timeout=timeout, context=ssl._create_unverified_context())


def api_request(api: str, path: str, token: str = "", body: object = None, headers: dict | None = None,
                timeout: float = 10) -> dict:
    request = urllib.request.Request(
        f"{api.rstrip('/')}{path}", method="POST" if body is not None else "GET",
        data=None if body is None else json.dumps(body).encode(),
        headers={**({"content-type": "application/json"} if body is not None else {}),
                 **({"authorization": f"Bearer {token}"} if token else {}), **(headers or {})})
    with open_upstream(request, timeout) as response:
        return json.loads(response.read() or b"{}")


def set_random_signals(api: str, token: str, enabled: bool) -> bool:
    try:
        api_request(api, "/api/emitter/main/signals", token, {"random": enabled})
    except (OSError, ValueError) as exc:
        print(f"[signals] could not turn random signals {'on' if enabled else 'off'}: {exc}")
        return False
    print(f"[signals] random signals {'on' if enabled else 'off'}")
    return True


def stop_on_sigterm(*_: object) -> None:
    raise KeyboardInterrupt


def make_handler(upstream: str, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVEDebugHost/0.2"

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                self._proxy("GET")
                return
            self._serve_static(path)

        def do_POST(self) -> None:
            if urlparse(self.path).path.startswith("/api/"):
                self._proxy("POST")
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _proxy(self, method: str) -> None:
            try:
                length = int(self.headers.get("content-length", "0") or "0")
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_REQUEST_BYTES:
                self.close_connection = True
                self._send_json({"error": "Request is too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            body = self.rfile.read(length) if length else None
            headers = {
                name: value
                # The board headers let the page's simulated unit poll as a board.
                for name in ("content-type", "authorization", "x-alive-board", "x-alive-uptime-ms",
                             "x-alive-reset", "x-alive-network")
                if (value := self.headers.get(name))
            }
            if token and "authorization" not in headers:
                headers["authorization"] = f"Bearer {token}"
            request = urllib.request.Request(
                f"{upstream.rstrip('/')}{self.path}", data=body, headers=headers, method=method
            )
            try:
                with open_upstream(request, timeout=120) as response:
                    payload = response.read()
                    content_type = response.headers.get("content-type", "application/json")
                    status = response.status
            except urllib.error.HTTPError as error:
                payload = error.read()
                content_type = error.headers.get("content-type", "application/json")
                status = error.code
            except (urllib.error.URLError, OSError) as error:
                reason = getattr(error, "reason", error)
                self._send_json({"error": f"API upstream unreachable: {reason}"}, HTTPStatus.BAD_GATEWAY)
                return
            self._send_bytes(payload, content_type, status)

        def _serve_static(self, request_path: str) -> None:
            if request_path in {"", "/"}:
                target = DEBUG_APP
            else:
                target = (DEBUG_APP_DIR / request_path.lstrip("/")).resolve()
                try:
                    target.relative_to(DEBUG_APP_DIR.resolve())
                except ValueError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send_bytes(target.read_bytes(), content_type)

        def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(json.dumps(payload).encode("utf-8"), "application/json", status)

        def _send_bytes(self, data: bytes, content_type: str,
                        status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)


def speaker_player() -> list[str]:
    for command in (["afplay"], ["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(command[0]):
            return command
    return []


def run_speaker_unit(api: str, player: list[str], amplitude: int, stop: threading.Event) -> None:
    """Poll the API like a board and play each signal through the speakers."""
    from signals import score_seconds, score_wav

    started = time.monotonic()
    reset = "1"
    while not stop.is_set():
        try:
            reply = api_request(api, "/api/emitter/main/current", headers={
                "x-alive-board": SPEAKER_BOARD, "x-alive-uptime-ms": str(int((time.monotonic() - started) * 1000)),
                "x-alive-reset": reset, "x-alive-network": "this computer"})
        except (OSError, ValueError) as exc:
            print(f"[unit] poll failed: {exc}")
            stop.wait(2)
            continue
        reset = "3"
        play = reply.get("play")
        if play:
            text = f": {play['text']}" if play.get("text") else ""
            print(f"[unit] playing {play['kind']}{text} ({score_seconds(play):.1f} s)")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as file:
                file.write(score_wav(play, amplitude))
            try:
                subprocess.run(player + [file.name], check=False)
            finally:
                os.unlink(file.name)
        stop.wait(2)


def start_local_api(manual: bool, host: str = "127.0.0.1", port: int = 0) -> tuple[str, str]:
    """Run the API in this process, by default on a free loopback port. Returns
    its URL and a note on replies."""
    # The local API takes no tokens. On loopback this script is its only
    # caller; on the network it is a test API for boards and needs none either.
    for name in ("ALIVE_WEB_TOKEN", "ALIVE_DEVICE_TOKEN", "ALIVE_WEB_ORIGIN", "ALIVE_NOTIFY_URL"):
        os.environ.pop(name, None)
    os.environ["ALIVE_PUBLIC_DEMO"] = "1"
    key, source = load_secret(
        "OPENAI_API_KEY", "openai-key",
        "cat ~/.config/alive/openai-key 2>/dev/null || "
        "sed -n 's/^OPENAI_API_KEY=//p' ~/workspace/github.com/JR-4B3/ALIVE/.env")
    if key:
        os.environ["OPENAI_API_KEY"] = key
    import emitter

    # Real boards may still be playing a signal from before a restart, so
    # only the loopback API for -sim skips the startup silence.
    state = emitter.ApiState() if host != "127.0.0.1" else emitter.ApiState(startup_silence=0)
    if manual:
        state.set_random_signals(False)
    server = emitter.QuietThreadingHTTPServer((host, port), emitter.make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    replies = (f"on (OpenAI key from {source})" if key else
               f"off: no OpenAI key in $OPENAI_API_KEY, ~/.config/alive/openai-key, or on {SERVER_SSH}")
    return f"http://127.0.0.1:{server.server_address[1]}", replies


def advertise_board_api(port: int) -> subprocess.Popen | None:
    """Announce the API to boards on this network over mDNS until stopped."""
    for command in (["dns-sd", "-R", "ALIVE API", BOARD_API_SERVICE, "local", str(port)],
                    ["avahi-publish-service", "ALIVE API", BOARD_API_SERVICE, str(port)]):
        if shutil.which(command[0]):
            return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


def board_lines(status: dict) -> list[str]:
    boards = [board for board in status.get("boards", []) if board.get("lastPollSeconds", 999) < 60]
    if not boards:
        return ["  no unit is polling right now"]
    return [f"  {board['board']}  {board['role']:<11} via {board.get('network') or '?':<20} "
            f"last poll {board['lastPollSeconds']:.0f} s ago" for board in boards]


def watch_units(api: str, token: str, stop: threading.Event) -> None:
    """Print a line whenever a unit appears, disappears, or changes role or network."""
    known: dict[str, tuple[str, str]] = {}
    first = True
    while not stop.wait(0 if first else 5):
        try:
            status = api_request(api, "/api/status", token)
        except (OSError, ValueError):
            continue
        now = {board["board"]: (board["role"], board.get("network") or "?")
               for board in status.get("boards", []) if board.get("lastPollSeconds", 999) < 60}
        if not first:
            for board in sorted(now.keys() | known.keys()):
                if board not in now:
                    print(f"[units] {board} stopped polling")
                elif now[board] != known.get(board):
                    print(f"[units] {board} is {now[board][0]} via {now[board][1]}")
        known, first = now, False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start an ALIVE test: the debug page for a phone, plus either a unit played by "
                    "this computer (-sim) or, by default, the real units through the API on the T480. "
                    "When the T480 does not answer, or with -local, the API runs on this computer.")
    parser.add_argument("-sim", "--sim", action="store_true",
                        help="no unit needed: run the API here and play the signals through this computer")
    parser.add_argument("-local", "--local", action="store_true",
                        help="real units without the T480: run the API here for boards on this network")
    parser.add_argument("--manual", action="store_true",
                        help="no random signals; units play only what you send from the Debug panel")
    parser.add_argument("--volume", type=int, default=60, metavar="0-100",
                        help="-sim: loudness of the signals from this computer (default: %(default)s)")
    parser.add_argument("--no-speaker", action="store_true",
                        help="-sim: do not play through this computer; use 'Simulate a unit on this page' instead")
    parser.add_argument("--api", default=SERVER_API,
                        help="without -sim or -local: API the units poll; if it does not answer, the API "
                             "runs here as with -local (default: %(default)s)")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--http", action="store_true",
                        help="serve plain HTTP; phone microphones usually need HTTPS")
    parser.add_argument("--rebuild", action="store_true", help="rebuild docs/debug before serving")
    parser.add_argument("-kill", "--kill", action="store_true", help="stop all running debug hosts and exit")
    args = parser.parse_args()

    if args.kill:
        return kill_debug_hosts()
    if args.rebuild or not DEBUG_APP.exists():
        if not build_debug_app():
            return 1

    stop = threading.Event()
    lines: list[str] = []
    restore_random = False
    advertiser: subprocess.Popen | None = None
    unreachable = ""
    if not args.sim and not args.local:
        try:
            api_request(args.api, "/healthz", timeout=8)
        except (OSError, ValueError) as exc:
            unreachable = str(exc)
        # On the T480's hotspot its public address refuses this computer too,
        # so try the T480 directly before running the API here.
        if unreachable and args.api == SERVER_API:
            try:
                api_request(HOTSPOT_API, "/healthz", timeout=3)
                args.api, unreachable = HOTSPOT_API, ""
            except (OSError, ValueError):
                pass
    local_api = not args.sim and bool(args.local or unreachable)
    if args.sim:
        api, replies = start_local_api(args.manual)
        token = ""
        player = [] if args.no_speaker else speaker_player()
        lines += [
            "Mode:     -sim, no unit needed",
            f"API:      local, inside this script. Replies: {replies}",
        ]
        if player:
            amplitude = round(32767 * max(0, min(args.volume, 100)) / 100)
            threading.Thread(target=run_speaker_unit, args=(api, player, amplitude, stop), daemon=True).start()
            lines += [f"Sound:    this computer plays the signals with {player[0]}, volume {args.volume}. "
                      "Turn the system volume up and hold the phone 0.5 to 1 m from the speakers."]
        else:
            lines += ["Sound:    nothing plays here" + ("" if args.no_speaker else " (no afplay, pw-play, paplay, or aplay)")
                      + ". On the page, tap Debug and tick 'Simulate a unit on this page'."]
    elif local_api:
        try:
            api, replies = start_local_api(args.manual, "0.0.0.0", BOARD_API_PORT)
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
            print(f"Port {BOARD_API_PORT} is in use. A debug host or emitter.py may already run; stop the "
                  "debug host with 'python3 debug_host.py -kill'.", file=sys.stderr)
            return 1
        token = ""
        advertiser = advertise_board_api(BOARD_API_PORT)
        board_url = f"http://{local_ip()}:{BOARD_API_PORT}"
        lines += ["Mode:     the real units, with the API on this computer"
                  + ("" if args.local else f" because {args.api} does not answer ({unreachable})")]
        lines += [f"API:      {board_url}, inside this script. Replies: {replies}"]
        lines += ["Boards:   " + (f"they find it over mDNS ({BOARD_API_SERVICE}) when they share this "
                                  "computer's Wi-Fi" if advertiser else
                                  "not announced (no dns-sd or avahi-publish-service); boards will not find it"),
                  "          and run firmware with that lookup. They switch to it within about 10 seconds",
                  "          of losing their usual API. macOS may ask to allow incoming connections; allow them."]
        threading.Thread(target=watch_units, args=(api, token, stop), daemon=True).start()
    else:
        api = args.api
        token, source = load_secret("ALIVE_WEB_TOKEN", "operator-token", "cat ~/.config/alive/operator-token")
        lines += ["Mode:     the real units (add -sim to test without one, -local to run the API here)",
                  f"API:      {api}"]
        if token:
            lines += [f"Token:    operator token from {source}; the page needs nothing pasted"]
            try:
                status = api_request(api, "/api/status", token)
                lines += ["Units:"] + board_lines(status)
                if args.manual:
                    restore_random = set_random_signals(api, token, False)
                threading.Thread(target=watch_units, args=(api, token, stop), daemon=True).start()
            except (OSError, ValueError) as exc:
                lines += [f"Units:    status unavailable ({exc}); the API may still run older code"]
        else:
            lines += ["Token:    not found. Signal buttons, status, and reset will fail.",
                      f"          On the T480 run 'sudo deploy/install.sh' once; it saves the token where this "
                      f"script fetches it over 'ssh {SERVER_SSH}'. Or put it in ~/.config/alive/operator-token."]
    if not args.sim:
        networks = firmware_networks()
        listed = f": {' > '.join(networks)}." if networks else " (secrets.h, not in this checkout)."
        if local_api:
            lines += [
                "Networks: units must be on this computer's Wi-Fi. They join the first network of their",
                "          firmware list that is in range" + listed,
                f"Visitors: {VISITOR_PAGE} needs the T480; use the page above instead.",
            ]
        else:
            lines += [
                "Networks: units need internet over Wi-Fi, nothing else. They join the first network of",
                "          their firmware list that is in range" + listed,
                "          At HfK that is the T480's hotspot (sudo deploy/laptop-hotspot.sh status on the T480).",
                "          If it fails, turn on your phone hotspot with Maximize Compatibility; units switch",
                "          to it within about a minute. 'Units' above lists each unit's network.",
                f"Visitors: {VISITOR_PAGE} works on any phone with mobile data.",
            ]

    ip = local_ip()
    try:
        server = QuietThreadingHTTPServer(("0.0.0.0", args.port), make_handler(api, token))
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        print(f"Port {args.port} is in use. A debug host may already run; stop it with "
              "'python3 debug_host.py -kill'.", file=sys.stderr)
        return 1
    https_active = not args.http and apply_https(server, ip)
    scheme = "https" if https_active else "http"
    url = f"{scheme}://{ip}:{args.port}/"

    print("=" * 72)
    print("ALIVE debug")
    print("=" * 72)
    for line in lines:
        print(line)
    print(f"Signals:  {'only what you send (--manual)' if args.manual else 'random; add --manual to send only from the Debug panel'}")
    print(f"Page:     {url}  (phone on the same network as this computer)")
    print(f"          {scheme}://localhost:{args.port}/ on this computer")
    if https_active:
        print("          The phone shows a certificate warning once; accept it.")
    print("          Tap Debug for signal buttons, board roles, and 'reset to the first state'.")
    print("Other:    python3 debug_host.py [-sim | -local]   ·   --help for all options   ·   -kill to stop")
    try:
        print(terminal_qr(url))
    except Exception:
        print(f"[QR] {url}")

    signal.signal(signal.SIGTERM, stop_on_sigterm)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[stopped]")
    finally:
        stop.set()
        server.server_close()
        if advertiser:
            advertiser.terminate()
        if restore_random:
            set_random_signals(api, token, True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
