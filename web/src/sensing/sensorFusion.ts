import type { ConfidenceInputs } from '../types';

export function combineConfidence(inputs: ConfidenceInputs): number {
  const available: Array<[number, number]> = [
    [inputs.audio, 0.82],
    [inputs.stability, 0.18]
  ];

  if (inputs.camera !== undefined) {
    available.push([inputs.camera, 0.0]);
  }
  if (inputs.ble !== undefined) {
    available.push([inputs.ble, 0.0]);
  }

  const weighted = available.reduce(
    (acc, [value, weight]) => {
      acc.total += clamp(value, 0, 100) * weight;
      acc.weight += weight;
      return acc;
    },
    { total: 0, weight: 0 }
  );

  return weighted.weight > 0 ? weighted.total / weighted.weight : 0;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function noteBleFuture(): string {
  return 'Web apps usually cannot make a phone advertise BLE for an emitter to scan; this likely needs a native app, OS beacon, or controller-side pairing later.';
}
