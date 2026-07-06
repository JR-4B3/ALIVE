import './styles.css';
import { SignalLevelTracker } from './sensing/signalLevelTracker';
import { TranslationDecoder } from './sensing/translationDecoder';
import type { ReceiverStatus } from './types';

const app = requiredElement<HTMLDivElement>('#app');
app.innerHTML = `
  <main class="mx-auto flex min-h-dvh w-full max-w-xl flex-col gap-4 px-4 py-4">
    <section class="border border-white px-4 py-4">
      <div class="text-xs uppercase tracking-[0.24em] text-neutral-400">receiver</div>
      <div id="receiverStatus" class="mt-2 text-3xl font-semibold uppercase leading-tight tracking-normal sm:text-5xl">idle</div>
      <div class="mt-3 border-t border-white pt-3">
        <div id="signalState" class="text-xs uppercase tracking-[0.16em] text-neutral-400">microphone disabled</div>
      </div>
    </section>

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
        <button id="send" class="min-h-11 px-3 text-xs uppercase tracking-[0.16em]">send</button>
        <details>
          <summary class="cursor-pointer text-xs uppercase tracking-[0.18em] text-neutral-400">api</summary>
          <input id="apiBase" class="mt-3 min-h-11 w-full px-3 font-mono text-sm" placeholder="api base URL">
        </details>
        <div id="contactStatus" class="min-h-6 font-mono text-xs uppercase tracking-[0.16em] text-neutral-400">---</div>
      </form>
      <div id="debug" class="whitespace-pre-wrap border border-white px-3 py-3 font-mono text-xs text-neutral-400"></div>
    </section>
  </main>
`;

const refs = {
  receiverStatus: requiredElement<HTMLDivElement>('#receiverStatus'),
  signalState: requiredElement<HTMLDivElement>('#signalState'),
  translationState: requiredElement<HTMLDivElement>('#translationState'),
  message: requiredElement<HTMLDivElement>('#message'),
  mic: requiredElement<HTMLButtonElement>('#mic'),
  clear: requiredElement<HTMLButtonElement>('#clear'),
  contactForm: requiredElement<HTMLFormElement>('#contactForm'),
  prompt: requiredElement<HTMLInputElement>('#prompt'),
  apiBase: requiredElement<HTMLInputElement>('#apiBase'),
  contactStatus: requiredElement<HTMLDivElement>('#contactStatus'),
  debug: requiredElement<HTMLDivElement>('#debug')
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
    const payload = (await response.json()) as { reply?: string; message?: string };
    refs.contactStatus.textContent = payload.reply ?? payload.message ?? 'sent';
    refs.prompt.value = '';
  } catch (error) {
    refs.contactStatus.textContent = error instanceof Error ? error.message : 'send failed';
  } finally {
    refs.prompt.disabled = false;
    refs.prompt.focus();
  }
}

function render(): void {
  refs.receiverStatus.textContent = micActive ? levelSnapshot.status : 'idle';
  refs.signalState.textContent = micActive ? 'listening for encoded audio' : 'microphone disabled';
  refs.translationState.textContent = `${translationSnapshot.title} · ${translationSnapshot.verdict}`;
  refs.message.textContent = translationSnapshot.message;
  renderStatus(levelSnapshot.status);

  refs.debug.textContent = [
    `level ${levelSnapshot.levelDb.toFixed(1)} dB / floor ${levelSnapshot.noiseFloorDb.toFixed(1)} dB`,
    `pair ${translationSnapshot.pair}`
  ].join('\n');
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
