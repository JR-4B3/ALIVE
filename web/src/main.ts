import './styles.css';
import { SignalLevelTracker } from './sensing/signalLevelTracker';
import { TranslationDecoder } from './sensing/translationDecoder';
import { encodeRecording } from './audio/recording';
import { uploadRecording } from './audio/recordingUpload';
import type { ReceiverStatus } from './types';

// Set at build time: `bun run build` publishes the clean visitor page to docs/,
// `bun run build:debug` keeps every diagnostic control for local testing.
declare const __DEBUG_UI__: boolean;
const DEBUG_UI = __DEBUG_UI__;

if (DEBUG_UI) document.title = 'ALIVE Receiver · debug';

const app = requiredElement<HTMLDivElement>('#app');
app.innerHTML = `
  <main class="mx-auto flex min-h-dvh w-full max-w-xl flex-col gap-4 px-4 py-4">
    <section class="flex flex-1 flex-col border border-white">
      <div class="flex items-center justify-between border-b border-white px-3 py-2">
        <div>
          <div class="text-xs uppercase tracking-[0.24em] text-neutral-400">translation${DEBUG_UI ? ' · debug' : ''}</div>
          <div id="translationState" class="mt-1 text-xs uppercase tracking-[0.16em]">Listening</div>
        </div>
        <button id="clear" class="px-3 py-2 text-xs uppercase tracking-[0.16em]">clear</button>
      </div>
      <div class="flex min-h-48 flex-1 items-center justify-center px-4 py-8">
        <div id="message" class="w-full break-words text-center font-mono text-4xl leading-tight sm:text-6xl">---</div>
      </div>
    </section>

    <section class="grid gap-3">
      <button id="mic" class="min-h-14 px-4 text-base uppercase tracking-[0.18em]">enable microphone</button>
      ${DEBUG_UI ? `<div id="micDiagnostics" class="break-words font-mono text-xs text-neutral-400">RX V6 · MIC OFF</div>` : ''}
      <form id="contactForm" class="grid gap-3 border border-white px-3 py-3">
        <div class="text-xs uppercase tracking-[0.24em] text-neutral-400">contact</div>
        <input id="prompt" class="min-h-11 px-3 text-base" maxlength="120" placeholder="message">
        <div class="grid grid-cols-2 gap-3">
          <button id="send" class="min-h-11 px-3 text-xs uppercase tracking-[0.16em]">send</button>
          <button id="playSignal" type="button" class="min-h-11 px-3 text-xs uppercase tracking-[0.16em]">play signal</button>
        </div>
        ${DEBUG_UI ? `
        <details class="border-t border-neutral-700 pt-2 text-xs text-neutral-400">
          <summary class="cursor-pointer uppercase tracking-[0.16em]">connection settings</summary>
          <label class="mt-3 grid gap-1 uppercase tracking-[0.16em]" for="apiBase">
            NAS API URL
            <input id="apiBase" class="min-h-11 px-3 text-base normal-case tracking-normal" type="url" placeholder="https://api.example.com">
          </label>
          <label class="mt-3 grid gap-1 uppercase tracking-[0.16em]" for="apiToken">
            Private operator token (leave empty at the exhibition)
            <input id="apiToken" class="min-h-11 px-3 text-base normal-case tracking-normal" type="password" autocomplete="off" placeholder="optional">
          </label>
        </details>
        <div id="contactStatus" class="min-h-6 font-mono text-xs uppercase tracking-[0.16em] text-neutral-400">---</div>
        <label class="text-sm text-neutral-400">
          <input id="recordDiagnostic" type="checkbox">
          Record next playback for diagnosis (up to 25 seconds of microphone and room sound). A WAV download is kept on this phone; NAS upload is optional and requires the operator token.
        </label>
        <div id="recordStatus" class="text-sm text-neutral-400"></div>` : ''}
      </form>
    </section>
  </main>
`;

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
  contactStatus: requiredElement<HTMLDivElement>('#contactStatus'),
  recordDiagnostic: requiredElement<HTMLInputElement>('#recordDiagnostic'),
  recordStatus: requiredElement<HTMLDivElement>('#recordStatus')
} : null;

const params = new URLSearchParams(location.search);
const exhibitionApi = location.hostname === 'jr-4b3.github.io' && location.pathname.startsWith('/ALIVE/')
  ? 'https://ds720.tail688a7b.ts.net' : '';
const initialApiBase = params.get('api') ?? (exhibitionApi
  ? (localStorage.getItem('aliveExhibitionApi') || exhibitionApi)
  : (localStorage.getItem('aliveApiBase') || ''));
const initialApiToken = params.get('token') ?? (sessionStorage.getItem('aliveApiToken') ?? '');
if (debugRefs) {
  debugRefs.apiBase.value = initialApiBase;
  debugRefs.apiToken.value = initialApiToken;
}

const levels = new SignalLevelTracker();
const decoder = new TranslationDecoder();
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

render();

async function toggleMicrophone(): Promise<void> {
  if (micActive) {
    await stopMicrophone();
    return;
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
    sourceNode.connect(processor);
    processor.connect(silentNode).connect(audioCtx.destination);
    await audioCtx.resume();
    micActive = true;
    levels.startCalibration(performance.now());
    levelSnapshot = levels.snapshot();
    translationSnapshot = decoder.reset('decoded message will appear here');
    refs.mic.textContent = 'disable microphone';
    renderStatus('calibrating');
    render();
  } catch (error) {
    renderStatus('mic-blocked');
    refs.translationState.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function stopMicrophone(): Promise<void> {
  cancelRecording();
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
  refs.mic.textContent = 'enable microphone';
  render();
}

async function sendContactMessage(): Promise<void> {
  const message = refs.prompt.value.trim();
  if (!message) return;
  reportStatus('sending', refs.send, 'send');
  refs.prompt.disabled = true;
  try {
    const apiBase = requestApiBase();
    const response = await fetch(`${apiBase}/api/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...apiAuthHeaders() },
      body: JSON.stringify({ message })
    });
    if (!response.ok) {
      const failure = (await response.json().catch(() => null)) as { error?: string } | null;
      throw new Error(failure?.error ?? `HTTP ${response.status}`);
    }
    const payload = (await response.json()) as { reply?: string; message?: string; duration?: number };
    reportStatus(payload.reply ?? payload.message ?? 'sent', refs.send, 'send');
    refs.prompt.value = '';
  } catch (error) {
    reportStatus(error instanceof Error ? error.message : 'send failed', refs.send, 'send');
  } finally {
    refs.prompt.disabled = false;
    refs.prompt.focus();
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
    if (micActive) {
      translationSnapshot = decoder.beginCapture(performance.now());
      render();
    }
    setContactStatus('playing');
    lockReplay(1);
    const response = await requestPlayWithOfflineRetry(apiBase);
    const payload = (await response.json()) as { duration?: number; message?: string };
    if (DEBUG_UI) {
      if (recording) {
        recording.message = payload.message ?? '';
        window.clearTimeout(recording.timer);
        recording.timer = window.setTimeout(() => void saveRecording(), Math.min(23, (payload.duration ?? 20) + 1.5) * 1000);
      }
    }
    if (micActive && payload.duration) decoder.setCaptureDuration(performance.now(), payload.duration);
    setContactStatus('ESP32 signal queued');
    lockReplay(payload.duration, DEBUG_UI ? 0 : 1000);
  } catch (error) {
    cancelRecording();
    unlockReplay();
    reportStatus(error instanceof Error ? error.message : 'play failed', refs.playSignal, 'play signal');
  } finally {
    playPending = false;
  }
}

async function requestPlayWithOfflineRetry(apiBase: string): Promise<Response> {
  const retryUntil = Date.now() + 5000;
  while (true) {
    const response = await fetch(`${apiBase}/api/emitter/main/play`, {
      method: 'POST', headers: apiAuthHeaders()
    });
    if (response.ok) return response;
    if (response.status === 405) throw new Error(DEBUG_UI ? 'HTTP 405: enter the NAS API URL above' : 'HTTP 405: no signal API');
    const failure = (await response.json().catch(() => null)) as { error?: string } | null;
    const error = failure?.error ?? `HTTP ${response.status}`;
    if (DEBUG_UI || response.status !== 503 || !error.startsWith('ESP32 is offline') || Date.now() >= retryUntil) {
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
    link.textContent = 'Download WAV recording';
    link.className = 'underline';
    const status = document.createTextNode('Recording ready. ');
    debugRefs!.recordStatus.replaceChildren(status, link);
    const headers = apiAuthHeaders();
    if (!headers.authorization) link.click();
    status.textContent = `${await uploadRecording(wav, captured.api, captured.message, headers)} `;
  } catch (error) {
    setRecordStatus(error instanceof Error ? error.message : 'Could not save recording.');
  }
}

function lockReplay(durationSeconds = 0, extraWaitMs = 0): void {
  const durationMs = Math.max(1000, Math.ceil(durationSeconds * 1000) + 250) + extraWaitMs;
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
  refs.translationState.textContent = `${translationSnapshot.title} · ${translationSnapshot.verdict}`;
  refs.message.textContent = translationSnapshot.message;
  if (DEBUG_UI) {
    const diagnostics = debugRefs?.micDiagnostics;
    if (diagnostics) {
      diagnostics.textContent = micActive
        ? `RX V6 · MIC ${Math.round(levelSnapshot.levelDb)} dB · ROOM ${Math.round(levelSnapshot.noiseFloorDb)} dB · TONE ${translationSnapshot.pair} · RX ${translationSnapshot.stream}`
        : 'RX V6 · MIC OFF — enable microphone before play to decode';
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
  return (debugRefs?.apiBase.value ?? initialApiBase).trim().replace(/\/+$/, '');
}

function requestApiBase(): string {
  const apiBase = normalizedApiBase();
  if (debugRefs) {
    localStorage.setItem('aliveApiBase', apiBase);
    if (exhibitionApi) localStorage.setItem('aliveExhibitionApi', apiBase);
  }
  // An explicit URL wins; otherwise the API lives at this page's own origin
  // (NAS container, laptop emitter, or the debug host's /api proxy).
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
