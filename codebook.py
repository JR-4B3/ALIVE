# codebook.py
# Dual-tone frequency codebook (DTMF-inspired).
# Each letter = one LOW frequency + one HIGH frequency played simultaneously.
# Receiver extracts the two peaks via FFT.
# Gaps between bursts are a secondary timing channel + ALIVE/DEAD classifier.

LOW_FREQS  = [400, 500, 600, 700, 800, 900, 1000]
HIGH_FREQS = [2000, 2300, 2600, 2900]

# 7 x 4 = 28 combos (27 used for A-Z + space)
FREQ_MAP = {
    'A': (400, 2000),  'B': (400, 2300),  'C': (400, 2600),  'D': (400, 2900),
    'E': (500, 2000),  'F': (500, 2300),  'G': (500, 2600),  'H': (500, 2900),
    'I': (600, 2000),  'J': (600, 2300),  'K': (600, 2600),  'L': (600, 2900),
    'M': (700, 2000),  'N': (700, 2300),  'O': (700, 2600),  'P': (700, 2900),
    'Q': (800, 2000),  'R': (800, 2300),  'S': (800, 2600),  'T': (800, 2900),
    'U': (900, 2000),  'V': (900, 2300),  'W': (900, 2600),  'X': (900, 2900),
    'Y': (1000, 2000), 'Z': (1000, 2300), ' ': (1000, 2600),
    # (1000, 2900) is unused / reserved
}

REV_FREQ = {v: k for k, v in FREQ_MAP.items()}

GAP_MAP = {
    'A': 100, 'B': 150, 'C': 200, 'D': 250, 'E': 300,
    'F': 350, 'G': 400, 'H': 450, 'I': 500, 'J': 550,
    'K': 600, 'L': 650, 'M': 700, 'N': 750, 'O': 800,
    'P': 850, 'Q': 900, 'R': 950, 'S': 1000, 'T': 1050,
    'U': 1100, 'V': 1150, 'W': 1200, 'X': 1250, 'Y': 1300,
    'Z': 1350, ' ': 1600,
}

REV_GAP = {v: k for k, v in GAP_MAP.items()}
