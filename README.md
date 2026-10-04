# ALIVE

ALIVE sends short text as dual-tone audio. A phone page receives and decodes the sound. An optional server prepares replies, and an ESP32-C3 with a MAX98357 amplifier plays them through a passive speaker.

```text
phone page -> HTTPS API -> ESP32 over Wi-Fi -> amplifier -> speaker
     ^                                             |
     +-------------- phone microphone -------------+
```

The phone does the decoding locally. The API creates replies and queues a one-time play command. See [the deployment guide](DEPLOY.md) for the server, network, firmware, and publishing steps. The guide uses placeholders for every deployment-specific address.

## Visitor contact threshold

For the proximity installation, set `ALIVE_PROXIMITY_RSSI_MIN` in `/etc/alive/api.env` and configure `ALIVE_VISITOR_AP_SSID` and `ALIVE_VISITOR_AP_PASSWORD` in the ESP32 secrets file. The ESP32 joins the venue Wi-Fi for the API connection and hosts a separate, one-client visitor Wi-Fi network. A visitor joins that network before pressing **Send**. The ESP32 reports the connected phone's averaged RSSI with each authenticated poll. The API accepts contact only while exactly one phone is connected, its reading arrived with one of the last two polls, and RSSI is at least the configured threshold. **Send** plays the reply automatically. Outside the threshold it skips the model and returns a clock-like dead signal, also played on the phone. No near/medium/far state is used.

Start with `-65` dBm and tune it in the room by moving the phone across the intended boundary. The access point itself does not provide internet forwarding; the iPhone must still reach GitHub Pages and the API through cellular data with Connectivity Assist, or the ESP32 must be given a separate internet forwarding setup. Test this on the actual iPhone before opening the exhibition. This is a one-visitor interaction cue, not person-specific access control: a remote request can still coincide with another phone connected inside the threshold. [Espressif documents the averaged AP RSSI](https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/wifi.html); [Apple describes Connectivity Assist](https://support.apple.com/en-us/111107).

## Build and run

Install the frontend dependencies and build both pages:

```bash
cd web
bun install
bun run build
bun run build:debug
```

The builds write to `docs/` and `docs/debug/`. Publish `docs/` with any static host that serves the debug subdirectory too. The visitor page has only translation, microphone, and contact controls. The debug page adds signal diagnostics, connection settings, and an optional recording download or upload.

The published pages call the API named by `PUBLISHED_API` in `web/vite.config.ts`, so the plain GitHub Pages link works on any phone. A link can name another API with `?api=https%3A%2F%2Fapi.example.com`. The debug page also has an API URL field, which it remembers. Under `vite dev`, requests go to the page's own origin. The API must allow the static site's exact origin with `ALIVE_WEB_ORIGIN`.

For local development, `python emitter.py` serves the app and Wi-Fi API. `python debug_host.py` can serve the debug page and proxy API requests. Use `python emitter.py --help` and `python debug_host.py --help` for options. Set `OPENAI_API_KEY` in the environment or an ignored `.env` file to generate replies. The default model can be overridden with `ALIVE_OPENAI_MODEL`.

The API uses only the Python standard library. Python tests require `pytest`.

## Hardware

The ESP32-C3 and MAX98357 connections are shown in [the wiring diagram](docs/alive-esp32-max98357-wiring-usb-left.svg). Connect a 4–8 Ω passive speaker across `SPK+` and `SPK−`, never to ground. Disconnect power before changing wiring. The Wi-Fi firmware is in `firmware/esp32_i2s_emitter/`; copy its `include/secrets.example.h` to the ignored `include/secrets.h` and set the network, API URL, device token, and trusted CA certificate there.

## Source layout

- `web/src/`: phone receiver and UI.
- `emitter.py`, `reply_engine.py`: API, one-time play state, and reply handling.
- `firmware/esp32_i2s_emitter/`: hardware sender.
- `docs/`: built static pages and wiring diagram.
- `DEPLOY.md`: deployment and test guide.

## Checks

```bash
pytest -q
cd web && bun test && bun run build && bun run build:debug
```
