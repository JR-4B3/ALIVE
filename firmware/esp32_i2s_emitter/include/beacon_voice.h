#pragma once
#include <cstdint>
// Near-ultrasound chirp alphabet. Mirrors web/src/audio/beacon.ts, and
// `bun test` checks both produce identical samples.
namespace beacon {
constexpr uint32_t rate = 48000;
constexpr uint32_t frames = 17280; // 360 ms, with smooth attack and release.
constexpr int syncHz = 18200;
constexpr int firstLetterHz = 18450;
constexpr int spacingHz = 64;
// The sweep stays under half the spacing, which leaves room for hand-held Doppler.
constexpr int sweepHz = 24;
constexpr int32_t amplitude = 6000;
#include "beacon_tables.h"
inline int symbolFor(char ch) { return ch == ' ' ? 26 : ch >= 'A' && ch <= 'Z' ? ch - 'A' : -1; }
inline int frequencyFor(int symbol) {
  return symbol < 0 ? syncHz : firstLetterHz + symbol * spacingHz;
}
struct Voice {
  uint32_t frame = 0, phase = 0, step = 0, stepDelta = 0;
  void reset(int symbol) {
    frame = phase = 0;
    stepDelta = (static_cast<uint64_t>(2 * sweepHz) << 32) / (frames * static_cast<uint64_t>(rate));
    step = (static_cast<uint64_t>(frequencyFor(symbol) + sweepHz) << 32) / rate;
  }
  int16_t next() {
    if (frame >= frames) return 0;
    const uint32_t index = phase >> 22;
    const int32_t fraction = (phase >> 12) & 1023;
    const int32_t wave = (static_cast<int32_t>(sine[index]) * (1024 - fraction) + static_cast<int32_t>(sine[index + 1]) * fraction) >> 10;
    const int32_t shaped = (wave * envelope[frame * 1024 / frames]) >> 15;
    phase += step;
    step -= stepDelta;
    ++frame;
    return (shaped * amplitude) >> 15;
  }
};
}
