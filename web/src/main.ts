import './styles.css';
import { AudioZoneTracker } from './sensing/audioZoneTracker';
import { TranslationDecoder } from './sensing/translationDecoder';
import type { ControllerPayload, ReceiverStatus } from './types';

const POST_INTERVAL_MS = 500;

const app = requiredElement<HTMLDivElement>('#app');
app.innerHTML = `
  <main class="mx-auto flex min-h-dvh w-full max-w-xl flex-col gap-4 px-4 py-4">
    <section class="border border-white px-4 py-4">
      <div class="text-xs uppercase tracking-[0.24em] text-neutral-400">current zone</div>
      <div id="zone" class="mt-2 text-[3.35rem] font-semibold leading-none tracking-normal sm:text-7xl">far</div>
      <div class="mt-3 flex items-center justify-between gap-3 border-t border-white pt-3">
        <div id="activeEmitter" class="min-w-0 truncate text-xs uppercase tracking-[0.16em] text-neutral-400">no emitter lock</div>
        <div id="confidence" class="shrink-0 font-mono text-lg">0%</div>
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
      <details class="border border-white px-3 py-3">
        <summary class="cursor-pointer text-xs uppercase tracking-[0.18em] text-neutral-400">control</summary>
        <div class="mt-3 grid gap-3">
          <input id="controller" class="min-h-11 px-3 font-mono text-sm" placeholder="controller URL">
          <div id="debug" class="whitespace-pre-wrap border border-white px-3 py-3 font-mono text-xs text-neutral-400"></div>
        </div>
      </details>
    </section>
  </main>
`;

const refs = {
  zone: requiredElement<HTMLDivElement>('#zone'),
  activeEmitter: requiredElement<HTMLDivElement>('#activeEmitter'),
  confidence: requiredElement<HTMLDivElement>('#confidence'),
  translationState: requiredElement<HTMLDivElement>('#translationState'),
  message: requiredElement<HTMLDivElement>('#message'),
  mic: requiredElement<HTMLButtonElement>('#mic'),
  clear: requiredElement<HTMLButtonElement>('#clear'),
  controller: requiredElement<HTMLInputElement>('#controller'),
  debug: requiredElement<HTMLDivElement>('#debug')
};

const params = new URLSearchParams(location.search);
refs.controller.value = params.get('controller') ?? '';

const tracker = new AudioZoneTracker();
const decoder = new TranslationDecoder();
let zoneSnapshot = tracker.snapshot();
let translationSnapshot = decoder.snapshot();
let audioCtx: AudioContext | null = null;
let micStream: MediaStream | null = null;
let sourceNode: MediaStreamAudioSourceNode | null = null;
let processor: ScriptProcessorNode | null = null;
let silentNode: GainNode | null = null;
let micActive = false;
let lastPostAt = 0;
let lastPostedKey = '';

refs.mic.addEventListener('click', () => {
  void toggleMicrophone();
});
refs.clear.addEventListener('click', () => {
  translationSnapshot = decoder.reset();
  render();
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
      zoneSnapshot = tracker.process(input, audioCtx.sampleRate, audioCtx.currentTime, nowMs);
      translationSnapshot = decoder.process(
        input,
        audioCtx.sampleRate,
        zoneSnapshot.levelDb,
        zoneSnapshot.noiseFloorDb,
        audioCtx.currentTime,
        nowMs
      );
      render();
      void postZoneIfNeeded();
    };
    sourceNode.connect(processor);
    processor.connect(silentNode).connect(audioCtx.destination);
    await audioCtx.resume();
    micActive = true;
    tracker.startCalibration(performance.now());
    zoneSnapshot = tracker.snapshot();
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
  tracker.stop();
  zoneSnapshot = tracker.snapshot();
  refs.mic.textContent = 'enable microphone';
  render();
}

function render(): void {
  const active = zoneSnapshot.active;
  refs.zone.textContent = active?.zone ?? 'far';
  refs.confidence.textContent = `${Math.round(active?.confidence ?? 0)}%`;
  refs.activeEmitter.textContent = active
    ? `${active.emitter.label} · audio ${Math.round(active.audioConfidence)}%`
    : micActive
      ? 'listening for emitter'
      : 'no emitter lock';

  refs.translationState.textContent = `${translationSnapshot.title} · ${translationSnapshot.verdict}`;
  refs.message.textContent = translationSnapshot.message;
  renderStatus(zoneSnapshot.status);

  refs.debug.textContent = [
    `level ${zoneSnapshot.levelDb.toFixed(1)} dB / floor ${zoneSnapshot.noiseFloorDb.toFixed(1)} dB`,
    `active ${active?.emitter.id ?? 'none'} / pair ${translationSnapshot.pair}`
  ].join('\n');
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
    case 'locked':
      return 'lock';
    case 'mic-blocked':
      return 'blocked';
    case 'control-offline':
      return 'offline';
    case 'idle':
    default:
      return 'idle';
  }
}

async function postZoneIfNeeded(force = false): Promise<void> {
  const controller = normalizedControllerUrl();
  const active = zoneSnapshot.active;
  if (!controller || !active) return;
  const now = performance.now();
  const key = `${active.emitter.id}:${active.zone}:${Math.round(active.confidence / 5) * 5}:${translationSnapshot.message}`;
  if (!force && key === lastPostedKey && now - lastPostAt < POST_INTERVAL_MS) return;
  if (!force && now - lastPostAt < POST_INTERVAL_MS) return;
  lastPostAt = now;
  lastPostedKey = key;

  const payload: ControllerPayload = {
    emitterId: active.emitter.id,
    zone: active.zone,
    confidence: Math.round(active.confidence),
    message: translationSnapshot.message === '---' ? '' : translationSnapshot.message,
    levels: Object.fromEntries(
      zoneSnapshot.emitters.map((estimate) => [
        estimate.emitter.id,
        {
          zone: estimate.zone,
          confidence: Math.round(estimate.confidence)
        }
      ])
    )
  };

  try {
    await fetch(`${controller}/api/zone`, {
      method: 'POST',
      mode: 'cors',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
  } catch {
    renderStatus('control-offline');
  }
}

function normalizedControllerUrl(): string {
  return refs.controller.value.trim().replace(/\/+$/, '');
}

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`missing element ${selector}`);
  return element;
}
