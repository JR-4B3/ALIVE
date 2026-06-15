import { goertzel, rmsDb } from '../audio/dsp';
import type { TranslationSnapshot } from '../types';

const LOW_FREQS = [400, 500, 600, 700, 800, 900, 1000];
const HIGH_FREQS = [2000, 2300, 2600, 2900];
const MIC_MIN_BURST_SECONDS = 0.12;
const MIC_MAX_BURST_SECONDS = 0.42;
const CYCLE_BOUNDARY_GAP_MS = 1400;

const CODEBOOK = [
  ['A', 400, 2000, 65],
  ['B', 400, 2300, 98],
  ['C', 400, 2600, 130],
  ['D', 400, 2900, 163],
  ['E', 500, 2000, 195],
  ['F', 500, 2300, 228],
  ['G', 500, 2600, 260],
  ['H', 500, 2900, 293],
  ['I', 600, 2000, 325],
  ['J', 600, 2300, 358],
  ['K', 600, 2600, 390],
  ['L', 600, 2900, 423],
  ['M', 700, 2000, 455],
  ['N', 700, 2300, 488],
  ['O', 700, 2600, 520],
  ['P', 700, 2900, 553],
  ['Q', 800, 2000, 585],
  ['R', 800, 2300, 618],
  ['S', 800, 2600, 650],
  ['T', 800, 2900, 683],
  ['U', 900, 2000, 715],
  ['V', 900, 2300, 748],
  ['W', 900, 2600, 780],
  ['X', 900, 2900, 813],
  ['Y', 1000, 2000, 845],
  ['Z', 1000, 2300, 878],
  [' ', 1000, 2600, 1040]
] as const;

const COMMON_WORDS = new Set([
  'ALIVE',
  'ARE',
  'DEMO',
  'DISCOVER',
  'EARTH',
  'HELLO',
  'HERE',
  'LANGUAGE',
  'MESSAGE',
  'SIGNAL',
  'STILL',
  'TRANSLATE',
  'WE',
  'WORLD'
]);

interface LetterDetection {
  ch: string;
  confidence: number;
  low: number;
  high: number;
}

export class TranslationDecoder {
  private inBurst = false;
  private burstSamples: number[] = [];
  private burstStartAt = 0;
  private lastBurstEndAt = 0;
  private decoded = '';
  private finalMessage = '';
  private stream = '';
  private pendingLetter: LetterDetection | null = null;
  private recentGaps: number[] = [];
  private lastDecodedAt = 0;
  private lastFinalText = '';
  private pair = '--';

  process(
    input: Float32Array,
    sampleRate: number,
    _levelDb: number,
    noiseFloorDb: number,
    audioTimeSeconds: number,
    nowMs: number
  ): TranslationSnapshot {
    const chunkLevelDb = rmsDb(input);
    const startThreshold = Math.max(-90, noiseFloorDb + 6);
    const endThreshold = Math.max(-94, noiseFloorDb + 3);
    const chunkDuration = input.length / sampleRate;

    if (!this.inBurst && chunkLevelDb > startThreshold) {
      this.inBurst = true;
      this.burstSamples = [];
      this.burstStartAt = audioTimeSeconds;
    }

    if (this.inBurst) {
      this.burstSamples.push(...input);
      const burstDuration = audioTimeSeconds - this.burstStartAt + chunkDuration;
      if ((chunkLevelDb < endThreshold && burstDuration > MIC_MIN_BURST_SECONDS) || burstDuration > MIC_MAX_BURST_SECONDS) {
        this.inBurst = false;
        const gapMs = this.lastBurstEndAt ? (this.burstStartAt - this.lastBurstEndAt) * 1000 : 0;
        this.lastBurstEndAt = audioTimeSeconds;
        const result = detectLetter(this.burstSamples, sampleRate);
        this.pair = `${result.low}/${result.high} Hz`;
        if (result.confidence > 0.3) {
          this.acceptLetter(result, gapMs);
        }
      }
    }

    if (!this.inBurst && this.decoded.trim().length > 0 && nowMs - this.lastDecodedAt > 1800) {
      this.finishCycle();
    }

    return this.snapshot();
  }

  reset(reason = 'decoded stream cleared'): TranslationSnapshot {
    this.inBurst = false;
    this.burstSamples = [];
    this.lastBurstEndAt = 0;
    this.decoded = '';
    this.finalMessage = '';
    this.stream = reason;
    this.pendingLetter = null;
    this.recentGaps = [];
    this.lastDecodedAt = 0;
    this.lastFinalText = '';
    this.pair = '--';
    return this.snapshot();
  }

  snapshot(): TranslationSnapshot {
    const message = this.displayMessage();
    const classified = classify(message, this.recentGaps);
    return {
      title: classified.title,
      verdict: classified.verdict,
      message: message || '---',
      stream: this.stream.slice(-96) || 'decoded message will appear here',
      pair: this.pair
    };
  }

  private acceptLetter(result: LetterDetection, gapMs: number): void {
    if (gapMs > CYCLE_BOUNDARY_GAP_MS && (this.decoded.trim().length > 0 || this.pendingLetter)) {
      this.finishCycle();
    } else {
      this.commitPending(gapMs);
    }
    this.pendingLetter = result;
  }

  private finishCycle(): void {
    this.commitPending(0);
    const finalText = this.decoded.trim();
    if (finalText) {
      const repeated = finalText === this.lastFinalText;
      this.lastFinalText = finalText;
      this.finalMessage = finalText;
      this.stream = repeated ? 'repeat signal detected' : 'message complete';
    }
    this.decoded = '';
    this.pendingLetter = null;
    this.recentGaps = [];
    this.lastBurstEndAt = 0;
  }

  private commitPending(gapMs: number): void {
    if (!this.pendingLetter) return;
    const byGap = gapToChar(gapMs);
    const expectedGap = gapForChar(this.pendingLetter.ch);
    const expectedErr = expectedGap === null || !gapMs ? 0 : Math.abs(expectedGap - gapMs);
    const shouldTrustGap = byGap && (expectedErr > 260 || this.pendingLetter.confidence < 0.45);
    const ch = shouldTrustGap ? byGap.ch : this.pendingLetter.ch;
    this.commitLetter(ch, gapMs);
    this.pendingLetter = null;
  }

  private commitLetter(ch: string, gapMs: number): void {
    if (ch === ' ' && this.decoded.endsWith(' ')) return;
    if (gapMs > 0) {
      this.recentGaps.push(gapMs);
      if (this.recentGaps.length > 12) this.recentGaps.shift();
    }
    this.decoded += ch;
    this.stream += ch;
    if (this.finalMessage && !this.finalMessage.startsWith(this.decoded.trim())) {
      this.finalMessage = '';
    }
    this.lastDecodedAt = performance.now();
    if (this.decoded.length > 120) this.decoded = this.decoded.slice(-120);
  }

  private displayMessage(): string {
    const current = this.decoded.trim();
    if (!this.finalMessage) return current;
    if (!current || this.finalMessage.startsWith(current)) return this.finalMessage;
    return current;
  }
}

function detectLetter(samples: number[], sampleRate: number): LetterDetection {
  const trimmed = trimBurst(samples);
  let bestLow = LOW_FREQS[0];
  let bestLowMag = 0;
  let bestHigh = HIGH_FREQS[0];
  let bestHighMag = 0;
  for (const frequency of LOW_FREQS) {
    const magnitude = goertzel(trimmed, sampleRate, frequency);
    if (magnitude > bestLowMag) {
      bestLow = frequency;
      bestLowMag = magnitude;
    }
  }
  for (const frequency of HIGH_FREQS) {
    const magnitude = goertzel(trimmed, sampleRate, frequency);
    if (magnitude > bestHighMag) {
      bestHigh = frequency;
      bestHighMag = magnitude;
    }
  }

  let best = { ch: '?', err: Infinity };
  for (const [ch, low, high] of CODEBOOK) {
    const err = Math.abs(low - bestLow) + Math.abs(high - bestHigh);
    if (err < best.err) best = { ch, err };
  }
  const confidence = Math.min(1, Math.max(0, (160 - best.err) / 160));
  return { ch: best.ch, confidence, low: bestLow, high: bestHigh };
}

function trimBurst(samples: number[]): number[] {
  let peak = 0;
  for (const sample of samples) peak = Math.max(peak, Math.abs(sample));
  if (peak <= 0) return samples;
  const threshold = peak * 0.18;
  let start = 0;
  let end = samples.length - 1;
  while (start < samples.length && Math.abs(samples[start]) < threshold) start += 1;
  while (end > start && Math.abs(samples[end]) < threshold) end -= 1;
  return samples.slice(Math.max(0, start - 64), Math.min(samples.length, end + 65));
}

function gapToChar(gapMs: number): { ch: string; err: number } | null {
  if (!gapMs || gapMs <= 0 || gapMs > 1300) return null;
  let best: { ch: string; err: number } | null = null;
  for (const [ch, , , gap] of CODEBOOK) {
    const err = Math.abs(gap - gapMs);
    if (!best || err < best.err) best = { ch, err };
  }
  if (!best) return null;
  const tolerance = best.ch === ' ' ? 180 : 135;
  return best.err <= tolerance ? best : null;
}

function gapForChar(ch: string): number | null {
  const row = CODEBOOK.find(([entry]) => entry === ch);
  return row ? row[3] : null;
}

function classify(text: string, gaps: number[]): Pick<TranslationSnapshot, 'title' | 'verdict'> {
  const clean = text.trim().replace(/\s+/g, ' ');
  if (isPeriodic(gaps)) return { title: 'Clock signal', verdict: 'DEAD' };
  if (!clean) return { title: 'Listening', verdict: 'DEAD' };
  if (clean.length <= 2) return { title: 'Signal fragments', verdict: 'CLOCK' };
  const compact = clean.replace(/ /g, '');
  for (const word of COMMON_WORDS) {
    if (word.length >= 3 && compact.includes(word)) {
      return { title: 'Language lock', verdict: 'ALIVE' };
    }
  }
  return { title: 'Structured signal', verdict: 'UNKNOWN' };
}

function isPeriodic(gaps: number[]): boolean {
  const usable = gaps.filter((gap) => gap > 80 && gap < 1300).slice(-5);
  if (usable.length < 3) return false;
  return Math.max(...usable) - Math.min(...usable) <= 90;
}
