#pragma once
// Throwaway sound study. Tables avoid synthesis stalls in the I2S audio loop.
#include <cstdint>
#include <algorithm>
namespace space_sound {
constexpr uint32_t rate = 48000;
constexpr uint32_t frames = rate * 18 / 10;
#include "space_tables.h"
inline int16_t sample(uint32_t frame, int direction, bool outro = false) {
  if (direction < 1 || direction > 3 || frame >= frames) return 0;
  const int16_t *table = direction == 1 ? sound1 : direction == 3 ? sound3 : outro ? sound2outro : sound2;
  const uint32_t step = direction == 2 ? 3 : 12;
  const uint32_t index = frame / step, fraction = frame % step;
  return (static_cast<int32_t>(table[index]) * (step - fraction) + static_cast<int32_t>(table[index + 1]) * fraction) / step;
}
}
