# ALIVE Demo

This repository now contains two layers:

- `demo_server.py` + `experience_model.py` — the current single-source museum prototype. It models the new loop: source ID + smoothed RSSI -> 4-zone state -> phone-side content and audio behavior.
- `base_demo.py` + `codebook.py` — the old SETI-inspired audio demo. It is still runnable, but it should be treated as legacy/reference material rather than the architecture for the next version.

## Museum phone demo

Run the temporary single-source demo from the T480:

```bash
python demo_server.py
```

The script prints a phone URL and a terminal QR code. Put the phone on the same network as the laptop, scan the QR code, and use the live controller in the terminal:

```text
zone very_near      # simulate the phone very close to the source
zone near
zone mid
zone far
reveal mid          # move the meaningful message to the mid zone
reveal very_near
status
quit
```

The phone UI receives server-sent state updates, displays the selected source and zone, and changes its sound after tapping **Enable audio**. The server currently simulates BLE-style RSSI for one source (`ALIVE-T480`) so the demo does not depend on browser BLE support. The code is structured so real observations can later be fed into the same `SourceSelector` via `/api/ble-observation`.

### Current architecture notes

- App structure: a small Python project with no frontend build step. `demo_server.py` serves the phone HTML/CSS/JS and exposes live JSON/SSE endpoints. `experience_model.py` contains reusable source, smoothing, zone, selection, and content mapping logic. `base_demo.py`, `codebook.py`, and `test_demo.py` are the legacy audio demo.
- Message/audio/signal pipeline, new path: the script emits or accepts observations shaped like `source_id + RSSI`; RSSI is smoothed in `RssiSmoother`; `zone_from_rssi` maps it into `very_near`, `near`, `mid`, or `far`; `SourceSelector` keeps the dominant stable source; `content_for_zone` decides whether to reveal the message. Phone audio is controlled by app state and is not the message carrier.
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

# 4. Run the museum phone demo
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

- `experience_model.py` — source ID, RSSI smoothing, 4-zone classification, stable source selection, and zone-to-content mapping
- `demo_server.py` — single-source T480 demo server, phone UI, live controller, JSON/SSE endpoints
- `simple_qr.py` — dependency-free QR helper used by the demo server
- `test_experience_model.py` — headless tests for the new source/zone model
- `codebook.py` — dual-tone frequency map, gap map, word dictionary, and gibberish detector
- `base_demo.py` — sender (Horn/Laser/Vocal bursts with embedded dual-tone carriers) + receiver (RMS burst detection, FFT peak extraction, redundancy check, 4-state classifier)
- `test_demo.py` — legacy headless audio tests (no sound, no matplotlib popup)
- `transmission_spectrogram.png` — saved visualization after each run
- `HOW_IT_WORKS.md` — technical documentation
