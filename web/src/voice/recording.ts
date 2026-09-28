import { encodeRecording } from '../audio/recording';

// Use symmetric PCM scaling so re-importing a downloaded capture preserves its
// exact fingerprint. The classic recorder retains its existing format behavior.
export function encodeVoiceRecording(samples: Float32Array, rate: number): ArrayBuffer {
  const wav = encodeRecording([samples], rate), view = new DataView(wav);
  for (let i = 0; i < samples.length; i++) view.setInt16(44 + i * 2,
    Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32768))), true);
  return wav;
}
