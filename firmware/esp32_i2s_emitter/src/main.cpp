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
constexpr gpio_num_t STATUS_LED = GPIO_NUM_8;
constexpr i2s_port_t I2S_PORT = I2S_NUM_0;
// MAX98357A/B datasheet, LRCLK Polarity: 24 kHz is explicitly unsupported.
constexpr uint32_t SAMPLE_RATE = 48000;
static_assert(SAMPLE_RATE == 8000 || SAMPLE_RATE == 16000 ||
              SAMPLE_RATE == 32000 || SAMPLE_RATE == 44100 ||
              SAMPLE_RATE == 48000 || SAMPLE_RATE == 88200 ||
              SAMPLE_RATE == 96000, "Unsupported MAX98357 sample rate");
constexpr uint32_t BURST_MS = 300;
constexpr float GAP_SCALE = 0.65f;
constexpr uint32_t MIN_GAP_MS = 90;
constexpr uint32_t POLL_MS = 300;
// Start conservatively. The MAX98357 has substantial speaker gain.
constexpr int16_t AMPLITUDE = 300;
#if defined(ALIVE_HARDWARE_TEST)
constexpr uint32_t TEST_TONE_FRAMES = SAMPLE_RATE / 2;  // 500 ms
constexpr uint32_t TEST_CYCLE_FRAMES = SAMPLE_RATE * 6; // 6 seconds
constexpr uint32_t TEST_FADE_FRAMES = SAMPLE_RATE / 200; // 5 ms
constexpr uint32_t TEST_SINE_FRAMES = SAMPLE_RATE / 800; // Exact 800 Hz cycle
uint32_t testFrameCursor = 0;
int16_t testSine[TEST_SINE_FRAMES];
#endif
#if defined(ALIVE_MESSAGE_TEST) || defined(ALIVE_SERIAL_MESSAGE)
constexpr uint32_t MESSAGE_BURST_FRAMES = SAMPLE_RATE * 220 / 1000;
constexpr uint32_t MESSAGE_FADE_FRAMES = SAMPLE_RATE / 200;
constexpr uint32_t MESSAGE_SINE_FRAMES = SAMPLE_RATE / 100;
enum class MessageSegment { Idle, Lead, Tone, Gap, Pause };
#if defined(ALIVE_MESSAGE_TEST)
MessageSegment messageSegment = MessageSegment::Lead;
uint32_t messageSegmentLength = SAMPLE_RATE * 2;
#else
MessageSegment messageSegment = MessageSegment::Idle;
uint32_t messageSegmentLength = 0;
char serialLine[32] = {};
size_t serialLineLength = 0;
#endif
char messageText[21] = "HELLO";
uint32_t messageSegmentFrame = 0;
uint32_t messageGapFrames = 0;
size_t messageLetterIndex = 0;
uint16_t messageLowStep = 0;
uint16_t messageHighStep = 0;
uint16_t messageLowPhase = 0;
uint16_t messageHighPhase = 0;
int16_t messageSine[MESSAGE_SINE_FRAMES];
#endif

long lastRevision = -1;
uint32_t lastPollAt = 0;
uint32_t lastHardwareTestAt = 0;
uint32_t lastLedToggleAt = 0;
bool statusLedOn = false;

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
  // Interleaved left/right samples keep the I2S frame unambiguous for the amp.
  static int16_t zeros[512] = {};
  uint32_t remaining = (SAMPLE_RATE * durationMs) / 1000;
  while (remaining > 0) {
    const size_t count = min<uint32_t>(remaining, 256);
    size_t written = 0;
    i2s_write(I2S_PORT, zeros, count * 2 * sizeof(int16_t), &written, portMAX_DELAY);
    remaining -= count;
  }
}

void writeTone(float low, float high, uint32_t durationMs = BURST_MS) {
  int16_t samples[512];
  const uint32_t total = (SAMPLE_RATE * durationMs) / 1000;
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
      const int16_t sample = static_cast<int16_t>(signal * envelope * AMPLITUDE);
      samples[i * 2] = sample;
      samples[i * 2 + 1] = sample;
    }
    size_t written = 0;
    i2s_write(I2S_PORT, samples, count * 2 * sizeof(int16_t), &written, portMAX_DELAY);
    cursor += count;
  }
}

#if defined(ALIVE_HARDWARE_TEST)
void writeContinuousTestAudio() {
  int16_t samples[512];
  for (uint32_t i = 0; i < 256; ++i) {
    int16_t sample = 0;
    if (testFrameCursor < TEST_TONE_FRAMES) {
      const uint32_t fade = min(TEST_FADE_FRAMES,
                                min(testFrameCursor, TEST_TONE_FRAMES - testFrameCursor - 1));
      sample = static_cast<int32_t>(testSine[testFrameCursor % TEST_SINE_FRAMES]) *
               fade / TEST_FADE_FRAMES;
    }
    samples[i * 2] = sample;
    samples[i * 2 + 1] = sample;
    testFrameCursor = (testFrameCursor + 1) % TEST_CYCLE_FRAMES;
  }
  size_t written = 0;
  const esp_err_t error = i2s_write(I2S_PORT, samples, sizeof(samples),
                                   &written, portMAX_DELAY);
  if (error != ESP_OK || written != sizeof(samples)) {
    Serial.printf("I2S write failed: error=%d, bytes=%u\n", error,
                  static_cast<unsigned>(written));
  }
  if (testFrameCursor < 256) Serial.println("Hardware test beep");
}
#endif

#if defined(ALIVE_MESSAGE_TEST) || defined(ALIVE_SERIAL_MESSAGE)
void startMessageLetter() {
  float low = 0;
  float high = 0;
  uint16_t rawGapMs = 0;
  frequenciesFor(messageText[messageLetterIndex], low, high, rawGapMs);
  messageLowStep = static_cast<uint16_t>(low / 100);
  messageHighStep = static_cast<uint16_t>(high / 100);
  messageGapFrames = SAMPLE_RATE *
      max<uint32_t>(MIN_GAP_MS, lroundf(rawGapMs * GAP_SCALE)) / 1000;
  messageLowPhase = 0;
  messageHighPhase = 0;
  messageSegment = MessageSegment::Tone;
  messageSegmentFrame = 0;
  messageSegmentLength = MESSAGE_BURST_FRAMES;
}

void advanceMessageSegment() {
  if (messageSegment == MessageSegment::Lead) {
    startMessageLetter();
    return;
  } else if (messageSegment == MessageSegment::Tone) {
    messageSegment = MessageSegment::Gap;
    messageSegmentLength = messageGapFrames;
  } else if (messageSegment == MessageSegment::Gap) {
    if (++messageLetterIndex < strlen(messageText)) {
      startMessageLetter();
      return;
    }
    messageSegment = MessageSegment::Pause;
    messageSegmentLength = SAMPLE_RATE * 3;
  } else if (messageSegment == MessageSegment::Pause) {
#if defined(ALIVE_MESSAGE_TEST)
    messageLetterIndex = 0;
    startMessageLetter();
    return;
#else
    messageSegment = MessageSegment::Idle;
    messageSegmentLength = 0;
    Serial.println("DONE");
#endif
  }
  messageSegmentFrame = 0;
}

#if defined(ALIVE_SERIAL_MESSAGE)
void receiveSerialCommand() {
  while (Serial.available()) {
    const char ch = static_cast<char>(Serial.read());
    if (ch == '\r') continue;
    if (ch != '\n') {
      if (serialLineLength < sizeof(serialLine) - 1)
        serialLine[serialLineLength++] = ch;
      continue;
    }
    serialLine[serialLineLength] = '\0';
    if (strncmp(serialLine, "PLAY ", 5) == 0) {
      size_t count = 0;
      for (size_t i = 5; i < serialLineLength && count < 20; ++i) {
        const char letter = serialLine[i];
        if (letter >= 'A' && letter <= 'Z') messageText[count++] = letter;
        else if (letter == ' ' && count > 0) messageText[count++] = letter;
      }
      while (count > 0 && messageText[count - 1] == ' ') --count;
      messageText[count] = '\0';
      if (count > 0) {
        messageLetterIndex = 0;
        messageSegment = MessageSegment::Lead;
        messageSegmentFrame = 0;
        messageSegmentLength = SAMPLE_RATE / 4;
        Serial.printf("QUEUED %s\n", messageText);
      }
    }
    serialLineLength = 0;
  }
}
#endif

void writeContinuousMessageAudio() {
  int16_t samples[512];
  bool startedMessage = false;
  for (uint32_t i = 0; i < 256; ++i) {
    if (messageSegment != MessageSegment::Idle &&
        messageSegmentFrame >= messageSegmentLength) {
      advanceMessageSegment();
      if (messageSegment == MessageSegment::Tone && messageLetterIndex == 0)
        startedMessage = true;
    }
    int16_t sample = 0;
    if (messageSegment == MessageSegment::Tone) {
      const uint32_t fade = min(MESSAGE_FADE_FRAMES,
                                min(messageSegmentFrame,
                                    MESSAGE_BURST_FRAMES - messageSegmentFrame - 1));
      const int32_t mixed = messageSine[messageLowPhase] * 53 +
                            messageSine[messageHighPhase] * 47;
      sample = mixed * fade / (100 * MESSAGE_FADE_FRAMES);
      messageLowPhase = (messageLowPhase + messageLowStep) % MESSAGE_SINE_FRAMES;
      messageHighPhase = (messageHighPhase + messageHighStep) % MESSAGE_SINE_FRAMES;
    }
    samples[i * 2] = sample;
    samples[i * 2 + 1] = sample;
    ++messageSegmentFrame;
  }
  size_t written = 0;
  const esp_err_t error = i2s_write(I2S_PORT, samples, sizeof(samples),
                                   &written, portMAX_DELAY);
  if (error != ESP_OK || written != sizeof(samples)) {
    Serial.printf("I2S write failed: error=%d, bytes=%u\n", error,
                  static_cast<unsigned>(written));
  }
  if (startedMessage) Serial.printf("START %s\n", messageText);
}
#endif

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
  pinMode(STATUS_LED, OUTPUT);
  // The ESP32-C3 Super Mini's blue onboard LED is active-low.
  digitalWrite(STATUS_LED, HIGH);
  const i2s_config_t config = {
      .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
      .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
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
  ESP_ERROR_CHECK(i2s_driver_install(I2S_PORT, &config, 0, nullptr));
  ESP_ERROR_CHECK(i2s_set_pin(I2S_PORT, &pins));
  ESP_ERROR_CHECK(i2s_zero_dma_buffer(I2S_PORT));
  Serial.printf("I2S initialized: %lu Hz, 16-bit stereo, BCLK=4 LRC=5 DIN=6\n",
                static_cast<unsigned long>(SAMPLE_RATE));
#if defined(ALIVE_SILENCE_TEST)
  Serial.println("ALIVE silence test: I2S clocks active, speaker data is zero, blue LED blinking");
  writeSilence(500);
  lastHardwareTestAt = millis();
  lastLedToggleAt = millis();
#elif defined(ALIVE_HARDWARE_TEST)
  Serial.println("ALIVE hardware test: continuous 48 kHz I2S, 500 ms 800 Hz beep every 6 seconds");
  for (uint32_t i = 0; i < TEST_SINE_FRAMES; ++i) {
    testSine[i] = static_cast<int16_t>(sinf(TWO_PI * i / TEST_SINE_FRAMES) * AMPLITUDE);
  }
#elif defined(ALIVE_MESSAGE_TEST) || defined(ALIVE_SERIAL_MESSAGE)
  #if defined(ALIVE_MESSAGE_TEST)
  Serial.println("ALIVE message test: continuous 48 kHz I2S, sending HELLO repeatedly");
  #else
  Serial.println("ALIVE serial message ready: send PLAY <TEXT> followed by newline");
  #endif
  for (uint32_t i = 0; i < MESSAGE_SINE_FRAMES; ++i) {
    messageSine[i] = static_cast<int16_t>(sinf(TWO_PI * i / MESSAGE_SINE_FRAMES) * AMPLITUDE);
  }
#else
  connectWifi();
  Serial.println("ALIVE I2S emitter ready");
#endif
}

void loop() {
#if defined(ALIVE_SILENCE_TEST)
  writeSilence(100);
  if (millis() - lastLedToggleAt >= 250) {
    statusLedOn = !statusLedOn;
    digitalWrite(STATUS_LED, statusLedOn ? LOW : HIGH);
    lastLedToggleAt = millis();
  }
  if (millis() - lastHardwareTestAt >= 1000) {
    Serial.println("Silence test alive");
    lastHardwareTestAt = millis();
  }
#elif defined(ALIVE_HARDWARE_TEST)
  writeContinuousTestAudio();
#elif defined(ALIVE_MESSAGE_TEST)
  writeContinuousMessageAudio();
#elif defined(ALIVE_SERIAL_MESSAGE)
  receiveSerialCommand();
  writeContinuousMessageAudio();
#else
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (millis() - lastPollAt >= POLL_MS) {
    lastPollAt = millis();
    pollForMessage();
  }
#endif
#if !defined(ALIVE_HARDWARE_TEST) && !defined(ALIVE_MESSAGE_TEST) && !defined(ALIVE_SERIAL_MESSAGE)
  delay(10);
#endif
}
