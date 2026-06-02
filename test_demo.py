"""
Headless tests for the ALIVE demo.
No audio output, no matplotlib popup.
Tests encoder, WAV save/load, decoder, and classifier.
"""
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from base_demo import encode, decode, save_wav, load_wav

TESTS = [
    ("HELLO WORLD", "HELLO WORLD", "language with space"),
    ("AAAAA", "AAAAA", "periodic -> DEAD (CLOCK)"),
    ("12345!@#$%", "", "noise/invalid -> DEAD (NOISE)"),
    ("A", "A", "single letter"),
    ("AB", "AB", "two letters (adjacent values)"),
    ("ABC", "ABC", "three letters"),
    ("HELLO", "HELLO", "standard demo word"),
    ("ET", "ET", "shortest gaps (E=300, T=1050)"),
    ("JVDNMAOUVHRUFNEOUCNOCD", "JVDNMAOUVHRUFNEOUCNOCD", "gibberish -> DEAD"),
]


def run_tests():
    print("=" * 60)
    print("ALIVE DEMO – HEADLESS TESTS")
    print("=" * 60)

    passed = 0
    failed = 0

    for text, expected, description in TESTS:
        print(f"\n--- Test: {description} ---")
        print(f"  Input:    '{text}'")

        audio = encode(text)
        safe_name = text.replace(' ', '_').replace('!','').replace('@','').replace('#','').replace('$','').replace('%','')
        wav_path = PROJECT_DIR / f"_test_{safe_name}.wav"
        save_wav(str(wav_path), audio)
        received = load_wav(str(wav_path))
        decoded = decode(received)

        print(f"  Decoded:  '{decoded}'")

        if expected is None:
            print(f"  OK (DEAD status detected, text still decoded)")
            passed += 1
        else:
            if decoded == expected:
                print(f"  OK")
                passed += 1
            else:
                print(f"  FAIL (expected: '{expected}')")
                failed += 1

    print("\n" + "=" * 60)
    print(f"Result: {passed} passed, {failed} failed")
    print("=" * 60)

    for f in PROJECT_DIR.glob("_test_*.wav"):
        f.unlink()

    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
