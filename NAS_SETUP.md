# ALIVE: NAS and GitHub Pages setup

This is the laptop-free exhibition setup for the DS720+, ESP32-C3, MAX98357, speaker, and a visitor's phone. The phone loads the page from GitHub Pages. The NAS prepares a short reply, and the ESP32 plays its encoded sound once. The phone microphone decodes the sound locally.

```text
phone: https://jr-4b3.github.io/ALIVE/
   |  HTTPS API requests                         ^ sound into phone microphone
   v                                            |
NAS: public HTTPS address -> ALIVE container -> ESP32 on Wi-Fi -> amplifier -> speaker
                             OpenAI API
```

The phone, NAS, and ESP32 all need internet access. The phone and ESP32 may use different networks. No laptop is needed after firmware has been flashed. GitHub Pages hosts the page only; it cannot run the Python API, hold the OpenAI key, or send a Wi-Fi command to the ESP32 by itself.

## 0. Current hardware check

On 23 September, the connected ESP32 enumerated as `/dev/ttyACM0`, accepted `PLAY HI`, and made an audible sound through the MAX98357 and speaker. The website API also sent `HI` once successfully. No new USB over-current event appeared during those checks. Earlier PC logs **did** show over-current, so inspect the USB log again before flashing or leaving the installation running unattended. If an over-current event returns, unplug USB and investigate the power wiring before another active test. The successful short test does not prove that the setup is stable for a whole exhibition day.

The GitHub Pages QR page, public Funnel URL, NAS container, and a live GPT-6 Luna reply have since been verified. The remaining blocker is the ESP32's Wi-Fi association: it sees the home router and iPhone hotspot but repeatedly reports authentication expiry; a direct WPA2 PC hotspot also failed. The same failure occurs in firmware without I2S initialization. **Play signal** correctly reports `ESP32 is offline` until this is resolved. Inspect the ESP32 antenna area and power wiring before relying on the no-laptop setup at the exhibition.

## 1. Publish the matching phone page

GitHub Pages for `JR-4B3/ALIVE` is set to the `main` branch's `/docs` folder, at <https://jr-4b3.github.io/ALIVE/>. Include the built `docs/` files when publishing. The printable [exhibition QR](docs/ALIVE-QR.svg) points to that page. On the published page, the NAS address is already filled in and visitors do not enter a token. Connection settings are tucked under a disclosure for the operator.

Do not put `.env`, `secrets.h`, the OpenAI API key, or either private access token in GitHub. Public exhibition mode allows only sending a short message and requesting playback without a token. It limits messages to one every 10 seconds and 300 per running 24-hour window, and prevents overlapping playback requests. The ESP32 device endpoint and operator endpoints remain private. These limits bound normal use and basic abuse; monitor API usage during the exhibition.

## 2. Prepare the DS720+

1. In DSM **Package Center**, install **Container Manager** and **Tailscale**. Sign in to Tailscale on the NAS. You can use a free tailnet. Update Tailscale if its installed version is below `1.38.3`; Funnel requires that version or later. Synology's package may lag behind current releases.
2. In DSM **Control Panel → Terminal & SNMP**, enable SSH temporarily. On the current home network, the NAS was found at `192.168.178.28` (`DS720.local`), with SSH port 22 open. Connect from your PC with `ssh YOUR_DSM_USER@192.168.178.28` or `ssh YOUR_DSM_USER@DS720.local`. Use your actual DSM username; the DSM user needs administrator rights for `sudo`. The IP can change if the router assigns a different DHCP address later.
3. Create `/volume1/docker/alive` in File Station. Place a copy of the *same published ALIVE revision* there, including `Dockerfile.nas`, `compose.nas.yml`, `nas.env.example`, the Python files, and `docs/`. A ZIP of the published GitHub revision extracted in File Station works. If your volume is not named `volume1`, substitute its actual path throughout.
4. In the SSH session, go to the project directory and run the included bootstrap script. It creates `.env` with two different random tokens and leaves an existing `.env` untouched:

   ```bash
   cd /volume1/docker/alive
   sh nas-bootstrap.sh
   ```

5. Edit `.env` on the NAS. The script has already filled `ALIVE_WEB_TOKEN` and `ALIVE_DEVICE_TOKEN`; leave them private and distinct. Set `OPENAI_API_KEY` to your working key and `ALIVE_PUBLIC_DEMO=1` for the QR experience. Keep `ALIVE_WEB_ORIGIN=https://jr-4b3.github.io` exactly as shown; the `/ALIVE/` path does **not** belong in an origin. Save the file, then restrict its permissions:

   ```bash
   chmod 600 .env
   ```

   Avoid putting real secrets in screenshots, chat, or a Git commit. The old key file on the laptop is not automatically copied to the NAS.

6. Start the container and inspect its logs:

   ```bash
   sudo /usr/local/bin/docker compose --env-file .env -f compose.nas.yml up -d --build
   sudo /usr/local/bin/docker compose --env-file .env -f compose.nas.yml ps
   sudo /usr/local/bin/docker compose --env-file .env -f compose.nas.yml logs --tail=50
   curl -i http://127.0.0.1:8765/
   ```

   The last command should return the ALIVE HTML page. The container listens on the NAS's **localhost** port `8765`; it does not expose DSM or the API directly to the LAN. `restart: unless-stopped` starts it again after a NAS reboot, and its named volume preserves prepared reply state. Container Manager's **Project** screen can show the running service. If `docker compose` is unavailable on your DSM version, check Container Manager's Project support or install the current Container Manager package before changing the Compose file.

## 3. Give the API a public HTTPS address

On the NAS SSH session, run:

```bash
sudo /var/packages/Tailscale/target/bin/tailscale version
sudo /var/packages/Tailscale/target/bin/tailscale status
sudo /var/packages/Tailscale/target/bin/tailscale funnel --bg 8765
sudo /var/packages/Tailscale/target/bin/tailscale funnel status
```

The first Funnel run may print a link to approve Funnel, MagicDNS, HTTPS certificates, or a policy change in the Tailscale admin console. Follow that link and rerun the command. Record the resulting **public `https://...ts.net` URL**. `--bg` makes Funnel persist across Tailscale restarts and NAS reboots. Funnel publishes only the local ALIVE service; visitors do not need Tailscale. Ordinary `tailscale serve` is private to your tailnet and is not the visitor setup.

Turn off the phone's Wi-Fi for this check and open the Funnel URL in its browser. The ALIVE page or API root should load over HTTPS. If Funnel does not start, first check the installed Tailscale version and its Funnel status. Do not open DSM's admin port to the public internet for this project.

## 4. Set up the ESP32 for Wi-Fi

The current speaker test worked with the connected amplifier; there is no need to undo that wiring for this guide. Before flashing, check that USB remains stable and power down if you need to adjust any connection. In the *local* repository, copy `firmware/esp32_i2s_emitter/include/secrets.example.h` to `secrets.h` in the same directory. This file is Git-ignored. Fill in:

| Field | Value |
| --- | --- |
| `ALIVE_WIFI_SSID` / `ALIVE_WIFI_PASSWORD` | The exhibition Wi-Fi or a dedicated hotspot the ESP32 can join |
| `ALIVE_SERVER_URL` | The Funnel `https://...ts.net` URL, without a trailing slash |
| `ALIVE_DEVICE_TOKEN` | The device token from the NAS `.env` |
| `ALIVE_SERVER_CA_CERT` | The trusted root CA PEM for the Funnel certificate |

Use a normal password-protected 2.4 GHz Wi-Fi network without a browser login page. A phone hotspot or travel router is often simpler than venue Wi-Fi. The firmware needs working internet time for HTTPS certificate verification. **Add the CA certificate before exhibition use**: without `ALIVE_SERVER_CA_CERT`, the current firmware uses an insecure TLS fallback. Once the exact Funnel URL exists, verify its certificate chain and put the matching trusted root CA PEM in `secrets.h`; do not copy an arbitrary certificate from a web page.

Flash the Wi-Fi firmware once while the hardware is known safe, substituting the actual USB port:

```bash
.tmp/platformio-venv/bin/platformio run --project-dir firmware/esp32_i2s_emitter -e wifi_message -t upload --upload-port /dev/ttyACM0
```

After flashing, the ESP32 polls the public API using the **device** token. On first contact it ignores any old play command left from before its reboot. At the venue, power it from a suitable USB power supply; the laptop is not in the runtime path. Keep the amplifier's speaker outputs connected only across the passive speaker terminals, never to GND.

## 5. Run the complete test from the phone

1. Confirm the NAS container is running and `sudo /var/packages/Tailscale/target/bin/tailscale funnel status` still shows the public address.
2. Power the ESP32, then wait for it to join its configured Wi-Fi and poll the NAS. If **Play signal** reports device offline, check its Wi-Fi, URL, device token, and certificate before testing audio.
3. On the phone, scan the [exhibition QR](docs/ALIVE-QR.svg) or open <https://jr-4b3.github.io/ALIVE/>. Tap **Enable microphone** and allow access. Visitors do not need the NAS URL, private token, Tailscale, or the exhibition Wi-Fi.
4. Type a short message in **Contact** and tap **Send**. The NAS asks GPT-6 Luna for a reply capped at 12 characters. Tap **Play signal** once. One press should cause one playback. Hold the phone approximately 10–25 cm from the speaker and watch the translation. Use **Wait 2s** before another playback if needed.
5. Repeat once with the phone on mobile data and the ESP32 on its own Wi-Fi or hotspot. This checks that the public address works without the laptop or a shared local network.

If a visitor sees **401**, check `ALIVE_PUBLIC_DEMO=1` on the NAS and restart the container. If it shows **device offline**, check the ESP32's Wi-Fi, device token, URL, and polling. If it shows **failed to fetch** or a CORS error, check the public HTTPS URL and `ALIVE_WEB_ORIGIN`. If the sound plays but letters are missed, inspect speaker level, phone placement, and room noise; moving the API to the NAS does not by itself improve acoustic decoding.

## 6. Keeping it running

After a NAS reboot, confirm the Compose project and Funnel status before opening the exhibition. Use the two commands below for a quick check:

```bash
cd /volume1/docker/alive
sudo /usr/local/bin/docker compose --env-file .env -f compose.nas.yml ps
sudo /var/packages/Tailscale/target/bin/tailscale funnel status
```

When the code changes, copy the matching published revision to the NAS and run `sudo /usr/local/bin/docker compose --env-file .env -f compose.nas.yml up -d --build` again. Preserve `.env` and the Compose volume. GitHub Pages changes and NAS updates are separate deployments; keep their API versions matched.

Reference documentation: [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel), [Funnel CLI and persistence](https://tailscale.com/docs/reference/tailscale-cli/funnel), [Tailscale on Synology](https://tailscale.com/docs/integrations/synology), [Synology Container Manager projects](https://kb.synology.com/en-global/DSM/help/ContainerManager/docker_project).
