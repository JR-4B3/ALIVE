import { RATE } from './codec';

export type Waveform = 'sine' | 'triangle' | 'saw' | 'pulse';

export interface SynthSettings {
  waveform: Waveform;
  pitchHz: number;
  brightness: number;
  attack: number;
  decay: number;
  sustain: number;
  release: number;
}

export const DEFAULT_SYNTH: SynthSettings = {
  waveform: 'triangle', pitchHz: 390, brightness: .55,
  attack: .06, decay: .12, sustain: .55, release: .18
};

export function synthesize(settings: SynthSettings): Float32Array {
  const { waveform, pitchHz, brightness, attack, decay, sustain, release } = settings;
  if (!['sine', 'triangle', 'saw', 'pulse'].includes(waveform) ||
      ![pitchHz, brightness, attack, decay, sustain, release].every(Number.isFinite) ||
      pitchHz < 180 || pitchHz > 1200 || brightness < 0 || brightness > 1 ||
      attack < .005 || attack > .3 || decay < .01 || decay > .3 ||
      sustain < 0 || sustain > 1 || release < .02 || release > .4) throw Error('Invalid synth setting.');

  const hold = .16;
  const releaseAt = attack + decay + hold;
  const length = Math.round((releaseAt + release) * RATE);
  const samples = new Float32Array(length);
  let phase = 0;
  for (let i = 0; i < length; i++) {
    const t = i / RATE;
    const envelope = t < attack ? t / attack :
      t < attack + decay ? 1 + (sustain - 1) * (t - attack) / decay :
      t < releaseAt ? sustain : sustain * Math.max(0, 1 - (t - releaseAt) / release);
    // A slight continuous drift gives the source some life without a note sequence.
    const drift = 1 + .012 * Math.sin(2 * Math.PI * 2.8 * t);
    phase += 2 * Math.PI * pitchHz * drift / RATE;
    let body = Math.sin(phase);
    if (waveform !== 'sine') {
      let rich = 0, norm = 0;
      for (let harmonic = 1; harmonic <= 9; harmonic++) {
        if ((waveform === 'triangle' || waveform === 'pulse') && harmonic % 2 === 0) continue;
        const amplitude = waveform === 'triangle' ? (harmonic % 4 === 1 ? 1 : -1) / (harmonic * harmonic) :
          waveform === 'saw' ? (harmonic % 2 ? 1 : -1) / harmonic : 1 / harmonic;
        rich += amplitude * Math.sin(harmonic * phase);
        norm += Math.abs(amplitude);
      }
      body = (1 - brightness) * body + brightness * rich / norm;
    }
    samples[i] = body * envelope * .68;
  }
  return samples;
}
