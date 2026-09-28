import { describe, expect, test } from 'bun:test';
import { compileVoice, decodeAudio, generateSounds, renderMessage, segmentAudio } from './codec';
import { DEFAULT_SYNTH, synthesize } from './synth';

function rms(samples: Float32Array): number {
  return Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
}

describe('studio synth', () => {
  test('attack, sustain, and release visibly change the envelope', () => {
    const quick = synthesize({ ...DEFAULT_SYNTH, attack: .01, release: .05 });
    const slow = synthesize({ ...DEFAULT_SYNTH, attack: .25, release: .35 });
    expect(rms(quick.slice(320, 640))).toBeGreaterThan(rms(slow.slice(320, 640)) * 2);
    expect(slow.length).toBeGreaterThan(quick.length);
    const low = synthesize({ ...DEFAULT_SYNTH, sustain: .1 });
    const high = synthesize({ ...DEFAULT_SYNTH, sustain: .9 });
    expect(rms(high.slice(4000, 4800))).toBeGreaterThan(rms(low.slice(4000, 4800)) * 3);
    expect(segmentAudio(slow)).toHaveLength(1);
  });

  test('waveform, pitch, and brightness alter the sound', () => {
    const plain = synthesize({ ...DEFAULT_SYNTH, waveform: 'sine', brightness: 0 });
    const rough = synthesize({ ...DEFAULT_SYNTH, waveform: 'saw', brightness: 1 });
    const higher = synthesize({ ...DEFAULT_SYNTH, pitchHz: 700 });
    expect(rms(plain.map((x, i) => x - rough[i]))).toBeGreaterThan(.08);
    expect(rms(plain.map((x, i) => x - higher[i]))).toBeGreaterThan(.08);
  });

  test('a synth sound produces a decodable alphabet', async () => {
    const voice = await compileVoice(generateSounds(synthesize(DEFAULT_SYNTH)), 'My sound');
    const decoded = decodeAudio(renderMessage(voice, 'WE ARE HERE'), voice).map(part => part.symbol).join('');
    expect(decoded).toBe('WE ARE HERE');
  });
});
