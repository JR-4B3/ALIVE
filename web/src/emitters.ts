import type { EmitterFingerprint, Zone } from './types';

export const EMITTERS: EmitterFingerprint[] = [
  { id: 'emitter-1', label: 'Emitter 1', low: 1430, high: 2210, pulseHz: 1.05 },
  { id: 'emitter-2', label: 'Emitter 2', low: 1510, high: 2330, pulseHz: 1.27 },
  { id: 'emitter-3', label: 'Emitter 3', low: 1630, high: 2470, pulseHz: 1.51 },
  { id: 'emitter-4', label: 'Emitter 4', low: 1760, high: 2590, pulseHz: 1.73 },
  { id: 'emitter-5', label: 'Emitter 5', low: 1910, high: 2740, pulseHz: 1.93 }
];

export const ZONES: Zone[] = ['far', 'mid', 'near', 'close'];

export const ZONE_THRESHOLDS: Record<Zone, number> = {
  far: 12,
  mid: 34,
  near: 58,
  close: 80
};
