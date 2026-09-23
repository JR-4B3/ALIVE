# ALIVE

## Phone + NAS + ESP32 (exhibition setup)

For the full DS720+ setup and test sequence, open the [HTML guide](NAS_SETUP.html) or the [text version](NAS_SETUP.md).

The live installation runs without a laptop:

```text
phone on GitHub Pages -> HTTPS NAS API -> ESP32 over venue Wi-Fi -> MAX98357 -> speaker
         ^                                                     |
         +--------------- phone microphone <-------------------+
```

The page's receiver and microphone processing run on the phone. The NAS generates the short LLM reply and queues a one-time play command. The ESP32 polls the API over Wi-Fi and creates the sound. The NAS cannot improve missed letters in the phone microphone; use the page's diagnostic recording to inspect those.

The NAS API needs a **public, trusted HTTPS address** so both a visitor's phone and the ESP32 can reach it from the exhibition. A DSM reverse proxy with a domain and certificate works. [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel) is another option: Funnel exposes the API at a public `https://...ts.net` address, and visitors do not need Tailscale. Ordinary Tailscale Serve is private to your tailnet and does not work for general visitors. The API has separate browser and device tokens; do not expose DSM administration.

The NAS DS720+ can run the backend in Container Manager. On the NAS, copy this repository, copy `nas.env.example` to `.env`, replace all placeholders with independent private values, and start it with:

```bash
sudo /usr/local/bin/docker compose --env-file .env -f compose.nas.yml up -d --build
```

The container listens on host loopback port `8765`; route the public HTTPS address to `http://127.0.0.1:8765` with Funnel or the NAS reverse proxy. The container keeps the prepared reply, play revision, and optional microphone recordings in its `alive_state` volume. The OpenAI API key stays in the NAS environment. Use `python -c 'import secrets; print(secrets.token_urlsafe(32))'` twice for distinct web and device tokens. Set `ALIVE_WEB_ORIGIN` to the exact GitHub Pages origin, such as `https://jr-4b3.github.io` (no `/ALIVE` path).

Build `web/` with `bun run build`, publish the `docs/` folder as GitHub Pages, then open the page on the phone. Enter the public NAS HTTPS address in **NAS API URL** and the web token in **API access token**. The web token stays in browser session storage. The page can receive sound on its own; **Send** and **Play signal** need the NAS API.

Before the exhibition, copy `firmware/esp32_i2s_emitter/include/secrets.example.h` to ignored `secrets.h`. Put in the venue network SSID and password, the public HTTPS API address, the device token, and the API certificate authority PEM. Flash the `wifi_message` firmware once:

```bash
.tmp/platformio-venv/bin/platformio run --project-dir firmware/esp32_i2s_emitter -e wifi_message -t upload --upload-port /dev/ttyACM0
```

The computer is needed only for that one-time firmware upload. At the exhibition, power the ESP32 from a USB power supply. It uses outbound Wi-Fi; phone and ESP32 do not need to be on the same LAN. A dedicated hotspot or travel router with a known Wi-Fi password is useful when venue Wi-Fi requires a browser login or isolates devices. The installation still requires internet access to GitHub Pages, the NAS API, and OpenAI. Test the entire path at the venue before visitors arrive.

For HfK / Nebenflut / FLUT, configure the ESP32 with the exhibition Wi-Fi or your own hotspot credentials, then set `ALIVE_SERVER_URL` to the NAS's **public HTTPS address**. A `192.168.x.x` address or an ordinary Tailscale IP will not work from an unrelated venue network. If you use Tailscale, choose **Funnel** on the NAS, which gives the API a public `https://...ts.net` URL; ordinary Tailscale Serve would require every visitor to join your private tailnet. The phone can use mobile data while the ESP32 uses a hotspot. Check that the venue network allows outbound internet and does not require a browser login from the ESP32. With certificate verification enabled, the ESP32 also needs internet time synchronization. If internet is unreliable, arrange a hotspot with enough data or bring a local backend as an exhibition fallback.

The backend rejects **Play signal** while the ESP32 has not polled recently, so a disconnected device cannot silently queue a late beep. Its one-time commands survive NAS restarts through the state volume, and the ESP32 ignores an old command when it boots.

## Earlier laptop demo

The earlier local demo path is retained for development:

```text
phone prompt -> laptop reply API -> USB serial -> ESP32 -> MAX98357 -> speaker
                                             -> phone microphone -> browser decoder
```

The phone sends a player prompt to the laptop. GPT-6 Luna prepares a reply of at most 12 characters. Pressing **Play signal** sends it once over USB serial to the ESP32. The ESP32 synthesizes short dual-tone bursts through a MAX98357 I2S amplifier and speaker. The phone microphone decodes those bursts back into text.

## ESP32 + MAX98357 live demo

This demo needs an ESP32-C3 Super Mini, the MAX98357 board shown in the project notes, and a 4–8 ohm passive speaker. The amplifier is an output device; it does not contain a microphone.

Wire the boards with power disconnected:

| ESP32-C3 | MAX98357 |
| --- | --- |
| `5V` | `VIN` |
| `GND` | `GND` |
| `GPIO4` | `BCLK` |
| `GPIO5` | `LRC` |
| `GPIO6` | `DIN` |
| `3V3` | `SD` |

Connect the speaker directly to the green `+` and `-` terminals. Leave `GAIN` unconnected. Check the printed pin labels on both boards before applying power.

For the website-controlled demo, flash the `serial_message` environment. It stays silent until it receives a play command over USB. From the repository root:

```bash
.tmp/platformio-venv/bin/platformio run --project-dir firmware/esp32_i2s_emitter -e serial_message -t upload --upload-port /dev/ttyACM0
python emitter.py --serial-device /dev/ttyACM0 --message HELLO
```

Use the ESP32's actual serial port if it is not `/dev/ttyACM0`: check `ls -l /dev/serial/by-id/ /dev/ttyACM* /dev/ttyUSB*`. Keep the USB cable connected to the laptop. Open the printed HTTPS URL on the phone, accept the local certificate warning, enable the microphone, and press **Play signal**. Each press sends the prepared text once. The initial text is `HELLO`; entering a prompt and pressing **send** prepares a new reply without playing it. Playing preset text does not need an API key. Generating a new reply does.

For an independent repeating receiver test only, flash `message_test` instead. It repeatedly sends `HELLO` at the same quiet output level:

```bash
.tmp/platformio-venv/bin/platformio run --project-dir firmware/esp32_i2s_emitter -e message_test -t upload --upload-port /dev/ttyACM0
```

The phone receiver accepts stable pairs of codebook tones and filters ordinary room noise. The default laptop emitter uses softly faded dual-tone chimes. A single microphone can still decode another source that deliberately plays the same encoded tones.

The model plays LANTERN, an emergency beacon sent by the lost crew of the survey ship AURORA decades ago. It answers in a few words. The server enforces both a 12-character limit and a 15-second maximum encoded duration, including the ESP32 lead and trailing pause.

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

The laptop server is the temporary signal API before the NAS exists. The phone page includes a contact form; when served from the laptop it posts to the same origin by default.

```bash
curl -k -X POST https://127.0.0.1:8765/api/message \
  -H 'content-type: application/json' \
  -d '{"message":"hello are you alive"}'
```

The generated reply is sanitized to A-Z plus spaces and capped at 12 characters and 15 seconds of encoded audio. Sending a prompt prepares the reply. Use the web page's **play signal** button to send it once; the button stays locked until the current audio duration has elapsed. With `--serial-device`, the ESP32 plays it. Without that flag, the laptop speakers play it.

The laptop server needs an API key to generate a new reply. Without it, **send** shows an explicit configuration error and preserves the previous prepared signal. You can put `OPENAI_API_KEY=your_key_here` in a project-root `.env` file, which Git ignores. Alternatively, run `python setup_api_key.py` from the repository root and enter the key at the hidden prompt. It saves the key in `~/.config/alive/openai_api_key` with file permissions `600`; the running server reads that file on each request. Keep the key out of source files. To use an environment variable instead:

```bash
read -rsp 'OpenAI API key: ' OPENAI_API_KEY; export OPENAI_API_KEY; echo
python emitter.py --serial-device /dev/ttyACM0 --message HELLO
```

The default model is `gpt-6-luna`; set `ALIVE_OPENAI_MODEL` only to override it. Restart the server when changing its environment variables.

The USB demo sends `PLAY <TEXT>` over serial when this endpoint is called. The older Wi-Fi firmware polls this transport:

```text
GET /api/emitter/main/current
```

```json
{
  "emitterId": "main",
  "revision": 1,
  "message": "I AM HERE",
  "mode": "language",
  "maxChars": 12,
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
ask <text>              generate a max-12-char reply for the next play
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
- `firmware/esp32_i2s_emitter/` contains the MAX98357 live demo firmware.

## Tests

```bash
python test_audio_message.py
cd web && bun test && bun run build
```
