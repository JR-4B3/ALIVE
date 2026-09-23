import { expect, test } from 'bun:test';
import { encodeRecording } from './recording';

test('records microphone samples as mono PCM WAV without changing their timing', () => {
  const buffer = encodeRecording([new Float32Array([-1, 0]), new Float32Array([0.5, 1])], 48000);
  const view = new DataView(buffer);
  expect(buffer.byteLength).toBe(52);
  expect(view.getUint32(24, true)).toBe(48000);
  expect(view.getUint32(40, true)).toBe(8);
  expect([44, 46, 48, 50].map(offset => view.getInt16(offset, true))).toEqual([-32768, 0, 16384, 32767]);
});
