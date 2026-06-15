import type { EmitterFingerprint, Zone } from './types';

export const EMITTERS: EmitterFingerprint[] = [
  { id: 'audio-emitter', label: 'audio signal', low: 400, high: 2900, pulseHz: 0 }
];

export const ZONES: Zone[] = ['far', 'mid', 'near', 'close'];

export const ZONE_THRESHOLDS: Record<Zone, number> = {
  far: 10,
  mid: 28,
  near: 50,
  close: 68
};
