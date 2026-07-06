# ALIVE

ALIVE is now one demo path:

```text
laptop encoded-audio emitter -> phone microphone -> browser receiver
```

The laptop plays an encoded message as short dual-tone bursts. The phone listens through the microphone, calibrates against the local noise floor, decodes the bursts into text, and classifies the received signal.

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

## Reply API

The laptop server can also act as the temporary signal API before the NAS/ESP32 emitter exists. The phone page includes a contact form; when served from the laptop it posts to the same origin by default.

```bash
curl -X POST http://127.0.0.1:8765/api/message \
  -H 'content-type: application/json' \
  -d '{"message":"hello are you alive"}'
```

The generated reply is sanitized to A-Z plus spaces and capped at 20 characters before it is encoded and played once through the laptop. It does not loop automatically. Use the web page's **play signal** button to replay the current signal; the button stays locked until the current audio duration has elapsed.

Without `OPENAI_API_KEY`, the server uses deterministic fallback replies for local testing. With an API key:

```bash
export OPENAI_API_KEY=...
export ALIVE_OPENAI_MODEL=gpt-5.4-mini
python emitter.py
```

The future ESP32 I2S emitter can poll the same transport shape:

```text
GET /api/emitter/main/current
```

```json
{
  "emitterId": "main",
  "revision": 1,
  "message": "I AM HERE",
  "mode": "language",
  "maxChars": 20,
  "duration": 9.23,
  "active": true
}
```

The web replay button calls:

```text
POST /api/emitter/main/play
```

## Live Controls

While `python emitter.py` is running:

```text
start                   start the current signal
stop                    stop the current signal
message <text>          change encoded message
ask <text>              generate a max-20-char reply and play it
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
