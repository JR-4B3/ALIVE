#pragma once
#include <cstdint>
// Single-carrier Beacon alphabet. Shared DDS arithmetic is verified in native PCM.
namespace beacon {
constexpr uint32_t rate = 48000;
constexpr uint32_t frames = 17280; // 360 ms, with smooth attack and release.
constexpr int amplitude = 520;
constexpr int sweep = 36; // +36 Hz to -36 Hz, independently of the letter.
constexpr uint32_t stepDelta = (static_cast<uint64_t>(2 * sweep) << 32) / (frames * static_cast<uint64_t>(rate));
#include "beacon_tables.h"
inline int symbolFor(char ch) { return ch == ' ' ? 26 : ch >= 'A' && ch <= 'Z' ? ch - 'A' : -1; }
inline int frequencyFor(int symbol) { return symbol < 0 ? 550 : 680 + symbol * 44; }
struct Voice {
  uint32_t frame = 0, phase = 0, step = 0;
  void reset(int symbol) {
    frame = phase = 0;
    step = (static_cast<uint64_t>(frequencyFor(symbol) + sweep) << 32) / rate;
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
