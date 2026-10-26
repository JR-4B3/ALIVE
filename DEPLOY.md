# Deployment guide

This guide covers a static phone page, an HTTPS API run as a systemd service on a Linux server, and an ESP32-C3 audio sender. Replace example domains, ports, directories, and device names with values for your deployment. Do not commit private network addresses, tokens, credentials, diagnostic recordings, or a QR code that identifies an installation.

```text
phone: https://site.example/alive/?api=https%3A%2F%2Fapi.example.com
  | HTTPS requests                                 ^ sound into phone microphone
  v                                                |
Tailscale Funnel -> API service -> ESP32 on Wi-Fi -> amplifier -> speaker
```

The phone and ESP32 may use separate networks, but both must reach the public API. The page decodes audio locally; moving the API does not change microphone reception. The API hands each signal to one board, once, in reply to that board's poll, so a board that was offline never plays a stale signal.

## Publish the phone page

Build the visitor and debug pages from `web/` with `bun run build` and `bun run build:debug`. Publish `docs/` on a static HTTPS host. The visitor page has no connection settings. It calls `PUBLISHED_API` from `web/vite.config.ts`, unless the link names another API base URL in its `api` query parameter. The debug page also has a manual API URL field and recording controls. Its local WAV download remains available if an optional API upload fails.

Set `ALIVE_WEB_ORIGIN` to the page's exact origin, such as `https://site.example`, without a path or trailing slash. Neither page should contain an access token. In public demo mode, visitors can send short messages without logging in. Each visitor can send one message every 8 seconds. Only visitors whose phone decoded an intelligent message reach the reply model, with at most 600 model calls per 24 hours and at most 3 replies waiting for the air at once. Device and operator endpoints use separate tokens. With the operator token, `GET /api/status` lists each board's role and the next signal, `POST /api/emitter/main/play` with `{"kind": "noise"}`, `"clock"`, or `"intelligent"` sends that signal as soon as the air is free (or plays `{"message": "..."}`), `POST /api/emitter/main/signals` with `{"random": false}` stops the random signals so boards play only what you send, and `POST /api/emitter/main/reset` returns to the state after a start: no conversations, new roles, and a beacon as the next signal. The debug page's **reset to the first state** also clears that page's saved messages and session. After any signal, the random pause starts over. The debug page has buttons for all of these. `python debug_host.py --manual` turns random signals off while it runs and back on when it stops; it needs `ALIVE_WEB_TOKEN` in its environment.

## Start the API service

The API needs only Python 3 from the standard library. On the server, copy `deploy/api.env.example` to `/etc/alive/api.env` (the install script does this on its first run), then fill in `OPENAI_API_KEY`, `ALIVE_WEB_ORIGIN`, and two different random tokens, for example from `openssl rand -hex 32`. Then install or update the service from a checkout:

```bash
sudo deploy/install.sh
```

The script copies the API into `/opt/alive`, installs `deploy/alive-api.service`, and restarts it. The service runs under a dynamic unprivileged user, listens on `127.0.0.1:8765`, and keeps reply state and recordings in `/var/lib/alive`. systemd starts it at boot, restarts it after a crash, and restarts it when it stops answering `/healthz` for 30 seconds. Check it with:

```bash
systemctl status alive-api
journalctl -u alive-api -n 50
curl http://127.0.0.1:8765/healthz
```

Tailscale Funnel provides the public HTTPS address and certificate without router changes. Install Tailscale, log in, and publish the local port:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale funnel --bg 8765
tailscale funnel status
```

Funnel must be allowed for the machine in the Tailscale admin console. The configuration survives reboots. Open `https://<machine>.<tailnet>.ts.net/healthz` from a separate network to verify reachability.

## Configure the ESP32

With power disconnected, verify the ESP32-C3, MAX98357, and speaker wiring against [the wiring diagram](docs/alive-esp32-max98357-wiring-usb-left.svg). Connect the speaker only between the amplifier's two speaker terminals. Copy `firmware/esp32_i2s_emitter/include/secrets.example.h` to the ignored `secrets.h` in the same directory, then fill in:

| Field | Value |
| --- | --- |
| `ALIVE_WIFI_NETWORKS` | Name and password pairs for 2.4 GHz networks without a browser login, in order of preference. See [Networks at the venue](#networks-at-the-venue). |
| `ALIVE_SERVER_URL` | The public HTTPS API base URL, without a trailing slash |
| `ALIVE_DEVICE_TOKEN` | The device token from `/etc/alive/api.env` |
| `ALIVE_SERVER_CA_CERT` | The trusted root CA PEM for the API certificate chain |

The firmware needs working internet time to verify HTTPS certificates. Without `ALIVE_SERVER_CA_CERT`, it uses an insecure TLS test fallback, so supply the correct CA before public use. Flash the `wifi_message` environment with PlatformIO, substituting the actual serial port:

```bash
platformio run --project-dir firmware/esp32_i2s_emitter -e wifi_message -t upload --upload-port /dev/ttyACM0
```

Power the ESP32 from a suitable USB supply for operation. It polls the public API over Wi-Fi. Check that the network permits outbound internet and does not require browser authentication. A dedicated hotspot or travel router is useful where venue Wi-Fi isolates devices.

## End-to-end check

1. Confirm that `alive-api` and Tailscale Funnel are running.
2. Power the ESP32 and wait for it to join Wi-Fi and poll the API.
3. Open the visitor link on a phone and enable the microphone. The first signal after the API starts is a beacon. The signals are inaudible. Watch for the chirps in the top part of the spectrogram, above the 17.5 kHz line, and for the reading in the top window. The status turns green (ALIVE) when a message arrives. To hear a signal sooner, use **noise now**, **clock now**, or **message now** on the debug page.
4. After a green message, send a short message. The intelligent unit plays the reply when the air is free, and it appears in green.
5. Repeat with the phone on a separate network to confirm public access.

A `401` can mean public demo mode is off or an operator action lacks its token. For **device offline**, check the ESP32 network, API URL, token, CA certificate, and polling. For a fetch or CORS error, check HTTPS and `ALIVE_WEB_ORIGIN`. If chirps show on the spectrogram but letters are missed, check speaker level, phone placement, and room noise; use a diagnostic recording from the debug page. Only an iPhone 13 Pro has been tested so far; other phones may filter frequencies near 20 kHz.

Each letter is a 360 ms chirp that falls by 48 Hz around its own center frequency. Centers start at 18,450 Hz for A and are 64 Hz apart, with space at 20,114 Hz. Two 18,200 Hz sync chirps open a message and one closes it, with 180 ms of silence after each chirp. A 40-character reply lasts 24 seconds. The codec has framing but no checksum. Noise and clocks never use sync chirps, which is how the phone tells them from a message. The Wi-Fi sender polls every 2 seconds with Wi-Fi modem sleep on, reuses its HTTPS connection, and runs the amplifier clock only while it plays. A 30-second watchdog resets it if a network call or audio write hangs. Keep the firmware, API, and static page builds on matching revisions.

## Test from the MacBook

Run these from a checkout on the MacBook (or any computer with Python 3.9 or newer). The first run fetches the operator token and OpenAI key from the T480 over `ssh t480` and keeps them in `~/.config/alive/`; `sudo deploy/install.sh` on the T480 puts them where that fetch looks. Each command prints the page URL, a QR code, the API, the units and their networks, and the other options.

- `python3 debug_host.py sim` needs no unit. The API runs inside the script, and the computer plays every signal through its speakers, so a phone held near it receives noise, clocks, and messages, and can answer. Turn the volume up. `--volume` sets the level; `--no-speaker` leaves the sound to **Simulate a unit on this page** in the Debug panel.
- `python3 debug_host.py units` uses the real units through the API at home and lists each unit's role and network as they change.
- Add `--manual` to either one to stop random signals; units then play only what you send from the Debug panel. `units` turns random signals back on when it stops.
- `python3 debug_host.py -kill` stops every running copy.

## How the units behave

The API deals new roles every 10 minutes and whenever a board joins, but never while a visitor's reply is waiting or within 3 minutes of their last message. With five boards there is always one intelligent board, one clock, one noise, and two more chosen from clock, noise, and at most one dead board. A board that stops polling for 60 seconds loses its role; if it was intelligent, another board takes over. After each signal the air stays silent for 3 seconds plus a random 6 to 20 seconds. The API also keeps 4 seconds free for the signal to reach the board; a board drops a signal that took longer. After a restart, the API waits 26 seconds, the length of the longest signal, before granting the first one. The next unprompted signal is noise 45 % of the time, a clock 30 %, and a beacon 25 %. A visitor's reply skips the pause. These numbers are constants at the top of `emitter.py`.

If a board gets no valid reply from the API for 60 seconds, it plays signals on its own: noise, its own clock, or now and then a beacon, every 25 to 90 seconds. Boards cannot hear each other, so offline signals can overlap now and then. Visitors can watch and decode, but nothing answers until the API is back. The board returns to API control on its next good poll and restarts itself after 10 minutes without one.

## Networks at the venue

The API stays on the T480 at home, behind Tailscale Funnel; keep it on and online during the show. At the venue the boards only need a 2.4 GHz network with a password, no browser login, and a route to the internet. They do not need to share a network with the phones or the MacBook. List every network you may use in `ALIVE_WIFI_NETWORKS` in `secrets.h`, most preferred first:

```c
#define ALIVE_WIFI_NETWORKS \
  {"ALIVE/ALIFE", "..."}, \
  {"My iPhone", "..."}
```

A board joins the first listed network it can see. Each poll reports the network's name, and `python3 debug_host.py units` shows it per board. When a network gives no route to the API for a minute, the board tries the next visible network it has not tried yet. After every visible network has failed, it starts over from the top. Reflash every board after changing the list.

- **Repeater on the university LAN.** The preferred setup. Connect the repeater to the LAN and check from a phone on its Wi-Fi that `https://<machine>.<tailnet>.ts.net/healthz` answers.
- **Phone hotspot.** The backup until HfK approves the repeater, and for demos. On an iPhone, turn on **Maximize Compatibility** in Personal Hotspot so it uses 2.4 GHz, and keep the Personal Hotspot screen open while the boards first join. An iPhone hotspot may not accept more than about five Wi-Fi devices, so leave other devices off it.

Visitors' phones use mobile data and never join these networks.

## Measure battery runtime

Each poll sends the board's MAC address, its uptime, and its last reset reason. The API appends one row per poll to `/var/lib/alive/device-polls/<UTC date>.csv` and keeps 14 days. To time a battery:

1. Charge the battery, connect the board, and note the switch-on time.
2. Leave it running until it stops. Do not open its serial port meanwhile, because that resets the board.
3. Read its last row: `sudo grep -h <MAC> /var/lib/alive/device-polls/*.csv | tail -1`. Runtime is the switch-on time to that row, accurate to about 2 seconds, or 15 seconds if it was playing.

`sudo python3 battery_runtime.py` prints every board's runtime since its last power-on and whether it is still running, so you do not need to note switch-on times.

Rows that simply stop mean the battery cut off. Uptime that keeps falling back near zero with reset reason `9` (brownout) means the voltage sagged and the board reboot-looped; the end of the last steady stretch is the useful runtime. Reason `1` is power-on, `3` a software restart, and `6` the task watchdog.

To get a phone alert when a board goes quiet, set `ALIVE_NOTIFY_URL` in `/etc/alive/api.env` to an [ntfy](https://ntfy.sh) topic URL with a long random name, or to a Discord webhook URL, then restart the service. The API sends one message when a board has not polled for 5 minutes while others still poll, with its runtime since power-on, and another when it polls again. If every board goes quiet, it sends a single message that points to Wi-Fi or the API instead, then judges each board again once the others return.

After an update, run `sudo deploy/install.sh` again when the API changes, and republish `docs/` when the phone page changes. Back up `/etc/alive/api.env` and `/var/lib/alive`.
