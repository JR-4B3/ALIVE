# ALIVE Demo

Default demo: the laptop continuously plays an encoded audio message, and the phone acts as a live translator.

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

- `demo_server.py` serves the one-page phone translator UI and controls the live demo.
- `legacy_audio_loop.py` generates and loops the encoded laptop audio using the legacy codebook.
- `codebook.py` contains the frequency pairs, gap map, and language helper data.
- `base_demo.py` remains the old Python-only SETI-inspired sender/receiver demo.
- `ble_advertiser.py`, `audio_beacon.py`, and `experience_model.py` are retained from the BLE/proximity prototype, but they are not the default demo path.

## Tests

```bash
python test_demo.py
python test_experience_model.py
```

`test_demo.py` verifies the legacy encoded audio pipeline. `test_experience_model.py` verifies the retained source/zone model.

## Audio Requirements

Laptop playback uses `sounddevice`, which needs PortAudio:

- **Fedora/Nobara:** `sudo dnf install portaudio`
- **Debian/Ubuntu:** `sudo apt-get install libportaudio2`
- **macOS:** usually pre-installed
- **Windows:** usually works out of the box
