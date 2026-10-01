import { TranslationDecoder } from './translationDecoder';
import { BeaconDecoder } from './beaconDecoder';
import type { TranslationSnapshot } from '../types';

// Detect the protocol from audio. Switching needs no expected message or API data.
export class SignalReceiver {
  private legacy = new TranslationDecoder();
  private beacon = new BeaconDecoder();
  private selected: 'legacy' | 'beacon' = 'legacy';
  reset(reason?: string): TranslationSnapshot {
    this.selected = 'legacy'; this.beacon.reset(reason); return this.legacy.reset(reason);
  }
  beginCapture(nowMs: number): TranslationSnapshot {
    this.selected = 'legacy'; this.beacon.beginCapture(nowMs); return this.legacy.beginCapture(nowMs);
  }
  setCaptureDuration(nowMs: number, seconds: number): void { this.legacy.setCaptureDuration(nowMs, seconds); }
  snapshot(): TranslationSnapshot { return this.selected === 'beacon' ? this.beacon.snapshot() : this.legacy.snapshot(); }
  process(input: Float32Array, rate: number, levelDb: number, floorDb: number, audioTime: number, nowMs: number): TranslationSnapshot {
    const wasReceiving = this.beacon.receiving;
    const beacon = this.beacon.process(input, rate);
    if (this.beacon.receiving || wasReceiving) {
      this.selected = 'beacon'; this.legacy.reset(); return beacon;
    }
    const legacy = this.legacy.process(input, rate, levelDb, floorDb, audioTime, nowMs);
    if (legacy.message !== '---' && this.selected === 'beacon') {
      this.selected = 'legacy'; this.beacon.reset();
    }
    return this.selected === 'beacon' ? beacon : legacy;
  }
}
