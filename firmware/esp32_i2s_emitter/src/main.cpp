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
// A network that is joined but cannot reach the API is left for the next one.
constexpr uint32_t SWITCH_NETWORK_AFTER_MS = 60000;
// Without the API the board plays its own noise, clock, and beacon signals.
constexpr uint32_t OFFLINE_AFTER_MS = 60000;
constexpr uint32_t RESTART_AFTER_MS = 600000;
// The API keeps the air free for a signal for this long after granting it.
// A later arrival is dropped, since another board may already be playing.
constexpr uint32_t DELIVERY_MS = 4000;
constexpr uint32_t WATCHDOG_S = 30;
static_assert(SAMPLE_RATE == beacon::rate, "The chirp tables assume 48 kHz");

struct WifiNetwork {
  const char *ssid;
  const char *password;
};
#ifdef ALIVE_WIFI_NETWORKS
const WifiNetwork NETWORKS[] = {ALIVE_WIFI_NETWORKS};
#else
const WifiNetwork NETWORKS[] = {{ALIVE_WIFI_SSID, ALIVE_WIFI_PASSWORD}};
#endif
constexpr int NETWORK_COUNT = sizeof(NETWORKS) / sizeof(NETWORKS[0]);

// A chirp sequence: lead silence, then each chirp with the silence after it.
// signals.py on the API builds the same sequences.
struct Score {
  char kind[16] = {};
  uint32_t leadMs = 0;
  size_t count = 0;
  int8_t symbol[128] = {};
  uint16_t gapMs[128] = {};
};
Score score;

// Beacons for offline mode. The API sends the same lines.
const char *const BEACON_LINES[] = {"IS ANYONE THERE", "WE ARE HERE", "THIS IS LANTERN",
                                    "AURORA CALLING", "CAN YOU HEAR US", "ANSWER IF YOU HEAR"};

int currentNetwork = -1;
// Networks that failed since the last good poll, one bit each.
uint32_t failedNetworks = 0;
static_assert(NETWORK_COUNT <= 32, "failedNetworks has one bit per network");
uint32_t lastPollAt = 0;
uint32_t lastHealthyAt = 0;
uint32_t wifiJoinStartedAt = 0;
uint32_t nextOfflineSignalAt = 0;
bool offline = false;
// This board's offline clock: channel, period, and tick count.
int clockSymbol = 0;
uint32_t clockPeriodMs = 1000, clockTicks = 8;
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

bool writeScore() {
  if (!writeSilence(score.leadMs)) return false;
  for (size_t i = 0; i < score.count; ++i) {
    if (!writeChirp(score.symbol[i]) || !writeSilence(score.gapMs[i])) return false;
  }
  return true;
}

void addChirp(int symbol, uint32_t gapMs) {
  if (score.count >= sizeof(score.symbol)) return;
  score.symbol[score.count] = symbol;
  score.gapMs[score.count++] = gapMs;
}

// Two sync chirps, one chirp per character, and a closing sync chirp. The
// timing must match signal_duration_seconds() in reply_engine.py.
void composeMessage(const char *text) {
  strlcpy(score.kind, "intelligent", sizeof(score.kind));
  score.leadMs = 150;
  score.count = 0;
  addChirp(-1, 180);
  addChirp(-1, 280);
  for (size_t i = 0; text[i]; ++i) {
    if (beacon::symbolFor(text[i]) >= 0) addChirp(beacon::symbolFor(text[i]), 180);
  }
  addChirp(-1, 760);
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

void playScore() {
  if (score.count == 0) return;
  // The I2S clocks run only during playback; without them the amplifier
  // shuts down, which is most of the idle battery saving.
  startAudio();
  Serial.printf("Playing %s signal, %u chirps\n", score.kind, static_cast<unsigned>(score.count));
  if (!writeScore()) Serial.println("Playback stopped early");
  ESP_ERROR_CHECK(i2s_driver_uninstall(I2S_PORT));
}

// Offline mode: noise, this board's clock, or now and then a beacon. Boards
// cannot hear each other, so long random pauses keep overlaps rare.
void playOfflineSignal() {
  const long pick = random(100);
  score.count = 0;
  score.leadMs = 0;
  if (pick < 15) {
    composeMessage(BEACON_LINES[random(sizeof(BEACON_LINES) / sizeof(BEACON_LINES[0]))]);
  } else if (pick < 50) {
    strlcpy(score.kind, "clock", sizeof(score.kind));
    for (uint32_t i = 0; i < clockTicks; ++i) addChirp(clockSymbol, clockPeriodMs - 360);
  } else {
    strlcpy(score.kind, "noise", sizeof(score.kind));
    for (long i = random(3, 11); i > 0; --i) addChirp(random(27), random(180, 901));
  }
  playScore();
}

// Joins the first listed network the scan shows that has not failed since the
// last good poll. Once every visible network has failed, it starts over. With
// none in range, it tries each listed network in turn, for hidden ones.
void joinWifi() {
  const int found = WiFi.scanNetworks();
  int choice = -1;
  for (int pass = 0; pass < 2 && choice < 0; ++pass) {
    for (int k = 0; k < NETWORK_COUNT && choice < 0; ++k) {
      if (failedNetworks & (1u << k)) continue;
      for (int i = 0; i < found; ++i) {
        if (WiFi.SSID(i) != NETWORKS[k].ssid) continue;
        Serial.printf("Found %s at %d dBm\n", NETWORKS[k].ssid, static_cast<int>(WiFi.RSSI(i)));
        choice = k;
        break;
      }
    }
    if (choice < 0) failedNetworks = 0;
  }
  WiFi.scanDelete();
  if (choice < 0) choice = (currentNetwork + 1) % NETWORK_COUNT;
  currentNetwork = choice;
  WiFi.disconnect();
  WiFi.begin(NETWORKS[choice].ssid, NETWORKS[choice].password);
  Serial.printf("Connecting to %s\n", NETWORKS[choice].ssid);
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
  const uint32_t requestedAt = millis();
  const int status = http.GET();
  if (status == HTTP_CODE_OK) {
    JsonDocument json;
    // Consume the entire body, including HTTP/1.1 chunk framing, before reuse.
    const DeserializationError error = deserializeJson(json, http.getString());
    if (!error && json["role"].is<const char *>()) {
      if (!serverReachable)
        Serial.printf("API poll ready on %s: HTTPS verified, device token accepted, role %s\n",
                      NETWORKS[currentNetwork].ssid, json["role"].as<const char *>());
      serverReachable = true;
      offline = false;
      failedNetworks = 0;
      lastHealthyAt = millis();
      // The API hands out each signal once, to one board at a time.
      JsonObject play = json["play"].as<JsonObject>();
      if (!play.isNull() && millis() - requestedAt > DELIVERY_MS) {
        Serial.printf("Dropped a %s signal that arrived after %lu ms\n", play["kind"] | "",
                      static_cast<unsigned long>(millis() - requestedAt));
      } else if (!play.isNull()) {
        strlcpy(score.kind, play["kind"] | "signal", sizeof(score.kind));
        score.leadMs = min<uint32_t>(play["leadMs"] | 0, 2000);
        score.count = 0;
        for (JsonArray chirp : play["chirps"].as<JsonArray>()) {
          const int symbol = chirp[0] | -2;
          if (symbol >= -1 && symbol <= 26) addChirp(symbol, min<uint32_t>(chirp[1] | 0, 5000));
        }
        http.end();
        playScore();
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
  // random() draws from the hardware generator, which the radio seeds.
  clockSymbol = random(27);
  clockPeriodMs = random(900, 1601);
  clockTicks = random(6, 13);
  Serial.println("ALIVE ultrasound emitter ready");
}

void loop() {
  // A restart clears Wi-Fi, DNS, TLS, and HTTP state together. It is the last
  // recovery path for an outage that outlasts reconnects and network changes.
  const uint32_t sinceHealthy = millis() - lastHealthyAt;
  if (sinceHealthy >= RESTART_AFTER_MS) {
    Serial.println("No valid poll for 10 minutes; restarting");
    ESP.restart();
  }
  if (sinceHealthy >= OFFLINE_AFTER_MS) {
    if (!offline) {
      offline = true;
      // Boards usually lose the API together; spread their first signals.
      nextOfflineSignalAt = millis() + random(1000, 30000);
      Serial.println("API unreachable; playing offline signals");
    } else if (static_cast<int32_t>(millis() - nextOfflineSignalAt) >= 0) {
      playOfflineSignal();
      nextOfflineSignalAt = millis() + random(25000, 90000);
    }
  }
  const bool joinTimedOut = WiFi.status() != WL_CONNECTED && millis() - wifiJoinStartedAt >= WIFI_JOIN_TIMEOUT_MS;
  const bool noRoute = WiFi.status() == WL_CONNECTED && sinceHealthy >= SWITCH_NETWORK_AFTER_MS &&
                       millis() - wifiJoinStartedAt >= SWITCH_NETWORK_AFTER_MS;
  if (joinTimedOut || noRoute) {
    if (noRoute) Serial.printf("No API reply over %s; trying another network\n", NETWORKS[currentNetwork].ssid);
    if (currentNetwork >= 0) failedNetworks |= 1u << currentNetwork;
    joinWifi();
  } else if (WiFi.status() == WL_CONNECTED && millis() - lastPollAt >= POLL_MS) {
    lastPollAt = millis();
    pollForMessage();
  }
  delay(10);
}
