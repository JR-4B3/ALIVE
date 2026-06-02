import argparse
import sys
import numpy as np
import matplotlib.pyplot as plt
from scipy.io import wavfile
from scipy.fft import rfft, rfftfreq
from codebook import FREQ_MAP, GAP_MAP, REV_FREQ, REV_GAP, is_plausible_text

try:
    import sounddevice as sd
except OSError:
    sd = None

# config
SAMPLE_RATE = 44100
BURST_LEN = 0.22
BURST_AMP = 0.6
THRESHOLD = 0.1
TOLERANCE = 40
FREQ_TOLERANCE = 75


def make_burst(letter, mode="laser"):
    """Synthesize a burst. Each letter gets its original sound texture
    (horn / laser / vocal) plus two sine carriers at the codebook frequencies.
    Ear hears the texture; FFT sees the two clean peaks."""
    if letter not in FREQ_MAP:
        return np.zeros(0)

    low_f, high_f = FREQ_MAP[letter]
    t = np.linspace(0, BURST_LEN, int(SAMPLE_RATE * BURST_LEN), endpoint=False)

    # original texture
    if mode == "laser":
        carrier = np.sin(2 * np.pi * 4200 * t)
        sweep = np.sin(2 * np.pi * (4800 - 600 * t / BURST_LEN) * t)
        noise = np.random.normal(0, 0.08, size=t.shape)
        texture = (carrier * 0.4 + sweep * 0.35 + noise) * 0.35
        envelope = np.ones_like(t)
        attack = int(0.001 * SAMPLE_RATE)
        decay = int(0.008 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        texture = texture * envelope

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
        texture = body * 0.6 + shimmer * 0.3 + sub + noise * 0.2
        envelope = np.ones_like(t)
        attack = int(0.015 * SAMPLE_RATE)
        decay = int(0.030 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        tremolo = 1.0 + 0.15 * np.sin(2 * np.pi * 7 * t)
        texture = texture * envelope * tremolo
        texture = np.clip(texture, -0.95, 0.95)

    else:  # horn
        fundamental = np.sin(2 * np.pi * 100 * t)
        overtones = 0.40 * np.sin(2 * np.pi * 300 * t)
        overtones += 0.25 * np.sin(2 * np.pi * 500 * t)
        overtones += 0.15 * np.sin(2 * np.pi * 700 * t)
        high = 0.35 * np.sin(2 * np.pi * 1120 * t)
        click_env = np.exp(-t * 60)
        click = 0.5 * np.sin(2 * np.pi * 1600 * t) * click_env
        noise = np.random.normal(0, 0.18, size=t.shape)
        texture = fundamental * 0.55 + overtones + high * 0.6 + click + noise * 0.25
        texture = np.clip(texture * 2.2, -0.88, 0.88)
        envelope = np.ones_like(t)
        attack = int(0.003 * SAMPLE_RATE)
        decay = int(0.015 * SAMPLE_RATE)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-decay:] = np.linspace(1, 0, decay)
        texture = texture * envelope

    # dual-tone carriers for FFT decoding
    carrier_low = np.sin(2 * np.pi * low_f * t) * 0.45
    carrier_high = np.sin(2 * np.pi * high_f * t) * 0.35

    burst = texture + carrier_low + carrier_high
    burst = np.clip(burst, -0.95, 0.95)
    burst = burst / (np.max(np.abs(burst)) + 1e-9) * BURST_AMP
    return burst


def encode(text, mode="laser"):
    """Text -> NumPy audio array. Each letter = dual-tone burst + silence gap."""
    signal = []
    for ch in text.upper():
        if ch not in FREQ_MAP:
            print(f"  [WARN] Character '{ch}' skipped (not in codebook)")
            continue
        signal.extend(make_burst(ch, mode=mode))
        extra_ms = GAP_MAP[ch]
        extra_samples = int(SAMPLE_RATE * (extra_ms / 1000.0))
        signal.extend(np.zeros(extra_samples))
    signal.extend(make_burst(' ', mode=mode))  # terminator burst
    return np.array(signal, dtype=np.float32)


def save_wav(name, signal):
    wavfile.write(name, SAMPLE_RATE, (signal * 32767).astype(np.int16))


def load_wav(name):
    rate, data = wavfile.read(name)
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32767.0
    return data


def find_bursts(signal):
    """Return list of (start, end) indices for each burst.
    Uses short-term RMS energy instead of raw amplitude so phase
    cancellations inside a burst don't split it."""
    win = int(0.005 * SAMPLE_RATE)
    energy = np.convolve(signal**2, np.ones(win) / win, mode='same')
    above = energy > (THRESHOLD ** 2)
    edges = np.diff(above.astype(int))
    starts = np.where(edges == 1)[0] + 1
    ends = np.where(edges == -1)[0] + 1
    if above[0]:
        starts = np.insert(starts, 0, 0)
    if above[-1]:
        ends = np.append(ends, len(signal))
    regions = list(zip(starts, ends))

    MIN_BURST_GAP_MS = 60
    MIN_BURST_GAP_SAMPLES = int(SAMPLE_RATE * MIN_BURST_GAP_MS / 1000.0)
    merged = []
    for s, e in regions:
        if merged and s - merged[-1][1] < MIN_BURST_GAP_SAMPLES:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def detect_letter_from_burst(burst_signal, sr):
    """FFT-based extraction of the dominant frequency pair."""
    if len(burst_signal) < 64:
        return '?', float('inf')

    window = np.hanning(len(burst_signal))
    fft_vals = np.abs(rfft(burst_signal * window))
    freqs = rfftfreq(len(burst_signal), 1 / sr)

    low_mask = (freqs >= 350) & (freqs <= 1050)
    high_mask = (freqs >= 1800) & (freqs <= 2950)

    if not np.any(low_mask) or not np.any(high_mask):
        return '?', float('inf')

    low_freqs = freqs[low_mask]
    high_freqs = freqs[high_mask]
    low_fft = fft_vals[low_mask]
    high_fft = fft_vals[high_mask]

    best_low = low_freqs[np.argmax(low_fft)]
    best_high = high_freqs[np.argmax(high_fft)]

    best_char = '?'
    best_err = float('inf')
    for ch, (low, high) in FREQ_MAP.items():
        err = abs(low - best_low) + abs(high - best_high)
        if err < best_err:
            best_err = err
            best_char = ch

    return best_char, best_err


def classify_signal(gaps_ms, decoded_text, valid_freq_count, total_burst_count):
    """Four-state classifier: NOISE -> CLOCK -> GIBBERISH -> LANGUAGE."""
    if total_burst_count == 0 or valid_freq_count < total_burst_count * 0.5:
        return "NOISE -> STATUS: DEAD"

    if len(gaps_ms) >= 3:
        if max(gaps_ms) - min(gaps_ms) <= TOLERANCE:
            return "CLOCK (periodic) -> STATUS: DEAD"

    if not is_plausible_text(decoded_text):
        return "GIBBERISH -> STATUS: DEAD"

    return "LANGUAGE (structured, meaningful) -> STATUS: ALIVE"


def decode(signal):
    """Audio array -> text (FFT frequency decode + gap redundancy)."""
    regions = find_bursts(signal)
    num_bursts = len(regions)
    num_info_bursts = max(0, num_bursts - 1)
    print(f"  Receiver detected {num_info_bursts} info bursts "
          f"({num_bursts} total incl. terminator).")

    # primary channel: FFT decode
    freq_chars = []
    for s, e in regions[:-1]:  # skip terminator
        burst = signal[s:e]
        ch, err = detect_letter_from_burst(burst, SAMPLE_RATE)
        freq_chars.append(ch)
    print(f"  FFT decode (freq):   {freq_chars}")

    # secondary channel: gap timing
    gaps = []
    for i in range(len(regions) - 1):
        end_this = regions[i][1]
        start_next = regions[i + 1][0]
        ms = int(round(((start_next - end_this) / SAMPLE_RATE) * 1000.0 / 50.0)) * 50
        gaps.append(ms)
    print(f"  Measured gaps (ms):  {gaps}")

    gap_chars = []
    for g in gaps:
        closest = min(GAP_MAP.values(), key=lambda v: abs(v - g))
        if abs(closest - g) <= TOLERANCE:
            gap_chars.append(REV_GAP[closest])
        else:
            gap_chars.append('?')
    print(f"  Gap decode (time):   {gap_chars}")

    # redundancy merge
    chars = []
    for idx, (f_ch, g_ch) in enumerate(zip(freq_chars, gap_chars)):
        if f_ch == '?' and g_ch != '?':
            chars.append(g_ch)
        elif g_ch == '?' and f_ch != '?':
            chars.append(f_ch)
        elif f_ch != '?' and g_ch != '?' and f_ch != g_ch:
            print(f"  [!] Redundancy conflict at burst {idx+1}: "
                  f"freq={f_ch}, gap={g_ch} -> using freq")
            chars.append(f_ch)
        else:
            chars.append(f_ch)

    decoded_text = "".join(chars)
    valid_freq = sum(1 for c in freq_chars if c != '?')

    verdict = classify_signal(gaps, decoded_text, valid_freq, num_bursts)
    print(f"\n>>> {verdict} <<<")

    return decoded_text


def plot_signal(audio, show=False):
    """Waveform + spectrogram."""
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
    ax_wave.set_title("TRANSMISSION SIGNAL – Amplitude vs Time", color='white', fontsize=11)
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
    ax_spec.set_title("SPECTRAL ANALYSIS – Frequency vs Time", color='white', fontsize=11)
    ax_spec.set_xlabel("Time [s]", color='#aaaaaa')
    ax_spec.set_ylabel("Frequency [Hz]", color='#aaaaaa')
    ax_spec.set_ylim(0, 6000)
    ax_spec.tick_params(colors='#888888')

    cbar = fig.colorbar(im, ax=ax_spec, orientation='vertical', pad=0.02)
    cbar.set_label("Intensity [dB]", color='#aaaaaa')
    cbar.ax.yaxis.set_tick_params(color='#888888')
    cbar.ax.yaxis.set_tick_params(labelcolor='#aaaaaa')

    plt.tight_layout()

    plot_name = "transmission_spectrogram.png"
    plt.savefig(plot_name, dpi=150, facecolor='#0a0a0a')
    print(f"[SENDER] Waveform + spectrogram saved as {plot_name}")

    if show:
        plt.show(block=False)
        try:
            input("[SENDER] Press Enter to continue...")
        except (KeyboardInterrupt, EOFError):
            print("\n[SENDER] Continuing...")
        plt.close('all')
    else:
        plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="ALIVE Base Demo – Dual-tone frequency transmission with FFT decode"
    )
    parser.add_argument(
        "--show-plot",
        action="store_true",
        help="Show spectrogram window (non-blocking)"
    )
    parser.add_argument(
        "--horn",
        action="store_true",
        help="Powerful metallic horn burst"
    )
    parser.add_argument(
        "--laser",
        action="store_true",
        help="Quiet high laser psst tone (default)"
    )
    parser.add_argument(
        "--vocal",
        action="store_true",
        help="Deep growl / vocal syllable"
    )
    args = parser.parse_args()

    # pick tone mode (default = laser)
    if args.horn:
        tone_mode = "horn"
    elif args.vocal:
        tone_mode = "vocal"
    else:
        tone_mode = "laser"

    print("=" * 50)
    print("ALIVE BASE DEMO: Signal -> Send -> Receive")
    print("=" * 50)
    print(f"[CONFIG] Tone mode: {tone_mode}")
    print("[CONFIG] Encoding: dual-tone frequency (FFT-based) + gap redundancy")
    if args.show_plot:
        print("[CONFIG] Plot will be shown (non-blocking)")

    msg = input("\nEnter text (A-Z, spaces only): ").strip()
    print(f"\n[SENDER] Encoding message: '{msg}'")

    audio = encode(msg, mode=tone_mode)
    filename = "transmission.wav"
    save_wav(filename, audio)
    print(f"[SENDER] Saved as {filename}")

    if sd is not None:
        print(f"[SENDER] Playing signal ({len(audio)/SAMPLE_RATE:.2f} seconds)...")
        sd.play(audio, SAMPLE_RATE)
        sd.wait()
    else:
        print("[SENDER] Audio output unavailable (sounddevice/PortAudio missing).")

    plot_signal(audio, show=args.show_plot)

    print(f"\n[RECEIVER] Loading {filename}...")
    received = load_wav(filename)
    decoded = decode(received)
    print(f"[RECEIVER] Decoded text: '{decoded}'")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!] Interrupted by user (Ctrl+C).")
        raise SystemExit(0)
