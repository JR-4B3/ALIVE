# Deployment guide

This guide covers a static phone page, an HTTPS API run as a systemd service on a Linux server, and an ESP32-C3 audio sender. Replace example domains, ports, directories, and device names with values for your deployment. Do not commit private network addresses, tokens, credentials, diagnostic recordings, or a QR code that identifies an installation.

```text
phone: https://site.example/alive/?api=https%3A%2F%2Fapi.example.com
  | HTTPS requests                                 ^ sound into phone microphone
  v                                                |
Tailscale Funnel -> API service -> ESP32 on Wi-Fi -> amplifier -> speaker
```

The phone and ESP32 may use separate networks, but both must reach the public API. The page decodes audio locally; moving the API does not change microphone reception. The ESP32 ignores a play command left from before its reboot. A disconnected device cannot queue a late play request because the API checks recent device polling.

## Publish the phone page

Build the visitor and debug pages from `web/` with `bun run build` and `bun run build:debug`. Publish `docs/` on a static HTTPS host. The visitor page has no connection settings; pass the public API base URL in the `api` query parameter of the visitor link or a privately generated QR code. It is saved in that browser after the first request. A new browser needs the parameter in its link. The debug page also has a manual API URL field and recording controls. Its local WAV download remains available if an optional API upload fails.

Set `ALIVE_WEB_ORIGIN` to the page's exact origin, such as `https://site.example`, without a path or trailing slash. Neither page should contain an access token. In public demo mode, visitors can send short messages and request playback without logging in. Message requests are limited to one every 10 seconds and 300 per rolling 24 hours, and playback requests cannot overlap. Device and operator endpoints use separate tokens.

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
| `ALIVE_WIFI_SSID` / `ALIVE_WIFI_PASSWORD` | A password-protected 2.4 GHz network without a browser login |
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
3. Open the visitor link with its `api` parameter on a phone, enable the microphone, send a short message, then press **Play signal** once. Hold the phone near the speaker and observe the translation.
4. Repeat with the phone on a separate network to confirm public access.

A `401` can mean public demo mode is off or an operator action lacks its token. For **device offline**, check the ESP32 network, API URL, token, CA certificate, and polling. For a fetch or CORS error, check HTTPS and `ALIVE_WEB_ORIGIN`. If audio plays but letters are missed, check speaker level, phone placement, and room noise; use a diagnostic recording from the debug page.

The firmware keeps at least 220 ms of silence between letters, uses 24 ms fades, and adds a one-second tail. The web decoder also uses letter spacing to resolve ambiguous low tones. The Wi-Fi sender polls every 2 seconds with Wi-Fi modem sleep on, reuses its HTTPS connection, and runs the amplifier clock only while it plays. It restarts itself after 3 minutes without a valid poll, and a 30-second watchdog resets it if a network call or audio write hangs. The API advertises playback duration and a replay deadline so the page does not enable the next play too early. Keep the firmware, API, and static page builds on matching revisions.

After an update, run `sudo deploy/install.sh` again when the API changes, and republish `docs/` when the phone page changes. Back up `/etc/alive/api.env` and `/var/lib/alive`.

## Battery runtime test

Use one fully charged cell in its protected holder and regulated supply, with the ESP32, amplifier, speaker, Wi-Fi, and API configured exactly as they will be used. Keep USB and other external power disconnected during the run. The monitor needs a separate computer that stays on. If the computer can ping the ESP32 directly, use its IP address and no API token is needed:

```bash
python battery_runtime_monitor.py --host 192.0.2.10 --output battery-runs/baseline-1
```

The ESP32's IP address appears as `WiFi ready: ...` in its USB serial log. Confirm that ping works before unplugging USB. Keep the ESP32 on the same Wi-Fi network during the run, and check its IP again after the battery boot; DHCP may assign a different address. Ping proves network reachability, not that the API is working.

If direct ping is unavailable, the monitor can instead read the API's existing `deviceOnline` field without sending device heartbeats itself. Set the API URL and the web/operator token in the monitor computer's environment. Keep the token out of command history and reports. For example, load it from a local private environment file, then run:

```bash
python battery_runtime_monitor.py --api-url https://api.example.com --output battery-runs/baseline-1
```

The monitor writes `battery-runs/baseline-1.csv` after every check and updates `battery-runs/baseline-1.json` with the current status. Leave it running, then switch on the battery. Wait for `Device first online` before leaving the test. Write down the switch-on time and make a few representative plays during the run. A continuous two-minute offline period is flagged as `offline_unverified`; the monitor continues so it can record a recovery. Once that happens, check whether the battery protection cut off, the ESP32 lost power, Wi-Fi failed, or the API went down. Stop the monitor with Ctrl-C after the physical check.

The runtime estimate is between the first-online time and the last-online/first-offline times in the JSON report. In API mode, the monitor reads `/api/emitter/main/status`, which does not refresh device presence. `deviceOnline` stays true for up to 30 seconds after the last ESP32 poll, so API-mode times are accurate to about 30 seconds; the monitor checks every two seconds. In ping mode, an occasional lost packet or IP change can look like a power outage, so check any offline result against the hardware and Wi-Fi. Probe errors are logged separately and do not count as device death. The script does not measure current, voltage, cell capacity, or remaining charge; use a USB power meter or battery logger for those measurements. Keep the monitor computer awake for the whole test and use a new output prefix for each run. If the monitor stops early, restart it with the same `--output` and `--resume` to append to the run.
