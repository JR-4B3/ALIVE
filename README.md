# ALIVE

ALIVE is now one demo path:

```text
laptop encoded-audio emitter -> phone microphone -> browser receiver
```

The laptop plays an encoded message as short dual-tone bursts. The phone decodes the bursts into text and estimates `far` / `mid` / `near` / `close` from the same audio signal. The zone estimate holds through intentional silent gaps between message bursts instead of treating every gap as distance.

## Run

Build the phone app after frontend changes:

```bash
cd web
bun install
bun run build
cd ..
```

Start the emitter:

```bash
python emitter.py
```

Then scan/open the printed phone URL, accept the local HTTPS warning if needed, tap **Enable microphone**, and type `start` in the emitter terminal.

## Live Controls

While `python emitter.py` is running:

```text
start                   start the current signal
stop                    stop the current signal
message <text>          change encoded message
language / clock / burst  change signal type
status                  show current sender state
quit                    stop the server
```

Useful flags:

```bash
python emitter.py --message "HELLO WORLD"
python emitter.py --message TEST --horn
python emitter.py --signal clock
python emitter.py --signal burst
python emitter.py --http
```

Microphone access usually requires HTTPS. Use `--http` only for local desktop testing.

## Project Layout

- `emitter.py` serves the built phone app and controls the laptop audio emitter.
- `audio_message.py` generates and loops encoded language, clock, and burst signals.
- `codebook.py` defines the dual-tone character map and timing map.
- `simple_qr.py` prints the terminal QR code.
- `web/` contains the Vite/TypeScript phone receiver source.
- `docs/` contains the built static phone app for GitHub Pages.

## Tests

```bash
python test_audio_message.py
cd web && bun run build
```

## BLE Note

BLE can help later if hardware emitters advertise and the phone reads their signal strength, but browser support is limited and RSSI is noisy. The current browser demo should not depend on BLE for gap handling; the receiver smooths and holds the audio zone through normal encoded-message silence.
