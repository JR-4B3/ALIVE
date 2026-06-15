# ALIVE Demo

ALIVE now has two demo paths:

- `--zone-demo`: browser phone receiver estimates far/mid/near/close from emitter audio. This is the forward path for GitHub Pages and ESP32-C3 emitters.
- default translator: laptop plays an encoded audio message, and the phone acts as a live translator.

## Zone Receiver Demo

The phone app source lives in `web/` and builds into `docs/`, so GitHub Pages can keep serving from `/docs` without Python-only endpoints.

Default mode:

- open the static app from GitHub Pages or from the laptop server
- tap **Enable microphone**
- the phone estimates zones locally from microphone audio
- the UI shows only the strongest active emitter estimate, current zone, confidence, and translation window

Debug/control mode:

- run the laptop controller:

```bash
python demo_server.py --zone-demo
```

- type `start` in the terminal to play the laptop test emitter
- enter the printed controller URL in the phone app, or open the app with:

```text
?controller=https://YOUR-LAPTOP-IP:8765
```

The phone sends zone updates to `POST /api/zone`. The laptop switches the active emitter sound between:

- `far`
- `mid`
- `near`
- `close`

Each test emitter has a unique frequency pair and rhythm. The phone scores audio level above noise floor, frequency match, rhythm match, and recent stability; it maps confidence to a zone with smoothing and hysteresis rather than exact meters.
The TypeScript sensing model keeps camera and BLE confidence as future inputs, but they are not shown in the UI yet.

Terminal controls in zone mode:

```text
start
stop
emitter 1
zone near
far
mid
near
close
status
quit
```

Later, the laptop emitter can be replaced by ESP32-C3 units on Wi-Fi. Use an amplifier module for a speaker; do not drive a 4 ohm speaker directly from ESP32 pins.
Phone-to-emitter BLE contribution likely needs a native app, OS beacon, or controller-side pairing because normal browser pages generally cannot advertise BLE from the phone.

## Frontend Build

The frontend uses Bun, Vite, TypeScript, and Tailwind CSS. There is no React dependency.

```bash
cd web
bun install
bun run dev
bun run build
```

`bun run build` writes the static GitHub Pages app to `docs/`.

## Translator Demo

BLE/proximity experiments are not the primary demo path now. BLE browser scanning was too unreliable for tomorrow, and dB-based distance was not stable enough. The robust flow is:

```text
laptop encoded audio loop -> phone microphone -> codebook FFT decode -> translated message
```

## Run The Demo

```bash
python demo_server.py
```

The server:

- starts a continuous encoded message loop on the laptop speaker
- uses the legacy dual-tone frequency codebook and gap timing
- serves the phone translator page
- prints a phone URL and terminal QR code

On the phone:

1. Scan the QR code.
2. Accept the local HTTPS warning if shown.
3. Tap **Start translator**.
4. Hold the phone near the laptop audio.
5. Watch the decoded text reveal letter by letter.

## Live Controls

While the server is running:

```text
start
stop
message WE ARE STILL HERE
language
clock
burst
status
quit
```

The signal control switches between encoded language, periodic clock pulses, and an isolated burst signal.
Choose the sound style when starting the server with `--laser`, `--horn`, or `--vocal`.

## Useful Flags

```bash
python demo_server.py --message "HELLO WORLD" --vocal
python demo_server.py --horn
python demo_server.py --signal clock
python demo_server.py --signal burst
python demo_server.py --http
```

Phone microphone access usually requires HTTPS. `--http` is only for local desktop testing.

## Current Architecture

- `web/` is the Bun + Vite + TypeScript + Tailwind source for the phone app.
- `docs/` is the generated static GitHub Pages app.
- `zone_audio.py` defines five emitter fingerprints and the laptop test emitter/controller sound.
- `demo_server.py` serves either the static zone app or the translator UI and controls the live demo.
- `legacy_audio_loop.py` generates and loops the encoded laptop audio using the legacy codebook.
- `codebook.py` contains the frequency pairs, gap map, and language helper data.
- `base_demo.py` remains the old Python-only SETI-inspired sender/receiver demo.
- `ble_advertiser.py`, `audio_beacon.py`, and `experience_model.py` are retained from the BLE/proximity prototype, but they are not the default demo path.

## Tests

```bash
cd web && bun run build
python test_demo.py
python test_experience_model.py
python test_zone_audio.py
```

`test_demo.py` verifies the legacy encoded audio pipeline. `test_experience_model.py` verifies the retained source/zone model.
`test_zone_audio.py` verifies the zone-emitter fingerprints and controller state.

## Audio Requirements

Laptop playback uses `sounddevice`, which needs PortAudio:

- **Fedora/Nobara:** `sudo dnf install portaudio`
- **Debian/Ubuntu:** `sudo apt-get install libportaudio2`
- **macOS:** usually pre-installed
- **Windows:** usually works out of the box
