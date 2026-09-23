# Drowsy-Aware RC Vehicle — ESP32 Firmware

Two ESP32 boards, linked over ESP-NOW. The Controller is also the USB
bridge to the host — the Vehicle has no WiFi/network of its own at all.

```
[Host: webcam + drowsiness detection + dashboard, over Tailscale]
        |  USB serial (115200 baud)
        v
[Controller ESP32]  <---- ESP-NOW ---->  [Vehicle ESP32]
 4 buttons (F/B/L/R)                      MPU6050 (I2C)
 status LED (D4)                          2 motors (4 direction pins)
                                           status LED (D4)
```

- **Controller ESP32** sits at the host end, wired to the host over USB. It
  reads its own 4 buttons and drives the vehicle from them directly, and can
  also be driven by FWD/BACK/LEFT/RIGHT/STOP commands sent over USB (see
  `host/drive_dashboard.py`) — a physical button press always overrides and
  cancels whatever the web command was. It relays the host's drowsy/awake
  state onward, and relays MPU6050 telemetry (received from the vehicle over
  ESP-NOW) back to the host over the same USB line.
- **Vehicle ESP32** sits on the car. No WiFi, no router dependency — pure
  ESP-NOW. It owns the MPU6050, drives the 2 motors, and enforces the
  kill-switch itself: if the drowsy flag is set, or the ESP-NOW link from
  the Controller goes quiet, motors are force-stopped. The Controller does
  not need to be trusted or even working correctly for the vehicle to fail
  safe.

## Files

- `controller_esp32/controller_esp32.ino`
- `vehicle_esp32/vehicle_esp32.ino`

## Wiring

### Controller ESP32
| Signal | GPIO |
|---|---|
| Button FORWARD | 32 (to GND, `INPUT_PULLUP`) |
| Button BACKWARD | 33 (to GND, `INPUT_PULLUP`) |
| Button LEFT | 25 (to GND, `INPUT_PULLUP`) |
| Button RIGHT | 26 (to GND, `INPUT_PULLUP`) |
| Status LED | 4 |
| USB | to host (Raspberry Pi / PC), 115200 baud |

### Vehicle ESP32
| Signal | GPIO |
|---|---|
| MPU6050 SDA / SCL | 21 / 22 (default I2C) |
| Motor L IN1 / IN2 | 25 / 26 |
| Motor R IN1 / IN2 | 27 / 14 |
| Status LED | 4 |

Motor pins assume a plain dual-H-bridge driver (L298N / L9110S style) with
`ENA`/`ENB` tied high — full speed only, digital direction control. No PWM
speed control yet since only 4 pins were specified; wire `ledcAttach` onto
the same pins later if variable speed is needed.

## ESP-NOW pairing

Both sketches print their own MAC on boot, pre-formatted to paste straight
into the other file:

```
This board's MAC (paste into vehicle_esp32.ino's controllerMac[]): {0x.., 0x.., 0x.., 0x.., 0x.., 0x..}
```

1. Flash the Controller, open Serial Monitor, copy its printed line into
   `vehicle_esp32.ino`'s `controllerMac[]`.
2. Flash the Vehicle, copy its printed line into `controller_esp32.ino`'s
   `vehicleMac[]`.
3. Re-flash both.

Neither board joins a real WiFi network, so both sit on the default ESP-NOW
channel automatically — no channel to configure or match.

## Wire protocol

**Host <-> Controller (USB serial, 115200, line-based):**
- Host -> Controller: `DROWSY\n` / `AWAKE\n`, `FWD\n` / `BACK\n` / `LEFT\n` / `RIGHT\n` / `STOP\n`
- Controller -> Host: `MPU,ax,ay,az,gx,gy,gz\n`, `LINK,OK\n` / `LINK,LOST\n`

A web drive command is only held for `WEB_CMD_TIMEOUT_MS` (500ms) before the
Controller auto-stops it — the dashboard re-sends the current direction
every 200ms while a key/button is held, so a dropped page or network stops
the vehicle instead of leaving it driving blind.

**Controller <-> Vehicle (ESP-NOW, raw structs):**
- Controller -> Vehicle: `ControlPacket { forward, backward, left, right, drowsy }`, sent at 10 Hz (also acts as the heartbeat the vehicle uses for link-loss detection).
- Vehicle -> Controller: `TelemetryPacket { ax, ay, az, gx, gy, gz }`, sent at 20 Hz.

The two structs are duplicated (not shared via a header) since keeping two
small structs in sync by hand across two sketches is simpler than adding a
shared library for a 2-node link — if you change one, change the other.

## Status LED (both boards, D4)

| State | Behavior |
|---|---|
| Link lost (no packet from the other board for 2s) | Blink, 1s period |
| Link OK | Solid on |

LED only reflects ESP-NOW link state — it doesn't indicate drowsy. Drowsy
still stops the vehicle's motors (see Safety behavior below), it just isn't
shown on either LED.

## Safety behavior

Motors stop whenever **either** condition holds, decided on the vehicle:
- ESP-NOW link from the Controller has been silent for 2+ seconds, or
- The last received `drowsy` flag is 1.

If the host's USB link to the Controller dies, the Controller keeps
whatever drowsy state it last had — if you want "host unreachable" to also
imply "stop the car", that's the host's job: have it send `DROWSY` if its
own serial write fails, or just note that a fully dead host means no one
is monitoring anyway.

## The rest of the system

Host-side dashboard (drowsiness detection, GPS/GSM, Tailscale hosting;
view/monitor only, no driving from it — `host/app.py`) and the separate
web-drive dashboard (`host/drive_dashboard.py`) live in
[`../host/`](../host/README.md). Top-level overview:
[`../readme.md`](../readme.md).
