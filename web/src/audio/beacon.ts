import { sine, envelope } from './beaconTables';

export const BEACON_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ';
export const BEACON_RATE = 48000;
const FRAMES = 17280;

// Near-ultrasound chirps for phone microphones at 44.1 or 48 kHz. The ESP32
// header firmware/esp32_i2s_emitter/include/beacon_voice.h mirrors these values.
export const SYNC_HZ = 18200;
export const FIRST_LETTER_HZ = 18450;
export const SPACING_HZ = 64;
// The sweep is narrower than half the spacing, which leaves room for hand-held Doppler.
const SWEEP_HZ = 24;
const AMPLITUDE = 6000;

export function beaconFrequency(symbol: number): number {
  return symbol < 0 ? SYNC_HZ : FIRST_LETTER_HZ + symbol * SPACING_HZ;
}

// This is the exact integer oscillator used on the ESP32, including quantization.
export function beaconPulse(symbol: number): Float32Array<ArrayBuffer> {
  const samples = new Float32Array(FRAMES);
  const stepDelta = Math.floor(2 * SWEEP_HZ * 2 ** 32 / (FRAMES * BEACON_RATE));
  let phase = 0;
  let step = Math.floor((beaconFrequency(symbol) + SWEEP_HZ) * 2 ** 32 / BEACON_RATE);
  for (let frame = 0; frame < FRAMES; frame++) {
    const index = phase >>> 22, fraction = (phase >>> 12) & 1023;
    const wave = (sine[index] * (1024 - fraction) + sine[index + 1] * fraction) >> 10;
    const shaped = (wave * envelope[Math.floor(frame * 1024 / FRAMES)]) >> 15;
    samples[frame] = ((shaped * AMPLITUDE) >> 15) / 32768;
    phase = (phase + step) >>> 0;
    step -= stepDelta;
  }
  return samples;
}

// Matches signal_duration_seconds() in reply_engine.py.
export function beaconDuration(message: string): number {
  return 2.45 + message.length * .54;
}

// [symbol, silence after it in ms], as in signals.py on the API.
export type Chirp = [symbol: number, gapMs: number];

// Two sync chirps, one chirp per character, and a closing sync chirp. A
// sealed message has a third opening sync chirp; its text is already sealed.
export function messageChirps(message: string, sealed = false): Chirp[] {
  const text = message.toUpperCase().replace(/[^A-Z ]/g, '').trim();
  const open: Chirp[] = sealed ? [[-1, 180], [-1, 180], [-1, 280]] : [[-1, 180], [-1, 280]];
  return [...open, ...[...text].map((char): Chirp => [BEACON_ALPHABET.indexOf(char), 180]), [-1, 760]];
}

// Reference rendering of what the ESP32 plays, used by the tests.
export function renderChirps(chirps: Chirp[], leadMs = 0): Float32Array<ArrayBuffer> {
  const parts: Float32Array[] = [];
  const silence = (ms: number) => parts.push(new Float32Array(Math.round(ms * BEACON_RATE / 1000)));
  silence(leadMs);
  for (const [symbol, gapMs] of chirps) { parts.push(beaconPulse(symbol)); silence(gapMs); }
  const output = new Float32Array(parts.reduce((n, part) => n + part.length, 0));
  let offset = 0; for (const part of parts) { output.set(part, offset); offset += part.length; }
  return output;
}

export function renderBeacon(message: string): Float32Array<ArrayBuffer> {
  return renderChirps(messageChirps(message), 150);
}
