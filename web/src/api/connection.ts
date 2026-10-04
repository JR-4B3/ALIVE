export function normalizeApiBase(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, '');
  if (!trimmed) return '';
  const url = new URL(trimmed);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('Enter an HTTP or HTTPS API URL without credentials, a query, or a fragment.');
  }
  return trimmed;
}

export class ApiConnectionError extends Error {
  constructor() { super('Set the ALIVE API URL in connection settings, then try again.'); }
}

export async function apiFailure(response: Response): Promise<Error> {
  const failure = await response.json().catch(() => null) as { error?: string } | null;
  if (failure?.error) return new Error(failure.error);
  if ([404, 405, 501].includes(response.status)) return new ApiConnectionError();
  return new Error(`HTTP ${response.status}`);
}
