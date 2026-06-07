# ALIVE Demo

This repository now contains two layers:

- `demo_server.py` + `audio_beacon.py` + `experience_model.py` — the current single-source museum prototype. It models the new loop: laptop beacon -> phone microphone sensing -> smoothed 4-zone state -> phone-side content and audio behavior.
- `base_demo.py` + `codebook.py` — the old SETI-inspired audio demo. It is still runnable, but it should be treated as legacy/reference material rather than the architecture for the next version.

## Museum phone demo

Run the temporary single-source demo from the T480:

```bash
python demo_server.py
```

The server starts a continuous laptop audio beacon, prints a phone URL, and shows a terminal QR code. Put the phone on the same network as the laptop, scan the QR code, accept the local HTTPS warning if shown, and tap **Start microphone sensing** in the phone UI. Move the phone closer to or farther from the laptop speaker to change the detected zone.

Use the live controller only to move the message target zone during the presentation:

```text
reveal mid          # move the meaningful message to the mid zone
reveal very_near
status
quit
```

Terminal proximity simulation is now an explicit fallback:

```bash
python demo_server.py --debug-sim
```

In that mode, `zone mid`, `zone far`, etc. can still drive the state manually. The default path is microphone sensing from the phone, posted to `/api/audio-observation`.

### Current architecture notes

- App structure: a small Python project with no frontend build step. `demo_server.py` serves the phone HTML/CSS/JS and exposes live JSON/SSE endpoints. `audio_beacon.py` owns the laptop speaker emitter. `experience_model.py` contains reusable source, smoothing, zone, selection, audio observation, and content mapping logic. `base_demo.py`, `codebook.py`, and `test_demo.py` are the legacy audio demo.
- Message/audio/signal pipeline, new path: the laptop emits a continuous two-tone beacon. The phone uses Web Audio microphone input, estimates beacon tone strength, smooths it, applies hysteresis, maps it into `very_near`, `near`, `mid`, or `far`, and posts the observation to the server. The selected zone plus `reveal_zone` decides whether the message is revealed. Phone response audio is controlled by app state and is not the message carrier.
- BLE-ready path: `SourceSelector`, `RssiSmoother`, and `zone_from_rssi` remain reusable for later source ID + RSSI observations. They are not the primary demo path in this iteration.
- Temporal/frequency encoding, old path: `base_demo.py::encode` maps typed text into bursts; `codebook.py::FREQ_MAP` defines dual frequency pairs; `codebook.py::GAP_MAP` defines timing gaps.
- Decoding, old path: `base_demo.py::find_bursts`, `detect_letter_from_burst`, and `decode` perform burst detection, FFT extraction, gap decoding, and redundancy merge.
- Old SETI-inspired/demo-only parts: `codebook.py` frequency/gap alphabet, `COMMON_WORDS`, `COMMON_BIGRAMS`, `is_plausible_text`, and `base_demo.py::classify_signal` implement the old `NOISE/CLOCK/GIBBERISH/LANGUAGE` story.
- Obsolete for the new direction: gibberish detection, full-message audio decoding, gap redundancy, and the language/dead classifier should not be part of the museum interaction core.
- Reusable: the old burst textures in `make_burst` can inspire sound design, and `plot_signal` can remain useful for presentation visuals. The tests show the legacy path still works.
- Refactor first: keep the old audio demo behind a `legacy_` boundary, then make real BLE observation ingestion another input adapter for `experience_model.py`.

## Quickstart (with uv)

```bash
# 1. Make sure uv is installed (https://docs.astral.sh/uv/)
# 2. Inside this directory:
uv venv
uv pip install -r requirements.txt

# 3. Run tests (no audio output needed)
uv run python test_experience_model.py
uv run python test_demo.py

# 4. Run the museum phone demo with laptop audio beacon
uv run python demo_server.py

# 5. Run the legacy interactive audio demo (default = laser)
uv run python base_demo.py

# 6. Legacy spectrogram window + horn or vocal style
uv run python base_demo.py --show-plot --horn
uv run python base_demo.py --show-plot --vocal
```

## Command-line flags

- `--show-plot` — show spectrogram window (non-blocking, press Enter to continue)
- `--laser` — quiet high laser psst tone with subtle noise (**default**)
- `--horn` — powerful metallic aggressive horn burst
- `--vocal` — deep growl, vocal-like syllable

## System requirement for audio playback

`sounddevice` needs the PortAudio library:
- **Debian/Ubuntu:** `sudo apt-get install libportaudio2`
- **Fedora/Nobara:** `sudo dnf install portaudio`
- **macOS:** usually pre-installed
- **Windows:** usually works out of the box

If PortAudio is missing, `base_demo.py` will still run but skip audio playback and show:
`[SENDER] Audio output unavailable (sounddevice/PortAudio missing).`

## Files

- `audio_beacon.py` — laptop-side continuous two-tone audio beacon emitter
- `experience_model.py` — source ID, RSSI smoothing, 4-zone classification, stable source selection, and zone-to-content mapping
- `demo_server.py` — single-source T480 demo server, phone microphone UI, live controller, JSON/SSE endpoints
- `simple_qr.py` — dependency-free QR helper used by the demo server
- `test_experience_model.py` — headless tests for the new source/zone model
- `codebook.py` — dual-tone frequency map, gap map, word dictionary, and gibberish detector
- `base_demo.py` — sender (Horn/Laser/Vocal bursts with embedded dual-tone carriers) + receiver (RMS burst detection, FFT peak extraction, redundancy check, 4-state classifier)
- `test_demo.py` — legacy headless audio tests (no sound, no matplotlib popup)
- `transmission_spectrogram.png` — saved visualization after each run
- `HOW_IT_WORKS.md` — technical documentation
