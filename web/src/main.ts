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
// `bun run build:debug` adds a debug panel below the same page.
declare const __DEBUG_UI__: boolean;
declare const __PUBLISHED_API__: string;
const DEBUG_UI = __DEBUG_UI__;
const SAVED_LIMIT = 50;
const NOTICE_MS = 5000;
const ONLINE_CHECK_MS = 30000;
// eduroam at the venue drops for a few seconds now and then. Visitors see
// the out-of-order notice only once the API has been away this long.
const OUT_OF_ORDER_AFTER_MS = 60000;
// The welcome notice can be closed only after this long, so visitors read it.
const INTRO_CLOSE_AFTER_MS = 4000;

if (DEBUG_UI) { document.title = 'Anybody Listening? · debug'; document.body.classList.add('debug-ui'); }

const app = requiredElement<HTMLDivElement>('#app');
app.innerHTML = `
  <main>
    <section class="receiver">
      <header class="receiver-head">
        <div class="receiver-ident">
          <span id="translationState" class="receiver-state">Microphone off · <b>DEAD</b></span>
        </div>
        ${DEBUG_UI ? `<button id="debugToggle" type="button" class="quiet-button" aria-expanded="false" aria-controls="debugPanel">Debug</button>` : ''}
        <button id="clear" type="button" class="quiet-button">Clear</button>
      </header>
      <div class="reading" aria-live="polite">
        <p id="readingMeta" class="reading-meta"></p>
        <p id="readingText" class="reading-text"></p>
        <p id="readingHint" class="reading-hint">Tap the microphone, then hold your phone toward the installation.</p>
      </div>
      <div id="saved" class="saved" hidden>
        <p class="saved-title">Saved messages</p>
        <ol id="savedList" class="saved-list"></ol>
      </div>
      <button id="savedToggle" type="button" class="saved-toggle" aria-expanded="false" aria-controls="saved" hidden></button>
      <button id="mic" type="button" class="mic-toggle" aria-label="Enable microphone" aria-pressed="false" title="Enable microphone">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="9" y="3" width="6" height="12" rx="3" />
          <path d="M6 10v2a6 6 0 0 0 12 0v-2M12 18v3M8 21h8" />
          <path class="mic-off-cross" d="M3 3l18 18" />
        </svg>
      </button>
    </section>

    <section class="contact">
      <form id="contactForm" class="compose">
        <input id="prompt" maxlength="120" placeholder="Message" autocomplete="off" enterkeyhint="send" aria-label="Message">
        <button id="send" type="submit" aria-label="Send message" title="Send message">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true">
            <path d="M12 20V5M5.5 11.5L12 5l6.5 6.5" />
          </svg>
        </button>
      </form>
    </section>
  </main>
  ${DEBUG_UI ? '' : `
  <div id="intro" class="notice" role="dialog" aria-modal="true" aria-labelledby="introTitle" hidden>
    <div class="notice-box">
      <p id="introTitle" class="notice-title">Anybody Listening?</p>
      <p class="notice-text">This installation sends signals too high for most ears to hear. Tap the microphone and hold your phone toward it. Your phone turns what it hears into text.</p>
      <p class="notice-text">Most of it is noise. When the status at the top turns green and reads ALIVE, someone is out there. Write back in the box at the bottom.</p>
      <button id="introClose" type="button" class="notice-button" disabled>OK</button>
    </div>
  </div>
  <div id="outOfOrder" class="notice out-of-order" role="alertdialog" aria-modal="true" aria-labelledby="outOfOrderTitle" hidden>
    <div class="notice-box">
      <p id="outOfOrderTitle" class="notice-title">Currently out of order :(</p>
      <p class="notice-text">Nothing can answer right now. This page carries on by itself once the connection is back.</p>
    </div>
  </div>`}
  ${DEBUG_UI ? `
  <section id="debugPanel" class="debug-panel" aria-label="Debug" hidden>
    <div id="micDiagnostics" class="debug-line">MIC OFF</div>
    <div id="contactStatus" class="debug-line">---</div>
    <div class="debug-signals" role="group" aria-label="Send a signal now">
      <button type="button" class="debug-button" data-kind="noise">noise now</button>
      <button type="button" class="debug-button" data-kind="clock">clock now</button>
      <button type="button" class="debug-button" data-kind="intelligent">message now</button>
    </div>
    <label class="debug-check">
      <input id="randomSignals" type="checkbox" checked>
      <span>Random signals between requests</span>
    </label>
    <label class="debug-check">
      <input id="simulateUnit" type="checkbox">
      <span>Simulate a unit on this page (local test API only; turns the microphone off)</span>
    </label>
    <div id="simulateStatus" class="debug-line"></div>
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
    <label class="debug-field" for="apiBase">API URL
      <input id="apiBase" type="url" placeholder="https://api.example.com">
    </label>
    <label class="debug-field" for="apiToken">Private operator token (required for signals, status, and reset)
      <input id="apiToken" type="password" autocomplete="off" placeholder="paste operator token">
    </label>
    <button id="showStatus" type="button" class="debug-button">show board roles</button>
    <button id="resetAll" type="button" class="debug-button">reset to the first state</button>
    <pre id="resetStatus" class="debug-line" role="status"></pre>
  </section>` : ''}
`;

const signalStrip = mountSignalStrip();

const refs = {
  translationState: requiredElement<HTMLSpanElement>('#translationState'),
  readingMeta: requiredElement<HTMLParagraphElement>('#readingMeta'),
  readingText: requiredElement<HTMLParagraphElement>('#readingText'),
  readingHint: requiredElement<HTMLParagraphElement>('#readingHint'),
  saved: requiredElement<HTMLDivElement>('#saved'),
  savedList: requiredElement<HTMLOListElement>('#savedList'),
  savedToggle: requiredElement<HTMLButtonElement>('#savedToggle'),
  mic: requiredElement<HTMLButtonElement>('#mic'),
  clear: requiredElement<HTMLButtonElement>('#clear'),
  contactForm: requiredElement<HTMLFormElement>('#contactForm'),
  prompt: requiredElement<HTMLInputElement>('#prompt'),
  send: requiredElement<HTMLButtonElement>('#send'),
  main: requiredElement<HTMLElement>('#app > main'),
  outOfOrder: DEBUG_UI ? null : requiredElement<HTMLDivElement>('#outOfOrder'),
  intro: DEBUG_UI ? null : requiredElement<HTMLDivElement>('#intro'),
  introClose: DEBUG_UI ? null : requiredElement<HTMLButtonElement>('#introClose')
};

// Debug-only controls. In the visitor build DEBUG_UI is false, so this object
// (and every diagnostic string in it) is removed from the bundle entirely.
const debugRefs = DEBUG_UI ? {
  toggle: requiredElement<HTMLButtonElement>('#debugToggle'),
  panel: requiredElement<HTMLElement>('#debugPanel'),
  micDiagnostics: requiredElement<HTMLDivElement>('#micDiagnostics'),
  signalButtons: [...document.querySelectorAll<HTMLButtonElement>('.debug-signals button')],
  randomSignals: requiredElement<HTMLInputElement>('#randomSignals'),
  simulateUnit: requiredElement<HTMLInputElement>('#simulateUnit'),
  simulateStatus: requiredElement<HTMLDivElement>('#simulateStatus'),
  apiBase: requiredElement<HTMLInputElement>('#apiBase'),
  apiToken: requiredElement<HTMLInputElement>('#apiToken'),
  showStatus: requiredElement<HTMLButtonElement>('#showStatus'),
  resetAll: requiredElement<HTMLButtonElement>('#resetAll'),
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
let session = sessionStorage.getItem('aliveSession') ?? newSession();

type Saved = { text: string; at: string };

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
// The window shows one reception: the one arriving, or else the last one.
let lastReception: (Reception & { at: Date }) | null = null;
// Intelligent messages stay for this tab. The newest one is what the API
// expects a visitor to repeat as proof of contact. Sent messages are not kept.
let saved = loadSaved();
let notice: { text: string; until: number } | null = null;
let noticeTimer = 0;
// Out of order once the API has been unreachable, or no unit has polled it,
// for OUT_OF_ORDER_AFTER_MS. Units may still play signals on their own then,
// but nothing can answer. The debug page never checks, so testing goes on.
let outOfOrder = false;
let offlineTimer = 0;
let sending = false;
let stopSimulation: (() => void) | null = null;
// The simulated unit's samples also play into the spectrogram, silently.
let simulationAudio: { ctx: AudioContext; input: GainNode; at: number } | null = null;
let recording: { chunks: Float32Array[]; samples: number; rate: number; api: string; timer: number } | null = null;
let recordingDownloadUrl: string | null = null;

refs.mic.addEventListener('click', () => {
  void toggleMicrophone();
});
refs.clear.addEventListener('click', () => {
  translationSnapshot = decoder.reset(listening() ? 'listening for signal' : undefined);
  lastReception = null;
  render();
});
refs.savedToggle.addEventListener('click', () => {
  setSavedOpen(refs.saved.hidden);
});
refs.contactForm.addEventListener('submit', (event) => {
  event.preventDefault();
  void sendContactMessage();
});
debugRefs?.toggle.addEventListener('click', () => {
  setDebugOpen(debugRefs.panel.hidden);
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
debugRefs?.resetAll.addEventListener('click', () => {
  void resetToFirstState();
});
if (debugRefs) {
  setDebugOpen(localStorage.getItem('aliveDebugOpen') === '1', false);
  if (initialApiToken) void operatorRequest('GET', '/api/status');
}

renderSaved();
render();
if (!DEBUG_UI) {
  showIntro();
  void checkOnline();
  window.setInterval(() => { if (!document.hidden) void checkOnline(); }, ONLINE_CHECK_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void checkOnline(); });
}

async function checkOnline(): Promise<void> {
  let online = true;
  try {
    const response = await fetch(`${requestApiBase()}/api/online`, { signal: AbortSignal.timeout(10000) });
    if (response.ok) online = ((await response.json()) as { online?: boolean }).online !== false;
    // An API without this endpoint answers 401 or 404; only a gateway error
    // means it is down.
    else online = response.status < 500;
  } catch {
    online = false;
  }
  if (online) {
    window.clearTimeout(offlineTimer);
    offlineTimer = 0;
    setOutOfOrder(false);
  } else if (!offlineTimer && !outOfOrder) {
    offlineTimer = window.setTimeout(() => {
      offlineTimer = 0;
      setOutOfOrder(true);
    }, OUT_OF_ORDER_AFTER_MS);
  }
}

// First-time visitors get a short welcome. Its button unlocks after
// INTRO_CLOSE_AFTER_MS; once closed it never shows again on this phone.
function showIntro(): void {
  const { intro, introClose } = refs;
  if (!intro || !introClose || localStorage.getItem('aliveIntroSeen') === '1') return;
  intro.hidden = false;
  renderInert();
  window.setTimeout(() => {
    introClose.disabled = false;
    introClose.focus();
  }, INTRO_CLOSE_AFTER_MS);
  introClose.addEventListener('click', () => {
    localStorage.setItem('aliveIntroSeen', '1');
    intro.hidden = true;
    renderInert();
  }, { once: true });
}

// Behind an open notice, the page takes no taps or focus.
function renderInert(): void {
  refs.main.inert = outOfOrder || refs.intro?.hidden === false;
}

// The notice covers the page and cannot be closed, so nobody waits for an
// answer that cannot come. It goes away by itself once the API is back.
function setOutOfOrder(value: boolean): void {
  if (outOfOrder === value || !refs.outOfOrder) return;
  outOfOrder = value;
  refs.outOfOrder.hidden = !value;
  renderInert();
  renderCompose();
}

function renderCompose(): void {
  refs.prompt.disabled = outOfOrder;
  refs.send.disabled = outOfOrder || sending;
}

function listening(): boolean {
  return micActive || stopSimulation !== null;
}

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
  if (simulationAudio) {
    signalStrip.stop();
    await simulationAudio.ctx.close();
    simulationAudio = null;
  }
  if (on) {
    // The decoder needs one unbroken stream, so the microphone stops first.
    if (micActive) await stopMicrophone();
    translationSnapshot = decoder.reset('listening for signal');
    const ctx = new AudioContext();
    const input = ctx.createGain();
    const mute = ctx.createGain();
    mute.gain.value = 0;
    input.connect(mute).connect(ctx.destination);
    signalStrip.connect(input);
    simulationAudio = { ctx, input, at: 0 };
    stopSimulation = startSimulatedUnit({
      apiBase: requestApiBase,
      feed: (samples, rate) => { showSimulated(samples, rate); receive(samples, rate); },
      status: (text) => { debugRefs.simulateStatus.textContent = text; }
    });
  } else {
    translationSnapshot = decoder.reset();
  }
  debugRefs.simulateUnit.checked = on;
  render();
}

function showSimulated(samples: Float32Array, rate: number): void {
  if (!simulationAudio) return;
  const { ctx, input } = simulationAudio;
  const buffer = ctx.createBuffer(1, samples.length, rate);
  buffer.copyToChannel(new Float32Array(samples), 0);
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(input);
  // Queue the chunks back to back; after a stall, restart just ahead of now.
  simulationAudio.at = Math.max(simulationAudio.at, ctx.currentTime + .05);
  source.start(simulationAudio.at);
  simulationAudio.at += buffer.duration;
}

function receive(input: Float32Array, sampleRate: number): void {
  translationSnapshot = decoder.process(input, sampleRate);
  for (const reception of decoder.takeCompleted()) {
    lastReception = { ...reception, at: new Date() };
    if (reception.kind === 'intelligent') saveMessage(reception.text);
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
    signalStrip.connect(sourceNode);
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
  signalStrip.stop();
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
  if (!message || sending || outOfOrder) return;
  refs.prompt.value = '';
  sending = true;
  renderCompose();
  setContactStatus('sending');
  try {
    const response = await fetch(`${requestApiBase()}/api/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...apiAuthHeaders() },
      body: JSON.stringify({ message, heard: saved.at(-1)?.text ?? '', session }),
      // The API gives the reply model 12 seconds before answering with an error.
      signal: AbortSignal.timeout(20000)
    });
    if (!response.ok) {
      const failure = (await response.json().catch(() => null)) as { error?: string } | null;
      throw new Error(failure?.error ?? `HTTP ${response.status}`);
    }
    // Without contact the message goes nowhere. The page says "Sent" either way.
    const payload = (await response.json()) as { contact?: boolean; queued?: number; reply?: string };
    showNotice('Sent');
    setContactStatus(!payload.contact ? 'no contact: nothing will answer'
      : `queued #${payload.queued ?? '?'}${payload.reply ? `: ${payload.reply}` : ''}`);
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'Sending failed.';
    if (!refs.prompt.value) refs.prompt.value = message;
    showNotice(`Not sent: ${reason}`);
    setContactStatus(reason);
    if (!DEBUG_UI) void checkOnline();
  } finally {
    sending = false;
    renderCompose();
    if (!outOfOrder) refs.prompt.focus();
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

// Back to what a first visit sees: the API forgets every conversation and
// sends a beacon next, and this page drops its saved messages and session.
async function resetToFirstState(): Promise<void> {
  if (!debugRefs) return;
  const reachedApi = await operatorRequest('POST', '/api/emitter/main/reset');
  saved = [];
  sessionStorage.removeItem('aliveMessages');
  session = newSession();
  lastReception = null;
  notice = null;
  translationSnapshot = decoder.reset(listening() ? 'listening for signal' : undefined);
  renderSaved();
  setContactStatus('---');
  render();
  if (!reachedApi) debugRefs.resetStatus.textContent += '\nThis page was reset; the API was not.';
}

async function operatorRequest(method: 'GET' | 'POST', path: string, body?: object): Promise<boolean> {
  if (!debugRefs) return false;
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
    return true;
  } catch (error) {
    cancelRecording();
    debugRefs.resetStatus.textContent = error instanceof Error ? error.message : 'Request failed';
    return false;
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
    status.textContent = `${await uploadRecording(wav, captured.api, saved.at(-1)?.text ?? '', headers)} `;
  } catch (error) {
    setRecordStatus(error instanceof Error ? error.message : 'Could not save recording.');
  }
}

function loadSaved(): Saved[] {
  try {
    const value = JSON.parse(sessionStorage.getItem('aliveMessages') ?? '[]') as unknown;
    return Array.isArray(value) ? value.filter((item): item is Saved =>
      typeof item?.text === 'string' && typeof item?.at === 'string') : [];
  } catch {
    return [];
  }
}

// A message heard again moves to the end with its new time instead of
// appearing twice, since units repeat their beacon lines.
function saveMessage(text: string): void {
  saved = saved.filter((item) => item.text !== text);
  saved.push({ text, at: new Date().toISOString() });
  saved = saved.slice(-SAVED_LIMIT);
  sessionStorage.setItem('aliveMessages', JSON.stringify(saved));
  renderSaved();
}

function renderSaved(): void {
  refs.savedToggle.hidden = saved.length === 0;
  refs.savedToggle.textContent = `Messages ${saved.length}`;
  refs.savedList.replaceChildren(...saved.map(({ text, at }) => {
    const item = document.createElement('li');
    const time = document.createElement('time');
    time.dateTime = at;
    time.textContent = clockTime(new Date(at));
    const body = document.createElement('p');
    body.textContent = text;
    item.append(time, body);
    return item;
  }));
  if (!saved.length) setSavedOpen(false);
  else if (!refs.saved.hidden) refs.savedList.lastElementChild?.scrollIntoView({ block: 'end' });
}

function setSavedOpen(open: boolean): void {
  refs.saved.hidden = !open;
  refs.savedToggle.setAttribute('aria-expanded', String(open));
  if (open) refs.savedList.lastElementChild?.scrollIntoView({ block: 'end' });
}

function setDebugOpen(open: boolean, scroll = true): void {
  if (!debugRefs) return;
  debugRefs.panel.hidden = !open;
  debugRefs.toggle.setAttribute('aria-expanded', String(open));
  // Closed, the debug page behaves like the visitor page. Open, it scrolls.
  document.body.classList.toggle('debug-open', open);
  localStorage.setItem('aliveDebugOpen', open ? '1' : '0');
  if (open && scroll) debugRefs.panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function showNotice(text: string): void {
  notice = { text, until: performance.now() + NOTICE_MS };
  window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(render, NOTICE_MS + 50);
  render();
}

function clockTime(date: Date): string {
  return date.toTimeString().slice(0, 8);
}

const KIND_LABELS = { noise: 'noise', clock: 'clock', intelligent: 'message' } as const;

function renderReading(live: Reception | null): void {
  const shown = live ?? lastReception;
  const kind = shown?.kind ?? '';
  const meta = !shown ? '' : live ? `receiving ${KIND_LABELS[live.kind]}`
    : `${clockTime(lastReception!.at)} · ${KIND_LABELS[shown.kind]}`;
  if (refs.readingText.dataset.kind !== kind) refs.readingText.dataset.kind = kind;
  if (refs.readingText.textContent !== (shown?.text ?? '')) refs.readingText.textContent = shown?.text ?? '';
  refs.readingText.toggleAttribute('data-live', Boolean(live));
  if (refs.readingMeta.textContent !== meta) refs.readingMeta.textContent = meta;
  const hint = shown ? '' : listening() ? 'Listening. Signals appear here as they arrive.'
    : micError || 'Tap the microphone, then hold your phone toward the installation.';
  if (refs.readingHint.textContent !== hint) refs.readingHint.textContent = hint;
}

function render(): void {
  refs.mic.dataset.active = String(micActive);
  refs.mic.setAttribute('aria-pressed', String(micActive));
  refs.mic.setAttribute('aria-label', micActive ? 'Disable microphone' : 'Enable microphone');
  refs.mic.title = micActive ? 'Disable microphone' : 'Enable microphone';
  renderReading(translationSnapshot.live);
  if (notice && performance.now() >= notice.until) notice = null;
  const state = notice?.text ?? (listening() ? translationSnapshot.title : 'Microphone off');
  const verdict = translationSnapshot.verdict;
  const key = `${state}/${verdict}`;
  if (refs.translationState.dataset.state !== key) {
    refs.translationState.dataset.state = key;
    refs.translationState.dataset.verdict = verdict;
    refs.translationState.replaceChildren(`${state} · `, Object.assign(document.createElement('b'), { textContent: verdict }));
  }
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
