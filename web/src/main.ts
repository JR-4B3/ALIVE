import './styles.css';
import { SignalLevelTracker } from './sensing/signalLevelTracker';
import { SignalReceiver } from './sensing/signalReceiver';
import { encodeRecording } from './audio/recording';
import { uploadRecording } from './audio/recordingUpload';
import type { ReceiverStatus } from './types';
import { normalizeApiBase, apiFailure, ApiConnectionError } from './api/connection';

// Set at build time: `bun run build` publishes the clean visitor page to docs/,
// `bun run build:debug` keeps every diagnostic control for local testing.
declare const __DEBUG_UI__: boolean;
declare const __PUBLISHED_API__: string;
const DEBUG_UI = __DEBUG_UI__;

if (DEBUG_UI) { document.title = 'ALIVE Receiver · debug'; document.body.classList.add('debug-ui'); }

const app = requiredElement<HTMLDivElement>('#app');
app.innerHTML = `
  <main class="mx-auto flex min-h-dvh w-full max-w-xl flex-col gap-4 px-4 py-4">
    <section class="flex flex-1 flex-col border border-white">
      <div class="flex items-center justify-between border-b border-white px-3 py-2">
        <div>
          <div class="whitespace-nowrap text-[13px] uppercase tracking-[0.06em] text-neutral-400">translation${DEBUG_UI ? ' · debug' : ''}</div>
          <div id="translationState" class="mt-1 text-sm uppercase tracking-[0.1em]">Listening</div>
        </div>
        <button id="clear" class="px-3 py-2 text-sm uppercase tracking-[0.1em]">clear</button>
      </div>
      <div class="flex min-h-48 flex-1 items-center justify-center px-4 py-8">
        <div id="message" class="w-full break-words text-center font-mono text-4xl leading-tight sm:text-6xl">---</div>
      </div>
      <button id="mic" type="button" class="mic-toggle" aria-label="Enable microphone" aria-pressed="false" title="Enable microphone">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="9" y="3" width="6" height="12" rx="3" />
          <path d="M6 10v2a6 6 0 0 0 12 0v-2M12 18v3M8 21h8" />
          <path class="mic-off-cross" d="M3 3l18 18" />
        </svg>
      </button>
    </section>

    <section class="grid min-w-0 grid-cols-1 gap-3">
      <form id="contactForm" class="grid min-w-0 grid-cols-1 gap-3 border border-white px-3 py-3">
        <div class="flex min-w-0 items-center gap-2">
          <div class="shrink-0 text-sm uppercase tracking-[0.12em] text-neutral-400">contact</div>
          ${DEBUG_UI ? `<div id="micDiagnostics" class="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap border-l border-neutral-600 pl-2 font-mono text-[clamp(10px,3vw,12px)] text-neutral-400">MIC OFF</div>` : ''}
        </div>
        <input id="prompt" class="min-h-11 px-3 text-lg" maxlength="120" placeholder="message">
        <div class="grid grid-cols-2 gap-3">
          <button id="send" class="min-h-11 px-2 text-sm uppercase tracking-normal">send</button>
          <button id="playSignal" type="button" class="min-h-11 whitespace-nowrap px-2 text-sm uppercase tracking-normal">play signal</button>
        </div>
        ${DEBUG_UI ? `
        <div id="contactStatus" class="min-h-6 font-mono text-sm uppercase tracking-[0.08em] text-neutral-400">---</div>
        <label class="flex cursor-pointer items-center gap-2 text-base text-neutral-400">
          <input id="recordDiagnostic" class="sr-only" type="checkbox">
          <span class="record-checkbox-mark" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="12" height="12" fill="none" aria-hidden="true">
              <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" stroke-width="2" />
            </svg>
          </span>
          <span>Record next playback (25s max)</span>
        </label>
        <div id="recordStatus" class="text-base text-neutral-400"></div>
        <details class="min-w-0 border-t border-neutral-700 pt-2 text-sm text-neutral-400">
          <summary class="cursor-pointer uppercase tracking-[0.1em]">connection settings</summary>
          <label class="mt-3 grid min-w-0 grid-cols-1 gap-1 uppercase tracking-[0.1em]" for="apiBase">
            API URL
            <input id="apiBase" class="min-h-11 min-w-0 w-full px-3 text-lg normal-case tracking-normal" type="url" placeholder="https://api.example.com">
          </label>
          <label class="mt-3 grid min-w-0 grid-cols-1 gap-1 uppercase tracking-[0.1em]" for="apiToken">
            Private operator token (required for reset)
            <input id="apiToken" class="min-h-11 min-w-0 w-full px-3 text-lg normal-case tracking-normal" type="password" autocomplete="off" placeholder="paste operator token">
          </label>
          <button id="resetMessage" type="button" class="mt-3 min-h-11 w-full px-3 text-sm uppercase tracking-[0.08em]">reset message</button>
          <div id="resetStatus" class="mt-2 font-mono text-xs empty:hidden" role="status"></div>
        </details>` : ''}
      </form>
      ${!DEBUG_UI ? `
      <details id="connectionSettings" class="min-w-0 text-sm text-neutral-400">
        <summary class="cursor-pointer uppercase tracking-[0.1em]">connection settings</summary>
        <label class="mt-3 grid gap-1" for="visitorApiBase">
          ALIVE API URL
          <input id="visitorApiBase" class="min-h-11 min-w-0 w-full px-3 text-base" type="url" placeholder="https://api.example.com">
        </label>
        <button id="saveConnection" type="button" class="mt-2 min-h-11 w-full px-3 uppercase">save connection</button>
      </details>
      <div id="connectionStatus" class="break-words text-sm text-neutral-400 empty:hidden" role="status"></div>` : ''}
    </section>
  </main>
`;

// Selected signal-strip layout on the visitor receiver. The sound codec remains experimental.
const PROTOTYPE_MODE = import.meta.env.MODE === 'prototype' ||
  (import.meta.env.DEV && new URLSearchParams(location.search).get('prototype') === 'space');
const signalStrip = !DEBUG_UI
  ? (await import('./prototype/spacePrototype')).mountSpacePrototype((samples, rate) => {
      const now = performance.now();
      levelSnapshot = levels.process(samples, now);
      translationSnapshot = decoder.process(samples, rate, levelSnapshot.levelDb, levelSnapshot.noiseFloorDb, now / 1000, now);
      render();
    }) : null;

const refs = {
  translationState: requiredElement<HTMLDivElement>('#translationState'),
  message: requiredElement<HTMLDivElement>('#message'),
  mic: requiredElement<HTMLButtonElement>('#mic'),
  clear: requiredElement<HTMLButtonElement>('#clear'),
  contactForm: requiredElement<HTMLFormElement>('#contactForm'),
  prompt: requiredElement<HTMLInputElement>('#prompt'),
  send: requiredElement<HTMLButtonElement>('#send'),
  playSignal: requiredElement<HTMLButtonElement>('#playSignal')
};

// Debug-only controls. In the visitor build DEBUG_UI is false, so this object
// (and every diagnostic string in it) is removed from the bundle entirely.
const debugRefs = DEBUG_UI ? {
  micDiagnostics: requiredElement<HTMLDivElement>('#micDiagnostics'),
  apiBase: requiredElement<HTMLInputElement>('#apiBase'),
  apiToken: requiredElement<HTMLInputElement>('#apiToken'),
  resetMessage: requiredElement<HTMLButtonElement>('#resetMessage'),
  resetStatus: requiredElement<HTMLDivElement>('#resetStatus'),
  contactStatus: requiredElement<HTMLDivElement>('#contactStatus'),
  recordDiagnostic: requiredElement<HTMLInputElement>('#recordDiagnostic'),
  recordStatus: requiredElement<HTMLDivElement>('#recordStatus')
} : null;

const params = new URLSearchParams(location.search);
// A link or a manually saved URL wins; otherwise the published API. The
// prototype server proxies /api on its own origin.
let initialApiBase = params.get('api')?.trim() || (PROTOTYPE_MODE ? '' :
  localStorage.getItem('aliveApiBase') || __PUBLISHED_API__);
const initialApiToken = params.get('token') ?? (PROTOTYPE_MODE ? '' : sessionStorage.getItem('aliveApiToken') ?? '');
if (debugRefs) {
  debugRefs.apiBase.value = initialApiBase;
  debugRefs.apiToken.value = initialApiToken;
}
const visitorApiBase = document.querySelector<HTMLInputElement>('#visitorApiBase');
if (visitorApiBase) visitorApiBase.value = initialApiBase;
document.querySelector('#saveConnection')?.addEventListener('click', () => {
  try {
    initialApiBase = normalizeApiBase(visitorApiBase!.value);
    if (initialApiBase) localStorage.setItem('aliveApiBase', initialApiBase);
    else localStorage.removeItem('aliveApiBase');
    const url = new URL(location.href);
    url.searchParams.delete('api');
    history.replaceState(null, '', url);
    requiredElement<HTMLDetailsElement>('#connectionSettings').open = false;
    requiredElement('#connectionStatus').textContent = 'Connection saved. Try send or play signal again.';
  } catch (error) {
    showConnectionError(error);
  }
});

const levels = new SignalLevelTracker();
const decoder = new SignalReceiver();
let levelSnapshot = levels.snapshot();
let translationSnapshot = decoder.snapshot();
let audioCtx: AudioContext | null = null;
let micStream: MediaStream | null = null;
let sourceNode: MediaStreamAudioSourceNode | null = null;
let processor: ScriptProcessorNode | null = null;
let silentNode: GainNode | null = null;
let micActive = false;
let replayReadyAt = 0;
let replayTimer: number | null = null;
let playPending = false;
let recording: { chunks: Float32Array[]; samples: number; rate: number; api: string; message: string; timer: number } | null = null;
let recordingDownloadUrl: string | null = null;

refs.mic.addEventListener('click', () => {
  void toggleMicrophone();
});
refs.clear.addEventListener('click', () => {
  translationSnapshot = decoder.reset();
  render();
});
refs.contactForm.addEventListener('submit', (event) => {
  event.preventDefault();
  void sendContactMessage();
});
refs.playSignal.addEventListener('click', () => {
  void playCurrentSignal();
});
debugRefs?.resetMessage.addEventListener('click', () => {
  void resetPreparedMessage();
});

render();

async function toggleMicrophone(): Promise<void> {
  if (signalStrip?.remoteActive()) { await signalStrip.stopRemote(); return; }
  if (micActive) {
    await stopMicrophone();
    return;
  }
  if (signalStrip?.remoteRequested()) {
    levels.startCalibration(performance.now());
    translationSnapshot = decoder.reset('listening for signal');
    await signalStrip.startRemote(); render(); return;
  }
  await startMicrophone();
}

async function startMicrophone(): Promise<void> {
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
      const nowMs = performance.now();
      levelSnapshot = levels.process(input, nowMs);
      translationSnapshot = decoder.process(
        input,
        audioCtx.sampleRate,
        levelSnapshot.levelDb,
        levelSnapshot.noiseFloorDb,
        audioCtx.currentTime,
        nowMs
      );
      render();
    };
    signalStrip?.connect(sourceNode, audioCtx);
    sourceNode.connect(processor);
    processor.connect(silentNode).connect(audioCtx.destination);
    await audioCtx.resume();
    micActive = true;
    levels.startCalibration(performance.now());
    levelSnapshot = levels.snapshot();
    translationSnapshot = decoder.reset('decoded message will appear here');

    renderStatus('calibrating');
    render();
  } catch (error) {
    renderStatus('mic-blocked');
    refs.translationState.textContent = error instanceof Error ? error.message : String(error);
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

  render();
}

async function sendContactMessage(): Promise<void> {
  const message = refs.prompt.value.trim();
  if (!message) return;
  reportStatus('sending', refs.send, 'send');
  refs.prompt.disabled = true;
  if (debugRefs) debugRefs.resetMessage.disabled = true;
  try {
    const apiBase = requestApiBase();
    const response = await fetch(`${apiBase}/api/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...apiAuthHeaders() },
      body: JSON.stringify({ message }),
      // The API gives the reply model 12 seconds before answering with an error.
      signal: AbortSignal.timeout(20000)
    });
    if (!response.ok) {
      throw await apiFailure(response);
    }
    const payload = (await response.json()) as { reply?: string; message?: string; duration?: number };
    reportStatus(DEBUG_UI ? (payload.reply ?? payload.message ?? 'sent') : 'sent', refs.send, 'send');
    refs.prompt.value = '';
  } catch (error) {
    if (error instanceof ApiConnectionError || error instanceof TypeError) showConnectionError(error);
    reportStatus(error instanceof Error ? error.message : 'send failed', refs.send, 'send');
  } finally {
    refs.prompt.disabled = false;
    if (debugRefs) debugRefs.resetMessage.disabled = false;
    refs.prompt.focus();
  }
}

async function resetPreparedMessage(): Promise<void> {
  if (!debugRefs || refs.prompt.disabled) return;
  debugRefs.resetMessage.disabled = true;
  refs.prompt.disabled = true;
  refs.send.disabled = true;
  debugRefs.resetStatus.textContent = 'Resetting…';
  try {
    const response = await fetch(`${requestApiBase()}/api/emitter/main/reset`, {
      method: 'POST', headers: apiAuthHeaders()
    });
    if (!response.ok) {
      if (response.status === 401) {
        debugRefs.apiToken.focus();
        throw new Error('Enter the correct operator token above');
      }
      const failure = (await response.json().catch(() => null)) as { error?: string } | null;
      throw new Error(failure?.error ?? `HTTP ${response.status}`);
    }
    const payload = (await response.json()) as { message: string };
    refs.prompt.value = '';
    translationSnapshot = decoder.reset();
    render();
    setContactStatus('---');
    debugRefs.resetStatus.textContent = `Ready: ${payload.message}`;
  } catch (error) {
    debugRefs.resetStatus.textContent = error instanceof Error ? error.message : 'Reset failed';
  } finally {
    refs.prompt.disabled = false;
    refs.send.disabled = false;
    debugRefs.resetMessage.disabled = false;
  }
}

async function playCurrentSignal(): Promise<void> {
  if (playPending || Date.now() < replayReadyAt) return;
  playPending = true;
  try {
    const apiBase = requestApiBase();
    if (DEBUG_UI) {
      const recordToggle = debugRefs?.recordDiagnostic;
      if (recordToggle?.checked) {
        if (!micActive || !audioCtx) throw new Error('Enable microphone before recording a diagnostic.');
        cancelRecording();
        recording = { chunks: [], samples: 0, rate: audioCtx.sampleRate, api: apiBase, message: '',
          timer: window.setTimeout(() => void saveRecording(), 25000) };
        recordToggle.checked = false;
        setRecordStatus('Recording microphone for diagnosis…');
      }
    }
    if (micActive || signalStrip?.remoteActive()) {
      translationSnapshot = decoder.beginCapture(performance.now());
      render();
    }
    setContactStatus('playing');
    lockReplay(1);
    const response = await requestPlayWhenReady(apiBase);
    const payload = (await response.json()) as { duration?: number; message?: string; replayAfterSeconds?: number };
    if (DEBUG_UI) {
      if (recording) {
        recording.message = payload.message ?? '';
        window.clearTimeout(recording.timer);
        recording.timer = window.setTimeout(() => void saveRecording(), Math.min(23, (payload.duration ?? 20) + 1.5) * 1000);
      }
    }
    if ((micActive || signalStrip?.remoteActive()) && payload.duration) decoder.setCaptureDuration(performance.now(), payload.duration);
    setContactStatus('ESP32 signal queued');
    // Match the API's replay deadline; older API builds only report the duration.
    lockReplay(Math.max(payload.duration ?? 0, payload.replayAfterSeconds ?? ((payload.duration ?? 0) + 1)));
  } catch (error) {
    cancelRecording();
    unlockReplay();
    if (error instanceof ApiConnectionError || error instanceof TypeError) showConnectionError(error);
    reportStatus(error instanceof Error ? error.message : 'play failed', refs.playSignal, 'play signal');
  } finally {
    playPending = false;
  }
}

async function requestPlayWhenReady(apiBase: string): Promise<Response> {
  const retryUntil = Date.now() + 5000;
  while (true) {
    const response = await fetch(`${apiBase}/api/emitter/main/play`, {
      method: 'POST', headers: { ...apiAuthHeaders(), 'content-type': 'application/json' },
      body: JSON.stringify(signalStrip ? { soundDirection: signalStrip.sound() } : {}),
      signal: AbortSignal.timeout(8000)
    });
    if (response.ok) return response;
    const failure = await apiFailure(response);
    if (failure instanceof ApiConnectionError) throw failure;
    const error = failure.message;
    const replayWait = response.status === 429 ? /^Wait (\d+)s before replaying$/.exec(error) : null;
    if (replayWait && Date.now() + Number(replayWait[1]) * 1000 <= retryUntil) {
      const waitSeconds = Number(replayWait[1]);
      lockReplay(waitSeconds);
      await new Promise<void>((resolve) => window.setTimeout(resolve, waitSeconds * 1000));
      continue;
    }
    if (response.status !== 503 || !error.startsWith('ESP32 is offline') || Date.now() >= retryUntil) {
      throw new Error(error);
    }
    showPlayLoading();
    await new Promise<void>((resolve) => window.setTimeout(resolve, 500));
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
    link.download = `alive-diagnostic-${Date.now()}-${captured.message.replace(/[^A-Z ]/g, '').trim().replaceAll(' ', '-') || 'signal'}.wav`;
    link.textContent = 'Download WAV';
    link.className = 'underline';
    const status = document.createTextNode('Ready · ');
    debugRefs!.recordStatus.replaceChildren(status, link);
    const headers = apiAuthHeaders();
    if (!headers.authorization) link.click();
    status.textContent = `${await uploadRecording(wav, captured.api, captured.message, headers)} `;
  } catch (error) {
    setRecordStatus(error instanceof Error ? error.message : 'Could not save recording.');
  }
}

function lockReplay(durationSeconds = 0): void {
  const durationMs = Math.max(1000, Math.ceil(durationSeconds * 1000) + 250);
  replayReadyAt = Date.now() + durationMs;
  if (replayTimer !== null) window.clearInterval(replayTimer);
  refs.playSignal.disabled = true;
  refs.playSignal.removeAttribute('aria-label');
  updateReplayButton();
  replayTimer = window.setInterval(updateReplayButton, 200);
}

function updateReplayButton(): void {
  const remainingMs = replayReadyAt - Date.now();
  if (remainingMs <= 0) {
    if (!playPending) unlockReplay();
    return;
  }
  refs.playSignal.textContent = `wait ${Math.ceil(remainingMs / 1000)}s`;
}

function showPlayLoading(): void {
  replayReadyAt = 0;
  if (replayTimer !== null) {
    window.clearInterval(replayTimer);
    replayTimer = null;
  }
  refs.playSignal.disabled = true;
  refs.playSignal.setAttribute('aria-label', 'Waiting for signal');
  if (!refs.playSignal.querySelector('.play-loading')) {
    refs.playSignal.innerHTML = '<span class="play-loading" aria-hidden="true"><span></span><span></span><span></span></span>';
  }
}

function unlockReplay(): void {
  replayReadyAt = 0;
  if (replayTimer !== null) {
    window.clearInterval(replayTimer);
    replayTimer = null;
  }
  refs.playSignal.disabled = false;
  refs.playSignal.removeAttribute('aria-label');
  refs.playSignal.textContent = 'play signal';
}

function render(): void {
  const capturing = micActive || !!signalStrip?.remoteActive();
  refs.mic.dataset.active = String(capturing);
  refs.mic.setAttribute('aria-pressed', String(capturing));
  refs.mic.setAttribute('aria-label', capturing ? 'Disable microphone' : 'Enable microphone');
  refs.mic.title = capturing ? 'Disable microphone' : 'Enable microphone';
  refs.translationState.textContent = `${translationSnapshot.title} · ${translationSnapshot.verdict}`;
  refs.message.textContent = translationSnapshot.message;
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
  if (DEBUG_UI) debugRefs?.contactStatus && (debugRefs.contactStatus.textContent = text);
}

function setRecordStatus(text: string): void {
  if (DEBUG_UI) debugRefs?.recordStatus && (debugRefs.recordStatus.textContent = text);
}

const flashTimers = new Map<HTMLButtonElement, number>();

// The clean visitor page has no status line, so send/play results flash on the
// button that caused them and return to its normal label.
function reportStatus(text: string, button: HTMLButtonElement, restoreLabel: string): void {
  const statusLine = debugRefs?.contactStatus;
  if (statusLine) {
    statusLine.textContent = text;
    return;
  }
  const previous = flashTimers.get(button);
  if (previous !== undefined) window.clearTimeout(previous);
  const flashed = text.length > 24 ? `${text.slice(0, 23)}…` : text;
  button.textContent = flashed;
  flashTimers.set(button, window.setTimeout(() => {
    flashTimers.delete(button);
    // A replay lock may have started meanwhile; it owns the label now.
    if (button.textContent === flashed) button.textContent = restoreLabel;
  }, 3000));
}

function normalizedApiBase(): string {
  return normalizeApiBase(debugRefs?.apiBase.value ?? initialApiBase);
}

function showConnectionError(error: unknown): void {
  const settings = document.querySelector<HTMLDetailsElement>('#connectionSettings') ?? debugRefs?.apiBase.closest('details');
  if (settings) settings.open = true;
  const status = document.querySelector('#connectionStatus') ?? debugRefs?.contactStatus;
  if (status) status.textContent = error instanceof TypeError
    ? 'Cannot reach the ALIVE API. Check its URL and that it allows this site to connect.'
    : error instanceof Error ? error.message : 'Check the ALIVE API URL.';
  (visitorApiBase ?? debugRefs?.apiBase)?.focus();
}

function requestApiBase(): string {
  if (PROTOTYPE_MODE && signalStrip) return normalizedApiBase() || signalStrip.api() || location.origin;
  const apiBase = normalizedApiBase();
  if (DEBUG_UI) localStorage.setItem('aliveApiBase', apiBase);
  // Without a URL the API lives at this page's own origin (local development
  // server or the debug host's /api proxy).
  return apiBase || location.origin;
}

function apiAuthHeaders(): Record<string, string> {
  const token = (debugRefs?.apiToken.value ?? initialApiToken).trim();
  if (!token) {
    if (!PROTOTYPE_MODE) sessionStorage.removeItem('aliveApiToken');
    return {};
  }
  if (!PROTOTYPE_MODE) sessionStorage.setItem('aliveApiToken', token);
  return { authorization: `Bearer ${token}` };
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
