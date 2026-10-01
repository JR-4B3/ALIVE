// Silent verification only. No AudioContext destination, USB writes, or speaker API requests.
import { fileURLToPath } from 'node:url';
import { renderBeacon, BEACON_RATE, beaconDuration } from '../audio/beacon';
import { encodeRecording } from '../audio/recording';
import { SignalReceiver } from '../sensing/signalReceiver';
import { TranslationDecoder } from '../sensing/translationDecoder';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const artifact = `${root}.tmp/beacon-silent-verification`;
const results: Record<string, unknown>[] = [];
function record(result: Record<string, unknown>) { results.push(result); }
function join(parts: Float32Array[]): Float32Array {
  const samples = new Float32Array(parts.reduce((n, part) => n + part.length, 0));
  let at = 0; for (const part of parts) { samples.set(part, at); at += part.length; }
  return samples;
}
function resample(input: Float32Array, rate: number): Float32Array {
  const output = new Float32Array(Math.round(input.length * rate / BEACON_RATE));
  for (let i = 0; i < output.length; i++) {
    const position = i * BEACON_RATE / rate, index = Math.floor(position), fraction = position - index;
    output[i] = (input[index] ?? 0) * (1 - fraction) + (input[index + 1] ?? 0) * fraction;
  }
  return output;
}
function receive(input: Float32Array, rate: number, decoder: SignalReceiver | TranslationDecoder = new SignalReceiver()): string {
  decoder.beginCapture(0);
  let result = decoder.snapshot();
  for (let i = 0; i < input.length; i += 2048) {
    result = decoder.process(input.subarray(i, i + 2048), rate, -40, -70, i / rate, i / rate * 1700);
  }
  return result.message;
}
function legacyAudio(text: string): Float32Array {
  const parts: Float32Array[] = [new Float32Array(12000)];
  for (const char of text) {
    const index = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ '.indexOf(char);
    const low = 400 + Math.floor(index / 4) * 100, high = 2000 + index % 4 * 300;
    const tone = new Float32Array(10560);
    for (let i = 0; i < tone.length; i++) {
      const fade = Math.min(1, i / 1152, (tone.length - i - 1) / 1152);
      tone[i] = .04 * fade * (.53 * Math.sin(2 * Math.PI * low * i / 48000) + .47 * Math.sin(2 * Math.PI * high * i / 48000));
    }
    const gap = Math.max(.22, (char === ' ' ? 1600 : 100 + index * 50) * .00065);
    parts.push(tone, new Float32Array(Math.round(gap * 48000)));
  }
  parts.push(new Float32Array(96000));
  return join(parts);
}
const messages = ['HELLO', 'WE ARE HERE', 'I HEAR YOU', 'STAY CALM', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'ZYXWVUTSRQPONMLKJIHGFEDCBA', 'NQIM VRSW ABCD', 'EEEE', 'ZZZZ', 'A A'];
for (const rate of [16000, 44100, 48000]) for (const text of messages) {
  const clean = resample(renderBeacon(text), rate);
  for (const condition of ['clean', 'quiet room']) {
    let input = clean;
    if (condition !== 'clean') {
      input = new Float32Array(clean.length + rate);
      let seed = 721;
      for (let i = 0; i < input.length; i++) {
        seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
        input[i] = .3 * (clean[i] ?? 0) + .06 * (clean[i - Math.round(rate * .07)] ?? 0) + .00025 * (seed / 2147483648 - 1);
      }
    }
    const decoded = receive(input, rate);
    record({ kind: 'Beacon PCM', rate, condition, expected: text, decoded, pass: decoded === text });
  }
}
for (const text of ['HELLO', 'WE ARE HERE', 'EEEE', 'AEI', 'NQIM VRSW ABCD']) {
  const samples = legacyAudio(text);
  const before = receive(samples, 48000, new TranslationDecoder());
  const decoded = receive(samples, 48000);
  record({ kind: 'legacy preserved', expected: text, before, decoded, pass: decoded === text && before === decoded });
}
for (const [parts, expected] of [
  [[legacyAudio('HELLO'), renderBeacon('STAY CALM')], 'STAY CALM'],
  [[renderBeacon('STAY CALM'), legacyAudio('HELLO')], 'HELLO'],
  [[renderBeacon('HELLO'), renderBeacon('STAY CALM')], 'STAY CALM']
] as [Float32Array[], string][]) {
  const decoded = receive(join(parts), 48000);
  record({ kind: 'automatic protocol switching', expected, decoded, pass: decoded === expected });
}
const orphaned = renderBeacon('HELLO').subarray(Math.round(1.43 * BEACON_RATE));
record({ kind: 'reject unframed chirps', pass: receive(orphaned, 48000) === '---' });
const noise = new Float32Array(48000 * 3);
let seed = 15;
for (let i = 0; i < noise.length; i++) { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; noise[i] = .025 * (seed / 2147483648 - 1); }
record({ kind: 'reject broadband noise', pass: receive(noise, 48000) === '---' });

// Execute the firmware oscillator on the host and compare every sample with the browser renderer.
const cpp = `#include <cstdio>
#include "${root}firmware/esp32_i2s_emitter/include/prototype/beacon_voice.h"
void silence(int n){int16_t zero=0;for(int i=0;i<n;i++)fwrite(&zero,2,1,stdout);}
void pulse(int symbol){beacon::Voice voice;voice.reset(symbol);for(uint32_t i=0;i<beacon::frames;i++){int16_t value=voice.next();fwrite(&value,2,1,stdout);}}
int main(){silence(7200);pulse(-1);silence(8640);pulse(-1);silence(13440);for(char ch: "HELLO"){if(!ch)break;pulse(beacon::symbolFor(ch));silence(8640);}pulse(-1);silence(36480);}
`;
await Bun.write(`${artifact}/native.cpp`, cpp);
const compiled = Bun.spawnSync(['g++', '-std=c++17', '-O2', `${artifact}/native.cpp`, '-o', `${artifact}/native`]);
if (compiled.exitCode) throw Error(new TextDecoder().decode(compiled.stderr));
const native = Bun.spawnSync([`${artifact}/native`]);
if (native.exitCode) throw Error('Native PCM generation failed');
const pcm = new DataView(native.stdout.buffer, native.stdout.byteOffset, native.stdout.byteLength);
const rendered = renderBeacon('HELLO');
let differences = Math.abs(rendered.length - pcm.byteLength / 2), peak = 0;
for (let i = 0; i < rendered.length; i++) {
  if (i * 2 >= pcm.byteLength || rendered[i] * 32768 !== pcm.getInt16(i * 2, true)) differences++;
  peak = Math.max(peak, Math.abs(rendered[i]));
}
record({ kind: 'firmware PCM matches browser PCM', samples: rendered.length, differences, pass: differences === 0 });
record({ kind: 'duration matches samples', expected: beaconDuration('HELLO'), seconds: rendered.length / BEACON_RATE,
  pass: Math.abs(beaconDuration('HELLO') - rendered.length / BEACON_RATE) < 1e-8 });
const nativeSamples = new Float32Array(pcm.byteLength / 2);
for (let i = 0; i < nativeSamples.length; i++) nativeSamples[i] = pcm.getInt16(i * 2, true) / 32768;
const nativeDecoded = receive(nativeSamples, 48000);
record({ kind: 'decode firmware PCM', expected: 'HELLO', decoded: nativeDecoded, pass: nativeDecoded === 'HELLO' });
await Bun.write(`${artifact}/beacon-HELLO.wav`, encodeRecording([nativeSamples], BEACON_RATE));
const report = { cases: results.length, failures: results.filter(result => !result.pass).length, peak,
  chirpCentersHz: { sync: 550, firstLetter: 680, lastLetter: 1780, space: 1824 },
  limits: 'Generated PCM and simulated noise/echo only. No speaker playback or microphone round-trip test.', results };
await Bun.write(`${artifact}/report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify({ cases: report.cases, failures: report.failures, peak, artifact }));
if (report.failures) process.exit(1);
