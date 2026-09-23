# ALIVE

ALIVE has a live hardware demo path:

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
