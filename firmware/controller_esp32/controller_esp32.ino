// Controller ESP32 — USB<->ESP-NOW bridge, plus its own 4 physical buttons.
// - Drives the Vehicle ESP32 over ESP-NOW: direction comes from whichever moved
//   most recently, the physical buttons or a drive command from the host's website.
//   Physical buttons win over a stale website command if both are held/set at once.
// - Relays the host's DROWSY/AWAKE state onward to the vehicle over ESP-NOW.
// - Relays MPU6050 telemetry (received from the vehicle over ESP-NOW) to the host over USB.
// - Status LED (D4): solid = linked to vehicle, blink (1s) = link lost
//
// Host serial protocol (115200 baud, line-based):
//   host -> controller : "DROWSY\n" | "AWAKE\n"
//                         "DIR,forward\n" | "DIR,backward\n" | "DIR,left\n" | "DIR,right\n" | "DIR,stop\n"
//   controller -> host : "MPU,ax,ay,az,gx,gy,gz\n"   (forwarded from vehicle)
//                        "LINK,OK\n" | "LINK,LOST\n" (vehicle connection status)

#include <esp_now.h>
#include <WiFi.h>
#include "esp_mac.h"

// ponytail: struct layout duplicated in vehicle_esp32.ino — keep both in sync by hand,
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

uint8_t vehicleMac[6] = {0x68, 0x09, 0x47, 0x87, 0xA4, 0x68}; // Vehicle ESP32

#define BTN_FORWARD  32
#define BTN_BACKWARD 33
#define BTN_LEFT     25
#define BTN_RIGHT    26
#define STATUS_LED   4

const unsigned long SEND_INTERVAL_MS = 100;   // 10 Hz control + heartbeat
const unsigned long LINK_TIMEOUT_MS  = 2000;
const unsigned long LOST_BLINK_MS    = 1000;

ControlPacket outPacket = {0, 0, 0, 0, 0};
String hostDir = "stop";      // last direction the website asked for
unsigned long lastSend = 0;
unsigned long lastTelemetryRx = 0;
unsigned long lastLedToggle = 0;
bool ledState = false;
bool linkWasOk = false;
String serialLine;
bool prevF = false, prevB = false, prevL = false, prevR = false;

void onDataRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != sizeof(TelemetryPacket)) return;
  TelemetryPacket t;
  memcpy(&t, data, sizeof(t));
  lastTelemetryRx = millis();
  Serial.printf("MPU,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f\n", t.ax, t.ay, t.az, t.gx, t.gy, t.gz);
}

void updateLed(bool linkOk) {
  unsigned long now = millis();
  if (!linkOk) {
    if (now - lastLedToggle >= LOST_BLINK_MS) {
      lastLedToggle = now;
      ledState = !ledState;
      digitalWrite(STATUS_LED, ledState);
    }
  } else {
    digitalWrite(STATUS_LED, HIGH);
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(BTN_FORWARD, INPUT_PULLUP);
  pinMode(BTN_BACKWARD, INPUT_PULLUP);
  pinMode(BTN_LEFT, INPUT_PULLUP);
  pinMode(BTN_RIGHT, INPUT_PULLUP);
  pinMode(STATUS_LED, OUTPUT);

  WiFi.mode(WIFI_STA); // ESP-NOW needs the radio up, even with no AP connection

  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA); // reads eFuse directly - reliable even before any WiFi activity
  Serial.printf("This board's MAC (paste into vehicle_esp32.ino's controllerMac[]): "
                "{0x%02X, 0x%02X, 0x%02X, 0x%02X, 0x%02X, 0x%02X}\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

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
      else if (serialLine.startsWith("DIR,")) hostDir = serialLine.substring(4);
      serialLine = "";
    } else if (c != '\r') {
      serialLine += c;
    }
  }
}

void loop() {
  pollHostSerial();

  // physical buttons are active LOW (INPUT_PULLUP, wired to GND) and always win
  // over a stale website command if someone's actually holding one down
  bool f = digitalRead(BTN_FORWARD)  == LOW;
  bool b = digitalRead(BTN_BACKWARD) == LOW;
  bool l = digitalRead(BTN_LEFT)     == LOW;
  bool r = digitalRead(BTN_RIGHT)    == LOW;
  bool anyButtonPressed = f || b || l || r;

  // debug: print on press (rising edge only, not held-down spam)
  if (f && !prevF) Serial.println("BTN,forward");
  if (b && !prevB) Serial.println("BTN,backward");
  if (l && !prevL) Serial.println("BTN,left");
  if (r && !prevR) Serial.println("BTN,right");
  prevF = f; prevB = b; prevL = l; prevR = r;

  if (anyButtonPressed) {
    outPacket.forward = f; outPacket.backward = b; outPacket.left = l; outPacket.right = r;
  } else {
    outPacket.forward  = (hostDir == "forward")  ? 1 : 0;
    outPacket.backward = (hostDir == "backward") ? 1 : 0;
    outPacket.left     = (hostDir == "left")     ? 1 : 0;
    outPacket.right    = (hostDir == "right")    ? 1 : 0;
  }

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

  updateLed(linkOk);
}
