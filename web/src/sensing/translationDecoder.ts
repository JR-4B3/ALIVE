import { goertzel, rmsDb } from '../audio/dsp';
import type { TranslationSnapshot } from '../types';

const LOW_FREQS = [400, 500, 600, 700, 800, 900, 1000];
const HIGH_FREQS = [2000, 2300, 2600, 2900];
const FRAME_SAMPLES = 2048;
const MIN_STABLE_FRAMES = 4;
const RELEASE_FRAMES = 2;
const CYCLE_BOUNDARY_GAP_MS = 1400;

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ';

interface TonePair {
  ch: string;
  low: number;
  high: number;
}

export class TranslationDecoder {
  private frame = new Float32Array(FRAME_SAMPLES);
  private frameFill = 0;
  private candidate: TonePair | null = null;
  private candidateFrames = 0;
  private releaseFrames = 0;
  private lastBurstEndAt = 0;
  private decoded = '';
  private finalMessage = '';
  private stream = '';
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
    for (let i = 0; i < input.length; i += 1) {
      this.frame[this.frameFill++] = input[i];
      if (this.frameFill === FRAME_SAMPLES) {
        const endAt = audioTimeSeconds + (i + 1) / sampleRate;
        this.processFrame(this.frame, sampleRate, noiseFloorDb, endAt, nowMs);
        this.frameFill = 0;
      }
    }
    if (!this.candidate && this.decoded.trim() && nowMs - this.lastDecodedAt > 1800) {
      this.finishCycle();
    }
    return this.snapshot();
  }

  reset(reason = 'decoded stream cleared'): TranslationSnapshot {
    this.frameFill = 0;
    this.candidate = null;
    this.candidateFrames = 0;
    this.releaseFrames = 0;
    this.lastBurstEndAt = 0;
    this.decoded = '';
    this.finalMessage = '';
    this.stream = reason;
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

  private processFrame(frame: Float32Array, sampleRate: number, noiseFloorDb: number, endAt: number, nowMs: number): void {
    const detected = detectTonePair(frame, sampleRate, noiseFloorDb);
    if (detected && detected.ch === this.candidate?.ch) {
      this.candidateFrames += 1;
      this.releaseFrames = 0;
      return;
    }
    if (this.candidate && (!detected || detected.ch !== this.candidate.ch)) {
      this.releaseFrames += 1;
      if (this.releaseFrames < RELEASE_FRAMES) return;
      this.finishBurst(endAt - (RELEASE_FRAMES * FRAME_SAMPLES) / sampleRate, nowMs, sampleRate);
    }
    if (detected) {
      this.candidate = detected;
      this.candidateFrames = 1;
      this.releaseFrames = 0;
    }
  }

  private finishBurst(endAt: number, nowMs: number, sampleRate: number): void {
    if (this.candidate && this.candidateFrames >= MIN_STABLE_FRAMES) {
      const startAt = endAt - (this.candidateFrames * FRAME_SAMPLES) / sampleRate;
      const gapMs = this.lastBurstEndAt ? (startAt - this.lastBurstEndAt) * 1000 : 0;
      if (gapMs > CYCLE_BOUNDARY_GAP_MS && this.decoded.trim()) this.finishCycle();
      this.commitLetter(this.candidate.ch, gapMs, nowMs);
      this.pair = `${this.candidate.low}/${this.candidate.high} Hz`;
      this.lastBurstEndAt = endAt;
    }
    this.candidate = null;
    this.candidateFrames = 0;
    this.releaseFrames = 0;
  }

  private finishCycle(): void {
    const finalText = this.decoded.trim();
    if (finalText) {
      const repeated = finalText === this.lastFinalText;
      this.lastFinalText = finalText;
      this.finalMessage = finalText;
      this.stream = repeated ? 'repeat signal detected' : 'message complete';
    }
    this.decoded = '';
    this.recentGaps = [];
    this.lastBurstEndAt = 0;
  }

  private commitLetter(ch: string, gapMs: number, nowMs: number): void {
    if (ch === ' ' && this.decoded.endsWith(' ')) return;
    if (gapMs > 0 && gapMs < CYCLE_BOUNDARY_GAP_MS) {
      this.recentGaps.push(gapMs);
      if (this.recentGaps.length > 12) this.recentGaps.shift();
    }
    this.decoded += ch;
    this.stream += ch;
    if (this.finalMessage && !this.finalMessage.startsWith(this.decoded.trim())) this.finalMessage = '';
    this.lastDecodedAt = nowMs;
    if (this.decoded.length > 120) this.decoded = this.decoded.slice(-120);
  }

  private displayMessage(): string {
    const current = this.decoded.trim();
    if (!this.finalMessage) return current;
    if (!current || this.finalMessage.startsWith(current)) return this.finalMessage;
    return current;
  }
}

function detectTonePair(samples: Float32Array, sampleRate: number, noiseFloorDb: number): TonePair | null {
  const levelDb = rmsDb(samples);
  if (levelDb < Math.max(-78, noiseFloorDb + 1.5)) return null;
  const low = rankedPeaks(samples, sampleRate, LOW_FREQS);
  const high = rankedPeaks(samples, sampleRate, HIGH_FREQS);
  const rms = 10 ** (levelDb / 20);
  // Both carriers must stand out from the rest of the sound and from adjacent code frequencies.
  if (low.best < rms * 0.12 || high.best < rms * 0.10) return null;
  if (low.best < low.second * 1.55 || high.best < high.second * 1.65) return null;
  if (low.best / high.best < 0.28 || high.best / low.best < 0.28) return null;
  const lowIndex = LOW_FREQS.indexOf(low.frequency);
  const highIndex = HIGH_FREQS.indexOf(high.frequency);
  const ch = LETTERS[lowIndex * HIGH_FREQS.length + highIndex];
  return ch ? { ch, low: low.frequency, high: high.frequency } : null;
}

function rankedPeaks(samples: Float32Array, sampleRate: number, frequencies: number[]): { frequency: number; best: number; second: number } {
  let frequency = frequencies[0];
  let best = 0;
  let second = 0;
  for (const current of frequencies) {
    const magnitude = goertzel(samples, sampleRate, current);
    if (magnitude > best) {
      second = best;
      best = magnitude;
      frequency = current;
    } else if (magnitude > second) {
      second = magnitude;
    }
  }
  return { frequency, best, second };
}

function classify(text: string, gaps: number[]): Pick<TranslationSnapshot, 'title' | 'verdict'> {
  const clean = text.trim().replace(/\s+/g, ' ');
  if (isPeriodic(gaps)) return { title: 'Clock signal', verdict: 'DEAD' };
  if (!clean) return { title: 'Listening', verdict: 'DEAD' };
  if (clean.length <= 2) return { title: 'Signal fragments', verdict: 'CLOCK' };
  return { title: 'Language lock', verdict: 'ALIVE' };
}

function isPeriodic(gaps: number[]): boolean {
  const usable = gaps.filter((gap) => gap > 80 && gap < 1300).slice(-5);
  if (usable.length < 3) return false;
  return Math.max(...usable) - Math.min(...usable) <= 90;
}
