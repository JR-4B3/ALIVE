export function rmsDb(samples: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    sum += samples[i] * samples[i];
  }
  return 20 * Math.log10(Math.sqrt(sum / samples.length) + 1e-8);
}

export function percentile(values: number[], ratio: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * ratio)));
  return sorted[index] ?? null;
}

export function goertzel(samples: Float32Array | number[], sampleRate: number, frequency: number): number {
  const omega = (2 * Math.PI * frequency) / sampleRate;
  const coeff = 2 * Math.cos(omega);
  let q0 = 0;
  let q1 = 0;
  let q2 = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const window = samples.length > 1 ? 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (samples.length - 1)) : 1;
    q0 = coeff * q1 - q2 + samples[i] * window;
    q2 = q1;
    q1 = q0;
  }
  const power = q1 * q1 + q2 * q2 - coeff * q1 * q2;
  return Math.sqrt(Math.max(power, 0)) / samples.length;
}

export function updateNoiseFloor(noiseFloorDb: number, levelDb: number): number {
  if (levelDb < noiseFloorDb) {
    return noiseFloorDb * 0.9 + levelDb * 0.1;
  }
  return noiseFloorDb * 0.997 + levelDb * 0.003;
}
