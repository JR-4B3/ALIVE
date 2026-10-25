// Visitor layout: reception log, a black-and-white spectrogram, and contact.
import './signalStrip.css';

const HIDDEN_LOW_HZ = 17500, HIDDEN_HIGH_HZ = 20500, HIDDEN_SHARE = .6;

export function mountSignalStrip() {
  document.body.classList.add('signal-strip');
  const main = document.querySelector('main')!;
  main.children[0].insertAdjacentHTML('afterend', `<section class="spectrum-panel" aria-label="Live sound spectrum">
    <div class="spectrum-heading"><span>Spectrogram</span><span id="inputState" role="status">Microphone off</span></div>
    <div class="spectrum-history"><canvas id="spectrogram" aria-label="Black-and-white microphone spectrogram"></canvas>
      <span class="spectrum-boundary" style="top: ${HIDDEN_SHARE * 100}%">${HIDDEN_LOW_HZ / 1000} kHz</span></div>
    <div class="spectrum-scale"><span>${HIDDEN_HIGH_HZ / 1000} kHz</span><span>Frequency / time</span><span>100 Hz · now</span></div>
  </section>`);
  const canvas = document.querySelector<HTMLCanvasElement>('#spectrogram')!;
  const drawing = canvas.getContext('2d')!;
  const inputState = document.querySelector('#inputState')!;
  let analyser: AnalyserNode | null = null;
  let bins = new Float32Array(2048);
  let animation = 0, lastDraw = 0;
  const resize = new ResizeObserver(() => {
    const box = canvas.parentElement!.getBoundingClientRect();
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.round(box.width * ratio));
    canvas.height = Math.max(1, Math.round(box.height * ratio));
    clear();
  });
  resize.observe(canvas.parentElement!);
  function clear() { drawing.fillStyle = '#000'; drawing.fillRect(0, 0, canvas.width, canvas.height); }
  // The top rows stretch the inaudible band so each letter's chirp gets its own
  // line. The rest keeps the audible room on a log scale for orientation.
  function rowFrequency(row: number): number {
    const position = row / canvas.height;
    if (position < HIDDEN_SHARE) return HIDDEN_HIGH_HZ - (HIDDEN_HIGH_HZ - HIDDEN_LOW_HZ) * position / HIDDEN_SHARE;
    return 100 * Math.pow(HIDDEN_LOW_HZ / 100, 1 - (position - HIDDEN_SHARE) / (1 - HIDDEN_SHARE));
  }
  function draw(time: number) {
    animation = requestAnimationFrame(draw);
    if (!analyser || time - lastDraw < 40) return;
    lastDraw = time;
    analyser.getFloatFrequencyData(bins);
    const step = Math.min(canvas.width, Math.max(2, Math.round(2 * Math.min(devicePixelRatio || 1, 2))));
    // Speakers and phone microphones lose 20-40 dB up here, so the inaudible
    // band is shown relative to its own median level in this column.
    const binHz = analyser.context.sampleRate / analyser.fftSize;
    const hidden = Array.from(bins.subarray(Math.round(HIDDEN_LOW_HZ / binHz), Math.round(HIDDEN_HIGH_HZ / binHz))).sort((a, b) => a - b);
    const hiddenFloor = hidden[hidden.length >> 1] ?? -120;
    // Scroll measured FFT history. Silence and a disabled microphone add no invented trace.
    if (canvas.width > step) drawing.drawImage(canvas, step, 0, canvas.width - step, canvas.height, 0, 0, canvas.width - step, canvas.height);
    for (let row = 0; row < canvas.height; row++) {
      const hz = rowFrequency(row);
      const level = bins[Math.round(hz / binHz)] ?? -120;
      const normalized = Math.max(0, Math.min(1, hz >= HIDDEN_LOW_HZ ? (level - hiddenFloor - 4) / 36 : (level + 120) / 75));
      const brightness = Math.round(Math.pow(normalized, 1.4) * 255);
      drawing.fillStyle = `rgb(${brightness},${brightness},${brightness})`;
      drawing.fillRect(canvas.width - step, row, step, 1);
    }
  }
  // iOS shrinks the visible area for the keyboard and also scrolls the page to the
  // focused field. Pinning the layout to the visible area cancels that scroll.
  function fitVisibleViewport() {
    const root = document.documentElement.style;
    root.setProperty('--alive-height', `${Math.round(visualViewport?.height ?? innerHeight)}px`);
    root.setProperty('--alive-top', `${Math.round(visualViewport?.offsetTop ?? 0)}px`);
  }
  visualViewport?.addEventListener('resize', fitVisibleViewport);
  visualViewport?.addEventListener('scroll', fitVisibleViewport); fitVisibleViewport();
  animation = requestAnimationFrame(draw);
  addEventListener('pagehide', () => {
    resize.disconnect(); cancelAnimationFrame(animation);
    visualViewport?.removeEventListener('resize', fitVisibleViewport);
    visualViewport?.removeEventListener('scroll', fitVisibleViewport);
  }, { once: true });
  return {
    connect(node: MediaStreamAudioSourceNode) {
      analyser = node.context.createAnalyser(); analyser.fftSize = 4096; analyser.smoothingTimeConstant = 0;
      analyser.minDecibels = -120; analyser.maxDecibels = -25;
      bins = new Float32Array(analyser.frequencyBinCount);
      clear(); inputState.textContent = 'Live microphone';
      node.connect(analyser);
    },
    stop() {
      analyser?.disconnect(); analyser = null;
      inputState.textContent = 'Microphone off';
    }
  };
}
