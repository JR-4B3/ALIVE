import { expect, test } from 'bun:test';
import { fileURLToPath } from 'node:url';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join as joinPath } from 'node:path';
import { renderBeacon, renderChirps, BEACON_RATE, beaconDuration, type Chirp } from './beacon';
import { BeaconDecoder } from '../sensing/beaconDecoder';

function resample(input: Float32Array, rate: number): Float32Array {
  const output = new Float32Array(Math.round(input.length * rate / BEACON_RATE));
  for (let i = 0; i < output.length; i++) {
    const position = i * BEACON_RATE / rate, index = Math.floor(position), fraction = position - index;
    output[i] = (input[index] ?? 0) * (1 - fraction) + (input[index + 1] ?? 0) * fraction;
  }
  return output;
}

function receive(input: Float32Array, rate = BEACON_RATE): string {
  const decoder = new BeaconDecoder();
  let result = decoder.beginCapture(0);
  for (let i = 0; i < input.length; i += 2048) result = decoder.process(input.subarray(i, i + 2048), rate);
  return result.message;
}

function noise(length: number, level: number, seed: number): Float32Array {
  const samples = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    samples[i] = level * (seed / 2147483648 - 1);
  }
  return samples;
}

const messages = ['HELLO', 'WE ARE HERE', 'I HEAR YOU', 'STAY CALM', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'ZYXWVUTSRQPONMLKJIHGFEDCBA', 'NQIM VRSW ABCD', 'EEEE', 'ZZZZ', 'A A'];

test('decodes every letter at 44.1 and 48 kHz, clean and in a quiet room with echo', () => {
  for (const rate of [44100, 48000]) for (const text of messages) {
    const clean = resample(renderBeacon(text), rate);
    expect(receive(clean, rate)).toBe(text);
    const hiss = noise(clean.length + rate, .00025, 721), room = new Float32Array(hiss.length);
    const echo = Math.round(rate * .07);
    for (let i = 0; i < room.length; i++) room[i] = .3 * (clean[i] ?? 0) + .06 * (clean[i - echo] ?? 0) + hiss[i];
    expect(receive(room, rate)).toBe(text);
  }
}, 60000);

// Real speaker-to-Scarlett chirps peaked near -80 dBFS with quieter edges.
test('decodes faint chirps', () => {
  for (const text of ['A A A', 'WE ARE HERE', 'ABCDEFGHIJKLM', 'NOPQRSTUVWXYZ']) {
    const clean = renderBeacon(text), hiss = noise(clean.length, .000004, 99);
    expect(receive(clean.map((sample, i) => sample * .0006 + hiss[i]))).toBe(text);
  }
});

// A hand-held phone moving at 0.3 m/s shifts 19 kHz by about 17 Hz.
test('tolerates hand-held Doppler shift', () => {
  for (const shift of [-17, 17]) {
    const clean = renderBeacon('WE ARE HERE'), shifted = new Float32Array(clean.length), ratio = 1 + shift / 19000;
    for (let i = 0; i < shifted.length; i++) {
      const position = i * ratio, index = Math.floor(position), fraction = position - index;
      shifted[i] = (clean[index] ?? 0) * (1 - fraction) + (clean[index + 1] ?? 0) * fraction;
    }
    expect(receive(shifted)).toBe('WE ARE HERE');
  }
});

test('rejects unframed chirps and broadband noise', () => {
  expect(receive(renderBeacon('HELLO').subarray(Math.round(1.43 * BEACON_RATE)))).toBe('---');
  expect(receive(noise(BEACON_RATE * 3, .025, 15))).toBe('---');
});

function receptions(input: Float32Array, rate = BEACON_RATE) {
  const decoder = new BeaconDecoder();
  decoder.beginCapture(0);
  const log = [], kinds = new Set<string>();
  for (let i = 0; i < input.length; i += 2048) {
    const snapshot = decoder.process(input.subarray(i, i + 2048), rate);
    if (snapshot.live) kinds.add(snapshot.live.kind);
    log.push(...decoder.takeCompleted());
  }
  return { log, kinds };
}

const pause = (seconds: number) => new Float32Array(Math.round(seconds * BEACON_RATE));
const join = (...parts: Float32Array[]) => {
  const output = new Float32Array(parts.reduce((n, part) => n + part.length, 0));
  let offset = 0; for (const part of parts) { output.set(part, offset); offset += part.length; }
  return output;
};
const clock = (symbol: number, periodMs: number, ticks: number) =>
  renderChirps(Array.from({ length: ticks }, (): Chirp => [symbol, periodMs - 360]));

test('tells a clock, noise, and a message apart, in the order they arrive', () => {
  const noiseChirps: Chirp[] = [[3, 400], [17, 180], [3, 900], [25, 250], [8, 600]];
  const { log } = receptions(join(clock(10, 1200, 8), pause(3), renderChirps(noiseChirps), pause(3),
    renderBeacon('IS ANYONE THERE'), pause(3), clock(26, 900, 6), pause(3)));
  expect(log).toEqual([
    { kind: 'clock', text: 'KKKKKKKK' },
    { kind: 'noise', text: 'DRDZI' },
    { kind: 'intelligent', text: 'IS ANYONE THERE' },
    { kind: 'clock', text: '      ' }
  ]);
});

test('a clock at the slowest period stays one reception', () => {
  const { log } = receptions(join(clock(4, 1600, 6), pause(3)));
  expect(log).toEqual([{ kind: 'clock', text: 'EEEEEE' }]);
});

test('one channel at an uneven pace is noise, not a clock', () => {
  const { log } = receptions(join(renderChirps([[5, 400], [5, 900], [5, 300], [5, 700]]), pause(3)));
  expect(log).toEqual([{ kind: 'noise', text: 'FFFF' }]);
});

test('unframed chirps never count as a message', () => {
  const { log, kinds } = receptions(join(renderChirps([[7, 180], [4, 180], [11, 180], [11, 180], [14, 180]]), pause(3)));
  expect(kinds.has('intelligent')).toBe(false);
  expect(log).toEqual([{ kind: 'noise', text: 'HELLO' }]);
});

test('decodes a 40-character reply', () => {
  const text = 'WE ARE THE LAST LIGHT OF AURORA AND WE A';
  expect(text.length).toBe(40);
  expect(receive(renderBeacon(text))).toBe(text);
});

test('duration matches the rendered samples and the API', () => {
  expect(renderBeacon('HELLO').length / BEACON_RATE).toBeCloseTo(beaconDuration('HELLO'), 8);
  // reply_engine.signal_duration_seconds('HI') in test_reply_engine.py.
  expect(beaconDuration('HI')).toBeCloseTo(3.53, 8);
});

// Runs the firmware oscillator on the host and compares every sample.
test.skipIf(!Bun.which('g++'))('firmware samples equal the browser renderer', () => {
  const header = fileURLToPath(new URL('../../../firmware/esp32_i2s_emitter/include/beacon_voice.h', import.meta.url));
  const dir = mkdtempSync(joinPath(tmpdir(), 'alive-beacon-'));
  const source = joinPath(dir, 'native.cpp'), binary = joinPath(dir, 'native');
  Bun.spawnSync(['sh', '-c', `cat > ${source}`], { stdin: new TextEncoder().encode(`#include <cstdio>
#include "${header}"
void silence(int n){int16_t zero=0;for(int i=0;i<n;i++)fwrite(&zero,2,1,stdout);}
void pulse(int symbol){beacon::Voice voice;voice.reset(symbol);for(uint32_t i=0;i<beacon::frames;i++){int16_t value=voice.next();fwrite(&value,2,1,stdout);}}
int main(){silence(7200);pulse(-1);silence(8640);pulse(-1);silence(13440);for(char ch: "HELLO"){if(!ch)break;pulse(beacon::symbolFor(ch));silence(8640);}pulse(-1);silence(36480);}
`) });
  const compiled = Bun.spawnSync(['g++', '-std=c++17', '-O2', source, '-o', binary]);
  expect(new TextDecoder().decode(compiled.stderr)).toBe('');
  const native = Bun.spawnSync([binary]).stdout;
  const pcm = new DataView(native.buffer, native.byteOffset, native.byteLength);
  const rendered = renderBeacon('HELLO');
  expect(pcm.byteLength).toBe(rendered.length * 2);
  let differences = 0;
  for (let i = 0; i < rendered.length; i++) if (rendered[i] * 32768 !== pcm.getInt16(i * 2, true)) differences++;
  expect(differences).toBe(0);
});
