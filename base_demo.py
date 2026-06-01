import argparse
import sys
import numpy as np
import matplotlib.pyplot as plt
from scipy.io import wavfile
from codebook import CODEBOOK, REVERSE

try:
    import sounddevice as sd
except OSError:
    sd = None

# --- KONFIGURATION ---
SAMPLE_RATE = 44100
BURST_LEN = 0.22
BURST_AMP = 0.6
THRESHOLD = 0.1
TOLERANCE = 40


def make_burst(mode="horn"):
    """Erzeugt einen Burst im gewählten Stil."""
    t = np.linspace(0, BURST_LEN, int(SAMPLE_RATE * BURST_LEN), endpoint=False)

    if mode == "laser":
        carrier = np.sin(2 * np.pi * 4200 * t)
        sweep = np.sin(2 * np.pi * (4800 - 600 * t / BURST_LEN) * t)
        noise = np.random.normal(0, 0.08, size=t.shape)
        burst = (carrier * 0.4 + sweep * 0.35 + noise) * 0.35
        envelope = np.ones_like(t)
        attack = int(0.001 * SAMPLE_RATE)
        decay = int(0.008 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        burst = burst * envelope * BURST_AMP

    elif mode == "vocal":
        f_start, f_end = 180, 140
        freq = f_start + (f_end - f_start) * (t / BURST_LEN)
        phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
        body = np.sin(phase)
        body += 0.35 * np.sin(3 * phase)
        body += 0.18 * np.sin(5 * phase)
        shimmer = np.sin(2 * np.pi * 251 * t) * 0.25
        sub_env = np.exp(-t * 20)
        sub = np.sin(2 * np.pi * 55 * t) * sub_env * 0.6
        noise = np.random.normal(0, 0.12, size=t.shape)
        burst = body * 0.6 + shimmer * 0.3 + sub + noise * 0.2
        envelope = np.ones_like(t)
        attack = int(0.015 * SAMPLE_RATE)
        decay = int(0.030 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        tremolo = 1.0 + 0.15 * np.sin(2 * np.pi * 7 * t)
        burst = burst * envelope * tremolo * BURST_AMP
        burst = np.clip(burst, -0.95, 0.95)

    else:  # mode == "horn" (default)
        fundamental = np.sin(2 * np.pi * 100 * t)
        overtones = 0.40 * np.sin(2 * np.pi * 300 * t)
        overtones += 0.25 * np.sin(2 * np.pi * 500 * t)
        overtones += 0.15 * np.sin(2 * np.pi * 700 * t)
        high = 0.35 * np.sin(2 * np.pi * 1120 * t)
        click_env = np.exp(-t * 60)
        click = 0.5 * np.sin(2 * np.pi * 1600 * t) * click_env
        noise = np.random.normal(0, 0.18, size=t.shape)
        burst = fundamental * 0.55 + overtones + high * 0.6 + click + noise * 0.25
        burst = np.clip(burst * 2.2, -0.88, 0.88)
        envelope = np.ones_like(t)
        attack = int(0.003 * SAMPLE_RATE)
        decay = int(0.015 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        burst = burst * envelope * BURST_AMP

    burst = burst / (np.max(np.abs(burst)) + 1e-9) * BURST_AMP
    return burst


def encode(text, mode="horn"):
    """Text → NumPy-Audio-Array."""
    burst = make_burst(mode=mode)
    signal = []
    for ch in text.upper():
        if ch not in CODEBOOK:
            continue
        signal.extend(burst)
        extra_ms = CODEBOOK[ch]
        extra_samples = int(SAMPLE_RATE * (extra_ms / 1000.0))
        signal.extend(np.zeros(extra_samples))
    signal.extend(burst)
    return np.array(signal, dtype=np.float32)


def save_wav(name, signal):
    wavfile.write(name, SAMPLE_RATE, (signal * 32767).astype(np.int16))


def load_wav(name):
    rate, data = wavfile.read(name)
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32767.0
    return data


def find_bursts(signal):
    """Gibt Liste von (start_index, end_index) der Bursts zurück."""
    above = np.abs(signal) > THRESHOLD
    edges = np.diff(above.astype(int))
    starts = np.where(edges == 1)[0] + 1
    ends = np.where(edges == -1)[0] + 1
    if above[0]:
        starts = np.insert(starts, 0, 0)
    if above[-1]:
        ends = np.append(ends, len(signal))
    regions = list(zip(starts, ends))

    MIN_BURST_GAP_MS = 10
    MIN_BURST_GAP_SAMPLES = int(SAMPLE_RATE * MIN_BURST_GAP_MS / 1000.0)
    merged = []
    for s, e in regions:
        if merged and s - merged[-1][1] < MIN_BURST_GAP_SAMPLES:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def classify_gaps(gaps_ms):
    """Einfache Regel-Klassifikation für die Demo."""
    if len(gaps_ms) == 0:
        return "NOISE -> STATUS: DEAD"

    if len(gaps_ms) >= 3:
        if max(gaps_ms) - min(gaps_ms) <= TOLERANCE:
            return "CLOCK (periodic) -> STATUS: DEAD"

    known = 0
    for g in gaps_ms:
        hits = [abs(g - v) <= TOLERANCE for v in CODEBOOK.values()]
        if any(hits):
            known += 1
    if known < len(gaps_ms) * 0.5:
        return "NOISE (unstructured) -> STATUS: DEAD"

    return "LANGUAGE (structured, non-periodic) -> STATUS: ALIVE"


def decode(signal):
    """Audio-Array → Text."""
    regions = find_bursts(signal)
    num_bursts = len(regions)
    num_info_bursts = max(0, num_bursts - 1)
    print(f"  Empfänger hat {num_info_bursts} Informations-Bursts erkannt "
          f"({num_bursts} total inkl. Abschluss-Puls).")

    gaps = []
    for i in range(len(regions) - 1):
        end_this = regions[i][1]
        start_next = regions[i + 1][0]
        ms = int(round(((start_next - end_this) / SAMPLE_RATE) * 1000.0 / 50.0)) * 50
        gaps.append(ms)
    print(f"  Gemessene Pausen (ms): {gaps}")

    verdict = classify_gaps(gaps)
    print(f"\n>>> {verdict} <<<")

    chars = []
    for g in gaps:
        closest = min(CODEBOOK.values(), key=lambda v: abs(v - g))
        if abs(closest - g) <= TOLERANCE:
            chars.append(REVERSE[closest])
        else:
            chars.append('?')
    return "".join(chars)


def plot_signal(audio, show=False):
    """Erzeugt Wellenform + Spectrogram und speichert beides."""
    import warnings

    plt.rcParams['figure.facecolor'] = '#0a0a0a'
    plt.rcParams['axes.facecolor'] = '#0a0a0a'
    plt.rcParams['axes.edgecolor'] = '#444444'
    plt.rcParams['axes.labelcolor'] = '#aaaaaa'
    plt.rcParams['xtick.color'] = '#888888'
    plt.rcParams['ytick.color'] = '#888888'

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={'height_ratios': [1, 3]})

    ax_wave = axes[0]
    time_axis = np.arange(len(audio)) / SAMPLE_RATE
    ax_wave.plot(time_axis, audio, color='#00ff88', linewidth=0.8)
    ax_wave.axhline(THRESHOLD, color='red', linestyle='--', alpha=0.5, linewidth=0.8)
    ax_wave.axhline(-THRESHOLD, color='red', linestyle='--', alpha=0.5, linewidth=0.8)
    ax_wave.set_title("TRANSMISSION SIGNAL – Amplitude über Zeit", color='white', fontsize=11)
    ax_wave.set_ylabel("Amp", color='#aaaaaa')
    ax_wave.set_xlim(0, time_axis[-1])
    ax_wave.set_ylim(-1, 1)
    ax_wave.tick_params(colors='#888888')

    ax_spec = axes[1]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        Pxx, freqs, bins, im = ax_spec.specgram(
            audio,
            Fs=SAMPLE_RATE,
            NFFT=512,
            noverlap=400,
            cmap='viridis',
            scale='dB',
            vmin=-100,
            vmax=-20
        )
    ax_spec.set_title("SPECTRAL ANALYSIS – Frequenz über Zeit", color='white', fontsize=11)
    ax_spec.set_xlabel("Zeit [s]", color='#aaaaaa')
    ax_spec.set_ylabel("Frequenz [Hz]", color='#aaaaaa')
    ax_spec.set_ylim(0, 6000)
    ax_spec.tick_params(colors='#888888')

    cbar = fig.colorbar(im, ax=ax_spec, orientation='vertical', pad=0.02)
    cbar.set_label("Intensität [dB]", color='#aaaaaa')
    cbar.ax.yaxis.set_tick_params(color='#888888')
    cbar.ax.yaxis.set_tick_params(labelcolor='#aaaaaa')

    plt.tight_layout()

    plot_name = "transmission_spectrogram.png"
    plt.savefig(plot_name, dpi=150, facecolor='#0a0a0a')
    print(f"[SENDER] Wellenform + Spectrogram gespeichert als {plot_name}")

    if show:
        plt.show(block=False)
        try:
            input("[SENDER] Drücke Enter, um fortzufahren...")
        except (KeyboardInterrupt, EOFError):
            print("\n[SENDER] Weiter...")
        plt.close('all')
    else:
        plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="ALIFE Base Demo – Signal → Senden → Empfangen"
    )
    parser.add_argument(
        "--show-plot",
        action="store_true",
        help="Zeigt das Spectrogram-Fenster an (non-blocking)"
    )
    parser.add_argument(
        "--horn",
        action="store_true",
        default=True,
        help="Mächtiger metallischer Horn-Burst (default)"
    )
    parser.add_argument(
        "--laser",
        action="store_true",
        help="Leiser hoher Laser-Psst-Ton"
    )
    parser.add_argument(
        "--vocal",
        action="store_true",
        help="Tiefes Growl / vokale Silbe"
    )
    args = parser.parse_args()

    # Tone-Modus auswählen
    if args.laser:
        tone_mode = "laser"
    elif args.vocal:
        tone_mode = "vocal"
    else:
        tone_mode = "horn"

    print("=" * 50)
    print("ALIFE BASE DEMO: Signal → Senden → Empfangen")
    print("=" * 50)
    print(f"[CONFIG] Ton-Modus: {tone_mode}")
    if args.show_plot:
        print("[CONFIG] Plot wird angezeigt (non-blocking)")
    msg = input("\nGib einen Text ein (nur A-Z, Leerzeichen): ").strip()
    print(f"\n[SENDER] Kodiere Nachricht: '{msg}'")

    audio = encode(msg, mode=tone_mode)
    filename = "transmission.wav"
    save_wav(filename, audio)
    print(f"[SENDER] Gespeichert als {filename}")
    if sd is not None:
        print(f"[SENDER] Spiele Signal ab ({len(audio)/SAMPLE_RATE:.2f} Sekunden)...")
        sd.play(audio, SAMPLE_RATE)
        sd.wait()
    else:
        print("[SENDER] Audio-Ausgabe nicht verfügbar (sounddevice/PortAudio fehlt).")

    plot_signal(audio, show=args.show_plot)

    print(f"\n[EMPFAENGER] Lade {filename}...")
    received = load_wav(filename)
    decoded = decode(received)
    print(f"[EMPFAENGER] Dekodierter Text: '{decoded}'")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!] Abbruch durch Benutzer (Ctrl+C).")
        raise SystemExit(0)
