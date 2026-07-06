#include <Arduino.h>

namespace {
constexpr int MP3_RX_PIN = 20; // ESP32-C3 RX pin, connected to player TX.
constexpr int MP3_TX_PIN = 21; // ESP32-C3 TX pin, connected to player RX.
constexpr int LED_PIN = 8;     // Common onboard LED pin on ESP32-C3 Super Mini boards.
constexpr int STOP_BUTTON_PIN = 9; // BOOT button on most ESP32-C3 Super Mini boards.
constexpr bool LED_ACTIVE_LOW = true;
constexpr unsigned long REPLAY_INTERVAL_MS = 8000;
constexpr unsigned long DEBOUNCE_MS = 40;

HardwareSerial mp3Serial(1);
unsigned long lastPlayCommandMs = 0;
unsigned long lastButtonChangeMs = 0;
int lastButtonReading = HIGH;
int stableButtonState = HIGH;
bool playbackStopped = false;

void setLed(bool on) {
  digitalWrite(LED_PIN, on == LED_ACTIVE_LOW ? LOW : HIGH);
}

void sendMp3Command(uint8_t command, uint16_t parameter) {
  uint8_t packet[10] = {
      0x7E,
      0xFF,
      0x06,
      command,
      0x01,
      static_cast<uint8_t>(parameter >> 8),
      static_cast<uint8_t>(parameter & 0xFF),
      0x00,
      0x00,
      0xEF,
  };

  uint16_t sum = 0;
  for (int i = 1; i <= 6; ++i) {
    sum += packet[i];
  }
  const uint16_t checksum = 0 - sum;
  packet[7] = static_cast<uint8_t>(checksum >> 8);
  packet[8] = static_cast<uint8_t>(checksum & 0xFF);

  mp3Serial.write(packet, sizeof(packet));
  mp3Serial.flush();
}

void stopPlayback() {
  sendMp3Command(0x0E, 0); // Pause playback.
  delay(80);
  sendMp3Command(0x16, 0); // Stop playback.
  playbackStopped = true;
  setLed(false);
  Serial.println("Playback stopped by BOOT button");
}
} // namespace

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  setLed(false);
  pinMode(STOP_BUTTON_PIN, INPUT_PULLUP);
  delay(1500);
  Serial.println("ALIVE MP3-TF play HELLO diagnostic");
  Serial.printf("LED pin GPIO%d disabled; stop button GPIO%d; MP3 RX=GPIO%d TX=GPIO%d\n",
                LED_PIN,
                STOP_BUTTON_PIN,
                MP3_RX_PIN,
                MP3_TX_PIN);

  mp3Serial.begin(9600, SERIAL_8N1, MP3_RX_PIN, MP3_TX_PIN);
  delay(1200);

  sendMp3Command(0x09, 0x0002); // Select TF/SD card.
  delay(800);
  sendMp3Command(0x06, 25);     // Volume 0-30.
  delay(500);
  sendMp3Command(0x12, 1);      // Play /mp3/0001.mp3.
  delay(500);
  sendMp3Command(0x03, 1);      // Fallback: play track index 0001.
  lastPlayCommandMs = millis();

  Serial.println("Sent play commands for 0001.mp3; press BOOT to stop");
}

void loop() {
  const int buttonReading = digitalRead(STOP_BUTTON_PIN);
  if (buttonReading != lastButtonReading) {
    lastButtonChangeMs = millis();
    lastButtonReading = buttonReading;
  }
  if (millis() - lastButtonChangeMs >= DEBOUNCE_MS && buttonReading != stableButtonState) {
    stableButtonState = buttonReading;
    if (stableButtonState == LOW && !playbackStopped) {
      stopPlayback();
    }
  }

  if (!playbackStopped && millis() - lastPlayCommandMs >= REPLAY_INTERVAL_MS) {
    sendMp3Command(0x12, 1);
    delay(250);
    sendMp3Command(0x03, 1);
    lastPlayCommandMs = millis();
    Serial.println("Re-sent play commands for 0001.mp3");
  }

  while (mp3Serial.available() > 0) {
    Serial.printf("MP3 response: 0x%02X\n", mp3Serial.read());
  }
  delay(50);
}
