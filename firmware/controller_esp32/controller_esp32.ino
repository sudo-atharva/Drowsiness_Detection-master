// Controller ESP32 (handheld RC unit)
// - 4 buttons: FORWARD / BACKWARD / LEFT / RIGHT
// - USB-serial link to host (Raspberry Pi / PC running drowsiness detection)
// - ESP-NOW link to Vehicle ESP32: sends button + drowsy state, receives MPU6050 telemetry
//
// Host serial protocol (115200 baud, line-based):
//   host -> controller : "DROWSY\n" | "AWAKE\n"
//   controller -> host : "MPU,ax,ay,az,gx,gy,gz\n"   (forwarded from vehicle)
//                        "LINK,OK\n" | "LINK,LOST\n" (vehicle connection status)

#include <esp_now.h>
#include <WiFi.h>

// ponytail: struct layout is duplicated in vehicle_esp32.ino — keep both in sync by hand,
// a shared header is overkill for two small structs on a 2-node link.
typedef struct {
  uint8_t forward;
  uint8_t backward;
  uint8_t left;
  uint8_t right;
  uint8_t drowsy; // 0 = awake, 1 = drowsy
} ControlPacket;

typedef struct {
  float ax, ay, az;
  float gx, gy, gz;
} TelemetryPacket;

uint8_t vehicleMac[6] = {0x58, 0x2A, 0xBD, 0xD2, 0xC0, 0x3C}; // Vehicle ESP32


#define BTN_FORWARD  32
#define BTN_BACKWARD 33
#define BTN_LEFT     25
#define BTN_RIGHT    26
#define STATUS_LED   4  // solid = linked+awake, 3s blink = drowsy, 1s blink = link lost

const unsigned long SEND_INTERVAL_MS = 100;   // 10 Hz control + heartbeat
const unsigned long LINK_TIMEOUT_MS  = 2000;
const unsigned long DROWSY_BLINK_MS  = 3000;
const unsigned long LOST_BLINK_MS    = 1000;

ControlPacket outPacket = {0, 0, 0, 0, 0};
unsigned long lastSend = 0;
unsigned long lastTelemetryRx = 0;
unsigned long lastLedToggle = 0;
bool ledState = false;
bool linkWasOk = false;
String serialLine;

void updateLed(bool linkOk, bool drowsy) {
  unsigned long now = millis();
  if (!linkOk) {
    if (now - lastLedToggle >= LOST_BLINK_MS) {
      lastLedToggle = now;
      ledState = !ledState;
      digitalWrite(STATUS_LED, ledState);
    }
  } else if (drowsy) {
    if (now - lastLedToggle >= DROWSY_BLINK_MS) {
      lastLedToggle = now;
      ledState = !ledState;
      digitalWrite(STATUS_LED, ledState);
    }
  } else {
    digitalWrite(STATUS_LED, HIGH);
  }
}

void onDataRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != sizeof(TelemetryPacket)) return;
  TelemetryPacket t;
  memcpy(&t, data, sizeof(t));
  lastTelemetryRx = millis();
  Serial.printf("MPU,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f\n", t.ax, t.ay, t.az, t.gx, t.gy, t.gz);
}

void setup() {
  Serial.begin(115200);

  pinMode(BTN_FORWARD, INPUT_PULLUP);
  pinMode(BTN_BACKWARD, INPUT_PULLUP);
  pinMode(BTN_LEFT, INPUT_PULLUP);
  pinMode(BTN_RIGHT, INPUT_PULLUP);

  WiFi.mode(WIFI_STA);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    return;
  }
  esp_now_register_recv_cb(onDataRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, vehicleMac, 6);
  peer.channel = 0;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    Serial.println("Failed to add vehicle peer");
  }
}

void pollHostSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      serialLine.trim();
      if (serialLine == "DROWSY") outPacket.drowsy = 1;
      else if (serialLine == "AWAKE") outPacket.drowsy = 0;
      serialLine = "";
    } else if (c != '\r') {
      serialLine += c;
    }
  }
}

void loop() {
  pollHostSerial();

  // buttons are active LOW (INPUT_PULLUP, wired to GND)
  outPacket.forward  = (digitalRead(BTN_FORWARD)  == LOW) ? 1 : 0;
  outPacket.backward = (digitalRead(BTN_BACKWARD) == LOW) ? 1 : 0;
  outPacket.left      = (digitalRead(BTN_LEFT)     == LOW) ? 1 : 0;
  outPacket.right     = (digitalRead(BTN_RIGHT)    == LOW) ? 1 : 0;

  unsigned long now = millis();
  if (now - lastSend >= SEND_INTERVAL_MS) {
    lastSend = now;
    esp_now_send(vehicleMac, (uint8_t *)&outPacket, sizeof(outPacket));
  }

  bool linkOk = (now - lastTelemetryRx < LINK_TIMEOUT_MS) && (lastTelemetryRx != 0);
  if (linkOk != linkWasOk) {
    linkWasOk = linkOk;
    Serial.println(linkOk ? "LINK,OK" : "LINK,LOST");
  }
}
