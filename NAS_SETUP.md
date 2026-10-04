# Deployment guide

This guide covers a static phone page, an HTTPS API hosted in a container, and an ESP32-C3 audio sender. Replace example domains, ports, directories, and device names with values for your deployment. Do not commit private network addresses, tokens, credentials, diagnostic recordings, or a QR code that identifies an installation.

```text
phone: https://site.example/alive/?api=https%3A%2F%2Fapi.example.com
  | HTTPS requests                                 ^ sound into phone microphone
  v                                                |
public HTTPS API -> local API container -> ESP32 on Wi-Fi -> amplifier -> speaker
```

The phone and ESP32 may use separate networks, but both must reach the public API. The page decodes audio locally; moving the API does not change microphone reception. The ESP32 ignores a play command left from before its reboot. A disconnected device cannot queue a late play request because the API checks recent device polling.

## Publish the phone page

Build the visitor and debug pages from `web/` with `bun run build` and `bun run build:debug`. Publish `docs/` on a static HTTPS host. Pass the public API base URL in the `api` query parameter of the visitor link or a privately generated QR code, enter it in connection settings, or set `VITE_ALIVE_API_URL` when building both pages. The browser saves a manually configured URL for later visits. A static host such as GitHub Pages cannot run the API. If a request reaches a static host, the page opens connection settings and explains how to correct the address. The debug page also has recording controls. Its local WAV download remains available if an optional API upload fails.

Set `ALIVE_WEB_ORIGIN` to the page's exact origin, such as `https://site.example`, without a path or trailing slash. Neither page should contain an access token. In public demo mode, visitors can send short messages and request playback without logging in. Message requests are limited to one every 10 seconds and 300 per rolling 24 hours, and playback requests cannot overlap. Device and operator endpoints use separate tokens.

## Start the API container

On a machine with Docker Compose, copy this repository into a deployment directory. Copy `nas.env.example` to the ignored `.env`, or run `sh nas-bootstrap.sh` to create it with separate random web and device tokens. Set `OPENAI_API_KEY`, `ALIVE_WEB_ORIGIN`, and `ALIVE_PUBLIC_DEMO=1` if public visitor access is desired. Restrict `.env` to the deploying user (`chmod 600 .env`). Keep the tokens distinct and private.

```bash
docker compose --env-file .env -f compose.nas.yml up -d --build
docker compose --env-file .env -f compose.nas.yml ps
docker compose --env-file .env -f compose.nas.yml logs --tail=50
curl -i http://127.0.0.1:8765/
```

The Compose service binds the API to host loopback port `8765`. Its named volume preserves prepared reply state and recordings across container restarts; `restart: unless-stopped` starts it again after a reboot. Use a public HTTPS reverse proxy to forward only the API to `http://127.0.0.1:8765`. A trusted domain and certificate or a public tunnel such as [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel) can provide HTTPS. Ordinary Tailscale Serve is private to a tailnet and cannot serve unrelated visitors. Keep machine administration ports outside the public proxy.

If using Funnel, the deployment machine must have Tailscale installed and authenticated. Check `tailscale version`, run `tailscale funnel --bg 8765`, and inspect `tailscale funnel status`. Install a version that supports Funnel and complete any approval requested by its admin console. Open the resulting public HTTPS URL from a separate network to verify reachability.

## Configure the ESP32

With power disconnected, verify the ESP32-C3, MAX98357, and speaker wiring against [the wiring diagram](docs/alive-esp32-max98357-wiring-usb-left.svg). Connect the speaker only between the amplifier's two speaker terminals. Copy `firmware/esp32_i2s_emitter/include/secrets.example.h` to the ignored `secrets.h` in the same directory, then fill in:

| Field | Value |
| --- | --- |
| `ALIVE_WIFI_SSID` / `ALIVE_WIFI_PASSWORD` | A password-protected 2.4 GHz network without a browser login |
| `ALIVE_SERVER_URL` | The public HTTPS API base URL, without a trailing slash |
| `ALIVE_DEVICE_TOKEN` | The device token from `.env` |
| `ALIVE_SERVER_CA_CERT` | The trusted root CA PEM for the API certificate chain |

The firmware needs working internet time to verify HTTPS certificates. Without `ALIVE_SERVER_CA_CERT`, it uses an insecure TLS test fallback, so supply the correct CA before public use. Flash the `wifi_message` environment with PlatformIO, substituting the actual serial port:

```bash
platformio run --project-dir firmware/esp32_i2s_emitter -e wifi_message -t upload --upload-port /dev/ttyACM0
```

Power the ESP32 from a suitable USB supply for operation. It polls the public API over Wi-Fi. Check that the network permits outbound internet and does not require browser authentication. A dedicated hotspot or travel router is useful where venue Wi-Fi isolates devices.

## End-to-end check

1. Confirm that the container and HTTPS proxy or tunnel are running.
2. Power the ESP32 and wait for it to join Wi-Fi and poll the API.
3. Open the visitor link with its `api` parameter on a phone, enable the microphone, send a short message, then press **Play signal** once. Hold the phone near the speaker and observe the translation.
4. Repeat with the phone on a separate network to confirm public access.

A `401` can mean public demo mode is off or an operator action lacks its token. For **device offline**, check the ESP32 network, API URL, token, CA certificate, and polling. For a fetch or CORS error, check HTTPS and `ALIVE_WEB_ORIGIN`. If audio plays but letters are missed, check speaker level, phone placement, and room noise; use a diagnostic recording from the debug page.

The firmware keeps at least 220 ms of silence between letters, uses 24 ms fades, and adds a one-second tail. The web decoder also uses letter spacing to resolve ambiguous low tones. The Wi-Fi sender polls every 100 ms while idle, reuses its HTTPS connection, and primes audio output with 50 ms of silence. The API advertises playback duration and a replay deadline so the page does not enable the next play too early. Keep the firmware, API, and static page builds on matching revisions.

After an update or reboot, check Compose status and the public HTTPS address. Rebuild the container when the API changes, and republish `docs/` when the phone page changes. Preserve `.env` and the Compose volume.
