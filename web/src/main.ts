import '@fontsource/space-mono/latin-400.css';
import '@fontsource/space-mono/latin-700.css';
import './styles.css';
import { SignalLevelTracker } from './sensing/signalLevelTracker';
import { BeaconDecoder } from './sensing/beaconDecoder';
import { mountSignalStrip } from './signalStrip';
import { encodeRecording } from './audio/recording';
import { uploadRecording } from './audio/recordingUpload';
import { startSimulatedUnit } from './debug/simulatedUnit';
import type { Reception, ReceiverStatus } from './types';

// Set at build time: `bun run build` publishes the clean visitor page to docs/,
// `bun run build:debug` keeps every diagnostic control for local testing.
declare const __DEBUG_UI__: boolean;
declare const __PUBLISHED_API__: string;
const DEBUG_UI = __DEBUG_UI__;
const LOG_LIMIT = 80;

if (DEBUG_UI) { document.title = 'ALIVE Receiver · debug'; document.body.classList.add('debug-ui'); }

const app = requiredElement<HTMLDivElement>('#app');
app.innerHTML = `
  <main>
    <section class="receiver">
      <header class="receiver-head">
        <div class="receiver-ident">
          <span class="wordmark">ALIVE${DEBUG_UI ? ' debug' : ''}</span>
          <span id="translationState" class="receiver-state">Listening · <b>DEAD</b></span>
        </div>
        <button id="clear" type="button" class="quiet-button">Clear</button>
      </header>
      <ol id="log" class="log" aria-live="polite" aria-label="Received signals"></ol>
      <p id="logEmpty" class="log-empty">Tap the microphone, then hold your phone toward the units.</p>
      <button id="mic" type="button" class="mic-toggle" aria-label="Enable microphone" aria-pressed="false" title="Enable microphone">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="9" y="3" width="6" height="12" rx="3" />
          <path d="M6 10v2a6 6 0 0 0 12 0v-2M12 18v3M8 21h8" />
          <path class="mic-off-cross" d="M3 3l18 18" />
        </svg>
      </button>
    </section>

    <section class="contact">
      <form id="contactForm" class="contact-form">
        ${DEBUG_UI ? `<div id="micDiagnostics" class="debug-line">MIC OFF</div>` : ''}
        <div class="compose">
          <input id="prompt" maxlength="120" placeholder="Message" autocomplete="off" enterkeyhint="send" aria-label="Message">
          <button id="send" type="submit" aria-label="Send message" title="Send message">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true">
              <path d="M12 20V5M5.5 11.5L12 5l6.5 6.5" />
            </svg>
          </button>
        </div>
        ${DEBUG_UI ? `
        <div id="contactStatus" class="debug-line">---</div>
        <div class="debug-signals" role="group" aria-label="Send a signal now">
          <button type="button" class="debug-button" data-kind="noise">noise now</button>
          <button type="button" class="debug-button" data-kind="clock">clock now</button>
          <button type="button" class="debug-button" data-kind="intelligent">message now</button>
        </div>
        <label class="debug-check">
          <input id="simulateUnit" type="checkbox">
          <span>Simulate a unit on this page (local test API only; turns the microphone off)</span>
        </label>
        <div id="simulateStatus" class="debug-line"></div>
        <label class="debug-check">
          <input id="randomSignals" type="checkbox" checked>
          <span>Random signals between requests (needs the operator token)</span>
        </label>
        <label class="debug-check">
          <input id="recordDiagnostic" class="sr-only" type="checkbox">
          <span class="record-checkbox-mark" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="12" height="12" fill="none" aria-hidden="true">
              <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" stroke-width="2" />
            </svg>
          </span>
          <span>Record 25 s with the next signal I send</span>
        </label>
        <div id="recordStatus" class="debug-line"></div>
        <details class="debug-settings">
          <summary>connection settings</summary>
          <label for="apiBase">API URL
            <input id="apiBase" type="url" placeholder="https://api.example.com">
          </label>
          <label for="apiToken">Private operator token (required for signals, status, and reset)
            <input id="apiToken" type="password" autocomplete="off" placeholder="paste operator token">
          </label>
          <button id="showStatus" type="button" class="debug-button">show board roles</button>
          <button id="resetMessage" type="button" class="debug-button">reset conversations and roles</button>
          <pre id="resetStatus" class="debug-line" role="status"></pre>
        </details>` : ''}
      </form>
    </section>
  </main>
`;

// Visitors get the spectrogram layout. The debug page keeps its scrolling
// diagnostics layout.
const signalStrip = DEBUG_UI ? null : mountSignalStrip();

const refs = {
  translationState: requiredElement<HTMLSpanElement>('#translationState'),
  log: requiredElement<HTMLOListElement>('#log'),
  logEmpty: requiredElement<HTMLParagraphElement>('#logEmpty'),
  mic: requiredElement<HTMLButtonElement>('#mic'),
  clear: requiredElement<HTMLButtonElement>('#clear'),
  contactForm: requiredElement<HTMLFormElement>('#contactForm'),
  prompt: requiredElement<HTMLInputElement>('#prompt'),
  send: requiredElement<HTMLButtonElement>('#send')
};

// Debug-only controls. In the visitor build DEBUG_UI is false, so this object
// (and every diagnostic string in it) is removed from the bundle entirely.
const debugRefs = DEBUG_UI ? {
  micDiagnostics: requiredElement<HTMLDivElement>('#micDiagnostics'),
  signalButtons: [...document.querySelectorAll<HTMLButtonElement>('.debug-signals button')],
  randomSignals: requiredElement<HTMLInputElement>('#randomSignals'),
  simulateUnit: requiredElement<HTMLInputElement>('#simulateUnit'),
  simulateStatus: requiredElement<HTMLDivElement>('#simulateStatus'),
  apiBase: requiredElement<HTMLInputElement>('#apiBase'),
  apiToken: requiredElement<HTMLInputElement>('#apiToken'),
  showStatus: requiredElement<HTMLButtonElement>('#showStatus'),
  resetMessage: requiredElement<HTMLButtonElement>('#resetMessage'),
  resetStatus: requiredElement<HTMLPreElement>('#resetStatus'),
  contactStatus: requiredElement<HTMLDivElement>('#contactStatus'),
  recordDiagnostic: requiredElement<HTMLInputElement>('#recordDiagnostic'),
  recordStatus: requiredElement<HTMLDivElement>('#recordStatus')
} : null;

const params = new URLSearchParams(location.search);
// Visitors always use the published API unless a link names another one, so an
// address saved by an older page can never redirect them. Operators set the
// debug page's URL by hand, and it is remembered there.
const initialApiBase = params.get('api')?.trim() ||
  (DEBUG_UI ? localStorage.getItem('aliveApiBase') ?? '' : __PUBLISHED_API__);
const initialApiToken = params.get('token') ?? (sessionStorage.getItem('aliveApiToken') ?? '');
if (debugRefs) {
  debugRefs.apiBase.value = initialApiBase;
  debugRefs.apiToken.value = initialApiToken;
}
// The API keeps each visitor's conversation under this id for this tab.
const session = sessionStorage.getItem('aliveSession') ?? newSession();

const levels = new SignalLevelTracker();
const decoder = new BeaconDecoder();
let levelSnapshot = levels.snapshot();
let translationSnapshot = decoder.snapshot();
let audioCtx: AudioContext | null = null;
let micStream: MediaStream | null = null;
let sourceNode: MediaStreamAudioSourceNode | null = null;
let processor: ScriptProcessorNode | null = null;
let silentNode: GainNode | null = null;
let micActive = false;
let micError = '';
// The last intelligent message this phone decoded. The API answers only
// visitors who can repeat what they heard.
let heard = '';
let liveEntry: HTMLLIElement | null = null;
let stopSimulation: (() => void) | null = null;
let recording: { chunks: Float32Array[]; samples: number; rate: number; api: string; timer: number } | null = null;
let recordingDownloadUrl: string | null = null;

refs.mic.addEventListener('click', () => {
  void toggleMicrophone();
});
refs.clear.addEventListener('click', () => {
  translationSnapshot = decoder.reset();
  refs.log.replaceChildren();
  liveEntry = null;
  render();
});
refs.contactForm.addEventListener('submit', (event) => {
  event.preventDefault();
  void sendContactMessage();
});
for (const button of debugRefs?.signalButtons ?? []) {
  button.addEventListener('click', () => void requestSignal(button.dataset.kind ?? 'intelligent'));
}
debugRefs?.simulateUnit.addEventListener('change', () => {
  void toggleSimulation(debugRefs.simulateUnit.checked);
});
debugRefs?.randomSignals.addEventListener('change', () => {
  void operatorRequest('POST', '/api/emitter/main/signals', { random: debugRefs.randomSignals.checked });
});
debugRefs?.showStatus.addEventListener('click', () => {
  void operatorRequest('GET', '/api/status');
});
if (debugRefs && initialApiToken) void operatorRequest('GET', '/api/status');
debugRefs?.resetMessage.addEventListener('click', () => {
  void operatorRequest('POST', '/api/emitter/main/reset');
});

render();

async function toggleMicrophone(): Promise<void> {
  if (micActive) {
    await stopMicrophone();
    return;
  }
  await startMicrophone();
}

async function toggleSimulation(on: boolean): Promise<void> {
  if (!debugRefs) return;
  stopSimulation?.();
  stopSimulation = null;
  if (on) {
    // The decoder needs one unbroken stream, so the microphone stops first.
    if (micActive) await stopMicrophone();
    translationSnapshot = decoder.reset('listening for signal');
    stopSimulation = startSimulatedUnit({
      apiBase: requestApiBase,
      feed: receive,
      status: (text) => { debugRefs.simulateStatus.textContent = text; }
    });
  } else {
    translationSnapshot = decoder.reset();
  }
  debugRefs.simulateUnit.checked = on;
  render();
}

function receive(input: Float32Array, sampleRate: number): void {
  translationSnapshot = decoder.process(input, sampleRate);
  for (const reception of decoder.takeCompleted()) {
    if (reception.kind === 'intelligent') heard = reception.text;
    appendEntry(reception.kind, reception.text);
  }
  render();
}

async function startMicrophone(): Promise<void> {
  if (DEBUG_UI && stopSimulation) await toggleSimulation(false);
  try {
    renderStatus('requesting');
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
    });
    audioCtx = new AudioContext();
    sourceNode = audioCtx.createMediaStreamSource(micStream);
    processor = audioCtx.createScriptProcessor(2048, 1, 1);
    silentNode = audioCtx.createGain();
    silentNode.gain.value = 0;
    processor.onaudioprocess = (event) => {
      if (!audioCtx) return;
      const input = event.inputBuffer.getChannelData(0);
      if (DEBUG_UI && recording && recording.samples < recording.rate * 25) {
        const chunk = input.slice(0, recording.rate * 25 - recording.samples);
        recording.chunks.push(chunk);
        recording.samples += chunk.length;
      }
      levelSnapshot = levels.process(input, performance.now());
      receive(input, audioCtx.sampleRate);
    };
    signalStrip?.connect(sourceNode);
    sourceNode.connect(processor);
    processor.connect(silentNode).connect(audioCtx.destination);
    await audioCtx.resume();
    micActive = true;
    micError = '';
    levels.startCalibration(performance.now());
    levelSnapshot = levels.snapshot();
    translationSnapshot = decoder.reset('listening for signal');
    renderStatus('calibrating');
    render();
  } catch (error) {
    renderStatus('mic-blocked');
    micError = `The microphone is blocked${error instanceof Error ? ` (${error.message})` : ''}. ` +
      'Allow it in the browser settings, then tap the microphone again.';
    render();
  }
}

async function stopMicrophone(): Promise<void> {
  cancelRecording();
  signalStrip?.stop();
  processor?.disconnect();
  sourceNode?.disconnect();
  silentNode?.disconnect();
  micStream?.getTracks().forEach((track) => track.stop());
  if (audioCtx && audioCtx.state !== 'closed') await audioCtx.close();
  audioCtx = null;
  micStream = null;
  sourceNode = null;
  processor = null;
  silentNode = null;
  micActive = false;
  levels.stop();
  levelSnapshot = levels.snapshot();
  translationSnapshot = decoder.reset();
  render();
}

async function sendContactMessage(): Promise<void> {
  const message = refs.prompt.value.trim();
  if (!message || refs.send.disabled) return;
  const entry = appendEntry('sent', message);
  refs.prompt.value = '';
  refs.send.disabled = true;
  setContactStatus('sending');
  try {
    const response = await fetch(`${requestApiBase()}/api/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...apiAuthHeaders() },
      body: JSON.stringify({ message, heard, session }),
      // The API gives the reply model 12 seconds before answering with an error.
      signal: AbortSignal.timeout(20000)
    });
    if (!response.ok) {
      const failure = (await response.json().catch(() => null)) as { error?: string } | null;
      throw new Error(failure?.error ?? `HTTP ${response.status}`);
    }
    // Without contact the message goes nowhere, and the page shows nothing more.
    const payload = (await response.json()) as { contact?: boolean; queued?: number; reply?: string };
    setContactStatus(!payload.contact ? 'no contact: nothing will answer'
      : `queued #${payload.queued ?? '?'}${payload.reply ? `: ${payload.reply}` : ''}`);
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'Sending failed.';
    entry.dataset.failed = 'true';
    const note = document.createElement('p');
    note.className = 'entry-note';
    note.textContent = `Not sent. ${reason}`;
    entry.append(note);
    if (!refs.prompt.value) refs.prompt.value = message;
    setContactStatus(reason);
  } finally {
    refs.send.disabled = false;
    refs.prompt.focus();
  }
}

async function requestSignal(kind: string): Promise<void> {
  if (!debugRefs) return;
  const recordToggle = debugRefs.recordDiagnostic;
  if (recordToggle.checked) {
    if (!micActive || !audioCtx) {
      setRecordStatus('Enable the microphone before recording a diagnostic.');
      return;
    }
    cancelRecording();
    recording = { chunks: [], samples: 0, rate: audioCtx.sampleRate, api: requestApiBase(),
      timer: window.setTimeout(() => void saveRecording(), 25000) };
    recordToggle.checked = false;
    setRecordStatus('Recording microphone for diagnosis…');
  }
  await operatorRequest('POST', '/api/emitter/main/play', { kind });
}

async function operatorRequest(method: 'GET' | 'POST', path: string, body?: object): Promise<void> {
  if (!debugRefs) return;
  debugRefs.resetStatus.textContent = '…';
  try {
    const response = await fetch(`${requestApiBase()}${path}`, {
      method,
      headers: { ...(body ? { 'content-type': 'application/json' } : {}), ...apiAuthHeaders() },
      body: body ? JSON.stringify(body) : undefined
    });
    const payload = (await response.json().catch(() => null)) as { error?: string; randomSignals?: boolean } | null;
    if (!response.ok) {
      if (response.status === 401) debugRefs.apiToken.focus();
      throw new Error(response.status === 401 ? 'Enter the correct operator token above'
        : payload?.error ?? `HTTP ${response.status}`);
    }
    if (typeof payload?.randomSignals === 'boolean') debugRefs.randomSignals.checked = payload.randomSignals;
    debugRefs.resetStatus.textContent = JSON.stringify(payload, null, 1);
  } catch (error) {
    cancelRecording();
    debugRefs.resetStatus.textContent = error instanceof Error ? error.message : 'Request failed';
  }
}

function cancelRecording(): void {
  if (!DEBUG_UI || !recording) return;
  window.clearTimeout(recording.timer);
  recording = null;
  setRecordStatus('Diagnostic recording cancelled.');
}

async function saveRecording(): Promise<void> {
  if (!DEBUG_UI) return;
  const captured = recording;
  if (!captured) return;
  recording = null;
  window.clearTimeout(captured.timer);
  setRecordStatus('Preparing recording…');
  try {
    if (!captured.samples) throw new Error('No microphone samples recorded.');
    const wav = encodeRecording(captured.chunks, captured.rate);
    if (recordingDownloadUrl) URL.revokeObjectURL(recordingDownloadUrl);
    const link = document.createElement('a');
    recordingDownloadUrl = URL.createObjectURL(new Blob([wav], { type: 'audio/wav' }));
    link.href = recordingDownloadUrl;
    link.download = `alive-diagnostic-${Date.now()}.wav`;
    link.textContent = 'Download WAV';
    link.className = 'underline';
    const status = document.createTextNode('Ready · ');
    debugRefs!.recordStatus.replaceChildren(status, link);
    const headers = apiAuthHeaders();
    if (!headers.authorization) link.click();
    status.textContent = `${await uploadRecording(wav, captured.api, heard, headers)} `;
  } catch (error) {
    setRecordStatus(error instanceof Error ? error.message : 'Could not save recording.');
  }
}

const KIND_LABELS = { noise: 'noise', clock: 'clock', intelligent: 'message', sent: 'you' } as const;

function buildEntry(kind: keyof typeof KIND_LABELS, text: string): HTMLLIElement {
  const entry = document.createElement('li');
  entry.className = 'entry';
  entry.dataset.kind = kind;
  entry.innerHTML = '<div class="entry-meta"><time></time><span class="entry-kind"></span></div><p class="entry-text"></p>';
  const now = new Date();
  const time = requiredChild<HTMLTimeElement>(entry, 'time');
  time.dateTime = now.toISOString();
  time.textContent = now.toTimeString().slice(0, 8);
  requiredChild(entry, '.entry-kind').textContent = KIND_LABELS[kind];
  requiredChild(entry, '.entry-text').textContent = text;
  return entry;
}

function appendEntry(kind: keyof typeof KIND_LABELS, text: string): HTMLLIElement {
  const stick = isScrolledToEnd();
  const entry = buildEntry(kind, text);
  // Noise and clocks pass by: only the latest one stays on screen. Messages
  // and the conversation are kept.
  if (kind === 'noise' || kind === 'clock') {
    refs.log.querySelectorAll(':is([data-kind=noise], [data-kind=clock]):not([data-live])')
      .forEach((old) => old.remove());
  }
  // A reception still arriving stays last, below messages sent meanwhile.
  refs.log.insertBefore(entry, liveEntry);
  if (kind !== 'sent' && liveEntry) { liveEntry.remove(); liveEntry = null; }
  while (refs.log.children.length > LOG_LIMIT) refs.log.firstElementChild?.remove();
  refs.logEmpty.hidden = true;
  if (stick || kind === 'sent') scrollToEnd();
  return entry;
}

function renderLive(live: Reception | null): void {
  if (!live) {
    liveEntry?.remove();
    liveEntry = null;
    return;
  }
  const stick = isScrolledToEnd();
  if (!liveEntry) {
    liveEntry = buildEntry(live.kind, '');
    liveEntry.dataset.live = 'true';
    requiredChild(liveEntry, '.entry-kind').textContent = 'receiving';
    refs.log.append(liveEntry);
    refs.logEmpty.hidden = true;
  }
  if (liveEntry.dataset.kind !== live.kind) liveEntry.dataset.kind = live.kind;
  const text = requiredChild(liveEntry, '.entry-text');
  if (text.textContent !== live.text) text.textContent = live.text;
  if (stick) scrollToEnd();
}

function isScrolledToEnd(): boolean {
  return refs.log.scrollHeight - refs.log.scrollTop - refs.log.clientHeight < 40;
}

function scrollToEnd(): void {
  refs.log.scrollTop = refs.log.scrollHeight;
}

function render(): void {
  refs.mic.dataset.active = String(micActive);
  refs.mic.setAttribute('aria-pressed', String(micActive));
  refs.mic.setAttribute('aria-label', micActive ? 'Disable microphone' : 'Enable microphone');
  refs.mic.title = micActive ? 'Disable microphone' : 'Enable microphone';
  renderLive(translationSnapshot.live);
  const state = micActive || stopSimulation ? translationSnapshot.title : 'Microphone off';
  const verdict = translationSnapshot.verdict;
  if (refs.translationState.dataset.state !== `${state}/${verdict}`) {
    refs.translationState.dataset.state = `${state}/${verdict}`;
    refs.translationState.dataset.verdict = verdict;
    refs.translationState.innerHTML = `${state} · <b>${verdict}</b>`;
  }
  const empty = refs.log.children.length === 0;
  if (refs.logEmpty.hidden !== !empty) refs.logEmpty.hidden = !empty;
  const hint = micActive ? 'Listening. Signals appear here as they arrive.'
    : micError || 'Tap the microphone, then hold your phone toward the units.';
  if (empty && refs.logEmpty.textContent !== hint) refs.logEmpty.textContent = hint;
  if (DEBUG_UI) {
    const diagnostics = debugRefs?.micDiagnostics;
    if (diagnostics) {
      diagnostics.textContent = micActive
        ? `M/R ${Math.round(levelSnapshot.levelDb)}/${Math.round(levelSnapshot.noiseFloorDb)}dB · ${translationSnapshot.pair}`
        : 'MIC OFF';
    }
  }
  renderStatus(levelSnapshot.status);
}

function setContactStatus(text: string): void {
  if (DEBUG_UI && debugRefs) debugRefs.contactStatus.textContent = text;
}

function setRecordStatus(text: string): void {
  if (DEBUG_UI && debugRefs) debugRefs.recordStatus.textContent = text;
}

function normalizedApiBase(): string {
  return (debugRefs?.apiBase.value ?? initialApiBase).trim().replace(/\/+$/, '');
}

function requestApiBase(): string {
  const apiBase = normalizedApiBase();
  if (DEBUG_UI) localStorage.setItem('aliveApiBase', apiBase);
  // Without a URL the API lives at this page's own origin (local development
  // server or the debug host's /api proxy).
  return apiBase || location.origin;
}

function apiAuthHeaders(): Record<string, string> {
  const token = (debugRefs?.apiToken.value ?? initialApiToken).trim();
  if (!token) {
    sessionStorage.removeItem('aliveApiToken');
    return {};
  }
  sessionStorage.setItem('aliveApiToken', token);
  return { authorization: `Bearer ${token}` };
}

function newSession(): string {
  const id = crypto.randomUUID?.() ?? Array.from(crypto.getRandomValues(new Uint8Array(16)),
    (byte) => byte.toString(16).padStart(2, '0')).join('');
  sessionStorage.setItem('aliveSession', id);
  return id;
}

function renderStatus(status: ReceiverStatus): void {
  document.documentElement.dataset.status = statusLabel(status);
}

function statusLabel(status: ReceiverStatus): string {
  switch (status) {
    case 'requesting':
      return 'mic';
    case 'calibrating':
      return 'cal';
    case 'listening':
      return 'listen';
    case 'mic-blocked':
      return 'blocked';
    case 'idle':
    default:
      return 'idle';
  }
}

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`missing element ${selector}`);
  return element;
}

function requiredChild<T extends Element = HTMLElement>(parent: Element, selector: string): T {
  const element = parent.querySelector<T>(selector);
  if (!element) throw new Error(`missing element ${selector}`);
  return element;
}
