#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <driver/i2s.h>
#include <math.h>

#include "secrets.h"

// ESP32-C3 Super Mini -> MAX98357. Change these if your board layout needs it.
constexpr gpio_num_t I2S_BCLK = GPIO_NUM_4;
constexpr gpio_num_t I2S_LRC = GPIO_NUM_5;
constexpr gpio_num_t I2S_DIN = GPIO_NUM_6;
constexpr i2s_port_t I2S_PORT = I2S_NUM_0;
constexpr uint32_t SAMPLE_RATE = 24000;
constexpr uint32_t BURST_MS = 220;
constexpr float GAP_SCALE = 0.65f;
constexpr uint32_t MIN_GAP_MS = 90;
constexpr uint32_t POLL_MS = 300;
constexpr int16_t AMPLITUDE = 8500;

long lastRevision = -1;
uint32_t lastPollAt = 0;

bool frequenciesFor(char ch, float &low, float &high, uint16_t &rawGapMs) {
  if (ch == ' ') {
    low = 1000; high = 2600; rawGapMs = 1600;
    return true;
  }
  if (ch < 'A' || ch > 'Z') return false;
  const uint8_t index = ch - 'A';
  low = 400 + (index / 4) * 100;
  high = 2000 + (index % 4) * 300;
  rawGapMs = 100 + index * 50;
  return true;
}

void writeSilence(uint32_t durationMs) {
  static int16_t zeros[256] = {};
  uint32_t remaining = (SAMPLE_RATE * durationMs) / 1000;
  while (remaining > 0) {
    const size_t count = min<uint32_t>(remaining, 256);
    size_t written = 0;
    i2s_write(I2S_PORT, zeros, count * sizeof(int16_t), &written, portMAX_DELAY);
    remaining -= count;
  }
}

void writeTone(float low, float high) {
  int16_t samples[256];
  const uint32_t total = (SAMPLE_RATE * BURST_MS) / 1000;
  uint32_t cursor = 0;
  while (cursor < total) {
    const size_t count = min<uint32_t>(total - cursor, 256);
    for (size_t i = 0; i < count; ++i) {
      const uint32_t frame = cursor + i;
      const float time = static_cast<float>(frame) / SAMPLE_RATE;
      float envelope = 1.0f;
      if (frame < SAMPLE_RATE / 200) envelope = frame / (SAMPLE_RATE / 200.0f);
      const uint32_t tail = total - frame;
      if (tail < SAMPLE_RATE / 50) envelope = min(envelope, tail / (SAMPLE_RATE / 50.0f));
      const float signal = 0.53f * sinf(TWO_PI * low * time) +
                           0.47f * sinf(TWO_PI * high * time);
      samples[i] = static_cast<int16_t>(signal * envelope * AMPLITUDE);
    }
    size_t written = 0;
    i2s_write(I2S_PORT, samples, count * sizeof(int16_t), &written, portMAX_DELAY);
    cursor += count;
  }
}

void playMessage(const String &message) {
  Serial.printf("Playing revision %ld: %s\n", lastRevision, message.c_str());
  writeSilence(500);
  for (size_t i = 0; i < message.length(); ++i) {
    float low = 0;
    float high = 0;
    uint16_t rawGapMs = 0;
    if (!frequenciesFor(message[i], low, high, rawGapMs)) continue;
    writeTone(low, high);
    const uint32_t gapMs = max<uint32_t>(MIN_GAP_MS, lroundf(rawGapMs * GAP_SCALE));
    writeSilence(gapMs);
  }
  writeSilence(1800);
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ALIVE_WIFI_SSID, ALIVE_WIFI_PASSWORD);
  Serial.printf("Connecting to %s", ALIVE_WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print('.');
  }
  Serial.printf("\nWiFi ready: %s\n", WiFi.localIP().toString().c_str());
}

void pollForMessage() {
  WiFiClientSecure client;
  client.setInsecure();  // The local demo server uses a short lived self signed cert.
  HTTPClient http;
  const String url = String(ALIVE_SERVER_URL) + "/api/emitter/main/current";
  if (!http.begin(client, url)) return;
  const int status = http.GET();
  if (status == HTTP_CODE_OK) {
    JsonDocument json;
    const DeserializationError error = deserializeJson(json, http.getStream());
    if (!error) {
      const long revision = json["revision"] | -1;
      const String message = json["message"] | "";
      if (revision > lastRevision && message.length() > 0) {
        lastRevision = revision;
        http.end();
        playMessage(message);
        return;
      }
    } else {
      Serial.printf("JSON error: %s\n", error.c_str());
    }
  } else {
    Serial.printf("Poll failed: HTTP %d\n", status);
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(500);
  const i2s_config_t config = {
      .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 8,
      .dma_buf_len = 256,
      .use_apll = false,
      .tx_desc_auto_clear = true,
      .fixed_mclk = 0,
  };
  const i2s_pin_config_t pins = {
      .mck_io_num = I2S_PIN_NO_CHANGE,
      .bck_io_num = I2S_BCLK,
      .ws_io_num = I2S_LRC,
      .data_out_num = I2S_DIN,
      .data_in_num = I2S_PIN_NO_CHANGE,
  };
  i2s_driver_install(I2S_PORT, &config, 0, nullptr);
  i2s_set_pin(I2S_PORT, &pins);
  i2s_zero_dma_buffer(I2S_PORT);
  connectWifi();
  Serial.println("ALIVE I2S emitter ready");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (millis() - lastPollAt >= POLL_MS) {
    lastPollAt = millis();
    pollForMessage();
  }
  delay(10);
}
