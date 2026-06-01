# ALIVE Base Demo

## Quickstart (with uv)

```bash
# 1. Make sure uv is installed (https://docs.astral.sh/uv/)
# 2. Inside this directory:
uv venv
uv pip install -r requirements.txt

# 3. Run tests (no audio output needed)
uv run python test_demo.py

# 4. Run the interactive demo
uv run python base_demo.py

# 5. With spectrogram window + laser tone mode
uv run python base_demo.py --show-plot --tone laser
```

## Command-line flags

- `--show-plot` — zeigt das Spectrogram-Fenster an (non-blocking, Enter zum Weiterfahren)
- `--tone {horn,laser,vocal}` — wählt den Burst-Sound:
  - `horn` (default) — mächtig, metallisch, aggressiv
  - `laser` — leiser, hoher Laser-Psst-Ton mit dezentem Rauschen
  - `vocal` — tiefes Growl, vokal-artig

## System requirement for audio playback

`sounddevice` needs the PortAudio library:
- **Debian/Ubuntu:** `sudo apt-get install libportaudio2`
- **Fedora/Nobara:** `sudo dnf install portaudio`
- **macOS:** usually pre-installed
- **Windows:** usually works out of the box

If PortAudio is missing, `base_demo.py` will still run but skip audio playback and show:
`[SENDER] Audio-Ausgabe nicht verfügbar (sounddevice/PortAudio fehlt).`

## Files

- `codebook.py` – alphabet → gap duration mapping
- `base_demo.py` – sender + receiver pipeline
- `test_demo.py` – headless tests (no sound, no matplotlib popup)
- `transmission_spectrogram.png` – gespeicherte Visualisierung nach jedem Lauf
