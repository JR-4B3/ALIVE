import { goertzel, rmsDb } from '../audio/dsp';
import { BEACON_ALPHABET, BEACON_SYNC_HZ, beaconFrequency } from '../audio/beacon';
import type { TranslationSnapshot } from '../types';

// A framed, single-carrier chirp decoder. No text or reply metadata enters it.
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
  private text = '';
  private finalText = '';
  private lastLetterAt = -Infinity;
  private lastLetterStartAt = -Infinity;
  private pair = '--';
  private stream = 'listening for signal';

  reset(reason = 'decoded stream cleared'): TranslationSnapshot {
    this.fill = this.processed = this.evidence = this.quiet = this.peak = 0;
    this.votes.clear(); this.firstSync = null; this.locked = false;
    this.text = this.finalText = ''; this.lastLetterAt = this.lastLetterStartAt = -Infinity;
    this.pair = '--'; this.stream = reason;
    return this.snapshot();
  }
  beginCapture(_nowMs: number): TranslationSnapshot { return this.reset('listening for signal'); }
  setCaptureDuration(_nowMs: number, _seconds: number): void {}
  get receiving(): boolean { return this.locked; }
  get active(): boolean { return this.locked || !!this.text || !!this.finalText; }

  snapshot(): TranslationSnapshot {
    const message = this.text.trim() || this.finalText;
    return { title: message ? 'Language lock' : this.locked ? 'Receiving' : 'Listening',
      verdict: message ? 'ALIVE' : 'DEAD', message: message || '---', stream: this.stream,
      pair: this.pair };
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
    if (best < .000006 || best < second * 1.35) return null;
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
        if (this.locked) this.finishMessage();
        else if (this.firstSync !== null && this.burstStart - this.firstSync >= .38 && this.burstStart - this.firstSync < .72) {
          this.locked = true; this.text = ''; this.firstSync = null; this.lastLetterStartAt = -Infinity;
          this.lastLetterAt = this.burstEnd; this.stream = 'Beacon signal acquired';
        } else this.firstSync = this.burstStart;
        this.pair = `${BEACON_SYNC_HZ} Hz`;
      } else if (this.locked && this.burstStart - this.lastLetterStartAt > .36) {
        this.text += BEACON_ALPHABET[winner];
        this.lastLetterAt = this.burstEnd; this.lastLetterStartAt = this.burstStart;
        this.pair = `${beaconFrequency(winner)} Hz`;
        this.stream = this.text;
      }
    }
    this.votes.clear(); this.evidence = this.quiet = this.peak = 0;
  }
  private finishMessage(): void {
    this.finalText = this.text.trim(); this.locked = false; this.firstSync = null;
    this.stream = 'message complete';
  }
}
