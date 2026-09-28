#!/usr/bin/env python3
"""Compile DAW WAV exports into the same portable package as the browser studio."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sound_voice import (LETTERS, RATE, compile_voice, confusion_report, generated_sounds,
                         load_voice, read_audio, render_message)
from scipy.io import wavfile
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--seed', type=Path, help='Generate 27 continuous variations of one WAV')
    source.add_argument('--alphabet', type=Path, help='Directory containing A.wav–Z.wav and SPACE.wav')
    source.add_argument('--inspect', type=Path, help='Validate and report on an existing package')
    parser.add_argument('--name', default='Designed voice')
    parser.add_argument('--output', type=Path, help='New JSON package (will not overwrite an existing file)')
    parser.add_argument('--message', default='WE ARE HERE')
    parser.add_argument('--wav', type=Path, help='Optional message WAV (will not overwrite an existing file)')
    args = parser.parse_args()
    if args.output and args.output.exists() or args.wav and args.wav.exists():
        parser.error('Output already exists; choose a new filename')
    if args.inspect:
        voice = load_voice(args.inspect)
    else:
        if not args.output:
            parser.error('--output is required when compiling a voice')
        sounds = generated_sounds(read_audio(args.seed)) if args.seed else {
            ch: read_audio(args.alphabet / ('SPACE.wav' if ch == ' ' else f'{ch}.wav')) for ch in LETTERS}
        voice = compile_voice(sounds, args.name)
    audio = render_message(voice, args.message.upper())
    if len(audio) > RATE * 30:
        parser.error('Message exceeds the experimental 30-second limit')
    if args.output:
        args.output.write_text(json.dumps(voice, ensure_ascii=False), encoding='utf-8')
    if args.wav:
        wavfile.write(args.wav, RATE, np.clip(np.round(audio * 32768), -32768, 32767).astype('<i2'))
    print(json.dumps(confusion_report(voice), indent=2))


if __name__ == '__main__':
    main()
