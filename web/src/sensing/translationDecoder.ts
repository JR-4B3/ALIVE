import { goertzel, rmsDb } from '../audio/dsp';
import type { TranslationSnapshot } from '../types';

const LOW_FREQS = [400, 500, 600, 700, 800, 900, 1000];
const HIGH_FREQS = [2000, 2300, 2600, 2900];
// A 93 ms window at 44.1 kHz separates adjacent low carriers much more
// reliably than the old 46 ms window, even when the phone is farther away.
const FRAME_SAMPLES = 4096;
const FRAME_HOP = 1024;
const MIN_EVIDENCE_SECONDS = 0.065;
const RELEASE_SECONDS = 0.045;
const CYCLE_BOUNDARY_GAP_MS = 1400;

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ';

interface TonePair {
  ch: string;
  low: number;
  high: number;
  strength: number;
  confidence: number;
}

export class TranslationDecoder {
  private frame = new Float32Array(FRAME_SAMPLES);
  private frameFill = 0;
  private processedSamples = 0;
  private candidate: TonePair | null = null;
  private votes = new Map<string, { pair: TonePair; score: number; frames: number }>();
  private burstStartAt = 0;
  private burstLastAt = 0;
  private burstPeak = 0;
  private releaseFrames = 0;
  private lastBurstEndAt = 0;
  private lastLetterStartAt: number | null = null;
  private lastLetter = '';
  private decoded = '';
  private finalMessage = '';
  private stream = '';
  private recentGaps: number[] = [];
  private lastDecodedAt = 0;
  private lastFinalText = '';
  private pair = '--';
  private captureUntilMs = 0;

  beginCapture(nowMs: number): TranslationSnapshot {
    this.reset('listening for signal');
    this.captureUntilMs = nowMs + 20000;
    return this.snapshot();
  }

  setCaptureDuration(nowMs: number, durationSeconds: number): void {
    if (Number.isFinite(durationSeconds) && durationSeconds > 0) {
      this.captureUntilMs = nowMs + Math.min(durationSeconds, 20) * 1000 + 2000;
    }
  }

  process(
    input: Float32Array,
    sampleRate: number,
    _levelDb: number,
    noiseFloorDb: number,
    _audioTimeSeconds: number,
    nowMs: number
  ): TranslationSnapshot {
    for (let i = 0; i < input.length; i += 1) {
      this.frame[this.frameFill++] = input[i];
      if (this.frameFill === FRAME_SAMPLES) {
        // Callback delivery on a busy phone can be uneven; protocol timing
        // comes from recorded samples, never the callback's wall clock.
        const endAt = (this.processedSamples + i + 1) / sampleRate;
        this.processFrame(this.frame, sampleRate, noiseFloorDb, endAt, nowMs);
        this.frame.copyWithin(0, FRAME_HOP);
        this.frameFill = FRAME_SAMPLES - FRAME_HOP;
      }
    }
    this.processedSamples += input.length;
    if (nowMs >= this.captureUntilMs && !this.candidate && this.decoded.trim() && nowMs - this.lastDecodedAt > 1800) {
      this.finishCycle();
    }
    return this.snapshot();
  }

  reset(reason = 'decoded stream cleared'): TranslationSnapshot {
    this.frameFill = 0;
    this.processedSamples = 0;
    this.candidate = null;
    this.votes.clear();
    this.burstStartAt = 0;
    this.burstLastAt = 0;
    this.burstPeak = 0;
    this.releaseFrames = 0;
    this.lastBurstEndAt = 0;
    this.lastLetterStartAt = null;
    this.lastLetter = '';
    this.decoded = '';
    this.finalMessage = '';
    this.stream = reason;
    this.recentGaps = [];
    this.lastDecodedAt = 0;
    this.lastFinalText = '';
    this.pair = '--';
    this.captureUntilMs = 0;
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
    // Vote over the whole burst. A changing harmonic or a reflection within
    // one tone must not become an extra letter. A quiet gap ends the burst.
    if (!detected || (this.candidate && detected.strength < this.burstPeak * 0.12)) {
      if (!this.candidate) return;
      this.releaseFrames += 1;
      if (this.releaseFrames * FRAME_HOP / sampleRate >= RELEASE_SECONDS) {
        this.finishBurst(this.burstLastAt, nowMs, sampleRate);
      }
      return;
    }
    if (!this.candidate) this.burstStartAt = endAt - FRAME_SAMPLES / sampleRate;
    this.candidate = detected;
    this.pair = `${detected.low}/${detected.high} Hz`;
    this.burstLastAt = endAt;
    this.burstPeak = Math.max(this.burstPeak, detected.strength);
    this.releaseFrames = 0;
    const vote = this.votes.get(detected.ch) ?? { pair: detected, score: 0, frames: 0 };
    vote.score += detected.confidence;
    vote.frames += 1;
    this.votes.set(detected.ch, vote);
  }

  private finishBurst(endAt: number, nowMs: number, sampleRate: number): void {
    const winner = [...this.votes.values()].sort((a, b) => b.score - a.score)[0];
    if (winner && winner.frames * FRAME_HOP / sampleRate >= MIN_EVIDENCE_SECONDS &&
        endAt - this.burstStartAt < 0.55) {
      const separation = this.lastLetterStartAt === null ? Infinity : this.burstStartAt - this.lastLetterStartAt;
      // The emitter sends 220 ms of sound followed by at least 90 ms of
      // silence. A fragment/echo arriving sooner cannot be another letter.
      const duplicate = separation < 0.265 || (winner.pair.ch === this.lastLetter &&
        separation < letterInterval(this.lastLetter) - 0.12);
      if (!duplicate) {
        const gapMs = this.lastBurstEndAt ? (this.burstStartAt - this.lastBurstEndAt) * 1000 : 0;
        if (nowMs >= this.captureUntilMs && gapMs > CYCLE_BOUNDARY_GAP_MS && this.decoded.trim()) this.finishCycle();
        this.correctOctaveFromTiming(separation);
        this.commitLetter(winner.pair.ch, gapMs, nowMs);
        this.pair = `${winner.pair.low}/${winner.pair.high} Hz`;
        this.lastBurstEndAt = endAt;
        this.lastLetterStartAt = this.burstStartAt;
        this.lastLetter = winner.pair.ch;
      }
    }
    this.candidate = null;
    this.votes.clear();
    this.burstPeak = 0;
    this.releaseFrames = 0;
  }

  private correctOctaveFromTiming(separation: number): void {
    if (!this.decoded || !Number.isFinite(separation)) return;
    const index = LETTERS.indexOf(this.lastLetter);
    const low = LOW_FREQS[Math.floor(index / 4)];
    // The gaps also encode the letter. Use that independent evidence only
    // for a plausible doubled fundamental (e.g. E's 500 Hz heard as Y's
    // 1000 Hz), and only when it clearly contradicts the spectral choice.
    const fundamentalIndex = LOW_FREQS.indexOf(low / 2);
    if (fundamentalIndex < 0) return;
    const corrected = LETTERS[fundamentalIndex * 4 + index % 4];
    if (Math.abs(separation - letterInterval(corrected)) < 0.10 &&
        Math.abs(separation - letterInterval(this.lastLetter)) > 0.25) {
      this.decoded = this.decoded.slice(0, -1) + corrected;
      this.stream = this.stream.slice(0, -1) + corrected;
      this.lastLetter = corrected;
    }
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
    this.lastLetterStartAt = null;
    this.lastLetter = '';
    this.captureUntilMs = 0;
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

function letterInterval(ch: string): number {
  const index = LETTERS.indexOf(ch);
  return 0.22 + (ch === ' ' ? 1.04 : Math.max(0.09, (100 + index * 50) * 0.00065));
}

function detectTonePair(samples: Float32Array, sampleRate: number, _noiseFloorDb: number): TonePair | null {
  const levelDb = rmsDb(samples);
  // A quiet dual tone can sit below the room's overall RMS level; the spectral
  // checks below decide whether it is a real signal.
  if (levelDb < -90) return null;
  let low = rankedPeaks(samples, sampleRate, LOW_FREQS);
  // Small speakers can make the second harmonic stronger than its fundamental.
  // Require measurable fundamental energy; never infer it from an octave alone.
  const fundamental = low.frequency / 2;
  if (LOW_FREQS.includes(fundamental)) {
    const energy = goertzel(samples, sampleRate, fundamental);
    if (energy >= low.best * 0.2 &&
        energy >= localNoise(samples, sampleRate, fundamental) * 5) {
      const competitors = LOW_FREQS.filter(f => f !== fundamental && f !== low.frequency);
      low = { frequency: fundamental, best: energy,
        second: rankedPeaks(samples, sampleRate, competitors).best };
    }
  }
  const high = rankedPeaks(samples, sampleRate, HIGH_FREQS);
  // Judge each carrier against nearby noise, independently. A small speaker
  // and phone mic can attenuate the low carrier much more than the high one.
  const lowNoise = localNoise(samples, sampleRate, low.frequency);
  const highNoise = localNoise(samples, sampleRate, high.frequency);
  if (low.best < lowNoise * 2.5 || high.best < highNoise * 2.5) return null;
  if (low.best < low.second * 1.5 || high.best < high.second * 1.5) return null;
  const lowIndex = LOW_FREQS.indexOf(low.frequency);
  const highIndex = HIGH_FREQS.indexOf(high.frequency);
  const ch = LETTERS[lowIndex * HIGH_FREQS.length + highIndex];
  return ch ? {
    ch, low: low.frequency, high: high.frequency,
    strength: Math.sqrt(low.best * high.best),
    confidence: Math.min(10, low.best / lowNoise, high.best / highNoise)
  } : null;
}

function localNoise(samples: Float32Array, sampleRate: number, frequency: number): number {
  return Math.max(1e-7,
    goertzel(samples, sampleRate, frequency - 45),
    goertzel(samples, sampleRate, frequency + 45));
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
