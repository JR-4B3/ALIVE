# ALIVE Base Demo

## Quickstart (with uv)

```bash
# 1. Make sure uv is installed (https://docs.astral.sh/uv/)
# 2. Inside this directory:
uv venv
uv pip install -r requirements.txt

# 3. Run tests (no audio output needed)
uv run python test_demo.py

# 4. Run the interactive demo (default = laser)
uv run python base_demo.py

# 5. With spectrogram window + horn or vocal style
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

- `codebook.py` — dual-tone frequency map, gap map, word dictionary, and gibberish detector
- `base_demo.py` — sender (Horn/Laser/Vocal bursts with embedded dual-tone carriers) + receiver (RMS burst detection, FFT peak extraction, redundancy check, 4-state classifier)
- `test_demo.py` — headless tests (no sound, no matplotlib popup)
- `transmission_spectrogram.png` — saved visualization after each run
- `HOW_IT_WORKS.md` — technical documentation
