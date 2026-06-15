from __future__ import annotations

import argparse
import json
import mimetypes
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

from codebook import COMMON_WORDS, FREQ_MAP
from legacy_audio_loop import (
    LoopingMessagePlayer,
    VALID_MODES,
    VALID_SIGNAL_TYPES,
    encoded_gap_ms,
    sanitize_message,
)
from zone_audio import VALID_ZONES, ZoneEmitterPlayer, normalize_zone


DEFAULT_MESSAGE = "WE ARE STILL HERE"
STATIC_PHONE_APP = Path(__file__).parent / "docs" / "index.html"


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
  .signal { grid-template-columns: 1fr; }
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
      <div>waiting for encoded audio</div>
    </div>
    <div class="pill" id="server">connecting</div>
  </header>

  <section class="signal">
    <div class="metric panel"><b>signal</b><span id="level">--</span></div>
    <div class="metric panel"><b>tone pair</b><span id="pair">--</span></div>
    <div class="metric panel"><b>gap</b><span id="gap">--</span></div>
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
const MIC_CALIBRATION_MS = 1200;
const els = {
  server: document.querySelector('#server'),
  level: document.querySelector('#level'),
  pair: document.querySelector('#pair'),
  gap: document.querySelector('#gap'),
  title: document.querySelector('#title'),
  verdict: document.querySelector('#verdict'),
  decoded: document.querySelector('#decoded'),
  stream: document.querySelector('#stream'),
  start: document.querySelector('#start'),
  reset: document.querySelector('#reset')
};

let audioCtx = null;
let micStream = null;
let sourceNode = null;
let processor = null;
let silentNode = null;
let micActive = false;
let noiseFloorDb = -65;
let calibrationUntil = 0;
let calibrationLevels = [];
let inBurst = false;
let burstSamples = [];
let burstStartAt = 0;
let lastBurstEndAt = 0;
let decoded = '';
let rawStream = '';
let pendingLetter = null;
let recentGaps = [];
let lastLevelDb = -120;
let lastDecodedAt = 0;
let lastFinalText = '';
let cycleTimer = null;
let pendingTimer = null;
let serverDurationMs = 0;
let serverRevision = null;
let serverCycle = null;
let serverSignal = 'language';
let serverActive = false;
let decoderArmed = false;
let sawServerState = false;

function connectEvents() {
  const events = new EventSource('/events');
  events.onopen = () => { els.server.textContent = 'live'; };
  events.onerror = () => { els.server.textContent = 'reconnecting'; };
  events.onmessage = event => {
    const state = JSON.parse(event.data);
    const firstState = !sawServerState;
    sawServerState = true;
    const wasActive = serverActive;
    serverSignal = state.signal;
    serverActive = Boolean(state.active);
    serverDurationMs = Math.max(0, (Number(state.duration) || 0) * 1000);
    els.server.textContent = !serverActive ? 'stopped' : state.signal === 'language' ? 'live' : state.signal;
    if (serverRevision === null) {
      serverRevision = state.revision;
    } else if (state.revision !== serverRevision) {
      serverRevision = state.revision;
      resetDecoder('sender reset');
      decoderArmed = serverActive && state.signal === 'language';
    }
    if (serverCycle === null) {
      serverCycle = state.cycle;
      decoderArmed = false;
    } else if (state.cycle !== serverCycle) {
      serverCycle = state.cycle;
      resetDecoder('signal done');
      decoderArmed = state.signal === 'language';
    }
    if (!firstState && !wasActive && serverActive) {
      resetDecoder('sender started');
      decoderArmed = state.signal === 'language';
    }
    if (!serverActive && (decoded || rawStream || pendingLetter)) {
      resetDecoder('sender stopped');
      decoderArmed = false;
    }
    if (state.signal !== 'language' && (decoded || rawStream || pendingLetter)) {
      resetDecoder(`${state.signal} signal`);
    }
    if (serverActive && state.signal !== 'language') {
      displayNonLanguageSignal(state.signal);
    }
  };
}

function rmsDb(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return 20 * Math.log10(Math.sqrt(sum / samples.length) + 1e-8);
}

function percentile(values, ratio) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * ratio)));
  return sorted[idx];
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
    const window = samples.length > 1 ? 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (samples.length - 1)) : 1;
    q0 = coeff * q1 - q2 + samples[i] * window;
    q2 = q1;
    q1 = q0;
  }
  const power = q1 * q1 + q2 * q2 - coeff * q1 * q2;
  return Math.sqrt(Math.max(power, 0)) / samples.length;
}

function trimBurst(samples) {
  let peak = 0;
  for (let i = 0; i < samples.length; i++) peak = Math.max(peak, Math.abs(samples[i]));
  if (peak <= 0) return samples;
  const threshold = peak * 0.18;
  let start = 0;
  let end = samples.length - 1;
  while (start < samples.length && Math.abs(samples[start]) < threshold) start++;
  while (end > start && Math.abs(samples[end]) < threshold) end--;
  return samples.slice(Math.max(0, start - 64), Math.min(samples.length, end + 65));
}

function detectLetter(samples, sampleRate) {
  samples = trimBurst(samples);
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

function isPeriodic(gaps) {
  const usable = gaps.filter(gap => gap > 80 && gap < 1300).slice(-5);
  if (usable.length < 3) return false;
  return Math.max(...usable) - Math.min(...usable) <= 90;
}

function classify(text, gaps = recentGaps) {
  const clean = text.trim().replace(/\\s+/g, ' ');
  if (isPeriodic(gaps)) return { title: 'Clock signal', verdict: 'DEAD' };
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

function gapToChar(gapMs) {
  if (!gapMs || gapMs <= 0 || gapMs > 1300) return null;
  let best = null;
  for (const row of CODEBOOK) {
    const err = Math.abs(row.gap - gapMs);
    if (!best || err < best.err) best = { ch: row.ch, err };
  }
  if (!best) return null;
  const tolerance = best.ch === ' ' ? 180 : 135;
  return best.err <= tolerance ? best : null;
}

function gapForChar(ch) {
  const row = CODEBOOK.find(entry => entry.ch === ch);
  return row ? row.gap : null;
}

function isCycleBoundaryGap(gapMs) {
  return gapMs > 1400;
}

function clearPendingTimer() {
  if (pendingTimer) {
    clearTimeout(pendingTimer);
    pendingTimer = null;
  }
}

function armPendingTimer(result) {
  clearPendingTimer();
  const expectedGap = gapForChar(result.ch) || 500;
  pendingTimer = setTimeout(() => {
    if (pendingLetter === result) commitPending(0);
  }, Math.max(350, expectedGap + 250));
}

function armCycleTimer() {
  if (cycleTimer) clearTimeout(cycleTimer);
  if (serverSignal !== 'language' || serverDurationMs <= 0) return;
  cycleTimer = setTimeout(() => {
    if (decoded.trim().length > 0 || pendingLetter) finishCycle();
  }, serverDurationMs + 450);
}

function commitLetter(ch, gapMs) {
  if (ch === ' ' && decoded.endsWith(' ')) return;
  if (gapMs > 0) {
    recentGaps.push(gapMs);
    if (recentGaps.length > 12) recentGaps.shift();
  }
  decoded += ch;
  rawStream += ch;
  lastDecodedAt = performance.now();
  if (decoded.length > 120) decoded = decoded.slice(-120);
  const state = classify(decoded, recentGaps);
  els.title.textContent = state.title;
  els.verdict.textContent = state.verdict;
  els.decoded.textContent = decoded || '---';
  els.stream.textContent = rawStream.slice(-96);
  els.gap.textContent = gapMs ? `${Math.round(gapMs)} ms` : '--';
}

function commitPending(gapMs) {
  if (!pendingLetter) return;
  clearPendingTimer();
  const byGap = gapToChar(gapMs);
  const expectedGap = gapForChar(pendingLetter.ch);
  const expectedErr = expectedGap === null || !gapMs ? 0 : Math.abs(expectedGap - gapMs);
  const shouldTrustGap = byGap && (expectedErr > 260 || pendingLetter.confidence < 0.45);
  const ch = shouldTrustGap ? byGap.ch : pendingLetter.ch;
  commitLetter(ch, gapMs);
  pendingLetter = null;
}

function acceptLetter(result, gapMs) {
  if (isCycleBoundaryGap(gapMs) && (decoded.trim().length > 0 || pendingLetter)) {
    finishCycle();
  } else {
    commitPending(gapMs);
  }
  pendingLetter = result;
  armPendingTimer(result);
  armCycleTimer();
}

function finishCycle() {
  clearPendingTimer();
  if (cycleTimer) {
    clearTimeout(cycleTimer);
    cycleTimer = null;
  }
  commitPending(0);
  const finalText = decoded.trim();
  if (finalText) {
    const repeated = finalText === lastFinalText;
    const state = classify(finalText, recentGaps);
    els.title.textContent = state.title;
    els.verdict.textContent = state.verdict;
    els.decoded.textContent = finalText;
    els.stream.textContent = repeated ? 'repeat signal detected' : 'message complete';
    lastFinalText = finalText;
  } else {
    els.stream.textContent = 'cycle reset';
  }
  decoded = '';
  rawStream = '';
  pendingLetter = null;
  recentGaps = [];
  lastBurstEndAt = 0;
}

function resetDecoder(reason = 'decoded stream cleared') {
  clearPendingTimer();
  if (cycleTimer) {
    clearTimeout(cycleTimer);
    cycleTimer = null;
  }
  decoded = '';
  rawStream = '';
  pendingLetter = null;
  recentGaps = [];
  lastBurstEndAt = 0;
  lastDecodedAt = 0;
  els.decoded.textContent = '---';
  els.stream.textContent = reason;
  els.title.textContent = micActive ? 'Listening' : 'Receiver idle';
  els.verdict.textContent = 'DEAD';
  els.gap.textContent = '--';
}

function displayNonLanguageSignal(signal) {
  if (signal === 'clock') {
    els.title.textContent = 'Clock signal';
    els.stream.textContent = 'repeating clock cycle';
  } else if (signal === 'burst') {
    els.title.textContent = 'Burst signal';
    els.stream.textContent = 'isolated burst detected';
  }
  els.verdict.textContent = 'DEAD';
}

function processChunk(input) {
  if (!audioCtx) return;
  const now = audioCtx.currentTime;
  const nowMs = performance.now();
  const levelDb = rmsDb(input);
  lastLevelDb = lastLevelDb * 0.75 + levelDb * 0.25;
  if (calibrationUntil > 0) {
    if (nowMs < calibrationUntil) {
      calibrationLevels.push(levelDb);
      els.level.textContent = `${lastLevelDb.toFixed(1)} dB`;
      els.title.textContent = 'Calibrating mic';
      els.verdict.textContent = 'DEAD';
      return;
    }
    const floor = percentile(calibrationLevels, 0.35);
    if (floor !== null) noiseFloorDb = floor;
    calibrationUntil = 0;
    calibrationLevels = [];
  }
  updateFloor(levelDb);
  const startThreshold = Math.max(-90, noiseFloorDb + 6);
  const endThreshold = Math.max(-94, noiseFloorDb + 3);
  const chunkDuration = input.length / audioCtx.sampleRate;

  els.level.textContent = `${lastLevelDb.toFixed(1)} dB`;

  if (!serverActive) return;
  if (serverSignal === 'language' && !decoderArmed) {
    els.title.textContent = 'Waiting for sync';
    els.verdict.textContent = 'DEAD';
    return;
  }

  if (!inBurst && levelDb > startThreshold) {
    inBurst = true;
    burstSamples = [];
    burstStartAt = now;
    els.title.textContent = 'Signal detected';
  }

  if (inBurst) {
    burstSamples.push(...input);
    const burstDuration = now - burstStartAt + chunkDuration;
    if ((levelDb < endThreshold && burstDuration > 0.12) || burstDuration > 0.42) {
      inBurst = false;
      const gapMs = lastBurstEndAt ? (burstStartAt - lastBurstEndAt) * 1000 : 0;
      lastBurstEndAt = now;
      if (serverSignal !== 'language') {
        if (gapMs > 0) {
          recentGaps.push(gapMs);
          if (recentGaps.length > 12) recentGaps.shift();
        }
        displayNonLanguageSignal(serverSignal);
      } else {
        const result = detectLetter(burstSamples, audioCtx.sampleRate);
        els.pair.textContent = `${result.low}/${result.high} Hz`;
        if (result.confidence > 0.22) {
          acceptLetter(result, gapMs);
        }
      }
    }
  }

  if (!inBurst && decoded.trim().length > 0 && performance.now() - lastDecodedAt > 1800) {
    finishCycle();
  }
}

async function startTranslator() {
  if (micActive) {
    await stopTranslator();
    return;
  }
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
    });
    audioCtx = new AudioContext();
    sourceNode = audioCtx.createMediaStreamSource(micStream);
    processor = audioCtx.createScriptProcessor(4096, 1, 1);
    silentNode = audioCtx.createGain();
    silentNode.gain.value = 0;
    processor.onaudioprocess = event => processChunk(event.inputBuffer.getChannelData(0));
    sourceNode.connect(processor);
    processor.connect(silentNode).connect(audioCtx.destination);
    await audioCtx.resume();
    micActive = true;
    noiseFloorDb = -65;
    calibrationLevels = [];
    calibrationUntil = performance.now() + MIC_CALIBRATION_MS;
    els.start.textContent = 'Stop translator';
    els.title.textContent = 'Calibrating mic';
    els.verdict.textContent = 'DEAD';
  } catch (error) {
    els.title.textContent = 'Microphone blocked';
    els.stream.textContent = error.message || String(error);
  }
}

async function stopTranslator() {
  if (processor) processor.disconnect();
  if (sourceNode) sourceNode.disconnect();
  if (silentNode) silentNode.disconnect();
  if (micStream) micStream.getTracks().forEach(track => track.stop());
  if (audioCtx && audioCtx.state !== 'closed') await audioCtx.close();
  audioCtx = null;
  micStream = null;
  sourceNode = null;
  processor = null;
  silentNode = null;
  micActive = false;
  calibrationUntil = 0;
  calibrationLevels = [];
  inBurst = false;
  burstSamples = [];
  pendingLetter = null;
  clearPendingTimer();
  if (cycleTimer) {
    clearTimeout(cycleTimer);
    cycleTimer = null;
  }
  els.start.textContent = 'Start translator';
  els.title.textContent = 'Receiver idle';
  els.verdict.textContent = 'DEAD';
}

els.start.addEventListener('click', startTranslator);
els.reset.addEventListener('click', () => {
  resetDecoder();
});

connectEvents();
</script>
</body>
</html>
"""


class DemoState:
    def __init__(self, player: LoopingMessagePlayer | ZoneEmitterPlayer) -> None:
        self.player = player
        self.running = True

    def snapshot(self) -> dict[str, object]:
        return self.player.snapshot()

    def public_snapshot(self) -> dict[str, object]:
        if hasattr(self.player, "public_snapshot"):
            return self.player.public_snapshot()
        return self.player.snapshot()


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)


def make_phone_html() -> str:
    entries = [
        {"ch": ch, "low": low, "high": high, "gap": encoded_gap_ms(ch)}
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


def make_static_phone_html() -> str:
    if STATIC_PHONE_APP.exists():
        return STATIC_PHONE_APP.read_text(encoding="utf-8")
    return "<!doctype html><title>ALIVE</title><p>Static phone app is missing.</p>"


def make_handler(state: DemoState, phone_html: str | None = None):
    phone_html = phone_html or make_phone_html()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVETranslator/0.3"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html", "/zone"}:
                self._send_text(phone_html, "text/html; charset=utf-8")
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
            self.send_header("access-control-allow-headers", "content-type")
            self.end_headers()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/zone":
                self._handle_zone_post()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle_configure(self, query: str) -> None:
            if not isinstance(state.player, LoopingMessagePlayer):
                self.send_error(HTTPStatus.BAD_REQUEST, "configure is only available in translator mode")
                return
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

        def _handle_zone_post(self) -> None:
            length = int(self.headers.get("content-length", "0") or "0")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid JSON body")
                return

            emitter_id = str(payload.get("emitterId") or payload.get("emitter") or "emitter-1")
            zone_raw = str(payload.get("zone") or "far")
            try:
                zone = normalize_zone(zone_raw)
            except ValueError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return

            confidence = float(payload.get("confidence") or 0.0)
            levels = payload.get("levels")
            if hasattr(state.player, "apply_phone_zone"):
                state.player.apply_phone_zone(
                    emitter_id=emitter_id,
                    zone=zone,
                    confidence=confidence,
                    levels=levels if isinstance(levels, dict) else None,
                )
            self._send_json({"ok": True, **state.public_snapshot()})

        def _send_cors_headers(self) -> None:
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-private-network", "true")

        def _send_text(self, text: str, content_type: str) -> None:
            data = text.encode("utf-8")
            self._send_bytes(data, content_type)

        def _send_bytes(self, data: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers()
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict[str, object]) -> None:
            self._send_text(json.dumps(payload), "application/json")

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
    zone_mode = isinstance(state.player, ZoneEmitterPlayer)
    print("\nLive controls:")
    print("  start                   start the current signal")
    print("  stop                    stop the current signal")
    if zone_mode:
        print("  emitter <1-5|id>        choose the laptop test emitter")
        print("  zone <far|mid|near|close>  change the emitted zone sound")
        print("  far / mid / near / close   shortcut for zone")
    else:
        print("  message <text>          change encoded message")
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
        elif zone_mode and command == "emitter" and value.strip():
            raw_id = value.strip().lower()
            emitter_id = f"emitter-{raw_id}" if raw_id.isdigit() else raw_id
            state.player.configure(emitter_id=emitter_id)
        elif zone_mode and command == "zone" and value.strip():
            try:
                state.player.configure(zone=normalize_zone(value))
            except ValueError as exc:
                print(f"[error] {exc}")
        elif zone_mode and command in VALID_ZONES:
            state.player.configure(zone=command)
        elif not zone_mode and command == "message" and value.strip():
            cleaned = sanitize_message(value)
            if cleaned:
                state.player.configure(message=cleaned, signal_type="language")
            else:
                print("[error] message must contain A-Z or spaces")
        elif not zone_mode and command == "signal" and value.strip():
            signal_type = value.strip().lower()
            if signal_type in VALID_SIGNAL_TYPES:
                state.player.configure(signal_type=signal_type)
            else:
                print("[error] signal must be language, clock, or burst")
        elif not zone_mode and command in VALID_SIGNAL_TYPES:
            state.player.configure(signal_type=command)
        else:
            if zone_mode:
                print("Unknown command. Try: start, stop, emitter 1, zone near, status, quit")
            else:
                print("Unknown command. Try: start, stop, message HELLO WORLD, signal clock, burst, status, quit")


def main() -> int:
    parser = argparse.ArgumentParser(description="ALIVE phone audio receiver demo")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--zone-demo", action="store_true", help="Run the phone zone receiver test emitter/controller")
    parser.add_argument("--emitter", default="emitter-1", help="Zone demo emitter id, e.g. emitter-1 or 1")
    parser.add_argument("--zone", choices=VALID_ZONES, default="far", help="Initial zone sound for --zone-demo")
    tone = parser.add_mutually_exclusive_group()
    tone.add_argument("--laser", dest="mode", action="store_const", const="laser", default="laser")
    tone.add_argument("--horn", dest="mode", action="store_const", const="horn")
    tone.add_argument("--vocal", dest="mode", action="store_const", const="vocal")
    parser.add_argument("--signal", choices=VALID_SIGNAL_TYPES, default="language")
    parser.add_argument("--http", action="store_true", help="Use HTTP instead of local HTTPS")
    args = parser.parse_args()

    emitter_id = f"emitter-{args.emitter}" if str(args.emitter).isdigit() else args.emitter
    if args.zone_demo:
        player = ZoneEmitterPlayer(emitter_id=emitter_id, zone=args.zone)
        phone_html = make_static_phone_html()
    else:
        player = LoopingMessagePlayer(args.message, args.mode, args.signal)
        phone_html = make_phone_html()
    state = DemoState(player)
    ip = local_ip()
    server = QuietThreadingHTTPServer((args.host, args.port), make_handler(state, phone_html))
    https_active = False
    if not args.http:
        https_active = apply_https(server, ip)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    scheme = "https" if https_active else "http"
    url = f"{scheme}://{ip}:{args.port}/"
    print("=" * 56)
    print("ALIVE zone receiver demo" if args.zone_demo else "ALIVE audio-codebook translator demo")
    print("=" * 56)
    print(f"Phone URL: {url}")
    if args.zone_demo:
        print(f"Controller URL for GitHub Pages app: {scheme}://{ip}:{args.port}")
        print(f"Emitter: {player.emitter.emitter_id}")
        print(f"Zone sound: {player.zone}")
        print("Audio emitter: stopped; type start to play the current fingerprint")
    else:
        print(f"Encoded message: {player.message}")
        print(f"Sound style: {player.mode}")
        print(f"Signal type: {player.signal_type}")
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
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
