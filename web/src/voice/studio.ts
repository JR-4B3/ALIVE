import './studio.css';
import { SoundVoiceDecoder } from './streamingDecoder';
import { encodeVoiceRecording } from './recording';
import { TranslationDecoder } from '../sensing/translationDecoder';
import { synthesize, type SynthSettings, type Waveform } from './synth';
import { RATE, LETTERS, type Voice, type Match, type Segment, compileVoice, confusionReport, decodeAudio,
  generateSounds, pcmDecode, renderMessage, segmentAudio, stamp, validateVoice, calibrateVoice,
  characterErrors, digest, join } from './codec';

const app = document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML = `
<main>
  <header><div><div class="eyebrow">ALIVE / experimental transmission</div><h1>Find a voice from elsewhere.</h1>
    <p class="muted">Design a sound alphabet. Hear it speak. Teach the receiver what survives the room.</p></div>
    <a href="${import.meta.env.DEV ? 'https://jr-4b3.github.io/ALIVE/debug/' : '../debug/'}">Classic receiver ↗</a></header>
  <div id="status" class="status" role="status" aria-live="polite">Loading the studio…</div>
  <div class="grid">
    <section><h2>1 · Make a sound</h2>
      <label>Voice name<input id="voiceName" maxlength="80" value="First contact"></label>
      <div class="synth-grid">
        <label>Waveform<select id="waveform"><option value="triangle">Soft / hollow</option><option value="sine">Pure</option><option value="saw">Rough</option><option value="pulse">Thin / metallic</option></select></label>
        <label>Pitch <output id="pitchHzValue" for="pitchHz"></output><input id="pitchHz" type="range" min="180" max="1200" step="10" value="390"></label>
        <label class="synth-full">Brightness <output id="brightnessValue" for="brightness"></output><input id="brightness" type="range" min="0" max="100" value="55"></label>
      </div>
      <div class="eyebrow envelope-title">Shape over time</div>
      <div class="synth-grid">
        <label>Attack <output id="attackValue" for="attack"></output><input id="attack" type="range" min="5" max="300" step="5" value="60"></label>
        <label>Decay <output id="decayValue" for="decay"></output><input id="decay" type="range" min="10" max="300" step="5" value="120"></label>
        <label>Sustain <output id="sustainValue" for="sustain"></output><input id="sustain" type="range" min="0" max="100" step="5" value="55"></label>
        <label>Release <output id="releaseValue" for="release"></output><input id="release" type="range" min="20" max="400" step="5" value="180"></label>
      </div>
      <p class="muted short-help">Attack grows the sound; decay settles it; sustain sets its held level; release fades it away.</p>
      <div class="row"><button id="previewSound">Hear this sound</button><button id="create" class="primary">Make voice from it</button></div>
      <p class="muted short-help">The alphabet grows from this sound. Each letter remains one continuous gesture.</p>
      <details class="secondary-tools"><summary>Use my own audio instead</summary>
        <label>Source<select id="importMode"><option value="seed">One sound from a DAW</option>
          <option value="alphabet">27 sounds: A–Z and SPACE</option><option value="sequence">One recording of 27 sounds</option></select></label>
        <label>Audio files<input id="sourceFiles" type="file" accept="audio/*,.wav" multiple></label>
        <p id="importHelp" class="muted">Use a 0.12–1.2 second sound. The generator turns it into continuous variations.</p>
        <button id="createFromFile">Make voice from file</button>
        <details><summary>Replace one letter's sound</summary>
          <label>Letter<select id="replaceSymbol"></select></label>
          <label>New sound<input id="replacement" type="file" accept="audio/*,.wav"></label>
          <button id="replace">Replace and rebuild</button>
        </details>
        <details><summary>Audio design notes</summary><p class="muted">WAV exports work best. Each symbol is 0.12–1.2 seconds, with a 220 ms pause between symbols. Give each sound a clear beginning and ending. For a full alphabet, name files A.wav through Z.wav and SPACE.wav. In a single long recording, leave at least 220 ms of silence between sounds.</p></details>
      </details>
    </section>
    <section><h2>2 · Listen to a transmission</h2>
      <label>Saved voice / revision<select id="voices"></select></label><div id="version" class="muted"></div>
      <label>Message<input id="message" value="WE ARE HERE" maxlength="20" autocomplete="off"></label>
      <div class="row"><button id="play" class="primary">Play in headphones</button><button id="stop">Stop</button><button id="render">Decode rendered audio</button></div>
      <label>Listening volume<input id="volume" type="range" min="0" max="100" value="25" aria-label="Listening volume"></label>
      <div id="decoded" class="readout" aria-live="polite">—</div>
      <canvas id="wave" width="900" height="100" aria-label="Transmission waveform"></canvas>
      <p id="duration" class="muted"></p>
      <details class="secondary-tools"><summary>Hear individual letters</summary><div id="symbols" class="symbols"></div></details>
      <details class="secondary-tools"><summary>Save or open a voice</summary>
        <div class="downloads"><button id="export">Export voice package</button><button id="exportAudio">Export message WAV</button></div>
        <label>Import an existing voice package<input id="voiceFile" type="file" accept=".json,application/json"></label>
      </details>
      <p class="muted">Rendered decoding tests the software path. Use speakers and a microphone recording to measure acoustic performance. Headphones are for listening.</p>
    </section>
    <section class="wide"><details><summary class="section-title">3 · Test with recordings</summary>
      <div class="row"><button id="record">Record microphone (30s max)</button><button id="finish" disabled>Finish recording</button>
        <label>Or import a debug-page WAV<input id="captureFile" type="file" accept="audio/*,.wav"></label></div>
      <div class="row"><label>Expected message (for scoring only)<input id="expected" maxlength="100" placeholder="What was actually transmitted?"></label>
        <label>Segmentation floor (dB)<input id="floor" type="number" min="-80" max="-10" value="-48" step="1"></label></div>
      <div class="row"><button id="analyze">Analyze recording</button><button id="legacy">Compare classic decoder</button><button id="holdout">Add to evaluation set</button></div>
      <p id="captureInfo" class="muted">No recording loaded. Record room noise too: unexpected decoded letters count as false detections.</p>
      <label>Optional recording metadata JSON<input id="captureMetadata" type="file" accept=".json,application/json"></label>
      <div id="captureDownloads" class="downloads"></div>
      <div class="scroll"><table><thead><tr><th>Time</th><th>Heard</th><th>Closest</th><th>Distance ↓</th><th>Margin ↑</th><th>Listen</th><th>Confirmed label</th></tr></thead><tbody id="segments"></tbody></table></div>
      <p class="muted">Labels are deliberately blank. Enter a confirmed letter, SPACE, or leave blank to exclude a segment. Listen before labelling. Split or missed segments need a cleaner recording or an adjusted floor; the expected message is never used to guess sounds.</p>
      <label class="check"><input id="reviewed" type="checkbox">I have listened and checked the labels I want to use for calibration.</label>
      <button id="calibrate">Create calibrated revision</button>
    </details></section>
    <section><details><summary class="section-title">4 · Check separation</summary><p id="separation" class="muted"></p>
      <div class="scroll"><table><thead><tr><th>Symbol</th><th>Could resemble</th><th>Distance ↑</th></tr></thead><tbody id="pairs"></tbody></table></div>
      <p class="muted">This is a digital separation check, not a guarantee of reliability in an exhibition. Similar sounds may need redesigning.</p>
    </details></section>
    <section><details><summary class="section-title">5 · Compare revisions</summary>
      <p class="muted">Add separate, labelled recordings to the evaluation set before calibrating. Training recordings cannot also be evaluation recordings. Re-run every revision on the same set.</p>
      <div class="row"><button id="evaluate">Evaluate current voice</button><button id="exportEvaluation">Export evaluation report</button></div>
      <p id="evaluation" class="muted">No evaluation recordings yet.</p>
      <div class="scroll"><table><thead><tr><th>Voice version</th><th>Recordings</th><th>Errors / letters</th></tr></thead><tbody id="evaluations"></tbody></table></div>
      <p class="muted">Voices are saved in this browser. Export packages as backups and to share voices between devices. Recordings and evaluation sets stay in this tab until exported; nothing is uploaded.</p>
    </details></section>
  </div>
</main>`;

function el<T extends HTMLElement>(id: string): T { return document.getElementById(id) as T; }
const status = el<HTMLDivElement>('status');
let voice: Voice | null = null;
const voices = new Map<string, Voice>();
let outputGain: GainNode | null = null;
let context: AudioContext | null = null, playing: AudioBufferSourceNode | null = null;
let recording: { stream: MediaStream; context: AudioContext; processor: ScriptProcessorNode;
  source: MediaStreamAudioSourceNode; mute: GainNode; chunks: Float32Array[]; count: number; timer: number; voiceId: string | null; expected: string } | null = null;
interface Capture { samples: Float32Array; id: string; name: string; voiceId: string | null; source: 'microphone' | 'import'; expected: string }
let capture: Capture | null = null;
let segments: (Segment & Match)[] = [];
let analyzedVoiceId = '', analyzedCaptureId = '', analyzedFloor = -48;
const holdouts: { capture: Capture; expected: string; floor: number }[] = [];
interface Evaluation { voiceId: string; voiceName: string; errors: number; letters: number;
  recordings: { id: string; expected: string; decoded: string; errors: number; floorDb: number }[] }
const evaluations: Evaluation[] = [];
const downloadUrls: string[] = [];
let busy = false;

function tell(text: string, error = false): void { status.textContent = text; status.classList.toggle('error', error); }
async function task(work: () => Promise<void> | void): Promise<void> {
  if (busy) return;
  busy = true;
  document.querySelectorAll<HTMLButtonElement>('button').forEach(b => { if (!['stop', 'finish'].includes(b.id)) b.disabled = true; });
  try { await work(); } catch (error) { tell(error instanceof Error ? error.message : String(error), true); }
  finally { busy = false; document.querySelectorAll<HTMLButtonElement>('button').forEach(b => { if (b.id !== 'finish') b.disabled = false; }); }
}
function on(id: string, work: () => Promise<void> | void): void { el(id).addEventListener('click', () => void task(work)); }
function current(): Voice { if (!voice) throw Error('Create or import a voice first.'); return voice; }
function message(): string {
  const text = el<HTMLInputElement>('message').value.toUpperCase().trim();
  if (!text || [...text].some(ch => !LETTERS.includes(ch))) throw Error('The message can contain letters A–Z and spaces.');
  return text;
}
function floor(): number {
  const value = Number(el<HTMLInputElement>('floor').value);
  if (!Number.isFinite(value) || value < -80 || value > -10) throw Error('Choose a segmentation floor between -80 and -10 dB.');
  return value;
}
function display(ch: string): string { return ch === ' ' ? 'SPACE' : ch; }
function cell(row: HTMLTableRowElement, text: string): HTMLTableCellElement { const c = row.insertCell(); c.textContent = text; return c; }
function stop(): void { playing?.stop(); playing = null; }
async function play(samples: Float32Array): Promise<void> {
  stop(); context ??= new AudioContext(); await context.resume();
  const buffer = context.createBuffer(1, samples.length, RATE); buffer.copyToChannel(new Float32Array(samples), 0);
  outputGain ??= context.createGain();
  outputGain.gain.value = Number(el<HTMLInputElement>('volume').value) / 100;
  outputGain.disconnect(); outputGain.connect(context.destination);
  playing = context.createBufferSource(); playing.buffer = buffer; playing.connect(outputGain);
  const source = playing; source.onended = () => { if (playing === source) playing = null; };
  source.start();
}
function draw(samples: Float32Array): void {
  const canvas = el<HTMLCanvasElement>('wave'), ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.strokeStyle = '#9ce0d3'; ctx.beginPath();
  for (let x = 0; x < canvas.width; x++) {
    let low = 0, high = 0;
    for (let i = Math.floor(x * samples.length / canvas.width); i < Math.floor((x + 1) * samples.length / canvas.width); i++) {
      low = Math.min(low, samples[i]); high = Math.max(high, samples[i]);
    }
    ctx.moveTo(x, 50 - high * 47); ctx.lineTo(x, 50 - low * 47);
  }
  ctx.stroke();
}
function download(data: BlobPart, name: string, type: string): void {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}
function jsonDownload(value: unknown, name: string): void { download(JSON.stringify(value, null, 2), name, 'application/json'); }
function synthSettings(): SynthSettings {
  const number = (id: string) => Number(el<HTMLInputElement>(id).value);
  return {
    waveform: el<HTMLSelectElement>('waveform').value as Waveform,
    pitchHz: number('pitchHz'), brightness: number('brightness') / 100,
    attack: number('attack') / 1000, decay: number('decay') / 1000,
    sustain: number('sustain') / 100, release: number('release') / 1000
  };
}
for (const id of ['pitchHz', 'brightness', 'attack', 'decay', 'sustain', 'release']) {
  const slider = el<HTMLInputElement>(id), output = el<HTMLOutputElement>(`${id}Value`);
  const update = () => { output.value = `${slider.value}${id === 'pitchHz' ? ' Hz' : ['brightness', 'sustain'].includes(id) ? '%' : ' ms'}`; };
  slider.addEventListener('input', update); update();
}
async function readFile(file: File, maxSeconds = 30): Promise<Float32Array> {
  if (file.size > 40_000_000) throw Error('Audio file exceeds 40 MB.');
  const decodeContext = new OfflineAudioContext(1, 1, RATE);
  const decoded = await decodeContext.decodeAudioData(await file.arrayBuffer());
  if (decoded.duration > maxSeconds || decoded.duration < .1) throw Error(`Use audio between 0.1 and ${maxSeconds} seconds.`);
  const mono = new Float32Array(decoded.length);
  for (let channel = 0; channel < decoded.numberOfChannels; channel++) {
    const samples = decoded.getChannelData(channel);
    for (let i = 0; i < mono.length; i++) mono[i] += samples[i] / decoded.numberOfChannels;
  }
  return mono;
}
function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('alive-voice-studio', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('voices', { keyPath: 'id' });
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
}
async function persist(v: Voice): Promise<void> {
  const database = await db();
  try { await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction('voices', 'readwrite'); transaction.objectStore('voices').put(v);
    transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error); transaction.onabort = () => reject(transaction.error);
  }); } finally { database.close(); }
}
async function selectVoice(v: Voice): Promise<void> {
  if (recording) throw Error('Finish the recording before changing voices.');
  stop(); voice = v; voices.set(v.id, v);
  const list = el<HTMLSelectElement>('voices'); list.replaceChildren();
  for (const entry of voices.values()) { const option = new Option(`${entry.name} · ${entry.id.slice(0, 8)}`, entry.id); list.add(option); }
  list.value = v.id; el<HTMLInputElement>('voiceName').value = v.name;
  el('version').textContent = `${v.id} · ${v.calibration.length} confirmed examples · experimental`;
  el('decoded').textContent = '—';
  el('symbols').replaceChildren();
  for (const ch of LETTERS) {
    const button = document.createElement('button'); button.textContent = ch === ' ' ? '␣' : ch;
    button.setAttribute('aria-label', `Listen to ${display(ch)}`);
    button.onclick = () => void task(() => play(pcmDecode(v.symbols[ch]))); el('symbols').append(button);
  }
  tell('Checking the sound alphabet…'); await new Promise(resolve => setTimeout(resolve, 0));
  const report = confusionReport(v);
  el('separation').textContent = report.failures.length ? `Needs work: ${report.failures.map(display).join(', ')} are ambiguous even before acoustic playback.` :
    'All 27 original sounds identify digitally. Next: test recordings through speakers and a microphone.';
  const table = el<HTMLTableSectionElement>('pairs'); table.replaceChildren();
  for (const pair of report.pairs) { const row = table.insertRow(); cell(row, display(pair.a)); cell(row, display(pair.b)); cell(row, pair.distance.toFixed(3)); }
  try { await persist(v); tell(`Voice ready: ${v.name}. ${report.failures.length ? 'Some symbols need redesigning; see the separation check.' : 'Ready for listening and acoustic experiments.'}`); }
  catch { tell('Voice ready, but browser storage is unavailable. Export the package to keep it.', true); }
}
async function loadVoices(): Promise<void> {
  const database = await db();
  try { const stored = await new Promise<Voice[]>((resolve, reject) => {
    const request = database.transaction('voices').objectStore('voices').getAll();
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
    for (const entry of stored) { try { const valid = await validateVoice(entry); voices.set(valid.id, valid); } catch { /* Ignore invalid stored packages. */ } }
    if (voices.size) {
      await selectVoice([...voices.values()].at(-1)!);
      tell('Saved voices keep their original sounds. Adjust the synth above and make a new voice to hear your changes.');
    }
    else tell('Adjust the synth, hear your sound, then make a voice. Nothing is sent to a server.');
  } finally { database.close(); }
}

el('importMode').addEventListener('change', () => {
  const mode = el<HTMLSelectElement>('importMode').value;
  el('importHelp').textContent = mode === 'seed' ? 'Use a 0.12–1.2 second sound. The generator turns the whole sound into 27 continuous variations with different pitch and motion. Each letter plays once.' :
    mode === 'alphabet' ? 'Choose 27 files named A.wav through Z.wav and SPACE.wav. Each trimmed sound must last 0.12–1.2 seconds.' :
    'Choose one recording with 27 sounds in A–Z, SPACE order, separated by at least 220 ms of silence. Maximum 45 seconds.';
});
for (const ch of LETTERS) el<HTMLSelectElement>('replaceSymbol').add(new Option(display(ch), ch));
on('previewSound', async () => {
  const sound = synthesize(synthSettings());
  draw(sound); await play(sound);
  tell('Playing one sound. Adjust the sliders and listen again.');
});
on('create', async () => {
  if (recording) throw Error('Finish recording before creating a voice.');
  tell('Making 27 sounds from your synth settings…');
  const source = synthesize(synthSettings());
  await selectVoice(await compileVoice(generateSounds(source), el<HTMLInputElement>('voiceName').value || 'Untitled voice'));
});
on('createFromFile', async () => {
  if (recording) throw Error('Finish recording before creating a voice.');
  const files = [...(el<HTMLInputElement>('sourceFiles').files ?? [])], mode = el<HTMLSelectElement>('importMode').value;
  if (!files.length) throw Error('Choose audio files first.');
  tell('Reading sounds and building recognition templates…');
  let sounds: Record<string, Float32Array> = {};
  if (mode === 'seed') {
    if (files.length !== 1) throw Error('Choose one signature sound.');
    sounds = generateSounds(await readFile(files[0], 5));
  } else if (mode === 'alphabet') {
    if (files.length !== 27) throw Error('Choose all 27 files: A–Z and SPACE.');
    for (const file of files) {
      const label = file.name.replace(/\.[^.]+$/, '').toUpperCase(), ch = label === 'SPACE' ? ' ' : label;
      if (ch.length !== 1 || !LETTERS.includes(ch) || sounds[ch]) throw Error(`Invalid or duplicate filename: ${file.name}`);
      sounds[ch] = await readFile(file, 5);
    }
  } else {
    if (files.length !== 1) throw Error('Choose one recording containing the alphabet.');
    const parts = segmentAudio(await readFile(files[0], 45), floor());
    if (parts.length !== 27) throw Error(`Found ${parts.length} sounds; need 27. Adjust the segmentation floor or the source pauses.`);
    [...LETTERS].forEach((ch, i) => { sounds[ch] = parts[i].samples; });
  }
  await selectVoice(await compileVoice(sounds, el<HTMLInputElement>('voiceName').value || 'Untitled voice'));
});
on('replace', async () => {
  const v = current(), file = el<HTMLInputElement>('replacement').files?.[0];
  if (!file) throw Error('Choose a replacement sound.');
  const ch = el<HTMLSelectElement>('replaceSymbol').value;
  const sounds = Object.fromEntries([...LETTERS].map(c => [c, pcmDecode(v.symbols[c])]));
  sounds[ch] = await readFile(file, 5);
  const rebuilt = await compileVoice(sounds, el<HTMLInputElement>('voiceName').value || v.name);
  // Preserve calibrated templates and exact PCM for the unchanged symbols.
  for (const other of LETTERS) if (other !== ch) rebuilt.symbols[other] = structuredClone(v.symbols[other]);
  rebuilt.calibration = v.calibration.filter(example => example.symbol !== ch);
  await selectVoice(await stamp(rebuilt));
});
el('voices').addEventListener('change', () => void task(async () => {
  const list = el<HTMLSelectElement>('voices');
  if (recording) { list.value = voice?.id ?? ''; throw Error('Finish the recording before changing voices.'); }
  const chosen = voices.get(list.value); if (chosen) await selectVoice(chosen);
}));
on('play', async () => {
  const audio = renderMessage(current(), message()); draw(audio); await play(audio);
  el('duration').textContent = `${(audio.length / RATE).toFixed(2)} seconds · headphones audition`;
  tell('Playing the designed voice. Use “Decode rendered audio” to check the digital path.');
});
el('stop').addEventListener('click', stop);
el('volume').addEventListener('input', () => { if (outputGain) outputGain.gain.value = Number(el<HTMLInputElement>('volume').value) / 100; });
on('render', () => {
  const v = current(), expected = message(), audio = renderMessage(v, expected), matches = decodeAudio(audio, v, floor());
  const decoded = matches.map(m => m.symbol).join(''); el('decoded').textContent = decoded || '—'; draw(audio);
  el('duration').textContent = `${(audio.length / RATE).toFixed(2)} seconds · ${characterErrors(expected, decoded)} character errors · digital only`;
  tell('Decoded only from rendered samples. Expected text was used for scoring, not recognition.');
});
on('export', () => { const v = current(); jsonDownload(v, `alive-voice-${v.id}.json`); });
on('exportAudio', () => { const v = current(); download(encodeVoiceRecording(renderMessage(v, message()), RATE), `alive-${v.id}-${message().replaceAll(' ', '-')}.wav`, 'audio/wav'); });
el('voiceFile').addEventListener('change', () => void task(async () => {
  const file = el<HTMLInputElement>('voiceFile').files?.[0]; if (!file) return;
  if (file.size > 4_000_000) throw Error('Voice package exceeds 4 MB.');
  await selectVoice(await validateVoice(JSON.parse(await file.text())));
}));

async function setCapture(samples: Float32Array, name: string, source: Capture['source'], voiceId: string | null, expected: string): Promise<void> {
  const id = await digest(encodeVoiceRecording(samples, RATE));
  capture = { samples, id, name, source, voiceId, expected };
  el<HTMLInputElement>('expected').value = expected;
  segments = []; el('segments').replaceChildren(); el<HTMLInputElement>('reviewed').checked = false;
  el('captureInfo').textContent = `${name} · ${(samples.length / RATE).toFixed(2)} seconds · ${source} · source voice ${voiceId?.slice(0, 8) ?? 'unknown (imported audio)'}`;
  draw(samples); captureDownloads(); tell('Recording ready. Analyze it, then inspect the detected segments.');
}
function captureDownloads(): void {
  if (!capture) return;
  for (const url of downloadUrls) URL.revokeObjectURL(url); downloadUrls.length = 0;
  const container = el('captureDownloads'); container.replaceChildren();
  const metadata = { format: 'alive-voice-capture', version: 1, recordingId: capture.id, voiceId: capture.voiceId,
    sampleRate: RATE, source: capture.source, message: el<HTMLInputElement>('expected').value.toUpperCase(),
    seconds: capture.samples.length / RATE, floorDb: floor() };
  for (const [label, data, suffix, type] of [
    ['Download WAV', encodeVoiceRecording(capture.samples, RATE), 'wav', 'audio/wav'],
    ['Download recording metadata', JSON.stringify(metadata, null, 2), 'json', 'application/json']
  ] as const) {
    const url = URL.createObjectURL(new Blob([data], { type })); downloadUrls.push(url);
    const link = document.createElement('a'); link.href = url; link.download = `alive-capture-${capture.id.slice(0, 12)}.${suffix}`; link.textContent = label; container.append(link);
  }
}
el('expected').addEventListener('change', () => { try { captureDownloads(); } catch (e) { tell(String(e), true); } });
el('captureFile').addEventListener('change', () => void task(async () => {
  if (recording) throw Error('Finish the microphone recording first.');
  const file = el<HTMLInputElement>('captureFile').files?.[0];
  if (file) await setCapture(await readFile(file), file.name, 'import', null, '');
}));
el('captureMetadata').addEventListener('change', () => void task(async () => {
  if (!capture) throw Error('Load the matching recording WAV first.');
  const file = el<HTMLInputElement>('captureMetadata').files?.[0]; if (!file) return;
  if (file.size > 100000) throw Error('Metadata file is too large.');
  const metadata = JSON.parse(await file.text());
  if (metadata.recordingId && metadata.recordingId !== capture.id) throw Error('This metadata belongs to a different recording.');
  if (typeof metadata.message !== 'string' || metadata.message.length > 100 || [...metadata.message].some((ch: string) => !LETTERS.includes(ch))) throw Error('Invalid expected message metadata.');
  if (metadata.voiceId != null && (typeof metadata.voiceId !== 'string' || !/^[a-f0-9]{24}$/.test(metadata.voiceId))) throw Error('Invalid source voice ID.');
  capture.expected = metadata.message; capture.voiceId = metadata.voiceId ?? null;
  el<HTMLInputElement>('expected').value = metadata.message; captureDownloads();
  el('captureInfo').textContent = `${capture.name} · source voice ${capture.voiceId ?? 'unknown / classic'} · metadata loaded`;
  tell('Recording metadata loaded. The expected message is used only for scoring.');
}));
on('record', async () => {
  if (recording) throw Error('A recording is already in progress.');
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  let ctx: AudioContext | null = null;
  try {
    ctx = new AudioContext(); await ctx.resume();
    const liveDecoder = voice ? new SoundVoiceDecoder(voice, floor()) : null;
    const source = ctx.createMediaStreamSource(stream), processor = ctx.createScriptProcessor(2048, 1, 1), mute = ctx.createGain(); mute.gain.value = 0;
    const active = { stream, context: ctx, processor, source, mute, chunks: [] as Float32Array[], count: 0, timer: 0,
      voiceId: voice?.id ?? null, expected: el<HTMLInputElement>('message').value.toUpperCase().trim() };
    recording = active;
    processor.onaudioprocess = event => {
      const remaining = Math.ceil(ctx!.sampleRate * 30) - active.count;
      if (remaining <= 0) return;
      const chunk = event.inputBuffer.getChannelData(0).slice(0, remaining); active.chunks.push(chunk); active.count += chunk.length;
      if (liveDecoder) { const result = liveDecoder.process(chunk, ctx!.sampleRate); el('decoded').textContent = result.message || 'Listening…'; }
      el('captureInfo').textContent = `Recording microphone · ${(active.count / ctx!.sampleRate).toFixed(1)} / 30 seconds`;
    };
    source.connect(processor); processor.connect(mute).connect(ctx.destination);
    active.timer = window.setTimeout(() => void finishRecording(), 30000);
    el<HTMLButtonElement>('finish').disabled = false;
    tell('Microphone recording. Play a transmission through a speaker or another device; headphones will not give an acoustic test.');
  } catch (error) { stream.getTracks().forEach(track => track.stop()); await ctx?.close(); throw error; }
});
async function finishRecording(): Promise<void> {
  const active = recording; if (!active) return; recording = null;
  window.clearTimeout(active.timer); active.processor.onaudioprocess = null;
  active.source.disconnect(); active.processor.disconnect(); active.mute.disconnect(); active.stream.getTracks().forEach(t => t.stop());
  const rate = active.context.sampleRate; await active.context.close(); el<HTMLButtonElement>('finish').disabled = true;
  try {
    if (!active.count) throw Error('No microphone samples were captured.');
    const raw = join(active.chunks), offline = new OfflineAudioContext(1, Math.ceil(raw.length * RATE / rate), RATE);
    const buffer = offline.createBuffer(1, raw.length, rate); buffer.copyToChannel(new Float32Array(raw), 0);
    const source = offline.createBufferSource(); source.buffer = buffer; source.connect(offline.destination); source.start();
    await setCapture(new Float32Array((await offline.startRendering()).getChannelData(0)), 'Microphone recording', 'microphone', active.voiceId, active.expected);
  } catch (error) { tell(error instanceof Error ? error.message : String(error), true); }
}
el('finish').addEventListener('click', () => void finishRecording());
function analyze(): void {
  if (!capture) throw Error('Record or import audio first.');
  const v = current(); segments = decodeAudio(capture.samples, v, floor()); analyzedVoiceId = v.id; analyzedCaptureId = capture.id; analyzedFloor = floor();
  el<HTMLInputElement>('reviewed').checked = false;
  const table = el<HTMLTableSectionElement>('segments'); table.replaceChildren();
  segments.forEach((segment, i) => {
    const row = table.insertRow(); cell(row, `${segment.start.toFixed(2)}–${segment.end.toFixed(2)}s`);
    cell(row, display(segment.symbol)); cell(row, display(segment.nearest)); cell(row, segment.distance.toFixed(3)); cell(row, segment.margin.toFixed(3));
    const listen = document.createElement('button'); listen.textContent = 'Listen'; listen.onclick = () => void task(() => play(segment.samples)); cell(row, '').append(listen);
    const label = document.createElement('input'); label.id = `label-${i}`; label.maxLength = 5; label.placeholder = 'skip'; label.setAttribute('aria-label', `Confirmed label for segment ${i + 1}`); cell(row, '').append(label);
  });
  const decoded = segments.map(s => s.symbol).join(''), expected = el<HTMLInputElement>('expected').value.toUpperCase();
  el('decoded').textContent = decoded || '—';
  tell(`${segments.length} sound segments. Decoded: ${decoded || '(nothing)'}. ${characterErrors(expected, decoded)} character errors against the entered expected message.`);
  captureDownloads();
}
on('analyze', analyze);
on('legacy', async () => {
  if (!capture) throw Error('Record or import audio first.');
  const rate = 44100;
  const offline = new OfflineAudioContext(1, Math.ceil(capture.samples.length * rate / RATE), rate);
  const buffer = offline.createBuffer(1, capture.samples.length, RATE); buffer.copyToChannel(new Float32Array(capture.samples), 0);
  const source = offline.createBufferSource(); source.buffer = buffer; source.connect(offline.destination); source.start();
  const samples = (await offline.startRendering()).getChannelData(0);
  const decoder = new TranslationDecoder(); decoder.beginCapture(0); decoder.setCaptureDuration(0, 30);
  let result = decoder.snapshot();
  for (let i = 0; i < samples.length; i += 2048) result = decoder.process(samples.subarray(i, i + 2048), rate, -40, -55, i / rate, i / rate * 1000);
  const decoded = result.message === '---' ? '' : result.message;
  tell(`Classic receiver: ${decoded || '(nothing decoded)'}. ${characterErrors(el<HTMLInputElement>('expected').value.toUpperCase(), decoded)} character errors. Designed voices need the new codebook; use classic recordings to verify the old path.`);
});
on('holdout', () => {
  if (!capture) throw Error('Record or import audio first.');
  if ([...voices.values()].some(v => v.calibration.some(example => example.recordingId === capture!.id))) throw Error('This recording has been used for training. Use a separate recording for evaluation.');
  if (holdouts.some(h => h.capture.id === capture!.id)) throw Error('This recording is already in the evaluation set.');
  const expected = el<HTMLInputElement>('expected').value.toUpperCase();
  if ([...expected].some(ch => !LETTERS.includes(ch))) throw Error('Expected text must contain A–Z/spaces, or be empty for room noise.');
  holdouts.push({ capture, expected, floor: floor() }); el('evaluation').textContent = `${holdouts.length} evaluation recordings. Blank expected text measures false detections.`;
  tell('Added to the evaluation set. This recording is now excluded from calibration in this tab.');
});
on('calibrate', async () => {
  const v = current();
  if (!capture || analyzedCaptureId !== capture.id || analyzedVoiceId !== v.id || analyzedFloor !== floor()) throw Error('Analyze this recording with the current voice before calibrating.');
  if (!el<HTMLInputElement>('reviewed').checked) throw Error('Listen to the selected segments, confirm labels, and check the review box first.');
  const examples = segments.map((segment, i) => ({ segment, label: el<HTMLInputElement>(`label-${i}`).value }));
  const next = await calibrateVoice(v, capture.id, examples, holdouts.map(h => h.capture.id));
  await selectVoice(next); tell(`Created a new revision with ${next.calibration.length - v.calibration.length} confirmed examples. The previous version is still in the voice list. Evaluate before choosing the new version.`);
});
on('evaluate', async () => {
  const v = current(); if (!holdouts.length) throw Error('Add separate labelled recordings to the evaluation set first.');
  if (holdouts.some(h => v.calibration.some(example => example.recordingId === h.capture.id))) throw Error('The selected voice was trained on an evaluation recording. Choose an independent evaluation set.');
  tell('Evaluating recordings…'); await new Promise(resolve => setTimeout(resolve, 0));
  const results = holdouts.map(h => { const decoded = decodeAudio(h.capture.samples, v, h.floor).map(s => s.symbol).join('');
    return { id: h.capture.id, expected: h.expected, decoded, errors: characterErrors(h.expected, decoded), floorDb: h.floor }; });
  const report: Evaluation = { voiceId: v.id, voiceName: v.name, recordings: results,
    errors: results.reduce((sum, r) => sum + r.errors, 0), letters: results.reduce((sum, r) => sum + r.expected.length, 0) };
  evaluations.push(report);
  const row = el<HTMLTableSectionElement>('evaluations').insertRow(); cell(row, v.id.slice(0, 8)); cell(row, String(results.length)); cell(row, `${report.errors} / ${report.letters}`);
  tell(`Evaluation: ${report.errors} character errors across ${report.letters} expected letters in ${results.length} recordings. Errors include insertions and rejected sounds.`);
});
on('exportEvaluation', () => {
  if (!evaluations.length) throw Error('Run an evaluation first.');
  jsonDownload({ format: 'alive-voice-evaluation', version: 1, evaluations }, 'alive-voice-evaluation.json');
});
window.addEventListener('pagehide', () => { stop(); recording?.stream.getTracks().forEach(t => t.stop()); });
void task(async () => { try { await loadVoices(); } catch { tell('Browser storage is unavailable. You can still create and export voice packages.'); } });
