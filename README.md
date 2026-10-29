# Anybody Listening?

An installation for the HfK course ALIVE/ALIFE. Five small speakers send short text as near-ultrasound chirps between 18.2 and 20.1 kHz, which most adults cannot hear. Visitors find the signals with a phone page that shows them on a spectrogram and decodes them, and can answer the one that sounds intelligent. A server deals the roles and prepares replies, and each unit, an ESP32-C3 with a MAX98357 amplifier, plays them through a passive speaker. The code and tools still use the working name ALIVE.

```text
phone page -> HTTPS API -> ESP32 over Wi-Fi -> amplifier -> speaker
     ^                                             |
     +-------------- phone microphone -------------+
```

Five ESP32 units transmit on their own, one at a time. The API deals each unit a random role every 10 minutes: one is intelligent, the others are a clock, noise, or dead. Noise is a few chirps on random channels. A clock repeats one channel at a fixed period. Now and then the intelligent unit sends a beacon such as `IS ANYONE THERE`, as one chirp per letter framed by sync chirps. The phone decodes the sound locally and judges each reception from the sound alone. It shows noise and clocks in grey and framed messages in green.

Once a phone has decoded a green message, its visitor can write back. The page sends the decoded text along, and the API asks a language model for a reply of at most 40 characters. The model sees the visitor's last six turns. The first voice is LANTERN, a guarded help beacon. Once a visitor shows care for the people behind the signal, the API gives that visitor's page the key; the key never goes on the air. From then on AURORA, the ship whose mission was cut from the records, answers in sealed messages. A sealed message opens with a third sync chirp and swaps its letters by a keyword alphabet, so only a page with the key can read it. Other phones show the scrambled letters. The story facts and the key are in `reply_engine.py`. The intelligent unit plays the reply as soon as the air is free. A message sent before the phone heard anything goes nowhere: the API makes no model call and nothing answers. See [the deployment guide](DEPLOY.md) for the server, network, firmware, and publishing steps. The guide uses placeholders for every deployment-specific address.

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

To test, run `python3 debug_host.py` (the real units, through the T480 or, without it, this computer) or `python3 debug_host.py -sim` (no unit; the computer plays the signals). See [Test from the MacBook](DEPLOY.md#test-from-the-macbook). For API development, `python emitter.py` serves the API on its own; `--manual-signals` starts it with random signals off. Use `python emitter.py --help` and `python debug_host.py --help` for options. Set `OPENAI_API_KEY` in the environment or an ignored `.env` file to generate replies. The default model can be overridden with `ALIVE_OPENAI_MODEL`.

The API uses only the Python standard library. Python tests require `pytest`.

## Hardware

The ESP32-C3 and MAX98357 connections are shown in [the wiring diagram](docs/alive-esp32-max98357-wiring-usb-left.svg). Connect a 4–8 Ω passive speaker across `SPK+` and `SPK−`, never to ground. Disconnect power before changing wiring. The Wi-Fi firmware is in `firmware/esp32_i2s_emitter/`; copy its `include/secrets.example.h` to the ignored `include/secrets.h` and set the network, API URL, device token, and trusted CA certificate there.

The current [three-part enclosure](hardware/enclosure/README.md) has a side-latch lid and perfboard rails. Its generator, print files and assembly viewer are in `hardware/enclosure/`.

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
