// Selected B layout. Experimental Beacon codec; no study controls in the visitor UI.
import './spacePrototype.css';

export function mountSpacePrototype(onSamples: (samples: Float32Array, rate: number) => void) {
  document.body.classList.add('space-prototype');
  const params = new URLSearchParams(location.search);
  if (params.has('variant')) {
    const url = new URL(location.href); url.searchParams.delete('variant'); history.replaceState(null, '', url);
  }
  const main = document.querySelector('main')!;
  main.children[0].classList.add('translation-panel');
  main.children[1].classList.add('contact-panel');
  main.children[0].insertAdjacentHTML('afterend', `<section class="spectrum-panel" aria-label="Live sound spectrum">
    <div class="spectrum-heading"><span>Signal strip</span><span id="inputState" role="status">Microphone off</span></div>
    <div class="spectrum-history"><canvas id="spectrogram" aria-label="Black-and-white microphone spectrogram"></canvas></div>
    <div class="spectrum-scale"><span>6 kHz</span><span>Frequency / time</span><span>100 Hz · now</span></div>
  </section>`);
  const canvas = document.querySelector<HTMLCanvasElement>('#spectrogram')!;
  const drawing = canvas.getContext('2d')!;
  const inputState = document.querySelector('#inputState')!;
  const apiBase = (params.get('api') ?? '').trim().replace(/\/+$/, '');
  let analyser: AnalyserNode | null = null;
  let bins = new Float32Array(2048);
  let animation = 0, lastDraw = 0;
  let remoteContext: AudioContext | null = null;
  let remoteTimer = 0, remoteCursor = 0, remoteTime = 0;
  let remoteAbort: AbortController | null = null;
  const resize = new ResizeObserver(() => {
    const box = canvas.parentElement!.getBoundingClientRect();
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.round(box.width * ratio));
    canvas.height = Math.max(1, Math.round(box.height * ratio));
    clear();
  });
  resize.observe(canvas.parentElement!);
  function clear() { drawing.fillStyle = '#000'; drawing.fillRect(0, 0, canvas.width, canvas.height); }
  function configure(context: BaseAudioContext) {
    analyser = context.createAnalyser(); analyser.fftSize = 4096; analyser.smoothingTimeConstant = 0;
    analyser.minDecibels = -120; analyser.maxDecibels = -25;
    bins = new Float32Array(analyser.frequencyBinCount);
    clear(); inputState.textContent = 'Live microphone'; canvas.dataset.input = 'microphone';
  }
  function draw(time: number) {
    animation = requestAnimationFrame(draw);
    if (!analyser || time - lastDraw < 40) return;
    lastDraw = time;
    analyser.getFloatFrequencyData(bins);
    const step = Math.min(canvas.width, Math.max(1, Math.round(Math.min(devicePixelRatio || 1, 2))));
    // Scroll measured FFT history. Silence and a disabled microphone add no invented trace.
    if (canvas.width > step) drawing.drawImage(canvas, step, 0, canvas.width - step, canvas.height, 0, 0, canvas.width - step, canvas.height);
    for (let row = 0; row < canvas.height; row++) {
      const hz = 100 * Math.pow(60, 1 - row / canvas.height);
      const bin = Math.round(hz * analyser.fftSize / analyser.context.sampleRate);
      const level = bins[bin] ?? -120;
      const normalized = Math.max(0, Math.min(1, (level + 120) / 75));
      const brightness = Math.round(Math.pow(normalized, 1.4) * 255);
      drawing.fillStyle = `rgb(${brightness},${brightness},${brightness})`;
      drawing.fillRect(canvas.width - step, row, step, 1);
    }
  }
  function stop() {
    analyser?.disconnect(); analyser = null;
    inputState.textContent = 'Microphone off'; canvas.dataset.input = 'off';
  }
  async function stopRemote() {
    clearTimeout(remoteTimer); remoteAbort?.abort(); remoteAbort = null;
    const context = remoteContext; remoteContext = null; await context?.close();
    stop(); onSamples(new Float32Array(0), 48000);
  }
  async function startRemote() {
    remoteContext = new AudioContext({ sampleRate: 48000 }); await remoteContext.resume();
    configure(remoteContext);
    const mute = remoteContext.createGain(); mute.gain.value = 0;
    analyser!.connect(mute).connect(remoteContext.destination);
    remoteTime = remoteContext.currentTime; remoteCursor = 0;
    remoteAbort = new AbortController();
    async function receive() {
      if (!remoteContext) return;
      try {
        const response = await fetch(`${apiBase}/api/prototype/microphone?after=${remoteCursor}`, { signal: remoteAbort!.signal });
        if (!response.ok) throw Error('Microphone unavailable');
        remoteCursor = Number(response.headers.get('x-audio-cursor'));
        const bytes = await response.arrayBuffer(); if (!remoteContext) return;
        const view = new DataView(bytes), samples = new Float32Array(bytes.byteLength / 2);
        for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i * 2, true) / 32768;
        if (samples.length) {
          onSamples(samples, 48000);
          const buffer = remoteContext.createBuffer(1, samples.length, 48000); buffer.copyToChannel(samples, 0);
          const source = remoteContext.createBufferSource(); source.buffer = buffer; source.connect(analyser!);
          remoteTime = Math.max(remoteTime, remoteContext.currentTime + .04); source.start(remoteTime); remoteTime += buffer.duration;
        }
      } catch (error) {
        if (!remoteContext) return;
        await stopRemote(); inputState.textContent = error instanceof Error ? error.message : 'Microphone unavailable'; return;
      }
      if (remoteContext) remoteTimer = window.setTimeout(() => void receive(), 100);
    }
    void receive();
  }
  function fitVisibleViewport() {
    document.documentElement.style.setProperty('--alive-height', `${Math.round(visualViewport?.height ?? innerHeight)}px`);
  }
  visualViewport?.addEventListener('resize', fitVisibleViewport); fitVisibleViewport();
  animation = requestAnimationFrame(draw);
  addEventListener('pagehide', () => {
    resize.disconnect(); cancelAnimationFrame(animation); void stopRemote();
    visualViewport?.removeEventListener('resize', fitVisibleViewport);
  }, { once: true });
  return {
    sound: () => 'beacon',
    api: () => apiBase,
    remoteRequested: () => params.get('input') === 'main',
    remoteActive: () => !!remoteContext,
    startRemote, stopRemote,
    connect(node: MediaStreamAudioSourceNode, context: AudioContext) { configure(context); node.connect(analyser!); },
    stop
  };
}
