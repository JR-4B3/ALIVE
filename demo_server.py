from __future__ import annotations

import argparse
import json
import random
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

from audio_beacon import BEACON_FREQS, AudioBeacon
from ble_advertiser import BLEAdvertiser
from experience_model import (
    SIGNAL_LEVEL_DB,
    ZONE_LABELS,
    ZONE_ORDER,
    Zone,
    parse_zone,
    snapshot_for_ble_observation,
    snapshot_for_audio_observation,
    snapshot_for_fused_observation,
    zone_from_ble_rssi,
    zone_from_score,
    zone_score,
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
  grid-template-columns: repeat(2, 1fr);
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
.bar {
  height: 8px;
  border-radius: 999px;
  background: #1c2529;
  overflow: hidden;
}
.bar > div {
  width: 0%;
  height: 100%;
  background: var(--accent);
  transition: width 120ms linear;
}
button {
  width: 100%;
  min-height: 46px;
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
.warn {
  color: var(--warn);
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
      <div id="source">audio beacon</div>
    </div>
    <div class="status" id="connection">connecting</div>
  </header>

  <section class="receiver">
    <div class="ring" id="ring">
      <div class="zone">
        <strong id="zone">--</strong>
        <span id="hint">start microphone sensing</span>
      </div>
    </div>

    <section class="message" id="message">
      <h1 id="title">Microphone not active</h1>
      <p id="body">Start microphone sensing so the phone can estimate distance from the laptop beacon.</p>
    </section>

    <section class="telemetry" aria-label="signal telemetry">
      <div class="metric"><b>mode</b><span id="mode">not started</span></div>
      <div class="metric"><b>BLE scan</b><span id="ble">inactive</span></div>
      <div class="metric"><b>BLE RSSI</b><span id="rssi">--</span></div>
      <div class="metric"><b>BLE smoothed</b><span id="rssiSmooth">--</span></div>
      <div class="metric"><b>microphone</b><span id="mic">inactive</span></div>
      <div class="metric"><b>beacon level</b><span id="level">--</span></div>
      <div class="metric"><b>smoothed level</b><span id="smooth">--</span></div>
      <div class="metric"><b>confidence</b><span id="confidence">--</span><div class="bar"><div id="confidenceBar"></div></div></div>
      <div class="metric"><b>target zone</b><span id="reveal">--</span></div>
      <div class="metric"><b>tones</b><span id="tones">1720 + 2290 Hz</span></div>
    </section>
  </section>

  <section class="controls">
    <button id="startBle">Start BLE only</button>
    <button id="startBleAudio">Start BLE + audio</button>
    <button id="audio">Enable phone response audio</button>
  </section>
</main>
<script>
const SOURCE_ID = "__SOURCE_ID__";
const BEACON_FREQS = __BEACON_FREQS__;
const els = {
  connection: document.querySelector('#connection'),
  source: document.querySelector('#source'),
  zone: document.querySelector('#zone'),
  hint: document.querySelector('#hint'),
  title: document.querySelector('#title'),
  body: document.querySelector('#body'),
  message: document.querySelector('#message'),
  mode: document.querySelector('#mode'),
  ble: document.querySelector('#ble'),
  rssi: document.querySelector('#rssi'),
  rssiSmooth: document.querySelector('#rssiSmooth'),
  mic: document.querySelector('#mic'),
  level: document.querySelector('#level'),
  smooth: document.querySelector('#smooth'),
  confidence: document.querySelector('#confidence'),
  confidenceBar: document.querySelector('#confidenceBar'),
  reveal: document.querySelector('#reveal'),
  tones: document.querySelector('#tones'),
  startBle: document.querySelector('#startBle'),
  startBleAudio: document.querySelector('#startBleAudio'),
  audio: document.querySelector('#audio'),
};

let latest = null;
let sensingMode = '__SENSING_MODE__';
let micActive = false;
let analysisCtx = null;
let analyser = null;
let samples = null;
let smoothedLevelDb = null;
let floorLevelDb = -105;
let peakLevelDb = -45;
let stableZone = 'far';
let candidateZone = 'far';
let candidateCount = 0;
let lastPostAt = 0;
let bleActive = false;
let bleScan = null;
let smoothedRssi = null;
let stableBleZone = 'far';
let candidateBleZone = 'far';
let candidateBleCount = 0;
let lastBlePostAt = 0;

let responseCtx = null;
let osc = null;
let gain = null;

els.tones.textContent = `${BEACON_FREQS[0]} + ${BEACON_FREQS[1]} Hz`;
els.mode.textContent = sensingMode === 'ble_audio' ? 'BLE + audio' : sensingMode;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function zoneLabel(zone) {
  return { close: 'close', near: 'near', mid: 'mid', far: 'far' }[zone] || 'no lock';
}

function proximityScore(levelDb, confidence) {
  if (levelDb < floorLevelDb) {
    floorLevelDb = floorLevelDb * 0.95 + levelDb * 0.05;
  } else {
    floorLevelDb = floorLevelDb * 0.998 + levelDb * 0.002;
  }
  if (levelDb > peakLevelDb) {
    peakLevelDb = peakLevelDb * 0.88 + levelDb * 0.12;
  } else {
    peakLevelDb = peakLevelDb * 0.995 + levelDb * 0.005;
  }
  const span = Math.max(26, peakLevelDb - floorLevelDb);
  const levelScore = clamp((levelDb - floorLevelDb) / span, 0, 1);
  return clamp(levelScore * 0.72 + confidence * 0.28, 0, 1);
}

function zoneFromProximity(score) {
  if (score >= 0.58) return 'close';
  if (score >= 0.42) return 'near';
  if (score >= 0.25) return 'mid';
  return 'far';
}

function zoneFromRssi(rssi) {
  if (rssi >= -50) return 'close';
  if (rssi >= -65) return 'near';
  if (rssi >= -80) return 'mid';
  return 'far';
}

function bleConfidenceFromRssi(rssi) {
  return clamp((rssi + 94) / 42, 0, 1);
}

function stabilizeZone(candidate) {
  if (candidate === stableZone) {
    candidateZone = candidate;
    candidateCount = 0;
    return stableZone;
  }
  if (candidate === candidateZone) {
    candidateCount += 1;
  } else {
    candidateZone = candidate;
    candidateCount = 1;
  }
  if (candidateCount >= 4) {
    stableZone = candidate;
    candidateCount = 0;
  }
  return stableZone;
}

function stabilizeBleZone(candidate) {
  if (candidate === stableBleZone) {
    candidateBleZone = candidate;
    candidateBleCount = 0;
    return stableBleZone;
  }
  if (candidate === candidateBleZone) {
    candidateBleCount += 1;
  } else {
    candidateBleZone = candidate;
    candidateBleCount = 1;
  }
  if (candidateBleCount >= 3) {
    stableBleZone = candidate;
    candidateBleCount = 0;
  }
  return stableBleZone;
}

function magnitudeAt(samples, sampleRate, frequency) {
  const omega = 2 * Math.PI * frequency / sampleRate;
  const coeff = 2 * Math.cos(omega);
  let q0 = 0;
  let q1 = 0;
  let q2 = 0;
  for (let i = 0; i < samples.length; i++) {
    q0 = coeff * q1 - q2 + samples[i];
    q2 = q1;
    q1 = q0;
  }
  const power = q1 * q1 + q2 * q2 - coeff * q1 * q2;
  return Math.sqrt(Math.max(power, 0)) / samples.length;
}

function analyzeFrame() {
  if (!micActive || !analyser || !samples) return;
  analyser.getFloatTimeDomainData(samples);

  let rmsSum = 0;
  for (let i = 0; i < samples.length; i++) {
    rmsSum += samples[i] * samples[i];
  }
  const rms = Math.sqrt(rmsSum / samples.length);
  const toneA = magnitudeAt(samples, analysisCtx.sampleRate, BEACON_FREQS[0]);
  const toneB = magnitudeAt(samples, analysisCtx.sampleRate, BEACON_FREQS[1]);
  const beacon = (toneA + toneB) * 0.5;
  const ambient = Math.max(1e-7, rms - beacon * 0.6);
  const signalLevelDb = 20 * Math.log10(beacon + 1e-8);
  const snrDb = 20 * Math.log10((beacon + 1e-8) / ambient);
  const confidence = clamp((snrDb - 1) / 18, 0, 1);

  smoothedLevelDb = smoothedLevelDb === null
    ? signalLevelDb
    : smoothedLevelDb * 0.84 + signalLevelDb * 0.16;

  const score = proximityScore(smoothedLevelDb, confidence);
  const candidateZone = confidence < 0.12 ? 'far' : zoneFromProximity(score);
  const zone = stabilizeZone(candidateZone);
  const now = performance.now();

  renderLocalMetrics({ signalLevelDb, smoothedLevelDb, confidence, zone });
  updateResponseAudio({ zone, confidence, revealed: latest && latest.content && latest.content.revealed });

  if (now - lastPostAt > 360) {
    lastPostAt = now;
    postObservation({ zone, signalLevelDb, smoothedLevelDb, confidence });
  }

  requestAnimationFrame(analyzeFrame);
}

function renderLocalMetrics(metric) {
  els.mic.textContent = micActive ? 'active' : 'inactive';
  els.level.textContent = `${metric.signalLevelDb.toFixed(1)} dB`;
  els.smooth.textContent = `${metric.smoothedLevelDb.toFixed(1)} dB`;
  els.confidence.textContent = `${Math.round(metric.confidence * 100)}%`;
  els.confidenceBar.style.width = `${Math.round(metric.confidence * 100)}%`;
  els.zone.textContent = zoneLabel(metric.zone);
  els.hint.textContent = metric.confidence < 0.18 ? 'beacon below lock threshold' : 'move through the signal field';
}

async function postObservation(metric) {
  try {
    await fetch('/api/audio-observation', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        sourceId: SOURCE_ID,
        micActive: true,
        zone: metric.zone,
        signalLevelDb: metric.signalLevelDb,
        smoothedSignalLevelDb: metric.smoothedLevelDb,
        confidence: metric.confidence
      })
    });
  } catch (error) {
    els.connection.textContent = 'post failed';
  }
}

async function setSensingMode(mode) {
  sensingMode = mode;
  els.mode.textContent = mode === 'ble_audio' ? 'BLE + audio' : mode;
  try {
    await fetch(`/api/set-mode?mode=${encodeURIComponent(mode)}`);
  } catch (error) {
    els.connection.textContent = 'mode post failed';
  }
}

async function startBleScan() {
  if (!navigator.bluetooth || !navigator.bluetooth.requestLEScan) {
    els.ble.innerHTML = '<span class="warn">unsupported</span>';
    els.hint.textContent = 'this browser does not expose BLE advertisement RSSI';
    els.body.textContent = 'BLE proximity needs Web Bluetooth LE Scan support. Use Chrome on Android with Web Bluetooth scanning enabled, or use BLE + audio/audio fallback.';
    return false;
  }
  if (bleActive) return true;
  try {
    bleScan = await navigator.bluetooth.requestLEScan({
      filters: [{ namePrefix: 'ALIVE' }],
      keepRepeatedDevices: true
    });
    navigator.bluetooth.addEventListener('advertisementreceived', onBleAdvertisement);
    bleActive = true;
    els.ble.textContent = bleScan.active ? 'active' : 'requested';
    return true;
  } catch (error) {
    els.ble.innerHTML = '<span class="warn">blocked</span>';
    els.hint.textContent = 'BLE scan permission was blocked or unavailable';
    els.body.textContent = `BLE scan could not start: ${error.message || error}`;
    return false;
  }
}

function onBleAdvertisement(event) {
  if (event.name && !event.name.includes('ALIVE')) return;
  if (typeof event.rssi !== 'number') return;

  const rawRssi = event.rssi;
  smoothedRssi = smoothedRssi === null ? rawRssi : smoothedRssi * 0.78 + rawRssi * 0.22;
  const confidence = bleConfidenceFromRssi(smoothedRssi);
  const zone = stabilizeBleZone(zoneFromRssi(smoothedRssi));
  const now = performance.now();

  els.ble.textContent = 'active';
  els.rssi.textContent = `${rawRssi.toFixed(0)} dBm`;
  els.rssiSmooth.textContent = `${smoothedRssi.toFixed(1)} dBm`;

  if (sensingMode === 'ble') {
    els.zone.textContent = zoneLabel(zone);
    els.confidence.textContent = `${Math.round(confidence * 100)}%`;
    els.confidenceBar.style.width = `${Math.round(confidence * 100)}%`;
    updateResponseAudio({ zone, confidence, revealed: latest && latest.content && latest.content.revealed });
  }

  if (now - lastBlePostAt > 320) {
    lastBlePostAt = now;
    postBleObservation({ zone, rawRssi, smoothedRssi, confidence });
  }
}

async function postBleObservation(metric) {
  try {
    await fetch('/api/ble-observation', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        sourceId: SOURCE_ID,
        bleActive: true,
        zone: metric.zone,
        rawRssi: metric.rawRssi,
        smoothedRssi: metric.smoothedRssi,
        confidence: metric.confidence
      })
    });
  } catch (error) {
    els.connection.textContent = 'BLE post failed';
  }
}

function renderServerState(state) {
  latest = state;
  els.connection.textContent = state.debugSimulated ? 'debug sim' : 'live';
  els.source.textContent = state.sourceId || SOURCE_ID;
  els.mode.textContent = state.mode === 'ble_audio' ? 'BLE + audio' : state.mode;
  els.reveal.textContent = state.revealZoneLabel || '--';
  els.title.textContent = state.content.title;
  els.body.textContent = state.content.body;
  els.message.classList.toggle('revealed', Boolean(state.content.revealed));
  if (!micActive || state.debugSimulated) {
    els.zone.textContent = state.zoneLabel || '--';
    els.level.textContent = state.signalLevelDb === null ? '--' : `${state.signalLevelDb} dB`;
    els.smooth.textContent = state.smoothedSignalLevelDb === null ? '--' : `${state.smoothedSignalLevelDb} dB`;
    els.rssi.textContent = state.rawRssi === null ? '--' : `${state.rawRssi} dBm`;
    els.rssiSmooth.textContent = state.smoothedRssi === null ? '--' : `${state.smoothedRssi} dBm`;
    els.confidence.textContent = `${Math.round((state.confidence || 0) * 100)}%`;
    els.confidenceBar.style.width = `${Math.round((state.confidence || 0) * 100)}%`;
    els.mic.textContent = state.micActive ? 'active' : 'inactive';
    els.ble.textContent = state.bleActive ? 'active' : 'inactive';
  }
  updateResponseAudio({
    zone: state.zone || stableZone,
    confidence: state.confidence || 0,
    revealed: state.content && state.content.revealed
  });
}

function connectEvents() {
  const events = new EventSource('/events');
  events.onopen = () => { els.connection.textContent = 'live'; };
  events.onerror = () => { els.connection.textContent = 'reconnecting'; };
  events.onmessage = event => renderServerState(JSON.parse(event.data));
}

async function startAudioSensing() {
  if (micActive) return true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false
      }
    });
    analysisCtx = new AudioContext();
    const source = analysisCtx.createMediaStreamSource(stream);
    analyser = new AnalyserNode(analysisCtx, { fftSize: 4096, smoothingTimeConstant: 0 });
    source.connect(analyser);
    samples = new Float32Array(analyser.fftSize);
    micActive = true;
    els.mic.textContent = 'active';
    await analysisCtx.resume();
    analyzeFrame();
    return true;
  } catch (error) {
    els.mic.innerHTML = '<span class="warn">blocked</span>';
    els.hint.textContent = 'microphone permission or HTTPS is required';
    els.body.textContent = `Microphone could not start: ${error.message || error}`;
    return false;
  }
}

els.startBle.addEventListener('click', async () => {
  await setSensingMode('ble');
  const ok = await startBleScan();
  els.startBle.textContent = ok ? 'BLE-only active' : 'BLE-only unavailable';
});

els.startBleAudio.addEventListener('click', async () => {
  await setSensingMode('ble_audio');
  const bleOk = await startBleScan();
  const audioOk = await startAudioSensing();
  els.startBleAudio.textContent = bleOk && audioOk ? 'BLE + audio active' : 'BLE + audio partially active';
});

els.audio.addEventListener('click', async () => {
  responseCtx = responseCtx || new AudioContext();
  if (!osc) {
    osc = new OscillatorNode(responseCtx, { type: 'sine', frequency: 135 });
    gain = new GainNode(responseCtx, { gain: 0 });
    osc.connect(gain).connect(responseCtx.destination);
    osc.start();
  }
  await responseCtx.resume();
  els.audio.textContent = 'Phone response audio enabled';
  updateResponseAudio({ zone: stableZone, confidence: latest ? latest.confidence : 0, revealed: latest && latest.content && latest.content.revealed });
});

function updateResponseAudio(state) {
  if (!responseCtx || !osc || !gain || !state || !state.zone) return;
  const revealed = state.revealed;
  const zone = state.zone;
  const freq = revealed ? 622 : { close: 440, near: 330, mid: 220, far: 135 }[zone];
  const volume = revealed ? 0.12 : { close: 0.075, near: 0.052, mid: 0.032, far: 0.012 }[zone] * clamp(state.confidence + 0.2, 0.15, 1);
  osc.frequency.setTargetAtTime(freq, responseCtx.currentTime, 0.08);
  gain.gain.setTargetAtTime(volume, responseCtx.currentTime, 0.12);
}

connectEvents();
</script>
</body>
</html>
"""


class DemoState:
    def __init__(
        self,
        source_id: str,
        reveal_zone: Zone,
        debug_sim: bool,
        sensing_mode: str,
    ) -> None:
        self.source_id = source_id
        self.reveal_zone = reveal_zone
        self.debug_sim = debug_sim
        self.sensing_mode = sensing_mode
        self.simulated_zone = Zone.FAR
        self.audio_zone: Zone | None = None
        self.signal_level_db: float | None = None
        self.smoothed_signal_level_db: float | None = None
        self.audio_confidence = 0.0
        self.mic_active = False
        self.last_audio_observation_at = 0.0
        self.ble_zone: Zone | None = None
        self.raw_rssi: float | None = None
        self.smoothed_rssi: float | None = None
        self.ble_confidence = 0.0
        self.ble_active = False
        self.last_ble_observation_at = 0.0
        self.lock = threading.Lock()
        self.running = True

    def set_audio_observation(
        self,
        zone: Zone,
        signal_level_db: float,
        smoothed_signal_level_db: float,
        confidence: float,
        mic_active: bool = True,
    ) -> None:
        with self.lock:
            self.audio_zone = zone
            self.signal_level_db = signal_level_db
            self.smoothed_signal_level_db = smoothed_signal_level_db
            self.audio_confidence = max(0.0, min(1.0, confidence))
            self.mic_active = mic_active
            self.last_audio_observation_at = time.monotonic()

    def set_ble_observation(
        self,
        zone: Zone,
        raw_rssi: float,
        smoothed_rssi: float,
        confidence: float,
        ble_active: bool = True,
    ) -> None:
        with self.lock:
            self.ble_zone = zone
            self.raw_rssi = raw_rssi
            self.smoothed_rssi = smoothed_rssi
            self.ble_confidence = max(0.0, min(1.0, confidence))
            self.ble_active = ble_active
            self.last_ble_observation_at = time.monotonic()

    def set_sensing_mode(self, mode: str) -> None:
        if mode not in {"audio", "ble", "ble_audio"}:
            raise ValueError("mode must be audio, ble, or ble_audio")
        with self.lock:
            self.sensing_mode = mode

    def set_simulated_zone(self, zone: Zone) -> None:
        with self.lock:
            self.simulated_zone = zone

    def set_reveal_zone(self, zone: Zone) -> None:
        with self.lock:
            self.reveal_zone = zone

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            now = time.monotonic()
            audio_stale = now - self.last_audio_observation_at > 2.5
            ble_stale = now - self.last_ble_observation_at > 3.5
            mic_active = self.mic_active and not audio_stale
            ble_active = self.ble_active and not ble_stale
            audio_zone = self.audio_zone if mic_active else None
            ble_zone = self.ble_zone if ble_active else None
            audio_confidence = self.audio_confidence if mic_active else 0.0
            ble_confidence = self.ble_confidence if ble_active else 0.0

            if self.sensing_mode == "ble":
                snapshot = snapshot_for_ble_observation(
                    self.source_id,
                    ble_zone,
                    self.raw_rssi if ble_active else None,
                    self.smoothed_rssi if ble_active else None,
                    ble_confidence,
                    ble_active,
                    self.reveal_zone,
                )
            elif self.sensing_mode == "ble_audio":
                zone, confidence = self._fused_zone(
                    ble_zone,
                    ble_confidence,
                    audio_zone,
                    audio_confidence,
                )
                snapshot = snapshot_for_fused_observation(
                    source_id=self.source_id,
                    zone=zone,
                    confidence=confidence,
                    reveal_zone=self.reveal_zone,
                    ble_active=ble_active,
                    mic_active=mic_active,
                    raw_rssi=self.raw_rssi if ble_active else None,
                    smoothed_rssi=self.smoothed_rssi if ble_active else None,
                    signal_level_db=self.signal_level_db if mic_active else None,
                    smoothed_signal_level_db=self.smoothed_signal_level_db
                    if mic_active
                    else None,
                    ble_confidence=ble_confidence,
                    audio_confidence=audio_confidence,
                )
            else:
                snapshot = snapshot_for_audio_observation(
                    self.source_id,
                    audio_zone,
                    self.signal_level_db if mic_active else None,
                    self.smoothed_signal_level_db if mic_active else None,
                    audio_confidence,
                    mic_active,
                    self.reveal_zone,
                )
            snapshot["debugSimulated"] = self.debug_sim
            snapshot["simulatedZone"] = self.simulated_zone.value
            snapshot["simulatedZoneLabel"] = ZONE_LABELS[self.simulated_zone]
            return snapshot

    def _fused_zone(
        self,
        ble_zone: Zone | None,
        ble_confidence: float,
        audio_zone: Zone | None,
        audio_confidence: float,
    ) -> tuple[Zone | None, float]:
        weighted_score = 0.0
        weight = 0.0
        if ble_zone is not None and ble_confidence >= 0.12:
            ble_weight = max(0.2, ble_confidence) * 1.15
            weighted_score += zone_score(ble_zone) * ble_weight
            weight += ble_weight
        if audio_zone is not None and audio_confidence >= 0.12:
            audio_weight = max(0.2, audio_confidence)
            weighted_score += zone_score(audio_zone) * audio_weight
            weight += audio_weight
        if weight == 0.0:
            return None, 0.0
        confidence = min(1.0, weight / 1.7)
        return zone_from_score(weighted_score / weight), confidence


def make_phone_html(source_id: str, sensing_mode: str) -> str:
    return (
        PHONE_HTML.replace("__SOURCE_ID__", source_id)
        .replace("__SENSING_MODE__", sensing_mode)
        .replace("__BEACON_FREQS__", json.dumps([round(freq) for freq in BEACON_FREQS]))
    )


def make_handler(state: DemoState):
    phone_html = make_phone_html(state.source_id, state.sensing_mode)

    class Handler(BaseHTTPRequestHandler):
        server_version = "ALIVEDemo/0.2"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_text(phone_html, "text/html; charset=utf-8")
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
            if parsed.path == "/api/set-mode":
                self._handle_set_mode(parsed.query)
                return
            if parsed.path == "/events":
                self._events()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/audio-observation":
                self._handle_audio_observation()
                return
            if parsed.path == "/api/ble-observation":
                self._handle_ble_observation()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _handle_audio_observation(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                zone = parse_zone(str(payload["zone"]))
                state.set_audio_observation(
                    zone=zone,
                    signal_level_db=float(payload["signalLevelDb"]),
                    smoothed_signal_level_db=float(payload["smoothedSignalLevelDb"]),
                    confidence=float(payload["confidence"]),
                    mic_active=bool(payload.get("micActive", True)),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True})

        def _handle_ble_observation(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                zone = parse_zone(str(payload["zone"]))
                state.set_ble_observation(
                    zone=zone,
                    raw_rssi=float(payload["rawRssi"]),
                    smoothed_rssi=float(payload["smoothedRssi"]),
                    confidence=float(payload["confidence"]),
                    ble_active=bool(payload.get("bleActive", True)),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True})

        def _handle_set_mode(self, query: str) -> None:
            params = parse_qs(query)
            mode = params.get("mode", [""])[0]
            try:
                state.set_sensing_mode(mode)
            except ValueError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(state.snapshot())

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
            elif state.debug_sim:
                state.set_simulated_zone(zone)
            else:
                self.send_error(
                    HTTPStatus.BAD_REQUEST,
                    "zone simulation is only available with --debug-sim",
                )
                return
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
                time.sleep(0.25)

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


def simulator_loop(state: DemoState) -> None:
    while state.running:
        with state.lock:
            zone = state.simulated_zone
        base = SIGNAL_LEVEL_DB[zone]
        level = base + random.uniform(-3.0, 3.0)
        state.set_audio_observation(zone, level, level, 0.95, mic_active=True)
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
    print(f"  reveal <{commands}>    choose the meaningful-message zone")
    if state.debug_sim:
        print(f"  zone <{commands}>      debug: simulate phone proximity")
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
                if not state.debug_sim:
                    print("[debug] zone simulation requires --debug-sim")
                    continue
                zone = parse_zone(" ".join(parts[1:]))
                state.set_simulated_zone(zone)
                print(f"[debug] simulated zone -> {ZONE_LABELS[zone]}")
            elif cmd == "reveal" and len(parts) >= 2:
                zone = parse_zone(" ".join(parts[1:]))
                state.set_reveal_zone(zone)
                print(f"[demo] meaningful message zone -> {ZONE_LABELS[zone]}")
            else:
                print("Unknown command. Try: reveal mid, status, quit")
        except ValueError as exc:
            print(f"[error] {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="ALIVE single-source phone demo server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--source-id", default="ALIVE-T480")
    parser.add_argument("--reveal-zone", default="close")
    parser.add_argument(
        "--sensing-mode",
        choices=["ble", "ble_audio", "audio"],
        default="ble_audio",
        help="Initial phone sensing mode",
    )
    parser.add_argument("--http", action="store_true", help="Use HTTP instead of local HTTPS")
    parser.add_argument("--debug-sim", action="store_true", help="Enable terminal zone simulation fallback")
    parser.add_argument("--no-audio-beacon", action="store_true", help="Do not emit the laptop audio beacon")
    parser.add_argument("--no-ble-advertising", action="store_true", help="Do not advertise over BlueZ BLE")
    args = parser.parse_args()

    try:
        reveal_zone = parse_zone(args.reveal_zone)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    ip = local_ip()
    state = DemoState(
        source_id=args.source_id,
        reveal_zone=reveal_zone,
        debug_sim=args.debug_sim,
        sensing_mode=args.sensing_mode,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    https_active = False
    if not args.http:
        https_active = apply_https(server, ip)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    beacon = AudioBeacon()
    beacon_active = False
    if not args.no_audio_beacon:
        beacon_active = beacon.start()

    ble_advertiser = BLEAdvertiser(local_name=args.source_id)
    ble_active = False
    if not args.no_ble_advertising:
        ble_active = ble_advertiser.start()

    if args.debug_sim:
        threading.Thread(target=simulator_loop, args=(state,), daemon=True).start()

    scheme = "https" if https_active else "http"
    url = f"{scheme}://{ip}:{args.port}/"
    print("=" * 56)
    print("ALIVE single-source BLE/audio demo")
    print("=" * 56)
    print(f"Phone URL: {url}")
    print(f"Source ID: {args.source_id}")
    print(f"Initial sensing mode: {args.sensing_mode}")
    print(f"Meaningful message starts in: {ZONE_LABELS[reveal_zone]}")
    print(f"BLE advertising: {'active' if ble_active else 'unavailable'}")
    print(f"Audio beacon: {'active' if beacon_active else 'unavailable'}")
    if not https_active:
        print("[HTTPS] HTTP mode is active. Phone microphone access may be blocked.")
    else:
        print("[HTTPS] The phone may show a certificate warning; accept it for the local demo.")
    print_qr_hint(url)

    try:
        controller_loop(state)
    finally:
        state.running = False
        beacon.stop()
        ble_advertiser.stop()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
