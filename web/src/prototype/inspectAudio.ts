// Re-run against actual mono/stereo PCM recordings: bun src/prototype/inspectAudio.ts <files.wav>
import { TranslationDecoder } from '../sensing/translationDecoder';
import { rmsDb } from '../audio/dsp';
for (const path of process.argv.slice(2)) {
  const buffer = await Bun.file(path).arrayBuffer(), view = new DataView(buffer);
  let rate = 0, channels = 0, bits = 0, data = 0, bytes = 0;
  for (let offset = 12; offset + 8 <= buffer.byteLength;) {
    const tag = String.fromCharCode(...new Uint8Array(buffer, offset, 4));
    const length = view.getUint32(offset + 4, true);
    if (tag === 'fmt ') { channels = view.getUint16(offset + 10, true); rate = view.getUint32(offset + 12, true); bits = view.getUint16(offset + 22, true); }
    if (tag === 'data') { data = offset + 8; bytes = Math.min(length, buffer.byteLength - data); break; }
    offset += 8 + length + length % 2;
  }
  if (bits !== 16 || !data || !channels || !rate) throw Error(`Expected PCM16 WAV: ${path}`);
  const samples = new Float32Array(bytes / 2 / channels);
  for (let i = 0; i < samples.length; i++) for (let ch = 0; ch < channels; ch++) samples[i] += view.getInt16(data + (i * channels + ch)*2, true) / 32768 / channels;
  const decoder = new TranslationDecoder(); decoder.beginCapture(0); decoder.setCaptureDuration(0, samples.length / rate);
  let result = decoder.snapshot();
  const transitions: {seconds: number; text: string}[] = [];
  for (let i = 0; i < samples.length; i += 2048) {
    result = decoder.process(samples.subarray(i, i + 2048), rate, -40, -65, i / rate, i / rate * 1000);
    if (result.message !== (transitions.at(-1)?.text ?? '---')) transitions.push({ seconds: +(i/rate).toFixed(3), text: result.message });
  }
  console.log(JSON.stringify({ path, rate, seconds: +(samples.length/rate).toFixed(3), rmsDb: +rmsDb(samples).toFixed(1), message: result.message, transitions }));
}
