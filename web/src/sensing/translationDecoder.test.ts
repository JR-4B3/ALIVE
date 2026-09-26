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

function noisyTone(low: number, high: number, amplitude = 0.006): Float32Array {
  const signal = tone(low, high, 0.22, amplitude);
  const background = noise(0.22, 0.008);
  for (let i = 0; i < signal.length; i += 1) signal[i] += background[i];
  return signal;
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

function decode(samples: Float32Array, noiseFloorDb: number, sampleRate = SAMPLE_RATE): string {
  const decoder = new TranslationDecoder();
  let message = '---';
  for (let i = 0; i < samples.length; i += 2048) {
    const snapshot = decoder.process(samples.slice(i, i + 2048), sampleRate, -40, noiseFloorDb, i / sampleRate, i / sampleRate * 1000);
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

  test('keeps letters from one playback together despite missed tones', () => {
    const decoder = new TranslationDecoder();
    decoder.beginCapture(0);
    const signal = concat(
      noise(0.3, 0.008), tone(800, 2300, 0.22, 0.035),
      noise(2.2, 0.008), tone(900, 2000, 0.22, 0.035), noise(0.4, 0.008)
    );
    let sawFirstLetter = false;
    let finalMessage = '---';
    for (let i = 0; i < signal.length; i += 2048) {
      const snapshot = decoder.process(signal.slice(i, i + 2048), SAMPLE_RATE, -40, -50,
        i / SAMPLE_RATE, i / SAMPLE_RATE * 1000);
      sawFirstLetter ||= snapshot.message === 'R';
      finalMessage = snapshot.message;
    }
    expect(sawFirstLetter).toBe(true);
    expect(finalMessage).toBe('RU');
  });

  test('accepts a short clean burst without accepting broadband noise', () => {
    expect(decode(concat(noise(0.3, 0.008), tone(400, 2000, 0.15, 0.035), noise(0.4, 0.008)), -50)).toBe('A');
  });

  test('decodes low volume carriers over steady microphone noise', () => {
    expect(decode(concat(noise(0.3, 0.008), noisyTone(800, 2300), noise(0.3, 0.008)), -45)).toBe('R');
  });

  test('recovers a distant dual tone below the overall room level', () => {
    const quiet = noisyTone(800, 2300, 0.0025);
    expect(decode(concat(noise(0.3, 0.008), quiet, noise(0.3, 0.008)), -45)).toBe('R');
  });

  test('keeps a quiet two-letter reply together', () => {
    expect(decode(concat(
      noise(0.3, 0.008), noisyTone(800, 2300, 0.0025), noise(0.6175, 0.008),
      noisyTone(900, 2000, 0.0025), noise(0.3, 0.008)
    ), -45)).toBe('RU');
  });

  test('decodes when the speaker attenuates one carrier and room rumble is louder', () => {
    const signal = noise(0.22, 0.001);
    for (let i = 0; i < signal.length; i += 1) {
      const t = i / SAMPLE_RATE;
      signal[i] += 0.0015 * Math.sin(2 * Math.PI * 500 * t) +
        0.018 * Math.sin(2 * Math.PI * 2900 * t) +
        0.04 * Math.sin(2 * Math.PI * 140 * t);
    }
    expect(decode(concat(noise(0.3, 0.001), signal, noise(0.3, 0.001)), -30)).toBe('H');
  });

  test('a changing harmonic inside one burst does not add another letter', () => {
    const signal = concat(noise(0.3, 0.001),
      tone(500, 2000, 0.15), tone(1000, 2000, 0.07), noise(0.3, 0.001));
    expect(decode(signal, -50)).toBe('E');
  });

  test('does not invent the missing carrier from noise around a single tone', () => {
    for (const frequency of [400, 500, 600, 700, 800, 900, 1000, 2000, 2300, 2600, 2900]) {
      const signal = noise(0.22, 0.008);
      for (let i = 0; i < signal.length; i += 1) {
        signal[i] += 0.02 * Math.sin(2 * Math.PI * frequency * i / SAMPLE_RATE);
      }
      expect(decode(concat(noise(0.3, 0.008), signal, noise(0.3, 0.008)), -45)).toBe('---');
    }
  });

  test('preserves repeated letters separated by the shortest emitter gap', () => {
    expect(decode(concat(noise(0.3, 0.001), tone(400, 2000),
      noise(0.09, 0.001), tone(400, 2000), noise(0.3, 0.001)), -50)).toBe('AA');
  });

  test('suppresses a delayed R echo while preserving a real second R', () => {
    expect(decode(concat(noise(0.3, 0.001), tone(800, 2300),
      noise(0.09, 0.001), tone(800, 2300, 0.15, 0.02), noise(0.3775, 0.001),
      tone(800, 2300), noise(0.4, 0.001)), -50)).toBe('RR');
  });

  test('uses the encoded gap to recover E when its second harmonic sounds like Y', () => {
    expect(decode(concat(noise(0.3, 0.001), tone(1000, 2000),
      noise(0.195, 0.001), tone(400, 2000), noise(0.4, 0.001)), -50)).toBe('EA');
  });

  test('preserves a genuine Y with its own encoded gap', () => {
    expect(decode(concat(noise(0.3, 0.001), tone(1000, 2000),
      noise(0.845, 0.001), tone(400, 2000), noise(0.4, 0.001)), -50)).toBe('YA');
  });

  test('uses sample timing even when microphone callbacks arrive late', () => {
    const signal = concat(noise(0.3, 0.001), tone(1000, 2000),
      noise(0.195, 0.001), tone(400, 2000), noise(0.4, 0.001));
    const decoder = new TranslationDecoder();
    let message = '---';
    for (let i = 0; i < signal.length; i += 2048) {
      const delayedTime = i / SAMPLE_RATE + (i > SAMPLE_RATE * 0.6 ? 0.25 : 0);
      message = decoder.process(signal.slice(i, i + 2048), SAMPLE_RATE,
        -40, -50, delayedTime, delayedTime * 1000).message;
    }
    expect(message).toBe('EA');
  });

  for (const rate of [44100, 48000]) {
    test(`receives I HEAR YOU with speaker rolloff and room noise at ${rate} Hz`, () => {
      const parts = [new Float32Array(Math.round(rate * 0.173))];
      for (const ch of 'I HEAR YOU') {
        const index = ch === ' ' ? 26 : ch.charCodeAt(0) - 65;
        const low = 400 + Math.floor(index / 4) * 100;
        const high = 2000 + index % 4 * 300;
        const samples = new Float32Array(Math.round(rate * 0.22));
        for (let i = 0; i < samples.length; i += 1) {
          const envelope = Math.min(1, i / (rate * 0.005), (samples.length - i) / (rate * 0.005));
          samples[i] = envelope * (0.0015 * Math.sin(2 * Math.PI * low * i / rate) +
            0.018 * Math.sin(2 * Math.PI * high * i / rate));
        }
        const gap = ch === ' ' ? 1.04 : Math.max(0.09, (100 + index * 50) * 0.00065);
        parts.push(samples, new Float32Array(Math.round(rate * gap)));
      }
      parts.push(new Float32Array(Math.round(rate * 0.4)));
      const signal = concat(...parts);
      let seed = 87654321;
      for (let i = 0; i < signal.length; i += 1) {
        seed = (1664525 * seed + 1013904223) >>> 0;
        signal[i] += 0.004 * (seed / 2147483648 - 1) + 0.02 * Math.sin(2 * Math.PI * 140 * i / rate);
      }
      expect(decode(signal, -35, rate)).toBe('I HEAR YOU');
    });
  }
});

// Firmware waveform through a deterministic two-reflection room model.
function beaconWithEcho(text: string, minGap: number, rate: number, distortion = false): Float32Array {
  const parts = [new Float32Array(Math.round(rate * 0.25))];
  for (const ch of text) {
    const index = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ '.indexOf(ch);
    const low = 400 + Math.floor(index / 4) * 100;
    const high = 2000 + index % 4 * 300;
    const signal = new Float32Array(Math.round(rate * 0.22));
    for (let i = 0; i < signal.length; i++) {
      const envelope = Math.min(1, i / (rate * 0.024), (signal.length - i) / (rate * 0.024));
      signal[i] = envelope * (0.008 * Math.sin(2 * Math.PI * low * i / rate) +
        0.025 * Math.sin(2 * Math.PI * high * i / rate));
      const intermodulation = high - 2 * low;
      if (distortion && intermodulation >= 400 && intermodulation <= 1000) {
        signal[i] += envelope * 0.011 * Math.sin(2 * Math.PI * intermodulation * i / rate);
      }
    }
    const gap = ch === ' ' ? 1.04 : Math.max(minGap, (100 + index * 50) * 0.00065);
    parts.push(signal, new Float32Array(Math.round(rate * gap)));
  }
  parts.push(new Float32Array(rate));
  const dry = concat(...parts);
  const wet = dry.slice();
  for (const [seconds, gain] of [[0.06, 0.55], [0.12, 0.25]]) {
    const delay = Math.round(rate * seconds);
    for (let i = delay; i < wet.length; i++) wet[i] += dry[i - delay] * gain;
  }
  return wet;
}

for (const rate of [44100, 48000]) {
  for (const message of ['STAY CALM', 'WE ARE HERE', 'I AM HERE', 'I HEAR YOU', 'HELLO']) {
    test(`separates ${message} through room reflections at ${rate} Hz`, () => {
      expect(decode(beaconWithEcho(message, 0.22, rate), -50, rate)).toBe(message);
    });
  }
}

// A real fundamental must survive a stronger speaker-generated second harmonic,
// including the final letter where no following gap can correct the choice.
test('recognizes a final E with a stronger second harmonic', () => {
  const signal = tone(500, 2000, 0.22, 0.03);
  const harmonic = tone(1000, 2000, 0.22, 0.06);
  for (let i = 0; i < signal.length; i++) signal[i] += harmonic[i];
  expect(decode(concat(noise(0.25, 0.001), signal, noise(1, 0.001)), -50)).toBe('E');
});

test('recognizes A when its 800 Hz harmonic is stronger than 400 Hz', () => {
  const signal = tone(400, 2000, 0.22, 0.03);
  const harmonic = tone(800, 2000, 0.22, 0.06);
  for (let i = 0; i < signal.length; i++) signal[i] += harmonic[i];
  expect(decode(concat(noise(0.25, 0.001), signal, noise(1, 0.001)), -50)).toBe('A');
});

test('keeps a genuine final Y despite weak energy at 500 Hz', () => {
  const signal = tone(1000, 2000, 0.22, 0.06);
  const background = tone(500, 2000, 0.22, 0.001);
  for (let i = 0; i < signal.length; i++) signal[i] += background[i];
  expect(decode(concat(noise(0.25, 0.001), signal, noise(1, 0.001)), -50)).toBe('Y');
});

test('recognizes N with a strong competing 900 Hz tone', () => {
  const signal = tone(700, 2300, 0.22, 0.012);
  for (let i = 0; i < signal.length; i++) {
    signal[i] += 0.012 * 0.48 * 0.75 * Math.sin(2 * Math.PI * 900 * i / SAMPLE_RATE);
  }
  expect(decode(concat(noise(0.25, 0.001), signal, noise(0.5, 0.001)), -50)).toBe('N');
});

for (const rate of [44100, 48000]) {
  for (const message of ['ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'ZYXWVUTSRQPONMLKJIHGFEDCBA', 'NQIM VRSW ABCD']) {
    test(`uses tone and rhythm for arbitrary symbols with stronger distortion at ${rate} Hz: ${message}`, () => {
      expect(decode(beaconWithEcho(message, 0.22, rate, true), -50, rate)).toBe(message);
    });
  }
}
