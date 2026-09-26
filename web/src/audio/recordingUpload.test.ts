import { expect, test } from 'bun:test';
import { uploadRecording } from './recordingUpload';

test('keeps recordings local without an operator token', async () => {
  const result = await uploadRecording(new ArrayBuffer(8), 'https://example.invalid', 'ABC', {},
    async () => { throw new Error('must not send an unauthenticated upload'); });
  expect(result).toBe('Recording ready on this device.');
});

for (const status of [401, 502]) {
  test(`retains the local recording when upload returns HTTP ${status}`, async () => {
    const wav = new Uint8Array([1, 2, 3]).buffer;
    const result = await uploadRecording(wav, 'https://example.invalid', 'ABC', { authorization: 'Bearer test' },
      async (_url, init) => {
        expect(init.body).toBe(wav);
        return { ok: false, status };
      });
    expect(result).toContain(`HTTP ${status}`);
    expect(result).toContain('local WAV is ready');
    expect([...new Uint8Array(wav)]).toEqual([1, 2, 3]);
  });
}

test('handles an interrupted upload without losing the local recording', async () => {
  const result = await uploadRecording(new ArrayBuffer(8), 'https://example.invalid', 'ABC', { authorization: 'Bearer test' },
    async () => { throw new TypeError('Network connection lost'); });
  expect(result).toBe('NAS upload unavailable. The local WAV is ready.');
});
