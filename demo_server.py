from __future__ import annotations

import argparse
import json
import socket
import ssl
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from codebook import COMMON_WORDS, FREQ_MAP, GAP_MAP
from legacy_audio_loop import LoopingMessagePlayer, VALID_MODES, sanitize_message


DEFAULT_MESSAGE = "WE ARE STILL HERE"


PHONE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ALIVE Translator</title>
<style>
:root {
  color-scheme: dark;
  --bg: #050607;
  --panel: #0d1214;
  --line: #253036;
  --text: #eef8f5;
  --muted: #8da19d;
  --accent: #35f2b6;
  --warn: #ffd166;
  --bad: #ff6b6b;
}
* { box-sizing: border-box; }
html, body { height: 100%; overflow: hidden; }
body {
  margin: 0;
  background:
    radial-gradient(circle at 50% 10%, rgba(53, 242, 182, 0.13), transparent 34%),
    linear-gradient(180deg, #050607, #070b0c);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
main {
  width: min(720px, 100%);
  height: 100dvh;
  margin: 0 auto;
  padding: 14px;
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  gap: 10px;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.brand {
  color: var(--muted);
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.pill {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 7px 10px;
  color: var(--accent);
  font-size: 0.78rem;
}
.panel {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(13, 18, 20, 0.82);
}
.signal {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
}
.metric { padding: 9px; min-width: 0; }
.metric b {
  display: block;
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 0.68rem;
  text-transform: uppercase;
}
.metric span { overflow-wrap: anywhere; }
.translator {
  min-height: 0;
  display: grid;
  grid-template-rows: auto 1fr auto;
}
.statusline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--line);
}
.statusline h1 {
  margin: 0;
  font-size: clamp(1.1rem, 5vw, 1.8rem);
}
.verdict {
  color: var(--warn);
  font-size: 0.78rem;
  text-transform: uppercase;
  white-space: nowrap;
}
.output {
  min-height: 0;
  padding: 16px 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
#decoded {
  width: 100%;
  text-align: center;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: clamp(2.1rem, 11vw, 4.8rem);
  line-height: 1.05;
  letter-spacing: 0.04em;
  color: var(--accent);
  text-shadow: 0 0 22px rgba(53, 242, 182, 0.28);
  overflow-wrap: anywhere;
}
.stream {
  border-top: 1px solid var(--line);
  padding: 10px 12px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.86rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.controls {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
button {
  min-height: 46px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  font: inherit;
}
button.primary {
  background: #10251f;
  border-color: rgba(53, 242, 182, 0.45);
}
@media (max-width: 480px) {
  main { padding: 10px; gap: 8px; }
  .signal { grid-template-columns: 1fr 1fr; }
  .metric { padding: 8px; }
  .controls { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<main>
  <header>
    <div>
      <div class="brand">ALIVE translator</div>
      <div id="source">waiting for encoded audio</div>
    </div>
    <div class="pill" id="server">connecting</div>
  </header>

  <section class="signal">
    <div class="metric panel"><b>microphone</b><span id="mic">inactive</span></div>
    <div class="metric panel"><b>signal</b><span id="level">--</span></div>
    <div class="metric panel"><b>burst</b><span id="burst">idle</span></div>
    <div class="metric panel"><b>tone pair</b><span id="pair">--</span></div>
    <div class="metric panel"><b>gap</b><span id="gap">--</span></div>
    <div class="metric panel"><b>sender</b><span id="sender">--</span></div>
  </section>

  <section class="translator panel">
    <div class="statusline">
      <h1 id="title">Receiver idle</h1>
      <div class="verdict" id="verdict">DEAD</div>
    </div>
    <div class="output">
      <div id="decoded">---</div>
    </div>
    <div class="stream" id="stream">decoded stream will appear here</div>
  </section>

  <section class="controls">
    <button class="primary" id="start">Start translator</button>
    <button id="reset">Reset decoded text</button>
  </section>
</main>

<script>
const CODEBOOK = __CODEBOOK__;
const COMMON_WORDS = new Set(__COMMON_WORDS__);
const LOW_FREQS = [400, 500, 600, 700, 800, 900, 1000];
const HIGH_FREQS = [2000, 2300, 2600, 2900];
const els = {
  server: document.querySelector('#server'),
  source: document.querySelector('#source'),
  mic: document.querySelector('#mic'),
  level: document.querySelector('#level'),
  burst: document.querySelector('#burst'),
  pair: document.querySelector('#pair'),
  gap: document.querySelector('#gap'),
  sender: document.querySelector('#sender'),
  title: document.querySelector('#title'),
  verdict: document.querySelector('#verdict'),
  decoded: document.querySelector('#decoded'),
  stream: document.querySelector('#stream'),
  start: document.querySelector('#start'),
  reset: document.querySelector('#reset')
};

let audioCtx = null;
let processor = null;
let micActive = false;
let noiseFloorDb = -110;
let inBurst = false;
let burstSamples = [];
let burstStartAt = 0;
let lastBurstEndAt = 0;
let decoded = '';
let rawStream = '';
let lastLevelDb = -120;
let senderState = null;
let lastDecodedAt = 0;

function connectEvents() {
  const events = new EventSource('/events');
  events.onopen = () => { els.server.textContent = 'live'; };
  events.onerror = () => { els.server.textContent = 'reconnecting'; };
  events.onmessage = event => {
    senderState = JSON.parse(event.data);
    els.sender.textContent = `${senderState.mode} / ${senderState.message}`;
    els.source.textContent = `laptop loop: ${senderState.message}`;
  };
}

function rmsDb(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return 20 * Math.log10(Math.sqrt(sum / samples.length) + 1e-8);
}

function updateFloor(levelDb) {
  if (levelDb < noiseFloorDb) {
    noiseFloorDb = noiseFloorDb * 0.92 + levelDb * 0.08;
  } else {
    noiseFloorDb = noiseFloorDb * 0.998 + levelDb * 0.002;
  }
}

function goertzel(samples, sampleRate, frequency) {
  const omega = 2 * Math.PI * frequency / sampleRate;
  const coeff = 2 * Math.cos(omega);
  let q0 = 0, q1 = 0, q2 = 0;
  for (let i = 0; i < samples.length; i++) {
    q0 = coeff * q1 - q2 + samples[i];
    q2 = q1;
    q1 = q0;
  }
  const power = q1 * q1 + q2 * q2 - coeff * q1 * q2;
  return Math.sqrt(Math.max(power, 0)) / samples.length;
}

function detectLetter(samples, sampleRate) {
  let bestLow = LOW_FREQS[0], bestLowMag = 0;
  let bestHigh = HIGH_FREQS[0], bestHighMag = 0;
  for (const f of LOW_FREQS) {
    const mag = goertzel(samples, sampleRate, f);
    if (mag > bestLowMag) { bestLow = f; bestLowMag = mag; }
  }
  for (const f of HIGH_FREQS) {
    const mag = goertzel(samples, sampleRate, f);
    if (mag > bestHighMag) { bestHigh = f; bestHighMag = mag; }
  }
  let best = { ch: '?', err: Infinity, low: bestLow, high: bestHigh };
  for (const row of CODEBOOK) {
    const err = Math.abs(row.low - bestLow) + Math.abs(row.high - bestHigh);
    if (err < best.err) best = { ch: row.ch, err, low: bestLow, high: bestHigh };
  }
  const confidence = Math.min(1, Math.max(0, (160 - best.err) / 160));
  return { ...best, confidence };
}

function charFromGap(gapMs) {
  if (!gapMs) return '';
  let best = { ch: '', err: Infinity, gap: 0 };
  for (const row of CODEBOOK) {
    const err = Math.abs(row.gap - gapMs);
    if (err < best.err) best = { ch: row.ch, err, gap: row.gap };
  }
  return best.err <= 90 ? best.ch : '?';
}

function classify(text) {
  const clean = text.trim().replace(/\\s+/g, ' ');
  if (!clean) return { title: 'Listening', verdict: 'DEAD' };
  if (clean.length <= 2) return { title: 'Signal fragments', verdict: 'CLOCK' };
  const compact = clean.replace(/ /g, '');
  for (const word of COMMON_WORDS) {
    if (word.length >= 3 && compact.includes(word)) {
      return { title: 'Language lock', verdict: 'ALIVE' };
    }
  }
  return { title: 'Structured signal', verdict: 'UNKNOWN' };
}

function appendLetter(ch, gapMs) {
  if (gapMs > 2200 && decoded.trim().length > 0) {
    finishCycle();
    decoded = '';
    rawStream = '';
  }
  if (ch === ' ' && decoded.endsWith(' ')) return;
  decoded += ch;
  rawStream += ch;
  lastDecodedAt = performance.now();
  if (decoded.length > 42) decoded = decoded.slice(-42);
  const state = classify(decoded);
  els.title.textContent = state.title;
  els.verdict.textContent = state.verdict;
  els.decoded.textContent = decoded || '---';
  els.stream.textContent = rawStream.slice(-96);
  const gapChar = charFromGap(gapMs);
  els.gap.textContent = gapMs ? `${Math.round(gapMs)} ms -> ${gapChar || '?'}` : '--';
}

function finishCycle() {
  const finalText = decoded.trim();
  if (finalText) {
    const state = classify(finalText);
    els.title.textContent = state.title;
    els.verdict.textContent = state.verdict;
    els.decoded.textContent = finalText;
    setTimeout(() => {
      decoded = '';
      rawStream = '';
      els.decoded.textContent = '---';
      els.stream.textContent = 'waiting for next loop';
    }, 1200);
  }
}

function processChunk(input) {
  const now = audioCtx.currentTime;
  const levelDb = rmsDb(input);
  lastLevelDb = lastLevelDb * 0.75 + levelDb * 0.25;
  updateFloor(levelDb);
  const startThreshold = Math.max(-86, noiseFloorDb + 18);
  const endThreshold = Math.max(-94, noiseFloorDb + 10);
  const chunkDuration = input.length / audioCtx.sampleRate;

  els.level.textContent = `${lastLevelDb.toFixed(1)} dB`;

  if (!inBurst && levelDb > startThreshold) {
    inBurst = true;
    burstSamples = [];
    burstStartAt = now;
    els.burst.textContent = 'capturing';
    els.title.textContent = 'Signal detected';
  }

  if (inBurst) {
    burstSamples.push(...input);
    const burstDuration = now - burstStartAt + chunkDuration;
    if ((levelDb < endThreshold && burstDuration > 0.12) || burstDuration > 0.42) {
      inBurst = false;
      els.burst.textContent = 'decoding';
      const gapMs = lastBurstEndAt ? (burstStartAt - lastBurstEndAt) * 1000 : 0;
      lastBurstEndAt = now;
      const result = detectLetter(burstSamples, audioCtx.sampleRate);
      els.pair.textContent = `${result.low}/${result.high} Hz`;
      if (result.confidence > 0.22) appendLetter(result.ch, gapMs);
      els.burst.textContent = 'idle';
    }
  }

  if (!inBurst && decoded.trim().length > 0 && performance.now() - lastDecodedAt > 3000) {
    finishCycle();
  }
}

async function startTranslator() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
    });
    audioCtx = new AudioContext();
    const source = audioCtx.createMediaStreamSource(stream);
    processor = audioCtx.createScriptProcessor(4096, 1, 1);
    const silent = audioCtx.createGain();
    silent.gain.value = 0;
    processor.onaudioprocess = event => processChunk(event.inputBuffer.getChannelData(0));
    source.connect(processor);
    processor.connect(silent).connect(audioCtx.destination);
    await audioCtx.resume();
    micActive = true;
    els.mic.textContent = 'active';
    els.start.textContent = 'Translator active';
    els.title.textContent = 'Listening';
    els.verdict.textContent = 'DEAD';
  } catch (error) {
    els.mic.textContent = 'blocked';
    els.title.textContent = 'Microphone blocked';
    els.stream.textContent = error.message || String(error);
  }
}

els.start.addEventListener('click', startTranslator);
els.reset.addEventListener('click', () => {
  decoded = '';
  rawStream = '';
  els.decoded.textContent = '---';
  els.stream.textContent = 'decoded stream cleared';
  els.title.textContent = micActive ? 'Listening' : 'Receiver idle';
  els.verdict.textContent = 'DEAD';
});

connectEvents();
</script>
</body>
</html>
"""


class DemoState:
    def __init__(self, player: LoopingMessagePlayer) -> None:
        self.player = player
        self.running = True

    def snapshot(self) -> dict[str, object]:
        return self.player.snapshot()


def make_phone_html() -> str:
    entries = [
        {"ch": ch, "low": low, "high": high, "gap": GAP_MAP[ch]}
        for ch, (low, high) in FREQ_MAP.items()
    ]
    demo_words = {
        "ALIVE",
        "ARE",
        "DEMO",
        "DISCOVER",
        "EARTH",
        "HELLO",
        "HERE",
        "LANGUAGE",
        "MESSAGE",
        "SIGNAL",
        "STILL",
        "TRANSLATE",
        "WE",
        "WORLD",
    }
    words = sorted(demo_words | {word for word in COMMON_WORDS if 3 <= len(word) <= 8})
    return (
        PHONE_HTML.replace("__CODEBOOK__", json.dumps(entries))
        .replace("__COMMON_WORDS__", json.dumps(words))
    )


def make_handler(state: DemoState):
    phone_html = make_phone_html()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVETranslator/0.3"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_text(phone_html, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/state":
                self._send_json(state.snapshot())
                return
            if parsed.path == "/api/configure":
                self._handle_configure(parsed.query)
                return
            if parsed.path == "/events":
                self._events()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle_configure(self, query: str) -> None:
            params = parse_qs(query)
            message = params.get("message", [None])[0]
            mode = params.get("mode", [None])[0]
            if mode is not None and mode not in VALID_MODES:
                self.send_error(HTTPStatus.BAD_REQUEST, "mode must be laser, horn, or vocal")
                return
            state.player.configure(message=message, mode=mode)
            self._send_json(state.snapshot())

        def _send_text(self, text: str, content_type: str) -> None:
            data = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict[str, object]) -> None:
            self._send_text(json.dumps(payload), "application/json")

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
                time.sleep(0.5)

    return Handler


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
    print("  message <text>          change encoded message")
    print("  mode <laser|horn|vocal> change sender sound style")
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
        elif command == "status":
            print(json.dumps(state.snapshot(), indent=2))
        elif command == "message" and value.strip():
            cleaned = sanitize_message(value)
            if cleaned:
                state.player.configure(message=cleaned)
            else:
                print("[error] message must contain A-Z or spaces")
        elif command == "mode" and value.strip():
            mode = value.strip().lower()
            if mode in VALID_MODES:
                state.player.configure(mode=mode)
            else:
                print("[error] mode must be laser, horn, or vocal")
        else:
            print("Unknown command. Try: message HELLO WORLD, mode vocal, status, quit")


def main() -> int:
    parser = argparse.ArgumentParser(description="ALIVE audio-codebook translator demo")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--mode", choices=VALID_MODES, default="laser")
    parser.add_argument("--http", action="store_true", help="Use HTTP instead of local HTTPS")
    args = parser.parse_args()

    player = LoopingMessagePlayer(args.message, args.mode)
    state = DemoState(player)
    ip = local_ip()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    https_active = False
    if not args.http:
        https_active = apply_https(server, ip)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    audio_active = player.start()

    scheme = "https" if https_active else "http"
    url = f"{scheme}://{ip}:{args.port}/"
    print("=" * 56)
    print("ALIVE audio-codebook translator demo")
    print("=" * 56)
    print(f"Phone URL: {url}")
    print(f"Encoded message: {player.message}")
    print(f"Sound style: {player.mode}")
    print(f"Audio loop: {'active' if audio_active else 'unavailable'}")
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
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
