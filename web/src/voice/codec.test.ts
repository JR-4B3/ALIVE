import { describe, expect, test } from 'bun:test';
import { RATE, LETTERS, compileVoice, generateSounds, demoSource, renderMessage, decodeAudio, features,
  pcmDecode, identify, validateVoice, confusionReport, characterErrors, stamp, segmentAudio } from './codec';

const voice = await compileVoice(generateSounds(demoSource()), 'Test voice');
function decoded(samples: Float32Array): string { return decodeAudio(samples, voice).map(s => s.symbol).join(''); }
function degraded(samples: Float32Array): Float32Array {
  let seed = 123;
  return samples.map((x, i) => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return x * .13 + (i > 320 ? samples[i - 320] * .018 : 0) + .001 * (seed / 2147483648 - 1);
  });
}
describe('designed acoustic voice', () => {
  test('all 27 generated sounds remain distinct without legacy carriers', () => {
    expect(confusionReport(voice).failures).toEqual([]);
    for (const ch of LETTERS) expect(identify(features(pcmDecode(voice.symbols[ch])), voice).symbol).toBe(ch);
  });
  test('decodes complete messages from samples, including spaces and repeats', () => {
    for (const message of ['WE ARE HERE', 'HELLO', 'AAA ZZ', 'ABCDEFGHIJKLM', 'NOPQRSTUVWXYZ']) {
      expect(decoded(renderMessage(voice, message))).toBe(message);
    }
  });
  test('survives reduced gain, low noise and a short reflection in a synthetic test', () => {
    expect(decoded(degraded(renderMessage(voice, 'WE ARE HERE')))).toBe('WE ARE HERE');
  });
  test('silence and unrelated noise do not become a message', () => {
    expect(decoded(new Float32Array(RATE))).toBe('');
    let seed = 7;
    const noise = Float32Array.from({ length: RATE * 3 }, () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return (seed / 2147483648 - 1) * .1;
    });
    expect(decoded(noise)).toBe('?');
    const burst = noise.slice(0, 6000);
    expect(decoded(burst)).toBe('?');
  });
  test('ambiguous codebooks reject the sound instead of choosing a forced label', () => {
    const copy = structuredClone(voice); copy.symbols.B = structuredClone(copy.symbols.A);
    expect(identify(features(pcmDecode(copy.symbols.A)), copy).symbol).toBe('?');
    expect(confusionReport(copy).failures).toContain('A');
  });
  test('validates integrity and structure of imported packages', async () => {
    expect((await validateVoice(JSON.parse(JSON.stringify(voice)))).id).toBe(voice.id);
    const tampered = structuredClone(voice); tampered.name = 'Changed';
    expect(validateVoice(tampered)).rejects.toThrow('version ID');
    const malformed = structuredClone(voice); malformed.symbols.A.templates[0][0][0] = NaN;
    expect(validateVoice(malformed)).rejects.toThrow('template');
    const truncated = structuredClone(voice); truncated.symbols.A.pcm = '';
    expect(validateVoice(truncated)).rejects.toThrow();
  });
  test('calibration revisions change ID and retain original playback samples', async () => {
    const revised = structuredClone(voice);
    revised.symbols.A.templates.push(features(degraded(pcmDecode(voice.symbols.A))));
    const stamped = await stamp(revised);
    expect(stamped.id).not.toBe(voice.id); expect(stamped.symbols.A.pcm).toBe(voice.symbols.A.pcm);
    expect(voice.symbols.A.templates).toHaveLength(1);
  });
  test('counts substitutions, deletions, insertions and false positives', () => {
    expect(characterErrors('HELLO', 'HE?O')).toBe(2);
    expect(characterErrors('', 'ALIEN')).toBe(5);
    expect(characterErrors('AAA', 'AA')).toBe(1);
  });
  test('requires a complete usable alphabet and bounds transmission duration', async () => {
    expect(compileVoice({}, 'bad')).rejects.toThrow();
    expect(compileVoice(Object.fromEntries([...LETTERS].map(c => [c, new Float32Array(RATE)])), 'silent')).rejects.toThrow('silent');
    expect(() => renderMessage(voice, '123')).toThrow();
    expect(() => renderMessage(voice, 'A'.repeat(21))).toThrow();
    const long = structuredClone(voice);
    for (const c of LETTERS) { long.symbols[c].samples = RATE * 1.2; long.symbols[c].pcm = btoa('\0'.repeat(RATE * 1.2 * 2)); }
    long.gapSeconds = .6;
    expect(() => renderMessage(long, 'A'.repeat(20))).toThrow('30 seconds');
  });
  test('segments the last sound even when the file has no trailing silence', () => {
    expect(segmentAudio(pcmDecode(voice.symbols.A))).toHaveLength(1);
  });
});

describe('streaming microphone decoding', () => {
  test('matches offline decoding across callback sizes and microphone sample rates', async () => {
    const { SoundVoiceDecoder } = await import('./streamingDecoder');
    const audio = renderMessage(voice, 'HELLO A');
    for (const rate of [16000, 44100, 48000]) {
      const input = Float32Array.from({ length: Math.ceil(audio.length * rate / RATE) }, (_, i) => {
        const p = i * RATE / rate, lo = Math.floor(p), hi = lo + 1;
        return (audio[lo] ?? 0) * (hi - p) + (audio[hi] ?? 0) * (p - lo);
      });
      for (const chunk of [1024, 2048]) {
        const decoder = new SoundVoiceDecoder(voice); let message = '';
        for (let i = 0; i < input.length; i += chunk) message = decoder.process(input.subarray(i, i + chunk), rate).message;
        expect(message).toBe('HELLO A');
      }
    }
  });
});

test('capture WAV fingerprints survive a PCM decode/re-encode roundtrip', async () => {
  const { encodeVoiceRecording } = await import('./recording');
  const original = encodeVoiceRecording(renderMessage(voice, 'HELLO'), RATE), view = new DataView(original);
  const samples = Float32Array.from({ length: (original.byteLength - 44) / 2 }, (_, i) => view.getInt16(44 + i * 2, true) / 32768);
  expect(new Uint8Array(encodeVoiceRecording(samples, RATE))).toEqual(new Uint8Array(original));
});

describe('reviewed recording calibration', () => {
  test('creates an immutable revision and rejects training/evaluation overlap', async () => {
    const { calibrateVoice } = await import('./codec');
    const samples = pcmDecode(voice.symbols.H).map((x, i) => x * .2 + Math.sin(i * 1.4) * .0005);
    const examples = [{ label: 'H', segment: { start: 0, end: samples.length / RATE, samples } }];
    const id = 'a'.repeat(64), next = await calibrateVoice(voice, id, examples);
    expect(next.id).not.toBe(voice.id);
    expect(next.symbols.H.templates.length).toBe(2);
    expect(voice.symbols.H.templates.length).toBe(1);
    expect(next.symbols.H.pcm).toBe(voice.symbols.H.pcm);
    expect((await validateVoice(next)).id).toBe(next.id);
    expect(calibrateVoice(next, id, examples)).rejects.toThrow('already represented');
    expect(calibrateVoice(voice, id, examples, [id])).rejects.toThrow('Evaluation');
    expect(calibrateVoice(voice, id, [{ ...examples[0], label: '' }])).rejects.toThrow('at least one');
    expect(calibrateVoice(voice, id, [{ ...examples[0], label: 'HELLO' }])).rejects.toThrow('one letter');
  });
  test('rejects malformed calibration provenance in imported packages', async () => {
    const malformed = structuredClone(voice);
    malformed.calibration = [null as never];
    expect(validateVoice(malformed)).rejects.toThrow('calibration history');
  });
  test('short seed padding does not split each generated symbol into separate sounds', async () => {
    const short = Float32Array.from({ length: Math.round(RATE * .125) }, (_, i) => .5 * Math.sin(2 * Math.PI * 930 * i / RATE));
    const generated = await compileVoice(generateSounds(short), 'Short seed');
    const segments = decodeAudio(renderMessage(generated, 'HELLO'), generated);
    expect(segments.length).toBe(5);
  });
});
