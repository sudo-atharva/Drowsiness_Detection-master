// Vehicle ESP32 (onboard the car/rover)
// - MPU6050 over I2C, read locally, streamed to Controller ESP32 via ESP-NOW
// - Drives 2 DC motors (4 direction pins total) from button commands received via ESP-NOW
// - Status LED (D4): solid = connected+awake, slow blink (3s) = drowsy, fast blink (1s) = link lost
// - Safety: motors are force-stopped whenever the link is lost OR the drowsy flag is set

#include <esp_now.h>
#include <WiFi.h>
#include <Wire.h>

// ponytail: struct layout is duplicated in controller_esp32.ino — keep both in sync by hand,
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

uint8_t controllerMac[6] = {0x30, 0x76, 0xF5, 0x90, 0x99, 0xC8}; // Controller ESP32 (remote)

// Motor driver pins: 2 direction pins per motor, digital full-speed only
// (matches a plain L298N/L9110-style driver with ENA/ENB tied high; add PWM later for speed control)
#define MOTOR_L_IN1 25
#define MOTOR_L_IN2 26
#define MOTOR_R_IN1 27
#define MOTOR_R_IN2 14
#define STATUS_LED  4

const uint8_t MPU_ADDR = 0x68;
const unsigned long TELEMETRY_INTERVAL_MS = 50;   // 20 Hz
const unsigned long LINK_TIMEOUT_MS       = 2000;
const unsigned long DROWSY_BLINK_MS       = 3000;
const unsigned long LOST_BLINK_MS         = 1000;

ControlPacket lastControl = {0, 0, 0, 0, 0};
unsigned long lastControlRx = 0;
unsigned long lastTelemetrySend = 0;
unsigned long lastLedToggle = 0;
bool ledState = false;

void mpuInit() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B); // PWR_MGMT_1
  Wire.write(0x00); // wake up
  Wire.endTransmission(true);
}

// raw register read -> accel in g, gyro in deg/s (default +-2g / +-250dps ranges)
void mpuRead(TelemetryPacket &t) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B); // ACCEL_XOUT_H
  Wire.endTransmission(false);
  Wire.requestFrom((int)MPU_ADDR, 14, true);

  int16_t ax = (Wire.read() << 8) | Wire.read();
  int16_t ay = (Wire.read() << 8) | Wire.read();
  int16_t az = (Wire.read() << 8) | Wire.read();
  Wire.read(); Wire.read(); // temperature, unused
  int16_t gx = (Wire.read() << 8) | Wire.read();
  int16_t gy = (Wire.read() << 8) | Wire.read();
  int16_t gz = (Wire.read() << 8) | Wire.read();

  t.ax = ax / 16384.0f;
  t.ay = ay / 16384.0f;
  t.az = az / 16384.0f;
  t.gx = gx / 131.0f;
  t.gy = gy / 131.0f;
  t.gz = gz / 131.0f;
}

void motorsStop() {
  digitalWrite(MOTOR_L_IN1, LOW);
  digitalWrite(MOTOR_L_IN2, LOW);
  digitalWrite(MOTOR_R_IN1, LOW);
  digitalWrite(MOTOR_R_IN2, LOW);
}

void motorsApply(const ControlPacket &c) {
  // priority: forward > backward > left (pivot) > right (pivot) > stop
  if (c.forward) {
    digitalWrite(MOTOR_L_IN1, HIGH); digitalWrite(MOTOR_L_IN2, LOW);
    digitalWrite(MOTOR_R_IN1, HIGH); digitalWrite(MOTOR_R_IN2, LOW);
  } else if (c.backward) {
    digitalWrite(MOTOR_L_IN1, LOW);  digitalWrite(MOTOR_L_IN2, HIGH);
    digitalWrite(MOTOR_R_IN1, LOW);  digitalWrite(MOTOR_R_IN2, HIGH);
  } else if (c.left) {
    digitalWrite(MOTOR_L_IN1, LOW);  digitalWrite(MOTOR_L_IN2, HIGH); // left motor reverse
    digitalWrite(MOTOR_R_IN1, HIGH); digitalWrite(MOTOR_R_IN2, LOW);  // right motor forward
  } else if (c.right) {
    digitalWrite(MOTOR_L_IN1, HIGH); digitalWrite(MOTOR_L_IN2, LOW);  // left motor forward
    digitalWrite(MOTOR_R_IN1, LOW);  digitalWrite(MOTOR_R_IN2, HIGH); // right motor reverse
  } else {
    motorsStop();
  }
}

void onDataRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != sizeof(ControlPacket)) return;
  memcpy(&lastControl, data, sizeof(lastControl));
  lastControlRx = millis();
}

void setup() {
  Serial.begin(115200);

  pinMode(MOTOR_L_IN1, OUTPUT);
  pinMode(MOTOR_L_IN2, OUTPUT);
  pinMode(MOTOR_R_IN1, OUTPUT);
  pinMode(MOTOR_R_IN2, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);
  motorsStop();

  Wire.begin(); // default SDA=21, SCL=22
  mpuInit();

  WiFi.mode(WIFI_STA);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    return;
  }
  esp_now_register_recv_cb(onDataRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, controllerMac, 6);
  peer.channel = 0;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    Serial.println("Failed to add controller peer");
  }
}

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

void loop() {
  unsigned long now = millis();

  bool linkOk = (lastControlRx != 0) && (now - lastControlRx < LINK_TIMEOUT_MS);

  if (!linkOk || lastControl.drowsy) {
    motorsStop();
  } else {
    motorsApply(lastControl);
  }

  updateLed(linkOk, lastControl.drowsy);

  if (now - lastTelemetrySend >= TELEMETRY_INTERVAL_MS) {
    lastTelemetrySend = now;
    TelemetryPacket t;
    mpuRead(t);
    esp_now_send(controllerMac, (uint8_t *)&t, sizeof(t));
  }
}
