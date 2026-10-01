# Signal strip and Beacon

The selected exhibition page is layout B. It now has only translation, a taller black-and-white spectrogram, and contact controls. The microphone is a 44-pixel square inside the translation area. The study header, sound lab, direction buttons, state dump, and variant switcher are gone. The page fits one phone viewport and adjusts to the visible viewport when the keyboard opens.

Run `cd web && bun run prototype`. The visitor page uses this layout at `/`, with no variant parameter. The temporary preview on main is `http://localhost:5178/`. A phone can use `https://192.168.178.20:5179/` after trusting the existing local certificate. Enable the phone microphone with the square button. For the main PC's Scarlett input, open `http://localhost:5178/?input=main` and use the same microphone button. All canvas pixels come from the active microphone's FFT measurements. Microphone audio is never sent back to a speaker.

## The new sound

Beacon now carries the message itself. Each symbol is one 360 ms descending chirp with a smooth sine-squared envelope and a 180 ms quiet gap. Letter centers are 680–1780 Hz, and space is 1824 Hz. Two 550 Hz chirps mark the beginning; one marks the end. The maximum instantaneous frequency is 1860 Hz, compared with the earlier Beacon effect's roughly 3600–4800 Hz. Peak amplitude is 520 in 16-bit PCM. No legacy dual tones, atmospheric introduction, or atmospheric outro are mixed into this transmission.

The receiver detects the Beacon framing and decodes its pitches from audio. It receives no expected text from the API. The original dual-tone decoder remains unchanged, and the combined receiver switches between both protocols. An original sender remains usable with the new receiver.

The browser renderer and ESP32 use the same fixed-point oscillator and generated sine/envelope tables. This avoids the live-synthesis stalls found during the previous experiment. Regenerate the tables with `python3 firmware/esp32_i2s_emitter/include/prototype/generate_beacon.py`.

## Quiet verification

No speaker playback or physical sound tests ran for this revision, at the user's request. The new firmware was compiled, uploaded in the idle serial-message mode, and checked with the silent INFO command. It responds with `BEACON_V1`. The serial bridge refuses to send Beacon to older firmware.

Run `cd web && bun run verify:beacon` for the silent check. Its 73 cases passed. They cover the full alphabet, repeated letters, spaces, three sample rates, lower volume with simulated room noise and echoes, automatic protocol switching, and rejection of unframed chirps. It compares every firmware-generated HELLO sample with the browser renderer and decodes the firmware PCM. It writes the WAV and report to `.tmp/beacon-silent-verification/` without playing them. This establishes digital round trips, not physical speaker-to-microphone reliability.

All 37 existing tone-decoder cases also passed through the combined receiver. The standard 42 frontend checks and 13 Python checks passed. The phone layout was inspected at 390 × 844, 320 × 568, and 320 × 400. Every control remained inside the viewport, with no page overflow. The signal strip measured about 311 pixels high on the larger phone and 184 pixels on the smaller phone. The real Scarlett input produced grayscale FFT history in the canvas, and stopping it restored the crossed microphone icon.

The older speaker reports in `evidence/HELLO-speaker.jsonl` and `evidence/WE-ARE-HERE-speaker.jsonl` belong to the superseded introduction/outro experiment. They do not verify the new Beacon alphabet. Earlier layouts and sound candidates remain in commit `d927190` on `prototype/space-communication`.

## Hardware session

The temporary code lives at `/tmp/alive-space-prototype` on main. The separate unfinished sound-studio checkout is untouched. Vite proxies requests to the serial bridge on port 8766. The bridge prepares literal contact text and plays only when the visitor presses Play signal. It discovers the connected ESP32 instead of relying on a fixed tty number. No automated playback is scheduled.

The connected speaker remains in experimental serial mode. Its original Wi-Fi firmware backup is `/tmp/alive-space-prototype/firmware-before.bin`. Restore it by stopping the bridge and writing that backup through the device's stable USB link:

```bash
ssh main 'pkill -f "^python3 /tmp/alive-space-prototype/prototype_server.py$"; python3 ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32c3 --port /dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_70:AF:09:0D:AB:24-if00 --baud 921600 write_flash 0 /tmp/alive-space-prototype/firmware-before.bin'
```

No NAS service was deployed. For the normal Wi-Fi installation, update the API, sender firmware, and receiver together so that Beacon selection and playback duration agree.
