# ALIVE

ALIVE sends short text as near-ultrasound chirps between 18.2 and 20.1 kHz, which most adults cannot hear. A phone page shows them on a spectrogram and decodes them. An optional server prepares replies, and an ESP32-C3 with a MAX98357 amplifier plays them through a passive speaker.

```text
phone page -> HTTPS API -> ESP32 over Wi-Fi -> amplifier -> speaker
     ^                                             |
     +-------------- phone microphone -------------+
```

Five ESP32 units transmit on their own, one at a time. The API deals each unit a random role every 10 minutes: one is intelligent, the others are a clock, noise, or dead. Noise is a few chirps on random channels. A clock repeats one channel at a fixed period. Now and then the intelligent unit sends a beacon such as `IS ANYONE THERE`, as one chirp per letter framed by sync chirps. The phone decodes the sound locally and judges each reception from the sound alone. It shows noise and clocks in grey and framed messages in green.

Once a phone has decoded a green message, its visitor can write back. The page sends the decoded text along, and the API asks a language model for a reply of at most 40 characters. The model sees the visitor's last six turns. The intelligent unit plays the reply as soon as the air is free. A message sent before the phone heard anything goes nowhere: the API makes no model call and nothing answers. See [the deployment guide](DEPLOY.md) for the server, network, firmware, and publishing steps. The guide uses placeholders for every deployment-specific address.

## Build and run

Install the frontend dependencies and build both pages:

```bash
cd web
bun install
bun run build
bun run build:debug
```

The builds write to `docs/` and `docs/debug/`. Publish `docs/` with any static host that serves the debug subdirectory too. The visitor page shows the last reception, a spectrogram of the microphone, and the message box. Intelligent messages are kept under **Messages** for the browser tab; the visitor's own messages are not shown or kept. The debug page is the same page with a **Debug** button that opens signal controls, diagnostics, connection settings, the recording option, and **reset to the first state** below it.

The published pages call the API named by `PUBLISHED_API` in `web/vite.config.ts`, so the plain GitHub Pages link works on any phone. A link can name another API with `?api=https%3A%2F%2Fapi.example.com`. The debug page also has an API URL field, which it remembers. Under `vite dev`, requests go to the page's own origin. The API must allow the static site's exact origin with `ALIVE_WEB_ORIGIN`.

For local development, `python emitter.py` serves the app and Wi-Fi API. `python debug_host.py` can serve the debug page and proxy API requests. `python emitter.py --manual-signals` starts with random signals off.

To test without hardware, run a local API with no device token, open the debug page with `?api=` pointing at it, and tick **Simulate a unit on this page**. The page then polls the API as a board and feeds each signal it gets straight into its decoder and spectrogram, so noise, clocks, messages, and replies show up as they would on a phone next to a unit:

```sh
ALIVE_PUBLIC_DEMO=1 python emitter.py --host 127.0.0.1 --port 8766 --http --manual-signals
python debug_host.py --api http://127.0.0.1:8766 --rebuild   # in a second terminal
# open the printed URL, tap Debug, tick "Simulate a unit on this page"
``` Use `python emitter.py --help` and `python debug_host.py --help` for options. Set `OPENAI_API_KEY` in the environment or an ignored `.env` file to generate replies. The default model can be overridden with `ALIVE_OPENAI_MODEL`.

The API uses only the Python standard library. Python tests require `pytest`.

## Hardware

The ESP32-C3 and MAX98357 connections are shown in [the wiring diagram](docs/alive-esp32-max98357-wiring-usb-left.svg). Connect a 4–8 Ω passive speaker across `SPK+` and `SPK−`, never to ground. Disconnect power before changing wiring. The Wi-Fi firmware is in `firmware/esp32_i2s_emitter/`; copy its `include/secrets.example.h` to the ignored `include/secrets.h` and set the network, API URL, device token, and trusted CA certificate there.

## Source layout

- `web/src/`: phone receiver and UI.
- `emitter.py`: API, unit roles, the shared air, and visitor conversations.
- `signals.py`: the chirp sequences for messages, noise, and clocks.
- `reply_engine.py`: reply model calls.
- `firmware/esp32_i2s_emitter/`: hardware sender. `include/beacon_voice.h` and `web/src/audio/beacon.ts` define the same chirp alphabet, and a web test checks that they produce identical samples.
- `docs/`: built static pages and wiring diagram.
- `DEPLOY.md`: deployment and test guide.

## Checks

```bash
pytest -q
cd web && bun test && bun run build && bun run build:debug
```
