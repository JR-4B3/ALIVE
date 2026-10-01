# Exhibition sound study

Throwaway branch `prototype/space-communication`. No sound or layout has been chosen for production. The question is which phone spectrogram layout and atmospheric transmission direction support an exhibition encounter while preserving the existing receiver.

Start with `cd web && bun run prototype`. Open `http://localhost:5173/?prototype=space&variant=B`. A puts the spectrogram above the translation, B puts a short strip below a larger translation, and C puts a frequency column beside the translation. The arrows change `variant` in the URL. The prototype is absent from production builds.

The phone view has no scrolling. Sound lab replaces the encounter with comparison controls. The square microphone button sits inside the translation area. Its crossed microphone SVG indicates that capture is off. The decoder receives the same unfiltered samples as before. The canvas displays FFT measurements rather than generated decoration.

Drift is a sustained low arrival, Beacon uses sparse high chirps, and Chorus uses beating low tones. All three surround the original letter signal. They keep its frequencies, amplitude, fades, and letter spacing. Browser auditions and WAV downloads use HELLO. The serial prototype's contact field sets literal test text without calling a model. The normal API's reply generation is unchanged.

## Hardware session on main

An isolated copy runs at `/tmp/alive-space-prototype` on `main`. It leaves the separate checkout's unfinished sound-studio files alone. The desktop preview is `http://localhost:5178/?prototype=space&variant=B`. The phone preview is `https://192.168.178.20:5179/?prototype=space&variant=B`. It uses the existing local certificate, which the phone must trust for microphone access. The HTTPS server accepts certificate paths through `ALIVE_PROTOTYPE_CERT` and `ALIVE_PROTOTYPE_KEY`. Vite proxies requests to a temporary serial bridge on port 8766. The connected ESP32 is temporarily running the experimental `serial_message` firmware. Press Play signal to hear the selected direction through its MAX98357 speaker. Playback only starts on request. The original Wi-Fi firmware is backed up in `/tmp/alive-space-prototype/firmware-before.bin`.

Use microphone on main reads the Scarlett capture input. It streams mono PCM from the physical input and feeds the unchanged decoder and the spectrogram. It does not send microphone audio back to the speaker. Phone microphone access requires localhost or HTTPS.

To restore the exact previous firmware and stop the bridge:

```bash
ssh main 'pkill -f "^python3 /tmp/alive-space-prototype/prototype_server.py$"; python3 ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32c3 --port /dev/ttyACM0 --baud 921600 write_flash 0 /tmp/alive-space-prototype/firmware-before.bin'
```

## What the recordings established

Real speaker audio went through the Scarlett microphone on main at 48 kHz. The current decoder processed those PCM WAVs without filtering. The reports in `evidence/` contain the actual decoded text and intermediate transitions. Recordings remain in `/tmp/alive-space-prototype/captures` on main and `.tmp/space-captures` in this workspace.

Original, Beacon, and Chorus decoded HELLO in the latest short recordings. Drift's previous version introduced false L characters. Its final revision uses a single sustained low tone, but has only passed rendered PCM verification. We stopped audible tests at the user's request before checking that revision physically.

Longer WE ARE HERE recordings were inconsistent in all directions, including Original. Some captures lack sufficient trailing audio and the receiver can confuse E with Y through this microphone/speaker path. These results do not establish reliable exhibition decoding. Keep this experiment separate from production.

An earlier live synthesis attempt stalled the ESP32 and stretched playback. Precomputed tables removed that stall. Beacon's earlier low accompaniment also introduced a false B; removing it produced a clean short recording. The generated tables come from `firmware/esp32_i2s_emitter/include/prototype/generate_tables.py` and use interpolation during playback.

The existing 42 browser audio/decoder checks and 13 Python checks pass. The decoder source has no changes. All final rendered HELLO WAVs decode correctly. The microphone button and the live main-input spectrogram were inspected in the collaborative preview. A 320 by 568 viewport fits the encounter and sound lab without scrolling.

For another physical check, choose one direction explicitly. This plays sound:

```bash
python3 /tmp/alive-space-prototype/prototype_capture.py --direction beacon --message HELLO
```

The default captures only Original. `--direction all` repeats the full comparison and should be used deliberately. Re-run decoding silently with `bun web/src/prototype/inspectAudio.ts <recording.wav>`.
