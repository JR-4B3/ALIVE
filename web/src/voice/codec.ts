// Experimental acoustic alphabet. Format and math match sound_voice.py.
export const RATE = 16000;
export const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ';
const FRAME = 512, HOP = 160, BANDS = 40, STEPS = 24;
export type Trajectory = number[][];
export interface VoiceSymbol { pcm: string; samples: number; templates: Trajectory[] }
export interface Voice {
  format: 'alive-sound-voice'; version: 1; id: string; name: string; sampleRate: number;
  gapSeconds: number; maxDistance: number; minMargin: number;
  symbols: Record<string, VoiceSymbol>;
  calibration: { recordingId: string; label: string; symbol: string }[];
}
export interface Match { symbol: string; nearest: string; distance: number; margin: number }
export interface Segment { start: number; end: number; samples: Float32Array }

const window = Float64Array.from({ length: FRAME }, (_, i) => .5 - .5 * Math.cos(2 * Math.PI * i / (FRAME - 1)));
const edges = Array.from({ length: BANDS + 2 }, (_, i) => 180 * (6500 / 180) ** (i / (BANDS + 1)));
const bank = edges.slice(0, BANDS).map((a, b) => Float64Array.from({ length: FRAME / 2 + 1 }, (_, k) => {
  const f = k * RATE / FRAME;
  return Math.max(0, Math.min((f - a) / (edges[b + 1] - a), (edges[b + 2] - f) / (edges[b + 2] - edges[b + 1])));
}));

function powerSpectrum(samples: Float32Array): Float64Array {
  const re = new Float64Array(FRAME), im = new Float64Array(FRAME);
  for (let i = 0; i < FRAME; i++) re[i] = (samples[i] ?? 0) * window[i];
  for (let i = 1, j = 0; i < FRAME; i++) {
    let bit = FRAME >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) [re[i], re[j]] = [re[j], re[i]];
  }
  for (let len = 2; len <= FRAME; len <<= 1) {
    const angle = -2 * Math.PI / len;
    for (let i = 0; i < FRAME; i += len) for (let j = 0; j < len / 2; j++) {
      const c = Math.cos(angle * j), s = Math.sin(angle * j), k = i + j, l = k + len / 2;
      const tr = re[l] * c - im[l] * s, ti = re[l] * s + im[l] * c;
      re[l] = re[k] - tr; im[l] = im[k] - ti; re[k] += tr; im[k] += ti;
    }
  }
  return Float64Array.from({ length: FRAME / 2 + 1 }, (_, i) => re[i] ** 2 + im[i] ** 2);
}
function normalize(row: number[]): number[] {
  const norm = Math.max(1e-9, Math.hypot(...row));
  return row.map(x => x / norm);
}
export function features(audio: Float32Array): Trajectory {
  const rows: number[][] = [];
  for (let offset = 0; offset <= Math.max(0, audio.length - FRAME); offset += HOP) {
    const powers = powerSpectrum(audio.subarray(offset, offset + FRAME));
    let row = bank.map(weights => Math.sqrt(weights.reduce((sum, w, i) => sum + w * powers[i], 0)));
    const floor = Math.max(...row) * .04;
    row = normalize(row.map(x => Math.max(0, x - floor)));
    rows.push(row);
  }
  return Array.from({ length: STEPS }, (_, i) => {
    const p = i * (rows.length - 1) / (STEPS - 1), lo = Math.floor(p), hi = Math.ceil(p);
    return normalize(rows[lo].map((x, b) => x + (rows[hi][b] - x) * (p - lo))).map(x => Math.round(x * 1e6) / 1e6);
  });
}
export function distance(a: Trajectory, b: Trajectory): number {
  let prev = new Float64Array(b.length + 1).fill(Infinity); prev[0] = 0;
  for (let i = 1; i <= a.length; i++) {
    const next = new Float64Array(b.length + 1).fill(Infinity);
    for (let j = Math.max(1, i - 3); j <= Math.min(b.length, i + 3); j++) {
      const cost = Math.max(0, 1 - a[i - 1].reduce((sum, x, k) => sum + x * b[j - 1][k], 0));
      next[j] = cost + Math.min(prev[j - 1], prev[j] + .025, next[j - 1] + .025);
    }
    prev = next;
  }
  return prev[b.length] / Math.max(a.length, b.length);
}
export function identify(trajectory: Trajectory, voice: Voice): Match {
  const ranked = Object.entries(voice.symbols).map(([ch, entry]) => ({ ch,
    score: Math.min(...entry.templates.map(t => distance(trajectory, t))) })).sort((a, b) => a.score - b.score);
  const first = ranked[0], margin = ranked[1].score - first.score;
  return { symbol: first.score <= voice.maxDistance && margin >= voice.minMargin ? first.ch : '?',
    nearest: first.ch, distance: first.score, margin };
}
export function prepare(input: Float32Array): Float32Array {
  if (!input.length || input.some(x => !Number.isFinite(x))) throw Error('Empty or invalid sound.');
  const mean = input.reduce((sum, x) => sum + x, 0) / input.length;
  const centered = input.map(x => x - mean);
  const peak = centered.reduce((p, x) => Math.max(p, Math.abs(x)), 0);
  if (peak < 1e-5) throw Error('This sound is silent.');
  let first = 0, last = centered.length - 1;
  while (Math.abs(centered[first]) <= peak * .015) first++;
  while (Math.abs(centered[last]) <= peak * .015) last--;
  const audio = centered.slice(Math.max(0, first - 160), Math.min(centered.length, last + 161));
  if (audio.length < RATE * .12 || audio.length > RATE * 1.2) throw Error('Each trimmed sound must last 0.12–1.2 seconds.');
  const edge = Math.min(160, Math.floor(audio.length / 10));
  for (let i = 0; i < edge; i++) { audio[i] *= i / (edge - 1); audio[audio.length - 1 - i] *= i / (edge - 1); }
  const gain = .7 / audio.reduce((p, x) => Math.max(p, Math.abs(x)), 1e-9);
  return audio.map(x => x * gain);
}
export function pcmEncode(audio: Float32Array): string {
  const bytes = new Uint8Array(audio.length * 2), view = new DataView(bytes.buffer);
  for (let i = 0; i < audio.length; i++) view.setInt16(i * 2, Math.round(Math.max(-1, Math.min(1, audio[i])) * 32767), true);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}
export function pcmDecode(entry: VoiceSymbol): Float32Array {
  const binary = atob(entry.pcm), bytes = Uint8Array.from(binary, c => c.charCodeAt(0)), view = new DataView(bytes.buffer);
  return Float32Array.from({ length: entry.samples }, (_, i) => view.getInt16(i * 2, true) / 32768);
}
function canonical(value: unknown): unknown {
  if (typeof value === 'number') return value.toFixed(6);
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, v]) => [k, canonical(v)]));
  return value;
}
export async function digest(text: string | ArrayBuffer): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', typeof text === 'string' ? new TextEncoder().encode(text) : text);
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
}
export async function stamp(voice: Voice): Promise<Voice> {
  const { id: _id, ...contents } = voice;
  return { ...contents, id: (await digest(JSON.stringify(canonical(contents)))).slice(0, 24) };
}
export async function compileVoice(sounds: Record<string, Float32Array>, name: string): Promise<Voice> {
  if (Object.keys(sounds).length !== 27 || [...LETTERS].some(ch => !sounds[ch])) throw Error('Provide A–Z and SPACE: 27 sounds.');
  const symbols: Voice['symbols'] = {};
  for (const ch of LETTERS) {
    const audio = prepare(sounds[ch]);
    const entry: VoiceSymbol = { pcm: pcmEncode(audio), samples: audio.length, templates: [] };
    entry.templates = [features(pcmDecode(entry))]; symbols[ch] = entry;
  }
  return stamp({ format: 'alive-sound-voice', version: 1, id: '', name: name.slice(0, 80), sampleRate: RATE,
    gapSeconds: .22, maxDistance: .24, minMargin: .045, symbols, calibration: [] });
}
export async function validateVoice(value: unknown): Promise<Voice> {
  const voice = value as Voice;
  if (!voice || voice.format !== 'alive-sound-voice' || voice.version !== 1 || voice.sampleRate !== RATE ||
      typeof voice.name !== 'string' || voice.name.length > 80 || !voice.symbols || Object.keys(voice.symbols).length !== 27 ||
      [...LETTERS].some(ch => !voice.symbols[ch]) || !Array.isArray(voice.calibration) || voice.calibration.length > 500 ||
      !(voice.gapSeconds >= .12 && voice.gapSeconds <= .6) || !(voice.maxDistance > 0 && voice.maxDistance <= .5) ||
      !(voice.minMargin >= .01 && voice.minMargin <= .3)) throw Error('Unsupported or invalid voice package.');
  if (voice.calibration.some(example => !example || !/^[a-f0-9]{64}$/.test(example.recordingId) ||
      typeof example.label !== 'string' || example.label.length > 80 || typeof example.symbol !== 'string' ||
      example.symbol.length !== 1 || !LETTERS.includes(example.symbol))) throw Error('Invalid calibration history.');
  for (const entry of Object.values(voice.symbols)) {
    if (!entry || !Number.isInteger(entry.samples) || entry.samples < RATE * .12 || entry.samples > RATE * 1.2 ||
        typeof entry.pcm !== 'string' || entry.pcm.length > 52000 || atob(entry.pcm).length !== entry.samples * 2 ||
        !Array.isArray(entry.templates) || entry.templates.length < 1 || entry.templates.length > 8 ||
        entry.templates.some(t => !Array.isArray(t) || t.length !== STEPS || t.some(row => !Array.isArray(row) || row.length !== BANDS ||
          row.some(x => typeof x !== 'number' || !Number.isFinite(x) || x < 0 || x > 1.001)))) throw Error('Invalid voice sound or template.');
  }
  if ((await stamp(voice)).id !== voice.id) throw Error('Voice contents do not match its version ID.');
  return voice;
}
export function join(parts: Float32Array[]): Float32Array {
  const output = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of parts) { output.set(part, offset); offset += part.length; }
  return output;
}
export function renderMessage(voice: Voice, message: string): Float32Array {
  if (!message.length || message.length > 20 || [...message].some(ch => !LETTERS.includes(ch))) throw Error('Use 1–20 letters/spaces.');
  const audio = join([new Float32Array(RATE / 2), ...[...message].flatMap(ch => [pcmDecode(voice.symbols[ch]),
    new Float32Array(Math.round(voice.gapSeconds * RATE))]), new Float32Array(RATE)]);
  if (audio.length > 30 * RATE) throw Error('This message exceeds 30 seconds; shorten the message.');
  return audio;
}
export function generateSounds(source: Float32Array): Record<string, Float32Array> {
  source = prepare(source);
  // Use the whole source. Stretch very short sounds and compress long ones so
  // pitch changes still fit inside a single recognizable symbol.
  const sourceLength = Math.round(Math.max(.24 * RATE, Math.min(.62 * RATE, source.length)));
  const seed = Float32Array.from({ length: sourceLength }, (_, i) => {
    const position = i * (source.length - 1) / (sourceLength - 1);
    const low = Math.floor(position), fraction = position - low;
    return source[low] * (1 - fraction) + source[Math.min(low + 1, source.length - 1)] * fraction;
  });
  const sounds: Record<string, Float32Array> = {};
  [...LETTERS].forEach((ch, index) => {
    const rate = .64 * 1.12 ** Math.floor(index / 3);
    const sweep = [-.4, 0, .4][index % 3];
    const length = Math.round(sourceLength / rate);
    sounds[ch] = Float32Array.from({ length }, (_, i) => {
      const progress = i / (length - 1);
      // The phase curve has no reset or internal silence: each letter is one
      // continuous gesture with a different pitch and direction of motion.
      const warped = progress + sweep * (progress * progress - progress);
      const position = warped * (sourceLength - 1);
      const low = Math.floor(position), fraction = position - low;
      const sample = seed[low] * (1 - fraction) + seed[Math.min(low + 1, sourceLength - 1)] * fraction;
      return sample * Math.sin(Math.PI * progress) ** .35;
    });
  });
  return sounds;
}
export function demoSource(): Float32Array {
  // A single resonant, breathy gesture for auditioning the generator.
  let phase = 0, noise = 0, random = 1729;
  const length = Math.round(RATE * .36);
  return Float32Array.from({ length }, (_, i) => {
    const t = i / RATE;
    phase += 2 * Math.PI * (320 + 330 * t + 95 * Math.sin(t * 27)) / RATE;
    random = (Math.imul(random, 1664525) + 1013904223) >>> 0;
    noise = noise * .96 + .04 * (random / 2147483648 - 1);
    const body = .48 * Math.sin(phase) + .32 * Math.sin(.47 * phase + .8 * Math.sin(t * 19)) +
      .16 * Math.sin(2.2 * phase) + .4 * noise;
    return Math.sin(Math.PI * i / (length - 1)) ** .7 * body * .7;
  });
}
export function confusionReport(voice: Voice): { failures: string[]; pairs: { a: string; b: string; distance: number }[] } {
  const failures = [...LETTERS].filter(ch => identify(features(pcmDecode(voice.symbols[ch])), voice).symbol !== ch ||
    decodeAudio(renderMessage(voice, ch), voice).map(match => match.symbol).join('') !== ch);
  const pairs: { a: string; b: string; distance: number }[] = [];
  [...LETTERS].forEach((a, i) => { for (const b of LETTERS.slice(i + 1)) pairs.push({ a, b,
    distance: Math.min(...voice.symbols[a].templates.flatMap(x => voice.symbols[b].templates.map(y => distance(x, y)))) }); });
  return { failures, pairs: pairs.sort((a, b) => a.distance - b.distance).slice(0, 12) };
}

// Silence-based segmentation is intentionally explicit: overlapping/continuous
// sound design needs another framing strategy. Never infer symbols from text.
export function segmentAudio(audio: Float32Array, floorDb = -48): Segment[] {
  const segments: Segment[] = [];
  const block = 160, release = 8; // 80 ms; tolerates brief quiet passages inside a designed sound.
  let start = -1, quiet = 0, lastActive = 0;
  const threshold = 10 ** (floorDb / 20);
  for (let offset = 0; offset < audio.length; offset += block) {
    const part = audio.subarray(offset, offset + block);
    const rms = Math.sqrt(part.reduce((s, x) => s + x * x, 0) / Math.max(1, part.length));
    if (rms > threshold) {
      if (start < 0) start = Math.max(0, offset - block);
      quiet = 0; lastActive = Math.min(audio.length, offset + block);
    } else if (start >= 0) quiet++;
    if (start >= 0 && (quiet >= release || offset + block >= audio.length)) {
      const end = Math.min(audio.length, lastActive + block);
      if (end - start >= RATE * .10) segments.push({ start: start / RATE, end: end / RATE, samples: audio.slice(start, end) });
      start = -1; quiet = 0;
    }
  }
  return segments;
}
export function decodeAudio(audio: Float32Array, voice: Voice, floorDb = -48): (Segment & Match)[] {
  return segmentAudio(audio, floorDb).map(segment => ({ ...segment,
    ...(segment.samples.length > RATE * 1.4 ? { symbol: '?', nearest: '?', distance: 1, margin: 0 } : identify(features(segment.samples), voice)) }));
}
export function characterErrors(expected: string, actual: string): number {
  let prev = Array.from({ length: actual.length + 1 }, (_, i) => i);
  for (let i = 1; i <= expected.length; i++) {
    const next = [i];
    for (let j = 1; j <= actual.length; j++) next[j] = Math.min(next[j - 1] + 1, prev[j] + 1, prev[j - 1] + (expected[i - 1] === actual[j - 1] ? 0 : 1));
    prev = next;
  }
  return prev[actual.length];
}


export async function calibrateVoice(voice: Voice, recordingId: string,
  examples: { segment: Segment; label: string }[], evaluationIds: string[] = []): Promise<Voice> {
  if (!/^[a-f0-9]{64}$/.test(recordingId)) throw Error('Invalid recording fingerprint.');
  if (evaluationIds.includes(recordingId)) throw Error('Evaluation recordings cannot be used for training.');
  if (voice.calibration.some(example => example.recordingId === recordingId)) throw Error('This recording is already represented in this voice. Use a fresh recording.');
  const next = structuredClone(voice); let count = 0;
  examples.forEach(({ segment, label }, i) => {
    if (!label) return;
    const ch = label.toUpperCase() === 'SPACE' ? ' ' : label.toUpperCase();
    if (ch.length !== 1 || !LETTERS.includes(ch)) throw Error(`Segment ${i + 1}: enter one letter or SPACE.`);
    if (segment.samples.length < RATE * .1 || segment.samples.length > RATE * 1.4 ||
        segment.samples.some(x => !Number.isFinite(x))) throw Error(`Segment ${i + 1} is invalid; check segmentation.`);
    const entry = next.symbols[ch];
    if (entry.templates.length >= 8) throw Error(`${ch === ' ' ? 'SPACE' : ch} already has 7 acoustic examples. Start from an earlier revision to curate examples.`);
    entry.templates.push(features(segment.samples));
    next.calibration.push({ recordingId, label: `${segment.start.toFixed(3)}–${segment.end.toFixed(3)}`, symbol: ch }); count++;
  });
  if (!count) throw Error('Enter at least one confirmed segment label.');
  if (next.calibration.length > 500) throw Error('Calibration history is full.');
  next.name = `${voice.name.replace(/ · calibrated$/, '').slice(0, 67)} · calibrated`;
  return stamp(next);
}
