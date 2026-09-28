# ALIVE sound studio

This is a browser-first experiment in sample-based acoustic communication. It keeps
the classic visitor receiver and ESP32 firmware available as the established baseline.
The experimental voice is not deployed to the NAS or the ESP32s.

## Open it

```bash
cd web
bun run dev:voice --port 5174
```

Open `http://localhost:5174/` on the same computer. Choose a waveform, pitch,
and brightness, then shape its attack, decay, sustain, and release. **Hear this
sound** auditions one gesture through your headphones. **Make voice from it**
turns it into an alphabet, and **Play in headphones** lets you hear a message.
Listening volume starts at 25%. **Decode rendered audio** checks the generated
samples against the codebook. It does not copy the input text into the decoded
result.

For the built page:

```bash
cd web
bun run build:voice
cd ..
python debug_host.py --rebuild
```

The existing debug host serves the studio at `/voice/`, with a link from its main
page. Its HTTPS address also works for phone microphone testing after accepting
the local certificate. HTTP on a non-localhost LAN address generally cannot use
the microphone or secure browser cryptography. Once published with the existing
`docs/` site, the studio is at `/ALIVE/voice/`. Building does not publish the site.

## Use your own sounds

Open **Use my own audio instead** to import sounds from a DAW. There are three
interchangeable starting points:

- **One signature sound:** import a short sound. The generator uses the entire
  source to make 27 continuous gestures. Each letter is one uninterrupted sound;
  it varies in pitch, duration, and motion, with no built-in note sequence.
  Sources shorter than 240 ms are stretched and sources longer than 620 ms are
  compressed before variation. This is a starting point, not a promise that every
  source will yield a good alphabet. Similar variants can remain ambiguous.
- **A designed alphabet:** import `A.wav` through `Z.wav` and `SPACE.wav` together.
  Each symbol keeps its designed waveform after mono conversion, resampling,
  trimming, short edge fades, and peak normalization.
- **An alphabet recording:** put those 27 sounds in A–Z, SPACE order in one file,
  with at least 220 ms of silence between them. Maximum source duration: 45 seconds.
  Segmentation must find exactly 27 sounds; the studio will report a mismatch.

You can replace any individual symbol in the same audio section and rebuild its template without losing
calibration for the other symbols. Choose different names and keep as many voice
packages as you need. No hardware identity is baked into a package; five different
voices can later be assigned to the five ESP32s.

Packages created with the earlier three-gesture generator retain those exact sounds
when loaded. Create a new package from the synth or source sound to hear continuous gestures.

Current experimental boundaries:

- Each trimmed symbol: 0.12–1.2 seconds.
- Playback and recognition: mono, 16 kHz; recognition features cover 180–6500 Hz.
- Sound separation: a 220 ms pause, with 80 ms of quiet used to detect endings.
  Long internal silences can split a symbol; long reverberation can merge symbols.
- Messages: A–Z and spaces, up to 20 symbols and 30 seconds including pauses.
- Live recording: 30 seconds maximum. WAV is recommended for source and capture files.
- Symbols that are too alike are rejected as `?`, rather than guessed from language.

The separation panel checks both original-template recognition and a rendered
symbol through the segmentation/decoding path. A failure means a sound needs
redesigning or different framing. Passing is only a digital check.

## Improve a voice using recordings

1. Export a voice package and retain the baseline revision.
2. For listening, use headphones. For acoustic tests, play through a speaker and
   record with a microphone, preferably on a separate device. Load the same voice
   package on the receiver. There is no automatic network distribution yet.
3. Record in the studio, or import a WAV saved by the existing debug page. The
   studio also decodes live during microphone recording. Imported classic tone
   recordings can be checked with **Compare classic decoder**; they do not train
   an unrelated designed voice meaningfully.
4. Enter the actual message and analyze. Expected text is used only for scoring.
   If room noise joins everything into one segment, raise the segmentation floor;
   if quiet sounds disappear, lower it. Listen to the extracted segments.
5. Leave some recordings out for evaluation. Add those to the evaluation set,
   including a room-noise recording with an empty expected message.
6. On different recordings, explicitly label selected segments with a letter or
   `SPACE`. Leave uncertain segments blank. Check the review box and create a
   calibrated revision. The studio adds acoustic templates; it does not guess
   ground-truth labels or silently adjust recognition thresholds.
7. Evaluate both old and new revisions against the same evaluation set. The score
   counts substitutions, missed symbols, rejected symbols, and extra symbols.
   Choose the new revision only when the results justify it.

Each symbol retains its original template and can hold seven acoustic examples.
Calibration creates a new content-derived version ID and preserves exact playback
PCM. Training/evaluation overlap is rejected using a recording fingerprint. This
catches identical captures, including a downloaded WAV re-imported unchanged;
editing or re-encoding a recording can produce a new fingerprint, so still keep
independent sessions for an honest evaluation.

Voice packages are saved to IndexedDB in this browser. Export them for backups and
sharing. Recordings, labels in progress, and evaluation sets live only in the current
tab. Download the WAV plus its metadata; the optional metadata importer restores
the expected message and source voice ID. Evaluation reports include per-recording
IDs, expected/decoded text, thresholds, and error counts. Nothing is uploaded.

## Recognition and package format

`web/src/voice/codec.ts` defines package version 1 and the shared offline decoder.
It extracts 40 spectral bands from 512-sample Hann windows at 16 kHz, with a 160-sample
hop. Gain-normalized trajectories are reduced to 24 frames and compared using
band-constrained dynamic time warping with cosine distance. Acceptance requires
both a maximum distance and a margin over the next-best symbol. Silence-based
segmentation precedes classification. The streaming decoder resamples incoming
microphone audio and applies the same feature and matching functions.

This is a bounded sound-alphabet recognizer, not a general model that understands
arbitrary unlabelled audio. It is inspired by standard template/time-alignment
approaches such as the [AudioLabs DTW material](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C3/C3S2_DTWbasic.html).

`alive-sound-voice` packages include PCM samples, recognition templates, thresholds,
and calibration provenance. Their ID hashes canonicalized content. Import checks
format, size, samples, template dimensions, provenance, and the hash. A package
contains everything needed for browser playback and recognition; it has no URLs,
executable recipes, API keys, or model dependency.

A matching Python compiler is available for batch preparation:

```bash
python tools/build_voice.py --seed my-sound.wav --name "Visitor one" --output visitor-one.json --wav audition.wav
python tools/build_voice.py --alphabet path/to/alphabet --name "Station" --output station.json
python tools/build_voice.py --inspect station.json
```

The CLI refuses to overwrite output files. Its report checks template separation;
use the studio to check segmentation and acoustic captures. Python and TypeScript
share the feature format and package fingerprint convention.

## Validation and next hardware step

```bash
cd web
bun test
bun run build:voice
bun run build:debug
bun run build
cd ..
python -m pytest -q
```

Tests exercise symbol separation, message decoding, repeated letters, spaces,
synthetic gain/noise/echo changes, rejection, packet validation, calibration
provenance, and incremental microphone processing at 16/44.1/48 kHz. These tests
do not establish parity with the existing receiver in the exhibition room.

The next hardware step is playback of package PCM on ESP32, with explicit package
selection/version agreement at each emitter and receiver. That work is deferred
until listening and independent acoustic recordings identify worthwhile voices.
Simultaneous overlapping transmissions from five emitters will also need a channel
or scheduling strategy; the present decoder handles one foreground transmission.
