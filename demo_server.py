from __future__ import annotations

import argparse
import json
import random
import socket
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from experience_model import (
    SourceObservation,
    SourceSelector,
    ZONE_LABELS,
    ZONE_ORDER,
    ZONE_RSSI,
    Zone,
    parse_zone,
    snapshot_for_source,
)


PHONE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ALIVE Room Receiver</title>
<style>
:root {
  color-scheme: dark;
  --bg: #050607;
  --panel: #101417;
  --line: #263139;
  --text: #edf7f4;
  --muted: #8ba19c;
  --accent: #35f2b6;
  --warn: #ffd166;
  --dead: #6b7880;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(circle at 50% 20%, rgba(53, 242, 182, 0.14), transparent 35%),
    var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
main {
  width: min(680px, 100%);
  min-height: 100vh;
  margin: 0 auto;
  padding: 18px;
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 14px;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
}
.brand {
  font-size: 0.78rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}
.status {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 7px 10px;
  color: var(--accent);
  font-size: 0.78rem;
}
.receiver {
  display: grid;
  align-content: center;
  gap: 18px;
}
.ring {
  width: min(76vw, 360px);
  aspect-ratio: 1;
  margin: 0 auto;
  border-radius: 50%;
  border: 1px solid rgba(53, 242, 182, 0.32);
  display: grid;
  place-items: center;
  background:
    repeating-radial-gradient(circle, rgba(53, 242, 182, 0.16) 0 1px, transparent 1px 27px),
    radial-gradient(circle, rgba(53, 242, 182, 0.18), rgba(53, 242, 182, 0.02) 62%, transparent 63%);
  box-shadow: 0 0 60px rgba(53, 242, 182, 0.10);
}
.zone {
  text-align: center;
}
.zone strong {
  display: block;
  font-size: clamp(2.1rem, 14vw, 5.2rem);
  line-height: 0.95;
  text-transform: uppercase;
}
.zone span {
  color: var(--muted);
  font-size: 0.95rem;
}
.message {
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 18px 0;
}
.message h1 {
  margin: 0 0 8px;
  font-size: clamp(1.45rem, 7vw, 2.8rem);
  line-height: 1.05;
}
.message p {
  margin: 0;
  color: var(--muted);
  font-size: 1rem;
  line-height: 1.45;
}
.message.revealed h1,
.message.revealed p {
  color: var(--accent);
  text-shadow: 0 0 20px rgba(53, 242, 182, 0.35);
}
.telemetry {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.metric {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  min-width: 0;
}
.metric b {
  display: block;
  font-size: 0.72rem;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 4px;
}
.metric span {
  overflow-wrap: anywhere;
}
button {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  font: inherit;
}
.controls {
  display: grid;
  gap: 8px;
}
.ble {
  display: none;
}
@media (max-width: 460px) {
  main { padding: 14px; }
  .telemetry { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<main>
  <header>
    <div>
      <div class="brand">ALIVE receiver</div>
      <div id="source">waiting for source</div>
    </div>
    <div class="status" id="connection">connecting</div>
  </header>

  <section class="receiver">
    <div class="ring" id="ring">
      <div class="zone">
        <strong id="zone">--</strong>
        <span id="hint">hold near the source</span>
      </div>
    </div>

    <section class="message" id="message">
      <h1 id="title">No source selected</h1>
      <p id="body">Waiting for a stable source identity.</p>
    </section>

    <section class="telemetry" aria-label="signal telemetry">
      <div class="metric"><b>raw RSSI</b><span id="raw">--</span></div>
      <div class="metric"><b>smoothed</b><span id="smooth">--</span></div>
      <div class="metric"><b>target zone</b><span id="reveal">--</span></div>
    </section>
  </section>

  <section class="controls">
    <button id="audio">Enable audio</button>
    <button class="ble" id="ble">Try browser BLE scan</button>
  </section>
</main>
<script>
const els = {
  connection: document.querySelector('#connection'),
  source: document.querySelector('#source'),
  zone: document.querySelector('#zone'),
  hint: document.querySelector('#hint'),
  title: document.querySelector('#title'),
  body: document.querySelector('#body'),
  message: document.querySelector('#message'),
  raw: document.querySelector('#raw'),
  smooth: document.querySelector('#smooth'),
  reveal: document.querySelector('#reveal'),
  audio: document.querySelector('#audio'),
  ble: document.querySelector('#ble'),
};

let latest = null;
let audioCtx = null;
let osc = null;
let gain = null;
let noise = null;

function updateAudio(state) {
  if (!audioCtx || !osc || !gain || !state || !state.zone) return;
  const revealed = state.content && state.content.revealed;
  const zone = state.zone;
  const freq = revealed ? 622 : { very_near: 440, near: 330, mid: 220, far: 135 }[zone];
  const volume = revealed ? 0.12 : { very_near: 0.085, near: 0.06, mid: 0.04, far: 0.022 }[zone];
  osc.frequency.setTargetAtTime(freq, audioCtx.currentTime, 0.08);
  gain.gain.setTargetAtTime(volume, audioCtx.currentTime, 0.12);
}

function render(state) {
  latest = state;
  const source = state.sourceId || 'waiting for source';
  els.source.textContent = source;
  els.zone.textContent = state.zoneLabel || '--';
  els.hint.textContent = state.content && state.content.revealed ? 'message lock acquired' : 'move through the signal field';
  els.title.textContent = state.content.title;
  els.body.textContent = state.content.body;
  els.raw.textContent = state.rawRssi === null ? '--' : `${state.rawRssi} dBm`;
  els.smooth.textContent = state.smoothedRssi === null ? '--' : `${state.smoothedRssi} dBm`;
  els.reveal.textContent = state.revealZoneLabel || '--';
  els.message.classList.toggle('revealed', Boolean(state.content.revealed));
  updateAudio(state);
}

function connectEvents() {
  const events = new EventSource('/events');
  events.onopen = () => { els.connection.textContent = 'live'; };
  events.onerror = () => { els.connection.textContent = 'reconnecting'; };
  events.onmessage = event => render(JSON.parse(event.data));
}

els.audio.addEventListener('click', async () => {
  audioCtx = audioCtx || new AudioContext();
  if (!osc) {
    osc = new OscillatorNode(audioCtx, { type: 'sine', frequency: 135 });
    gain = new GainNode(audioCtx, { gain: 0 });
    osc.connect(gain).connect(audioCtx.destination);
    osc.start();
  }
  await audioCtx.resume();
  els.audio.textContent = 'Audio enabled';
  updateAudio(latest);
});

if (navigator.bluetooth && navigator.bluetooth.requestLEScan) {
  els.ble.style.display = 'block';
  els.ble.addEventListener('click', async () => {
    try {
      const scan = await navigator.bluetooth.requestLEScan({
        acceptAllAdvertisements: true,
        keepRepeatedDevices: true
      });
      navigator.bluetooth.addEventListener('advertisementreceived', event => {
        if (!event.name || !event.name.includes('ALIVE')) return;
        fetch('/api/ble-observation', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sourceId: event.name, rssi: event.rssi })
        });
      });
      els.ble.textContent = scan.active ? 'Browser BLE scan active' : 'BLE scan requested';
    } catch (error) {
      els.ble.textContent = 'BLE scan unavailable';
    }
  });
}

connectEvents();
</script>
</body>
</html>
"""


class DemoState:
    def __init__(self, source_id: str, reveal_zone: Zone) -> None:
        self.source_id = source_id
        self.reveal_zone = reveal_zone
        self.simulated_zone = Zone.FAR
        self.selector = SourceSelector()
        self.lock = threading.Lock()
        self.running = True

    def observe(self, source_id: str, rssi: float) -> None:
        with self.lock:
            self.selector.observe(SourceObservation(source_id=source_id, rssi=rssi))

    def set_simulated_zone(self, zone: Zone) -> None:
        with self.lock:
            self.simulated_zone = zone

    def set_reveal_zone(self, zone: Zone) -> None:
        with self.lock:
            self.reveal_zone = zone

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            snapshot = snapshot_for_source(self.selector.selected, self.reveal_zone)
            snapshot["simulatedZone"] = self.simulated_zone.value
            snapshot["simulatedZoneLabel"] = ZONE_LABELS[self.simulated_zone]
            return snapshot


def make_handler(state: DemoState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVEDemo/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_text(PHONE_HTML, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/state":
                self._send_json(state.snapshot())
                return
            if parsed.path == "/api/set-zone":
                self._handle_set_zone(parsed.query, reveal=False)
                return
            if parsed.path == "/api/set-reveal-zone":
                self._handle_set_zone(parsed.query, reveal=True)
                return
            if parsed.path == "/events":
                self._events()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/ble-observation":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                state.observe(str(payload["sourceId"]), float(payload["rssi"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_text(self, text: str, content_type: str) -> None:
            data = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict[str, object]) -> None:
            self._send_text(json.dumps(payload), "application/json")

        def _handle_set_zone(self, query: str, reveal: bool) -> None:
            params = parse_qs(query)
            try:
                zone = parse_zone(params.get("zone", [""])[0])
            except ValueError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if reveal:
                state.set_reveal_zone(zone)
            else:
                state.set_simulated_zone(zone)
            self._send_json(state.snapshot())

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "keep-alive")
            self.end_headers()
            while state.running:
                payload = json.dumps(state.snapshot()).encode("utf-8")
                try:
                    self.wfile.write(b"data: " + payload + b"\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(0.45)

    return Handler


def local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def simulator_loop(state: DemoState) -> None:
    while state.running:
        with state.lock:
            zone = state.simulated_zone
        base = ZONE_RSSI[zone]
        rssi = base + random.uniform(-4.0, 4.0)
        state.observe(state.source_id, rssi)
        time.sleep(0.35)


def print_qr_hint(url: str) -> None:
    try:
        from simple_qr import terminal_qr
    except Exception:
        print(f"[QR] {url}")
        return
    print(terminal_qr(url))


def controller_loop(state: DemoState) -> None:
    commands = ", ".join(zone.value for zone in ZONE_ORDER)
    print("\nLive controls:")
    print(f"  zone <{commands}>      simulate where the phone is")
    print(f"  reveal <{commands}>    choose the meaningful-message zone")
    print("  status                  show current state")
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
        parts = raw.split()
        cmd = parts[0].lower()
        try:
            if cmd in {"quit", "exit"}:
                state.running = False
            elif cmd == "status":
                print(json.dumps(state.snapshot(), indent=2))
            elif cmd == "zone" and len(parts) >= 2:
                zone = parse_zone(" ".join(parts[1:]))
                state.set_simulated_zone(zone)
                print(f"[demo] simulated zone -> {ZONE_LABELS[zone]}")
            elif cmd == "reveal" and len(parts) >= 2:
                zone = parse_zone(" ".join(parts[1:]))
                state.set_reveal_zone(zone)
                print(f"[demo] meaningful message zone -> {ZONE_LABELS[zone]}")
            elif cmd in {zone.value for zone in ZONE_ORDER} or cmd in {"very", "near", "mid", "far"}:
                zone = parse_zone(raw)
                state.set_simulated_zone(zone)
                print(f"[demo] simulated zone -> {ZONE_LABELS[zone]}")
            else:
                print("Unknown command. Try: zone mid, reveal very_near, status, quit")
        except ValueError as exc:
            print(f"[error] {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="ALIVE single-source phone demo server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--source-id", default="ALIVE-T480")
    parser.add_argument("--reveal-zone", default="very_near")
    args = parser.parse_args()

    try:
        reveal_zone = parse_zone(args.reveal_zone)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    state = DemoState(source_id=args.source_id, reveal_zone=reveal_zone)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    threading.Thread(target=simulator_loop, args=(state,), daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    ip = local_ip()
    url = f"http://{ip}:{args.port}/"
    print("=" * 56)
    print("ALIVE single-source demo")
    print("=" * 56)
    print(f"Phone URL: {url}")
    print(f"Source ID: {args.source_id}")
    print(f"Meaningful message starts in: {ZONE_LABELS[reveal_zone]}")
    print_qr_hint(url)

    try:
        controller_loop(state)
    finally:
        state.running = False
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
