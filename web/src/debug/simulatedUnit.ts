import { BEACON_RATE, renderChirps, type Chirp } from '../audio/beacon';

// A unit that lives in the debug page, for tests without hardware. It polls
// the API like the firmware, and instead of playing a granted signal through a
// speaker it hands the samples straight to the decoder, in real time.
// The API must accept device polls without a token, as a local test API does.

const CHUNK = 2048;
const POLL_MS = 2000;
// A locally administered MAC address, so it never matches a real board.
const BOARD = '02:A1:1E:00:00:01';

type Play = { kind: string; leadMs: number; chirps: Chirp[] };

export function startSimulatedUnit(options: {
  apiBase: () => string;
  feed: (samples: Float32Array, rate: number) => void;
  status: (text: string) => void;
}): () => void {
  const startedAt = performance.now();
  let reset = '1';
  let signal: Float32Array | null = null;
  let offset = 0;
  let polling = false;
  let nextPollAt = 0;
  let stopped = false;

  async function poll(): Promise<void> {
    polling = true;
    try {
      const response = await fetch(`${options.apiBase()}/api/emitter/main/current`, {
        headers: {
          'x-alive-board': BOARD,
          'x-alive-uptime-ms': String(Math.round(performance.now() - startedAt)),
          'x-alive-reset': reset
        },
        signal: AbortSignal.timeout(5000)
      });
      const payload = (await response.json().catch(() => null)) as { role?: string; play?: Play | null; error?: string } | null;
      if (!response.ok) throw new Error(payload?.error ?? `HTTP ${response.status}`);
      reset = '3';
      if (stopped) return;
      if (payload?.play) {
        signal = renderChirps(payload.play.chirps, payload.play.leadMs);
        offset = 0;
      }
      options.status(`simulated unit ${BOARD} · role ${payload?.role ?? '?'}` +
        (payload?.play ? ` · playing ${payload.play.kind}` : ''));
    } catch (error) {
      options.status(`simulated unit: ${error instanceof Error ? error.message : 'poll failed'}`);
    } finally {
      polling = false;
      nextPollAt = performance.now() + POLL_MS;
    }
  }

  // Silence between signals matters too: the decoder ends a reception after
  // two quiet seconds.
  const timer = window.setInterval(() => {
    if (!signal && !polling && performance.now() >= nextPollAt) void poll();
    const chunk = new Float32Array(CHUNK);
    if (signal) {
      chunk.set(signal.subarray(offset, offset + CHUNK));
      offset += CHUNK;
      if (offset >= signal.length) signal = null;
    }
    options.feed(chunk, BEACON_RATE);
  }, CHUNK / BEACON_RATE * 1000);

  return () => {
    stopped = true;
    window.clearInterval(timer);
    options.status('simulated unit off');
  };
}
