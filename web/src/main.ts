import './styles.css';
import { SignalLevelTracker } from './sensing/signalLevelTracker';
import { TranslationDecoder } from './sensing/translationDecoder';
import { encodeRecording } from './audio/recording';
import type { ReceiverStatus } from './types';

const app = requiredElement<HTMLDivElement>('#app');
app.innerHTML = `
  <main class="mx-auto flex min-h-dvh w-full max-w-xl flex-col gap-4 px-4 py-4">
    <section class="flex flex-1 flex-col border border-white">
      <div class="flex items-center justify-between border-b border-white px-3 py-2">
        <div>
          <div class="text-xs uppercase tracking-[0.24em] text-neutral-400">translation</div>
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
      <div id="micDiagnostics" class="break-words font-mono text-xs text-neutral-400">RX V5 · MIC OFF</div>
      <form id="contactForm" class="grid gap-3 border border-white px-3 py-3">
        <div class="text-xs uppercase tracking-[0.24em] text-neutral-400">contact</div>
        <input id="prompt" class="min-h-11 px-3 text-base" maxlength="120" placeholder="message">
        <div class="grid grid-cols-2 gap-3">
          <button id="send" class="min-h-11 px-3 text-xs uppercase tracking-[0.16em]">send</button>
          <button id="playSignal" type="button" class="min-h-11 px-3 text-xs uppercase tracking-[0.16em]">play signal</button>
        </div>
        <label class="grid gap-1 text-xs uppercase tracking-[0.16em] text-neutral-400" for="apiBase">
          Laptop server URL (leave blank on local page)
          <input id="apiBase" class="min-h-11 px-3 text-base normal-case tracking-normal" type="url" placeholder="https://192.168.x.x:8765">
        </label>
        <div id="contactStatus" class="min-h-6 font-mono text-xs uppercase tracking-[0.16em] text-neutral-400">---</div>
        <label class="text-sm text-neutral-400">
          <input id="recordDiagnostic" type="checkbox">
          Record next playback for diagnosis (up to 25 seconds of microphone and room sound, saved to this laptop).
        </label>
        <div id="recordStatus" class="text-sm text-neutral-400"></div>
      </form>
    </section>
  </main>
`;

const refs = {
  translationState: requiredElement<HTMLDivElement>('#translationState'),
  message: requiredElement<HTMLDivElement>('#message'),
  mic: requiredElement<HTMLButtonElement>('#mic'),
  micDiagnostics: requiredElement<HTMLDivElement>('#micDiagnostics'),
  clear: requiredElement<HTMLButtonElement>('#clear'),
  contactForm: requiredElement<HTMLFormElement>('#contactForm'),
  prompt: requiredElement<HTMLInputElement>('#prompt'),
  apiBase: requiredElement<HTMLInputElement>('#apiBase'),
  contactStatus: requiredElement<HTMLDivElement>('#contactStatus'),
  playSignal: requiredElement<HTMLButtonElement>('#playSignal'),
  recordDiagnostic: requiredElement<HTMLInputElement>('#recordDiagnostic'),
  recordStatus: requiredElement<HTMLDivElement>('#recordStatus')
};

const params = new URLSearchParams(location.search);
refs.apiBase.value = params.get('api') ?? localStorage.getItem('aliveApiBase') ?? '';

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
let recording: { chunks: Float32Array[]; samples: number; rate: number; api: string; message: string; timer: number } | null = null;

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
      if (recording && recording.samples < recording.rate * 25) {
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
  refs.contactStatus.textContent = 'sending';
  refs.prompt.disabled = true;
  try {
    const apiBase = requestApiBase();
    const response = await fetch(`${apiBase}/api/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message })
    });
    if (!response.ok) {
      const failure = (await response.json().catch(() => null)) as { error?: string } | null;
      throw new Error(failure?.error ?? `HTTP ${response.status}`);
    }
    const payload = (await response.json()) as { reply?: string; message?: string; duration?: number };
    refs.contactStatus.textContent = payload.reply ?? payload.message ?? 'sent';
    refs.prompt.value = '';
  } catch (error) {
    refs.contactStatus.textContent = error instanceof Error ? error.message : 'send failed';
  } finally {
    refs.prompt.disabled = false;
    refs.prompt.focus();
  }
}

async function playCurrentSignal(): Promise<void> {
  if (Date.now() < replayReadyAt) return;
  try {
    const apiBase = requestApiBase();
    if (refs.recordDiagnostic.checked) {
      if (!micActive || !audioCtx) throw new Error('Enable microphone before recording a diagnostic.');
      cancelRecording();
      recording = { chunks: [], samples: 0, rate: audioCtx.sampleRate, api: apiBase, message: '',
        timer: window.setTimeout(() => void saveRecording(), 25000) };
      refs.recordDiagnostic.checked = false;
      refs.recordStatus.textContent = 'Recording microphone for diagnosis…';
    }
    if (micActive) {
      translationSnapshot = decoder.beginCapture(performance.now());
      render();
    }
    refs.contactStatus.textContent = 'playing';
    lockReplay(1);
    const response = await fetch(`${apiBase}/api/emitter/main/play`, {
      method: 'POST'
    });
    if (response.status === 405) throw new Error('HTTP 405: enter the laptop server URL above, or open its local ALIVE page');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = (await response.json()) as { duration?: number; message?: string };
    if (recording) {
      recording.message = payload.message ?? '';
      window.clearTimeout(recording.timer);
      recording.timer = window.setTimeout(() => void saveRecording(), Math.min(23, (payload.duration ?? 20) + 1.5) * 1000);
    }
    if (micActive && payload.duration) decoder.setCaptureDuration(performance.now(), payload.duration);
    refs.contactStatus.textContent = 'ESP32 started signal';
    lockReplay(payload.duration);
  } catch (error) {
    cancelRecording();
    unlockReplay();
    refs.contactStatus.textContent = error instanceof Error ? error.message : 'play failed';
  }
}

function cancelRecording(): void {
  if (!recording) return;
  window.clearTimeout(recording.timer);
  recording = null;
  refs.recordStatus.textContent = 'Diagnostic recording cancelled.';
}

async function saveRecording(): Promise<void> {
  const captured = recording;
  if (!captured) return;
  recording = null;
  window.clearTimeout(captured.timer);
  refs.recordStatus.textContent = 'Saving recording to laptop…';
  try {
    if (!captured.samples) throw new Error('No microphone samples recorded.');
    const response = await fetch(`${captured.api}/api/receiver/capture?message=${encodeURIComponent(captured.message)}`, {
      method: 'POST', headers: { 'content-type': 'audio/wav' },
      body: encodeRecording(captured.chunks, captured.rate)
    });
    if (!response.ok) throw new Error(`Recording upload failed: HTTP ${response.status}`);
    refs.recordStatus.textContent = 'Recording saved to laptop.';
  } catch (error) {
    refs.recordStatus.textContent = error instanceof Error ? error.message : 'Could not save recording.';
  }
}

function lockReplay(durationSeconds = 0): void {
  const durationMs = Math.max(1000, Math.ceil(durationSeconds * 1000) + 250);
  replayReadyAt = Date.now() + durationMs;
  if (replayTimer !== null) window.clearInterval(replayTimer);
  refs.playSignal.disabled = true;
  updateReplayButton();
  replayTimer = window.setInterval(updateReplayButton, 200);
}

function updateReplayButton(): void {
  const remainingMs = replayReadyAt - Date.now();
  if (remainingMs <= 0) {
    unlockReplay();
    return;
  }
  refs.playSignal.textContent = `wait ${Math.ceil(remainingMs / 1000)}s`;
}

function unlockReplay(): void {
  replayReadyAt = 0;
  if (replayTimer !== null) {
    window.clearInterval(replayTimer);
    replayTimer = null;
  }
  refs.playSignal.disabled = false;
  refs.playSignal.textContent = 'play signal';
}

function render(): void {
  refs.translationState.textContent = `${translationSnapshot.title} · ${translationSnapshot.verdict}`;
  refs.message.textContent = translationSnapshot.message;
  refs.micDiagnostics.textContent = micActive
    ? `RX V5 · MIC ${Math.round(levelSnapshot.levelDb)} dB · ROOM ${Math.round(levelSnapshot.noiseFloorDb)} dB · TONE ${translationSnapshot.pair} · RX ${translationSnapshot.stream}`
    : 'RX V5 · MIC OFF — enable microphone before play to decode';
  renderStatus(levelSnapshot.status);
}

function normalizedApiBase(): string {
  return refs.apiBase.value.trim().replace(/\/+$/, '');
}

function requestApiBase(): string {
  const apiBase = normalizedApiBase();
  localStorage.setItem('aliveApiBase', apiBase);
  if (apiBase) return apiBase;
  const host = location.hostname;
  if (host === 'localhost' || host === '127.0.0.1' || host.startsWith('192.168.') ||
      host.startsWith('10.') || /^172\.(1[6-9]|2\d|3[01])\./.test(host)) return location.origin;
  throw new Error('Enter the laptop server URL above, or open its local ALIVE page');
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
