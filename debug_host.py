#!/usr/bin/env python3
"""Serve the ALIVE debugging page on the local network and print its QR code.

GitHub Pages stays the clean visitor page. For testing, this script hosts the
debugging build of the same page (docs/debug) from this computer: microphone
and room levels, tone/stream diagnostics, connection settings, and the
diagnostic recording upload. Run it, then scan the printed QR code or type the
printed URL/IP with the phone.

    python debug_host.py                                        # laptop emitter API
    python debug_host.py --api https://ds720.tail688a7b.ts.net  # NAS API

Requests the page sends to /api/* are proxied to that upstream, so the phone
talks to this one origin only: no CORS setup and no certificate problems
between the phone and the API.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import socket
import ssl
import subprocess
import sys
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
DEFAULT_API = "https://127.0.0.1:8765"
MAX_REQUEST_BYTES = 12_000_000


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


def open_upstream(request: urllib.request.Request, timeout: float):
    """Open the upstream request, retrying without verification for self-signed
    local APIs such as the laptop emitter's HTTPS."""
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", error)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        print("[proxy] upstream certificate is not trusted; retrying without verification")
        return urllib.request.urlopen(
            request, timeout=timeout, context=ssl._create_unverified_context()
        )


def make_handler(upstream: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVEDebugHost/0.1"

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

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type, authorization")
            self.end_headers()

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
                for name in ("content-type", "authorization")
                if (value := self.headers.get(name))
            }
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

        def _send_cors_headers(self) -> None:
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-private-network", "true")

        def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(json.dumps(payload).encode("utf-8"), "application/json", status)

        def _send_bytes(self, data: bytes, content_type: str,
                        status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self._send_cors_headers()
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Host the ALIVE debugging page on the local network and print its QR code"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--api", default=DEFAULT_API,
                        help="upstream API for /api/* (default: %(default)s)")
    parser.add_argument("--http", action="store_true",
                        help="serve plain HTTP; phone microphone access usually needs HTTPS")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild docs/debug before serving")
    args = parser.parse_args()

    if args.rebuild or not DEBUG_APP.exists():
        if not build_debug_app():
            return 1

    ip = local_ip()
    server = QuietThreadingHTTPServer((args.host, args.port), make_handler(args.api))
    https_active = False
    if not args.http:
        https_active = apply_https(server, ip)
    scheme = "https" if https_active else "http"
    url = f"{scheme}://{ip}:{args.port}/"
    local_url = f"{scheme}://localhost:{args.port}/"

    print("=" * 56)
    print("ALIVE debugging page")
    print("=" * 56)
    print(f"Phone URL: {url}")
    print(f"Also try:  {local_url}")
    print(f"API proxy: {args.api}  (page requests to /api/* go there)")
    if https_active:
        print("[HTTPS] The phone may show a certificate warning; accept it for the local demo.")
    else:
        print("[HTTPS] HTTP mode is active. Phone microphone access may be blocked.")
    try:
        print(terminal_qr(url))
    except Exception:
        print(f"[QR] {url}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[stopped]")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
