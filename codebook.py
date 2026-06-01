# codebook.py
# Dauer der Stille nach jedem Burst (in Millisekunden)
# Jeder Buchstabe hat eine EINZIGARTIGE Pausenlänge,
# damit der Empfänger ihn eindeutig erkennen kann.
CODEBOOK = {
    'A': 100, 'B': 150, 'C': 200, 'D': 250, 'E': 300,
    'F': 350, 'G': 400, 'H': 450, 'I': 500, 'J': 550,
    'K': 600, 'L': 650, 'M': 700, 'N': 750, 'O': 800,
    'P': 850, 'Q': 900, 'R': 950, 'S': 1000, 'T': 1050,
    'U': 1100, 'V': 1150, 'W': 1200, 'X': 1250, 'Y': 1300,
    'Z': 1350, ' ': 1600
}
# Umgekehrte Map für die Dekodierung
REVERSE = {v: k for k, v in CODEBOOK.items()}
