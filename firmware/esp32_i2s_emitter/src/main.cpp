#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <driver/i2s.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "beacon_voice.h"
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
constexpr uint32_t POLL_MS = 2000;
constexpr uint32_t WIFI_JOIN_TIMEOUT_MS = 15000;
constexpr uint32_t RESTART_AFTER_MS = 180000;
constexpr uint32_t WATCHDOG_S = 30;
static_assert(SAMPLE_RATE == beacon::rate, "The chirp tables assume 48 kHz");

long lastRevision = -1;
uint32_t lastPollAt = 0;
uint32_t lastHealthyAt = 0;
uint32_t wifiJoinStartedAt = 0;
// Retain the TLS session between polls instead of negotiating on every request.
WiFiClientSecure pollClient;
HTTPClient pollHttp;

// Returns false when the amplifier stream fails, so playback stops instead of
// reporting a message it never sent.
bool writeFrames(const int16_t *samples, size_t frames) {
  size_t written = 0;
  // Interleaved left/right samples keep the I2S frame unambiguous for the amp.
  const size_t bytes = frames * 2 * sizeof(int16_t);
  const esp_err_t error = i2s_write(I2S_PORT, samples, bytes, &written, pdMS_TO_TICKS(1000));
  esp_task_wdt_reset();
  if (error != ESP_OK || written != bytes) {
    Serial.printf("I2S write failed: error=%d, bytes=%u\n", error,
                  static_cast<unsigned>(written));
    return false;
  }
  return true;
}

bool writeSilence(uint32_t durationMs) {
  static const int16_t zeros[512] = {};
  for (uint32_t remaining = SAMPLE_RATE * durationMs / 1000; remaining > 0;) {
    const uint32_t count = min<uint32_t>(remaining, 256);
    if (!writeFrames(zeros, count)) return false;
    remaining -= count;
  }
  return true;
}

// One 360 ms chirp. Symbol -1 is the sync chirp that frames a message.
bool writeChirp(int symbol) {
  beacon::Voice voice;
  voice.reset(symbol);
  int16_t samples[512];
  for (uint32_t frame = 0; frame < beacon::frames; frame += 256) {
    const uint32_t count = min<uint32_t>(256, beacon::frames - frame);
    for (uint32_t i = 0; i < count; ++i) samples[i * 2] = samples[i * 2 + 1] = voice.next();
    if (!writeFrames(samples, count)) return false;
  }
  return true;
}

// Two sync chirps, one chirp per character, and a closing sync chirp. The
// timing must match signal_duration_seconds() in reply_engine.py.
bool writeMessage(const char *text) {
  if (!writeSilence(150) || !writeChirp(-1) || !writeSilence(180) ||
      !writeChirp(-1) || !writeSilence(280))
    return false;
  for (size_t i = 0; text[i]; ++i) {
    if (!writeChirp(beacon::symbolFor(text[i])) || !writeSilence(180)) return false;
  }
  return writeChirp(-1) && writeSilence(760);
}

void startAudio() {
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
}

void playMessage(const String &message) {
  char text[21] = {};
  size_t count = 0;
  for (size_t i = 0; i < message.length() && count < sizeof(text) - 1; ++i) {
    const char ch = message[i];
    if ((ch >= 'A' && ch <= 'Z') || ch == ' ') text[count++] = ch;
  }
  if (count == 0) return;
  // The I2S clocks run only during playback; without them the amplifier
  // shuts down, which is most of the idle battery saving.
  startAudio();
  Serial.printf("Playing revision %ld: %s\n", lastRevision, text);
  if (!writeMessage(text)) Serial.println("Playback stopped early");
  ESP_ERROR_CHECK(i2s_driver_uninstall(I2S_PORT));
}

void joinWifi() {
  const int networkCount = WiFi.scanNetworks();
  int bestTargetRssi = -127;
  for (int i = 0; i < networkCount; ++i) {
    if (WiFi.SSID(i) == ALIVE_WIFI_SSID)
      bestTargetRssi = max(bestTargetRssi, static_cast<int>(WiFi.RSSI(i)));
  }
  WiFi.scanDelete();
  if (bestTargetRssi == -127) Serial.println("Target WiFi not found in scan");
  else Serial.printf("Target WiFi RSSI: %d dBm\n", bestTargetRssi);
  WiFi.disconnect();
  WiFi.begin(ALIVE_WIFI_SSID, ALIVE_WIFI_PASSWORD);
  Serial.printf("Connecting to %s\n", ALIVE_WIFI_SSID);
  wifiJoinStartedAt = millis();
}

void setupWifi() {
  WiFi.mode(WIFI_STA);
  // Modem sleep lets the radio doze between beacons while the board waits
  // for the next poll. Arduino applies it to every later connection.
  WiFi.setSleep(true);
  // This Super Mini repeatedly failed authentication/DHCP at default TX power.
  // 8.5 dBm is the measured working setting for the assembled device.
  Serial.printf("WiFi TX power 8.5 dBm: %s\n",
                WiFi.setTxPower(WIFI_POWER_8_5dBm) ? "set" : "failed");
  WiFi.onEvent([](WiFiEvent_t event, WiFiEventInfo_t info) {
    if (event == ARDUINO_EVENT_WIFI_STA_CONNECTED)
      Serial.println("WiFi associated; waiting for IP");
    if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP)
      Serial.printf("WiFi ready: %s\n", WiFi.localIP().toString().c_str());
    if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED)
      Serial.printf("WiFi disconnected: reason %u\n",
                    info.wifi_sta_disconnected.reason);
  });
#ifdef ALIVE_SERVER_CA_CERT
  // Certificate checks need real time. SNTP keeps retrying in the background;
  // polls fail until it succeeds and the restart deadline covers a long outage.
  configTime(0, 0, "pool.ntp.org", "time.google.com");
#endif
  joinWifi();
}

void pollForMessage() {
  static bool serverReachable = false;
  auto &client = pollClient;
  client.setHandshakeTimeout(8);
#ifdef ALIVE_SERVER_CA_CERT
  client.setCACert(ALIVE_SERVER_CA_CERT);
#else
  client.setInsecure();  // Local test only; configure a trusted CA for the API.
#endif
  auto &http = pollHttp;
  http.setConnectTimeout(5000);
  http.setTimeout(5000);
  http.setReuse(true);
  const String url = String(ALIVE_SERVER_URL) + "/api/emitter/main/current";
  if (!http.begin(client, url)) return;
#ifdef ALIVE_DEVICE_TOKEN
  http.addHeader("Authorization", String("Bearer ") + ALIVE_DEVICE_TOKEN);
#endif
  // The API logs these per board to time battery runtime and spot brownouts.
  http.addHeader("X-Alive-Board", WiFi.macAddress());
  http.addHeader("X-Alive-Uptime-Ms", String(millis()));
  http.addHeader("X-Alive-Reset", String(static_cast<int>(esp_reset_reason())));
  const int status = http.GET();
  if (status == HTTP_CODE_OK) {
    JsonDocument json;
    // Consume the entire body, including HTTP/1.1 chunk framing, before reuse.
    const DeserializationError error = deserializeJson(json, http.getString());
    if (!error && json["revision"].is<long>() && json["message"].is<const char *>()) {
      if (!serverReachable) Serial.println("API poll ready: HTTPS verified, device token accepted");
      serverReachable = true;
      lastHealthyAt = millis();
      const long revision = json["revision"];
      const String message = json["message"].as<const char *>();
      if (lastRevision < 0 || revision < lastRevision) {
        // Boot or server reset: observe the current command without replaying it.
        lastRevision = revision;
      } else if (revision > lastRevision && message.length() > 0) {
        lastRevision = revision;
        http.end();
        playMessage(message);
        return;
      }
    } else {
      client.stop();
      Serial.printf("Unexpected poll response: %s\n", error ? error.c_str() : "missing fields");
    }
  } else {
    serverReachable = false;
    char tlsError[128] = {};
    const int tlsCode = client.lastError(tlsError, sizeof(tlsError));
    Serial.printf("Poll failed: HTTP %d (%s), TLS %d (%s)\n", status,
                  http.errorToString(status).c_str(), tlsCode, tlsError);
    client.stop(); // Reconnect promptly if the server closed an idle session.
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(STATUS_LED, OUTPUT);
  // The ESP32-C3 Super Mini's blue onboard LED is active-low.
  digitalWrite(STATUS_LED, HIGH);
  // A stuck TLS handshake, HTTP read, or I2S write resets the board.
  esp_task_wdt_init(WATCHDOG_S, true);
  enableLoopWDT();
  setupWifi();
  Serial.println("ALIVE ultrasound emitter ready");
}

void loop() {
  // A restart clears Wi-Fi, DNS, TLS, and HTTP state together. It is the one
  // recovery path for every outage that outlasts ordinary reconnects.
  if (millis() - lastHealthyAt >= RESTART_AFTER_MS) {
    Serial.println("No valid poll for 3 minutes; restarting");
    ESP.restart();
  }
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - wifiJoinStartedAt >= WIFI_JOIN_TIMEOUT_MS) joinWifi();
  } else if (millis() - lastPollAt >= POLL_MS) {
    lastPollAt = millis();
    pollForMessage();
  }
  delay(10);
}
