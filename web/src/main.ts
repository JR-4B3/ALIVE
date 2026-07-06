import './styles.css';
import { SignalLevelTracker } from './sensing/signalLevelTracker';
import { TranslationDecoder } from './sensing/translationDecoder';
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
      <form id="contactForm" class="grid gap-3 border border-white px-3 py-3">
        <div class="text-xs uppercase tracking-[0.24em] text-neutral-400">contact</div>
        <input id="prompt" class="min-h-11 px-3 text-base" maxlength="120" placeholder="message">
        <div class="grid grid-cols-2 gap-3">
          <button id="send" class="min-h-11 px-3 text-xs uppercase tracking-[0.16em]">send</button>
          <button id="playSignal" type="button" class="min-h-11 px-3 text-xs uppercase tracking-[0.16em]">play signal</button>
        </div>
        <input id="apiBase" type="hidden">
        <div id="contactStatus" class="min-h-6 font-mono text-xs uppercase tracking-[0.16em] text-neutral-400">---</div>
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
  apiBase: requiredElement<HTMLInputElement>('#apiBase'),
  contactStatus: requiredElement<HTMLDivElement>('#contactStatus'),
  playSignal: requiredElement<HTMLButtonElement>('#playSignal')
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
    processor = audioCtx.createScriptProcessor(4096, 1, 1);
    silentNode = audioCtx.createGain();
    silentNode.gain.value = 0;
    processor.onaudioprocess = (event) => {
      if (!audioCtx) return;
      const input = event.inputBuffer.getChannelData(0);
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
  const apiBase = normalizedApiBase();
  localStorage.setItem('aliveApiBase', apiBase);
  try {
    const response = await fetch(`${apiBase}/api/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message })
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = (await response.json()) as { reply?: string; message?: string; duration?: number };
    refs.contactStatus.textContent = payload.reply ?? payload.message ?? 'sent';
    refs.prompt.value = '';
    lockReplay(payload.duration);
  } catch (error) {
    refs.contactStatus.textContent = error instanceof Error ? error.message : 'send failed';
  } finally {
    refs.prompt.disabled = false;
    refs.prompt.focus();
  }
}

async function playCurrentSignal(): Promise<void> {
  if (Date.now() < replayReadyAt) return;
  refs.contactStatus.textContent = 'playing';
  lockReplay(1);
  try {
    const response = await fetch(`${normalizedApiBase()}/api/emitter/main/play`, {
      method: 'POST'
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = (await response.json()) as { duration?: number };
    lockReplay(payload.duration);
  } catch (error) {
    unlockReplay();
    refs.contactStatus.textContent = error instanceof Error ? error.message : 'play failed';
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
  renderStatus(levelSnapshot.status);
}

function normalizedApiBase(): string {
  return refs.apiBase.value.trim().replace(/\/+$/, '');
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
