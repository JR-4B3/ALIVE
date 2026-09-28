import { RATE, type Voice, type Match, features, identify } from './codec';

/** Incremental microphone decoder. It never receives the transmitted message. */
export class SoundVoiceDecoder {
  private input: number[] = [];
  private position = 0;
  private rate = 0;
  private block: number[] = [];
  private previous: number[] = [];
  private active: number[] | null = null;
  private quiet = 0;
  private overlong = false;
  private message = '';
  constructor(private voice: Voice, private floorDb = -48) {}

  process(samples: Float32Array, sampleRate: number): { message: string; matches: Match[] } {
    if (this.rate && sampleRate !== this.rate) throw Error('Microphone sample rate changed; restart the decoder.');
    if (!Number.isFinite(sampleRate) || sampleRate < RATE) throw Error('Microphone requires at least 16 kHz.');
    this.rate = sampleRate;
    const matches: Match[] = [];
    if (sampleRate === RATE) {
      for (const sample of samples) this.consume(sample, matches);
    } else {
      // Bandlimited streaming resampling; keep lookahead and phase across callbacks.
      // A short windowed-sinc filter avoids folding high frequency noise into templates.
      for (const sample of samples) this.input.push(sample);
      const radius = 24, cutoff = .46 * RATE / sampleRate, step = sampleRate / RATE;
      while (this.position + radius < this.input.length) {
        const center = Math.floor(this.position);
        let value = 0, weight = 0;
        for (let k = center - radius + 1; k <= center + radius; k++) {
          const delta = k - this.position;
          const sinc = Math.abs(delta) < 1e-9 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * delta) / (Math.PI * delta);
          const w = sinc * (.5 + .5 * Math.cos(Math.PI * delta / radius));
          value += (this.input[k] ?? 0) * w; weight += w;
        }
        this.consume(value / weight, matches); this.position += step;
      }
      const remove = Math.max(0, Math.floor(this.position) - radius);
      if (remove) { this.input.splice(0, remove); this.position -= remove; }
    }
    return { message: this.message, matches };
  }

  private consume(sample: number, matches: Match[]): void {
    this.block.push(sample);
    if (this.block.length < 160) return;
    const rms = Math.sqrt(this.block.reduce((sum, x) => sum + x * x, 0) / 160);
    if (rms > 10 ** (this.floorDb / 20)) {
      if (!this.active) this.active = [...this.previous];
      this.quiet = 0;
    } else if (this.active) this.quiet++;
    if (this.active) {
      if (this.active.length < RATE * 1.5) this.active.push(...this.block);
      else this.overlong = true;
      if (this.quiet >= 8) {
        // Keep 10 ms after the final active block, matching offline segmentation.
        const sound = this.active.slice(0, Math.max(0, this.active.length - 7 * 160));
        if (sound.length >= RATE * .1) {
          const match = this.overlong || sound.length > RATE * 1.4 ?
            { symbol: '?', nearest: '?', distance: 1, margin: 0 } : identify(features(Float32Array.from(sound)), this.voice);
          this.message = (this.message + match.symbol).slice(-100); matches.push(match);
        }
        this.active = null; this.quiet = 0; this.overlong = false;
      }
    }
    this.previous = this.block; this.block = [];
  }
}
