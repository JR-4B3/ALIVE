// Throwaway study: three microphone spectrogram layouts on /?prototype=space&variant=A.
// Question: which layout and sound direction suit an exhibition encounter?
import './spacePrototype.css';
import { TranslationDecoder } from '../sensing/translationDecoder';
import { encodeRecording } from '../audio/recording';
import { rmsDb } from '../audio/dsp';

export function mountSpacePrototype(onSamples: (samples: Float32Array, rate: number) => void) {
  document.body.classList.add('space-prototype');
  const main = document.querySelector('main')!;
  const translation = main.children[0];
  translation.classList.add('translation-panel');
  main.children[1].classList.add('contact-panel');
  main.insertAdjacentHTML('afterbegin', `<header class="experiment-header"><span>ALIVE / sound study</span><button id="toggleLab">Sound lab</button></header>
    <section class="spectrum-panel"><div class="spectrum-heading"><span id="spectrumTitle">Listening field</span><span id="inputState">Microphone off</span></div><canvas id="spectrogram" width="1000" height="440" aria-label="Live microphone spectrogram"></canvas><div class="spectrum-scale"><span>6 kHz</span><span>Frequency / time</span><span>100 Hz · now</span></div></section>`);
  main.insertAdjacentHTML('beforeend', `<section class="sound-panel"><div class="study-label">Compare the transmission</div><div class="sound-choices">
    <button data-sound="drift" aria-pressed="true">01 / Drift<small>A low, sustained arrival</small></button>
    <button data-sound="beacon" aria-pressed="false">02 / Beacon<small>Sparse, distant chirps</small></button>
    <button data-sound="chorus" aria-pressed="false">03 / Chorus<small>Close tones beating together</small></button>
    <button data-sound="original" aria-pressed="false">00 / Original<small>Encoded signal alone</small></button></div>
    <div class="audition-controls"><button id="remoteMic">Use microphone on main</button><button id="audition">Listen on this device</button><button id="stopAudition" disabled>Stop</button><button id="downloadSound">Download WAV</button></div>
    <label class="study-label">Speaker API URL<input id="prototypeApi" type="url" placeholder="Leave blank for the local speaker bridge" /></label>
    <p class="study-note">Play signal sends the selected sound to the installation speaker. Listening here plays HELLO on this device. The local bridge sends your contact text literally. Enable the microphone to see the room and decode the speaker.</p>
    <details><summary>Audio verification</summary><label>Decode a speaker recording<input id="audioFile" type="file" accept="audio/*" /></label><output id="fileResult">No recording loaded</output><p>The decoder receives the original audio, with no filtering. Sound directions add an introduction and a reply after the encoded message.</p></details>
    <output id="prototypeState" aria-live="polite"></output></section>`);
  document.body.insertAdjacentHTML('beforeend', `<nav class="prototype-switcher" aria-label="Prototype variants"><button id="previousVariant" aria-label="Previous variant">←</button><span id="variantLabel"></span><button id="nextVariant" aria-label="Next variant">→</button></nav>`);
  const canvas = document.querySelector<HTMLCanvasElement>('#spectrogram')!;
  const drawing = canvas.getContext('2d')!;
  const state = document.querySelector<HTMLOutputElement>('#prototypeState')!;
  const api = document.querySelector<HTMLInputElement>('#prototypeApi')!;
  api.value = new URLSearchParams(location.search).get('api') ?? '';
  let variant = new URLSearchParams(location.search).get('variant') ?? 'A';
  let sound = 'drift';
  let input = 'off';
  let analyser: AnalyserNode | null = null;
  let animation = 0;
  let auditionContext: AudioContext | null = null;
  let auditionSource: AudioBufferSourceNode | null = null;
  let auditionAnalyser: AnalyserNode | null = null;
  let remoteContext: AudioContext | null = null;
  let remoteTimer = 0;
  let remoteCursor = 0;
  let remoteTime = 0;
  let lastDraw = 0;
  let db = -100;
  const variants = ['A', 'B', 'C'];
  const names = ['Listening field', 'Signal strip', 'Frequency column'];
  function showState() {
    state.textContent = `Layout ${variant} · Sound ${sound} · Input ${input} · ${Math.round(db)} dBFS`;
  }
  function setVariant(next: string) {
    variant = variants.includes(next) ? next : 'A';
    document.body.dataset.variant = variant;
    const url = new URL(location.href); url.searchParams.set('variant', variant); history.replaceState(null, '', url);
    document.querySelector('#variantLabel')!.textContent = `${variant} / ${names[variants.indexOf(variant)]}`;
    document.querySelector('#spectrumTitle')!.textContent = names[variants.indexOf(variant)];
    drawing.fillStyle = '#000'; drawing.fillRect(0, 0, canvas.width, canvas.height);
    showState();
  }
  function cycle(step: number) { setVariant(variants[(variants.indexOf(variant) + step + 3) % 3]); }
  document.querySelector('#previousVariant')!.addEventListener('click', () => cycle(-1));
  document.querySelector('#nextVariant')!.addEventListener('click', () => cycle(1));
  addEventListener('keydown', event => {
    if ((event.target as HTMLElement)?.closest('input, textarea, select, [contenteditable]')) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); cycle(event.key === 'ArrowLeft' ? -1 : 1); }
  });
  document.querySelectorAll<HTMLButtonElement>('[data-sound]').forEach(button => button.addEventListener('click', () => {
    stopAudition(); sound = button.dataset.sound!;
    document.querySelectorAll('[data-sound]').forEach(choice => choice.setAttribute('aria-pressed', String((choice as HTMLElement).dataset.sound === sound)));
    showState();
  }));
  function draw(time: number) {
    animation = requestAnimationFrame(draw);
    const active = analyser ?? auditionAnalyser;
    if (!active || time - lastDraw < 35) return;
    lastDraw = time;
    const frequencies = new Float32Array(active.frequencyBinCount);
    active.getFloatFrequencyData(frequencies);
    const wave = new Float32Array(active.fftSize); active.getFloatTimeDomainData(wave); db = rmsDb(wave);
    // Every pixel comes from measured FFT bins. No decorative or random signal.
    const vertical = variant === 'C';
    if (vertical) drawing.drawImage(canvas, 0, 0, canvas.width, canvas.height - 2, 0, 2, canvas.width, canvas.height - 2);
    else drawing.drawImage(canvas, 2, 0, canvas.width - 2, canvas.height, 0, 0, canvas.width - 2, canvas.height);
    const extent = vertical ? canvas.width : canvas.height;
    for (let pixel = 0; pixel < extent; pixel++) {
      const ratio = vertical ? pixel / extent : 1 - pixel / extent;
      const frequency = 100 * Math.pow(60, ratio);
      const bin = Math.round(frequency * active.fftSize / active.context.sampleRate);
      const intensity = Math.max(0, Math.min(255, ((frequencies[bin] ?? -100) + 90) / 65 * 255));
      drawing.fillStyle = `rgb(${intensity},${intensity},${intensity})`;
      if (vertical) drawing.fillRect(pixel, 0, 1, 2); else drawing.fillRect(canvas.width - 2, pixel, 2, 1);
    }
    showState();
  }
  function stopAudition() {
    auditionSource?.stop(); auditionSource = null; auditionAnalyser = null;
    void auditionContext?.close(); auditionContext = null;
    document.querySelector<HTMLButtonElement>('#stopAudition')!.disabled = true;
    if (!analyser) { input = 'off'; document.querySelector('#inputState')!.textContent = 'Microphone off'; }
    showState();
  }
  document.querySelector('#audition')!.addEventListener('click', async () => {
    stopAudition();
    auditionContext = new AudioContext({ sampleRate: 48000 }); await auditionContext.resume();
    const samples = transmission(sound, 'HELLO');
    const buffer = auditionContext.createBuffer(1, samples.length, 48000); buffer.copyToChannel(samples, 0);
    auditionSource = auditionContext.createBufferSource(); auditionSource.buffer = buffer;
    auditionAnalyser = auditionContext.createAnalyser(); auditionAnalyser.fftSize = 4096; auditionAnalyser.smoothingTimeConstant = 0;
    auditionSource.connect(auditionAnalyser).connect(auditionContext.destination);
    if (!analyser) { input = 'device audition'; document.querySelector('#inputState')!.textContent = 'Device audition · not microphone'; }
    document.querySelector<HTMLButtonElement>('#stopAudition')!.disabled = false;
    auditionSource.onended = () => { auditionSource = null; stopAudition(); };
    auditionSource.start(); showState();
  });
  async function stopRemote() {
    clearTimeout(remoteTimer); const context = remoteContext; remoteContext = null;
    await context?.close(); analyser = null; input = 'off';
    document.querySelector('#inputState')!.textContent = 'Microphone off';
    document.querySelector('#remoteMic')!.textContent = 'Use microphone on main';
    onSamples(new Float32Array(0), 48000); showState();
  }
  document.querySelector('#remoteMic')!.addEventListener('click', async () => {
    if (remoteContext) { await stopRemote(); return; }
    stopAudition(); remoteContext = new AudioContext({ sampleRate: 48000 }); await remoteContext.resume();
    analyser = remoteContext.createAnalyser(); analyser.fftSize = 4096; analyser.smoothingTimeConstant = 0;
    const mute = remoteContext.createGain(); mute.gain.value = 0; analyser.connect(mute).connect(remoteContext.destination);
    remoteTime = remoteContext.currentTime; remoteCursor = 0; input = 'microphone on main';
    document.querySelector('#inputState')!.textContent = 'Live microphone / main'; document.querySelector('#remoteMic')!.textContent = 'Stop microphone on main';
    async function receive() {
      if (!remoteContext) return;
      try {
        const response = await fetch(`${api.value.trim().replace(/\/$/, '')}/api/prototype/microphone?after=${remoteCursor}`);
        if (!response.ok) throw Error('Start the prototype speaker bridge on main');
        remoteCursor = Number(response.headers.get('x-audio-cursor'));
        const bytes = await response.arrayBuffer();
        if (!remoteContext) return;
        const view = new DataView(bytes), samples = new Float32Array(bytes.byteLength / 2);
        for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i*2, true) / 32768;
        if (samples.length) {
          onSamples(samples, 48000);
          const buffer = remoteContext.createBuffer(1, samples.length, 48000); buffer.copyToChannel(samples, 0);
          const source = remoteContext.createBufferSource(); source.buffer = buffer; source.connect(analyser!);
          remoteTime = Math.max(remoteTime, remoteContext.currentTime + .04); source.start(remoteTime); remoteTime += buffer.duration;
        }
      } catch (error) { document.querySelector('#inputState')!.textContent = String(error); }
      if (remoteContext) remoteTimer = window.setTimeout(() => void receive(), 100);
    }
    void receive(); showState();
  });
  document.querySelector('#stopAudition')!.addEventListener('click', stopAudition);
  document.querySelector('#downloadSound')!.addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([encodeRecording([transmission(sound, 'HELLO')], 48000)], { type: 'audio/wav' }));
    const link = document.createElement('a'); link.href = url; link.download = `alive-${sound}-HELLO.wav`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  document.querySelector('#audioFile')!.addEventListener('change', async event => {
    const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return;
    const context = new AudioContext();
    try {
      const recording = await context.decodeAudioData(await file.arrayBuffer());
      const decoder = new TranslationDecoder(); decoder.beginCapture(0); decoder.setCaptureDuration(0, recording.duration);
      const mono = new Float32Array(recording.length);
      for (let channel = 0; channel < recording.numberOfChannels; channel++) {
        const samples = recording.getChannelData(channel); for (let i = 0; i < mono.length; i++) mono[i] += samples[i] / recording.numberOfChannels;
      }
      let decoded = decoder.snapshot();
      for (let i = 0; i < mono.length; i += 2048) decoded = decoder.process(mono.subarray(i, i + 2048), recording.sampleRate, -40, -65, i / recording.sampleRate, i / recording.sampleRate * 1000);
      document.querySelector('#fileResult')!.textContent = `${file.name} · ${recording.duration.toFixed(2)}s · Decoded: ${decoded.message}`;
    } catch (error) { document.querySelector('#fileResult')!.textContent = String(error); }
    finally { await context.close(); }
  });
  document.querySelector('#toggleLab')!.addEventListener('click', () => {
    const lab = document.body.classList.toggle('show-sound-lab');
    document.querySelector('#toggleLab')!.textContent = lab ? 'Back to encounter' : 'Sound lab';
  });
  setVariant(variant); animation = requestAnimationFrame(draw);
  return {
    sound: () => sound,
    remoteActive: () => !!remoteContext,
    stopRemote,
    api: () => api.value.trim().replace(/\/$/, ''),
    connect(node: MediaStreamAudioSourceNode, context: AudioContext) {
      analyser = context.createAnalyser(); analyser.fftSize = 4096; analyser.smoothingTimeConstant = 0; node.connect(analyser);
      input = 'microphone'; document.querySelector('#inputState')!.textContent = 'Live microphone'; showState();
    },
    stop() { analyser?.disconnect(); analyser = null; input = auditionAnalyser ? 'device audition' : 'off'; document.querySelector('#inputState')!.textContent = input === 'off' ? 'Microphone off' : 'Device audition · not microphone'; showState(); },
    dispose() { cancelAnimationFrame(animation); stopAudition(); }
  };
}

export function transmission(direction: string, message: string): Float32Array<ArrayBuffer> {
  const rate = 48000, pi = Math.PI;
  const parts: Float32Array[] = [];
  const silence = (seconds: number) => parts.push(new Float32Array(Math.round(rate * seconds)));
  const atmosphere = (outro: boolean) => {
    const tableRate = direction === 'beacon' ? 16000 : 4000;
    const table = new Int16Array(tableRate * 1.8 + 1);
    for (let frame = 0; frame < table.length - 1; frame++) {
      const t = frame / tableRate, envelope = Math.sin(pi * frame / (table.length - 1));
      let value = 0;
      if (direction === 'drift') value = .85 * Math.sin(2*pi*173*t + .15*Math.sin(2*pi*.7*t));
      if (direction === 'beacon') value = .65 * Math.pow(Math.max(0, Math.sin(2*pi*(outro ? 2.7 : 1.7)*t)), 8) * Math.sin(2*pi*(3600*t + (outro ? -1 : 1)*330*t*t));
      if (direction === 'chorus') value = .32*Math.sin(2*pi*181*t + 1.2*Math.sin(2*pi*.4*t)) + .32*Math.sin(2*pi*187*t) + .25*Math.sin(2*pi*307*t + 1.8*Math.sin(2*pi*.6*t));
      table[frame] = Math.trunc(1200 * envelope * envelope * value);
    }
    const samples = new Float32Array(rate * 1.8), step = rate / tableRate;
    for (let frame = 0; frame < samples.length; frame++) {
      const index = Math.floor(frame / step), fraction = frame % step;
      samples[frame] = Math.trunc((table[index]*(step-fraction) + table[index+1]*fraction) / step) / 32768;
    }
    parts.push(samples);
  };
  if (direction !== 'original') { atmosphere(false); silence(.35); }
  silence(.05);
  for (const char of message) {
    const index = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ '.indexOf(char); if (index < 0) continue;
    const samples = new Float32Array(rate * .22);
    const low = 400 + Math.floor(index / 4) * 100, high = 2000 + index % 4 * 300;
    for (let i = 0; i < samples.length; i++) {
      const fade = Math.min(rate * .024, i, samples.length - i - 1) / (rate * .024);
      samples[i] = Math.trunc((Math.trunc(1200*Math.sin(2*pi*low*i/rate))*.53 + Math.trunc(1200*Math.sin(2*pi*high*i/rate))*.47)*fade) / 32768;
    }
    parts.push(samples); silence(Math.max(220, Math.floor(((char === ' ' ? 1600 : 100 + index * 50)*65 + 50)/100))/1000);
  }
  silence(1);
  if (direction !== 'original') atmosphere(true);
  const samples = new Float32Array(parts.reduce((n, part) => n + part.length, 0));
  let offset = 0; for (const part of parts) { samples.set(part, offset); offset += part.length; }
  return samples;
}
