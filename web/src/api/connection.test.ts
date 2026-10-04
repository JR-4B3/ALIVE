import { expect, test } from 'bun:test';
import { apiFailure, ApiConnectionError, normalizeApiBase } from './connection';

test('normalizes API URLs and allows an empty same-origin setting', () => {
  expect(normalizeApiBase(' https://api.example.com/alive/// ')).toBe('https://api.example.com/alive');
  expect(normalizeApiBase('')).toBe('');
  expect(normalizeApiBase('http://localhost:8765/')).toBe('http://localhost:8765');
});

test('rejects addresses that cannot be an API base URL', () => {
  for (const value of ['api.example.com', 'javascript:alert(1)', 'https://user:secret@example.com', 'https://example.com/?api=x', 'https://example.com/#api']) {
    expect(() => normalizeApiBase(value)).toThrow();
  }
});

test('static hosts offer connection recovery for both unsupported POST and missing routes', async () => {
  for (const status of [404, 405, 501]) {
    const error = await apiFailure(new Response('<html>Static host error</html>', { status }));
    expect(error).toBeInstanceOf(ApiConnectionError);
    expect(error.message).toContain('connection settings');
  }
});

test('preserves API errors used by offline and replay retry handling', async () => {
  for (const [status, error] of [[503, 'ESP32 is offline'], [429, 'Wait 2s before replaying'], [401, 'Unauthorized']] as const) {
    const failure = await apiFailure(Response.json({ error }, { status }));
    expect(failure).not.toBeInstanceOf(ApiConnectionError);
    expect(failure.message).toBe(error);
  }
});
