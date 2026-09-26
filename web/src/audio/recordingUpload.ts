type UploadRequest = (url: string, init: RequestInit) => Promise<Pick<Response, 'ok' | 'status'>>;

// The caller keeps a local WAV link throughout this optional upload.
export async function uploadRecording(
  wav: ArrayBuffer, api: string, message: string, headers: Record<string, string>,
  request: UploadRequest = fetch
): Promise<string> {
  if (!headers.authorization) return 'Recording ready on this device.';
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await request(`${api}/api/receiver/capture?message=${encodeURIComponent(message)}`, {
      method: 'POST', headers: { 'content-type': 'audio/wav', ...headers },
      body: wav, signal: controller.signal
    });
    return response.ok ? 'Recording also saved to the NAS.' :
      `NAS upload failed (HTTP ${response.status}). The local WAV is ready.`;
  } catch {
    return 'NAS upload unavailable. The local WAV is ready.';
  } finally {
    globalThis.clearTimeout(timer);
  }
}
