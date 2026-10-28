import { goertzel, rmsDb } from '../audio/dsp';
import { BEACON_ALPHABET, SYNC_HZ, beaconFrequency } from '../audio/beacon';
import type { Reception, ReceptionKind, TranslationSnapshot } from '../types';

// Speakers and microphones lose level near 20 kHz, so the decoder accepts weak
// chirps. In a speaker-to-Scarlett test the edges of each chirp measured 2e-6.
const MIN_ENERGY = .0000015;
// Unframed chirps further apart than this belong to separate receptions. The
// slowest clock leaves 1.24 s between chirps; the API leaves 3 s between signals.
const RAW_END_SECONDS = 2;

// A single-carrier chirp decoder. No text or reply metadata enters it: what a
// reception is, it judges from the sound alone.
export class BeaconDecoder {
  private frame = new Float32Array(4096);
  private fill = 0;
  private processed = 0;
  private hop = 1024;
  private votes = new Map<number, number>();
  private evidence = 0;
  private quiet = 0;
  private peak = 0;
  private burstStart = 0;
  private burstEnd = 0;
  private firstSync: number | null = null;
  private locked = false;
  private sealed = false;
  private text = '';
  private finalText = '';
  private lastLetterAt = -Infinity;
  private lastLetterStartAt = -Infinity;
  // Unframed chirps in progress: their symbols and start times.
  private raw: { symbol: number; start: number }[] = [];
  private rawEnd = 0;
  private lastKind: ReceptionKind | null = null;
  private completed: Reception[] = [];
  private pair = '--';
  private stream = 'listening for signal';

  reset(reason = 'decoded stream cleared'): TranslationSnapshot {
    this.fill = this.processed = this.evidence = this.quiet = this.peak = 0;
    this.votes.clear(); this.firstSync = null; this.locked = this.sealed = false;
    this.text = this.finalText = ''; this.lastLetterAt = this.lastLetterStartAt = -Infinity;
    this.raw = []; this.rawEnd = 0; this.lastKind = null; this.completed = [];
    this.pair = '--'; this.stream = reason;
    return this.snapshot();
  }
  beginCapture(_nowMs: number): TranslationSnapshot { return this.reset('listening for signal'); }
  get receiving(): boolean { return this.locked || this.raw.length > 0; }
  get active(): boolean { return this.locked || !!this.text || !!this.finalText; }

  // Receptions completed since the last call, oldest first.
  takeCompleted(): Reception[] {
    const completed = this.completed;
    this.completed = [];
    return completed;
  }

  snapshot(): TranslationSnapshot {
    const live = this.live();
    const kind = live?.kind ?? this.lastKind;
    return { title: live ? 'Receiving' : 'Listening',
      verdict: kind === 'intelligent' ? 'ALIVE' : kind === 'clock' ? 'CLOCK' : kind === 'noise' ? 'NOISE' : 'DEAD',
      message: this.text.trim() || this.finalText || '---', live, stream: this.stream, pair: this.pair };
  }

  private live(): Reception | null {
    if (this.locked) return this.message(this.text);
    if (!this.raw.length) return null;
    return { kind: this.rawKind(3), text: this.rawText() };
  }

  process(input: Float32Array, sampleRate: number): TranslationSnapshot {
    const size = 2 ** Math.round(Math.log2(sampleRate * .085));
    if (this.frame.length !== size) { this.frame = new Float32Array(size); this.hop = size / 4; this.fill = 0; }
    for (let i = 0; i < input.length; i++) {
      this.frame[this.fill++] = input[i];
      if (this.fill === size) {
        const time = (this.processed + i + 1) / sampleRate;
        this.processFrame(sampleRate, time);
        this.frame.copyWithin(0, this.hop); this.fill -= this.hop;
      }
    }
    this.processed += input.length;
    return this.snapshot();
  }

  private processFrame(rate: number, time: number): void {
    const detected = this.detect(rate);
    if (!detected || (this.peak && detected.energy < this.peak * .10)) {
      if (this.evidence) {
        this.quiet += this.hop / rate;
        if (this.quiet >= .065) this.finishBurst();
      }
      if (this.locked && time - this.lastLetterAt > 1.4 && this.text) this.finishMessage();
      if (this.raw.length && !this.evidence && time - this.rawEnd > RAW_END_SECONDS) this.finishRaw();
      return;
    }
    if (!this.evidence) this.burstStart = time - this.frame.length / rate;
    this.evidence += this.hop / rate;
    this.burstEnd = time; this.quiet = 0;
    this.peak = Math.max(this.peak, detected.energy);
    // The middle of the chirp has the greatest energy. Edge glides may enter
    // neighboring bands, so vote by energy rather than by counting frames.
    this.votes.set(detected.symbol, (this.votes.get(detected.symbol) ?? 0) + detected.energy ** 2);
  }

  private detect(rate: number): { symbol: number; energy: number } | null {
    if (rmsDb(this.frame) < -94) return null;
    let symbol = -1, best = 0, second = 0;
    for (let candidate = -1; candidate < BEACON_ALPHABET.length; candidate++) {
      const energy = goertzel(this.frame, rate, beaconFrequency(candidate));
      if (energy > best) { second = best; best = energy; symbol = candidate; }
      else second = Math.max(second, energy);
    }
    if (best < MIN_ENERGY || best < second * 1.35) return null;
    const frequency = beaconFrequency(symbol);
    const noise = Math.max(1e-7, goertzel(this.frame, rate, frequency - 110), goertzel(this.frame, rate, frequency + 110));
    if (best < noise * 4) return null;
    return { symbol, energy: best };
  }

  private finishBurst(): void {
    const winner = [...this.votes].sort((a, b) => b[1] - a[1])[0]?.[0];
    const duration = this.burstEnd - this.burstStart;
    if (winner !== undefined && this.evidence >= .10 && duration >= .14 && duration < .56) {
      if (winner === -1) {
        // A third sync chirp right after the pair marks a sealed message.
        if (this.locked && !this.text && !this.sealed && this.burstStart - this.lastLetterAt < .5) {
          this.sealed = true; this.lastLetterAt = this.burstEnd; this.stream = 'sealed signal acquired';
        } else if (this.locked) this.finishMessage();
        else if (this.firstSync !== null && this.burstStart - this.firstSync >= .38 && this.burstStart - this.firstSync < .72) {
          if (this.raw.length) this.finishRaw();
          this.locked = true; this.sealed = false; this.text = ''; this.firstSync = null; this.lastLetterStartAt = -Infinity;
          this.lastLetterAt = this.burstEnd; this.stream = 'ultrasound signal acquired';
        } else this.firstSync = this.burstStart;
        this.pair = `${SYNC_HZ} Hz`;
      } else if (this.locked) {
        if (this.burstStart - this.lastLetterStartAt > .36) {
          this.text += BEACON_ALPHABET[winner];
          this.lastLetterAt = this.burstEnd; this.lastLetterStartAt = this.burstStart;
          this.pair = `${beaconFrequency(winner)} Hz`;
          this.stream = this.text;
        }
      } else if (this.burstStart - (this.raw.at(-1)?.start ?? -Infinity) > .36) {
        this.raw.push({ symbol: winner, start: this.burstStart });
        this.rawEnd = this.burstEnd;
        this.pair = `${beaconFrequency(winner)} Hz`;
        this.stream = this.rawText();
      }
    }
    this.votes.clear(); this.evidence = this.quiet = this.peak = 0;
  }

  private finishMessage(): void {
    this.finalText = this.text.trim(); this.locked = false; this.firstSync = null;
    this.stream = 'message complete';
    if (this.finalText) this.complete(this.message(this.finalText));
    this.sealed = false;
  }

  private message(text: string): Reception {
    return this.sealed ? { kind: 'intelligent', text, sealed: true } : { kind: 'intelligent', text };
  }

  private finishRaw(): void {
    // A lone chirp is too little to log; it is most likely a stray sound.
    if (this.raw.length > 1) this.complete({ kind: this.rawKind(4), text: this.rawText() });
    this.raw = [];
  }

  private complete(reception: Reception): void {
    this.completed.push(reception);
    this.lastKind = reception.kind;
  }

  private rawText(): string {
    return this.raw.map(({ symbol }) => BEACON_ALPHABET[symbol]).join('');
  }

  // A clock repeats one channel at a period that varies by under 10 percent.
  private rawKind(minimumTicks: number): ReceptionKind {
    const raw = this.raw;
    if (raw.length < minimumTicks || raw.some(({ symbol }) => symbol !== raw[0].symbol)) return 'noise';
    const periods = raw.slice(1).map(({ start }, i) => start - raw[i].start).sort((a, b) => a - b);
    const median = periods[periods.length >> 1];
    return periods.every((period) => Math.abs(period - median) < median * .1) ? 'clock' : 'noise';
  }
}
