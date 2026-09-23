import { describe, expect, test } from 'bun:test';
import { TranslationDecoder } from './translationDecoder';

const SAMPLE_RATE = 44100;

function tone(low: number, high: number, seconds = 0.22, amplitude = 0.12): Float32Array {
  const samples = new Float32Array(Math.round(seconds * SAMPLE_RATE));
  for (let i = 0; i < samples.length; i += 1) {
    const edge = Math.min(1, i / (0.024 * SAMPLE_RATE), (samples.length - i) / (0.024 * SAMPLE_RATE));
    samples[i] = amplitude * edge * (
      0.48 * Math.sin(2 * Math.PI * low * i / SAMPLE_RATE) +
      0.42 * Math.sin(2 * Math.PI * high * i / SAMPLE_RATE)
    );
  }
  return samples;
}

function noise(seconds: number, amplitude = 0.025): Float32Array {
  const samples = new Float32Array(Math.round(seconds * SAMPLE_RATE));
  let seed = 1234567;
  for (let i = 0; i < samples.length; i += 1) {
    seed = (1664525 * seed + 1013904223) >>> 0;
    samples[i] = amplitude * (seed / 2147483648 - 1);
  }
  return samples;
}

function concat(...parts: Float32Array[]): Float32Array {
  const samples = new Float32Array(parts.reduce((length, part) => length + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    samples.set(part, offset);
    offset += part.length;
  }
  return samples;
}

function decode(samples: Float32Array, noiseFloorDb: number): string {
  const decoder = new TranslationDecoder();
  let message = '---';
  for (let i = 0; i < samples.length; i += 2048) {
    const snapshot = decoder.process(samples.slice(i, i + 2048), SAMPLE_RATE, -40, noiseFloorDb, i / SAMPLE_RATE, i / SAMPLE_RATE * 1000);
    message = snapshot.message;
  }
  return message;
}

describe('microphone tone decoding', () => {
  test('ignores broadband noise and a single tone', () => {
    expect(decode(noise(4, 0.05), -55)).toBe('---');
    const single = tone(400, 2000);
    for (let i = 0; i < single.length; i += 1) single[i] = Math.sin(2 * Math.PI * 400 * i / SAMPLE_RATE) * 0.12;
    expect(decode(concat(noise(0.3), single, noise(0.5)), -55)).toBe('---');
  });

  test('decodes consecutive soft dual tones at reduced volume', () => {
    const signal = concat(
      noise(0.4, 0.008), tone(400, 2000, 0.22, 0.035), noise(0.09, 0.008),
      tone(500, 2000, 0.22, 0.035), noise(0.09, 0.008),
      tone(600, 2000, 0.22, 0.035), noise(0.5, 0.008)
    );
    expect(decode(signal, -50)).toBe('AEI');
  });
});
