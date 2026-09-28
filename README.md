# ALIVE

ALIVE sends short text as dual-tone audio. A phone page receives and decodes the sound. An optional server prepares replies, and an ESP32-C3 with a MAX98357 amplifier plays them through a passive speaker.

```text
phone page -> HTTPS API -> ESP32 over Wi-Fi -> amplifier -> speaker
     ^                                             |
     +-------------- phone microphone -------------+
```

The phone does the decoding locally. The API creates replies and queues a one-time play command. See [the deployment guide](NAS_SETUP.md) for the server, network, firmware, and publishing steps. The guide uses placeholders for every deployment-specific address.

## Build and run

Install the frontend dependencies and build both pages:

```bash
cd web
bun install
bun run build
bun run build:debug
```

The builds write to `docs/` and `docs/debug/`. Publish `docs/` with any static host that serves the debug subdirectory too. The visitor page has only translation, microphone, and contact controls. The debug page adds signal diagnostics, connection settings, and an optional recording download or upload.

The page accepts an API URL through `?api=https%3A%2F%2Fapi.example.com`. It saves the URL in that browser's local storage after a request. For a public installation, generate a visitor link or QR code with the URL parameter; do not commit a deployment address. The debug page also has an API URL field. When a page is served directly by the API, same-origin requests work without an override. The API must allow the static site's exact origin with `ALIVE_WEB_ORIGIN`.

For local development, `python emitter.py` serves the app and Wi-Fi API. `python debug_host.py` can serve the debug page and proxy API requests. Use `python emitter.py --help` and `python debug_host.py --help` for options. Set `OPENAI_API_KEY` in the environment or an ignored `.env` file to generate replies. The default model can be overridden with `ALIVE_OPENAI_MODEL`.

The API uses only the Python standard library. Python tests require `pytest`.

## Hardware

The ESP32-C3 and MAX98357 connections are shown in [the wiring diagram](docs/alive-esp32-max98357-wiring-usb-left.svg). Connect a 4–8 Ω passive speaker across `SPK+` and `SPK−`, never to ground. Disconnect power before changing wiring. The Wi-Fi firmware is in `firmware/esp32_i2s_emitter/`; copy its `include/secrets.example.h` to the ignored `include/secrets.h` and set the network, API URL, device token, and trusted CA certificate there.

## Source layout

- `web/src/`: phone receiver and UI.
- `emitter.py`, `reply_engine.py`: API, one-time play state, and reply handling.
- `firmware/esp32_i2s_emitter/`: hardware sender.
- `docs/`: built static pages and wiring diagram.
- `NAS_SETUP.md`: reusable deployment and test guide.

## Checks

```bash
pytest -q
cd web && bun test && bun run build && bun run build:debug
```
