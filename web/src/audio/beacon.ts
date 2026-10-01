import { sine, envelope } from './beaconTables';

export const BEACON_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ';
export const BEACON_RATE = 48000;
export const BEACON_PULSE_SECONDS = .36;
export const BEACON_GAP_SECONDS = .18;
export const BEACON_SYNC_HZ = 550;
export const BEACON_AMPLITUDE = 520;
export const BEACON_SWEEP_HZ = 36;
const FRAMES = 17280;
const STEP_DELTA = Math.floor(2 * BEACON_SWEEP_HZ * 2 ** 32 / (FRAMES * BEACON_RATE));

export function beaconFrequency(symbol: number): number {
  return symbol < 0 ? BEACON_SYNC_HZ : 680 + symbol * 44;
}

// This is the exact integer oscillator used on the ESP32, including quantization.
export function beaconPulse(symbol: number): Float32Array<ArrayBuffer> {
  const samples = new Float32Array(FRAMES);
  let phase = 0;
  let step = Math.floor((beaconFrequency(symbol) + BEACON_SWEEP_HZ) * 2 ** 32 / BEACON_RATE);
  for (let frame = 0; frame < FRAMES; frame++) {
    const index = phase >>> 22, fraction = (phase >>> 12) & 1023;
    const wave = (sine[index] * (1024 - fraction) + sine[index + 1] * fraction) >> 10;
    const shaped = (wave * envelope[Math.floor(frame * 1024 / FRAMES)]) >> 15;
    samples[frame] = ((shaped * BEACON_AMPLITUDE) >> 15) / 32768;
    phase = (phase + step) >>> 0;
    step -= STEP_DELTA;
  }
  return samples;
}

export function beaconDuration(message: string): number {
  return 2.45 + message.length * .54;
}

export function renderBeacon(message: string): Float32Array<ArrayBuffer> {
  const text = message.toUpperCase().replace(/[^A-Z ]/g, '').trim();
  const parts: Float32Array[] = [];
  const silence = (seconds: number) => parts.push(new Float32Array(Math.round(seconds * BEACON_RATE)));
  silence(.15);
  parts.push(beaconPulse(-1)); silence(.18);
  parts.push(beaconPulse(-1)); silence(.28);
  for (const char of text) { parts.push(beaconPulse(BEACON_ALPHABET.indexOf(char))); silence(.18); }
  parts.push(beaconPulse(-1)); silence(.76);
  const output = new Float32Array(parts.reduce((n, part) => n + part.length, 0));
  let offset = 0; for (const part of parts) { output.set(part, offset); offset += part.length; }
  return output;
}
