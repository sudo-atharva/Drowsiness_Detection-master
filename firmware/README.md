# Drowsy-Aware RC Vehicle — ESP32 Firmware

Two ESP32 boards, linked over ESP-NOW, plus a host (Raspberry Pi or PC) doing
webcam-based drowsiness detection.

```
[Host: webcam + drowsiness detection + website over VPN]
        |  USB serial (115200 baud)
        v
[Controller ESP32]  <---- ESP-NOW ---->  [Vehicle ESP32]
 4 buttons                                MPU6050 (I2C)
 (F/B/L/R)                                2 motors (4 direction pins)
                                           status LED (D4)
```

- **Controller ESP32** sits at the host end, wired to the host over USB.
  It reads the 4 buttons, forwards the host's drowsy/awake state to the
  vehicle, and relays MPU6050 telemetry (received from the vehicle) back to
  the host over the same USB serial line.
- **Vehicle ESP32** sits on the car. It owns the MPU6050, drives the 2
  motors, and is the one that actually enforces the kill-switch: if the
  drowsy flag is set, or the ESP-NOW link drops, motors are force-stopped —
  the vehicle doesn't trust the controller to behave.

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

Both sketches currently have a **placeholder MAC address** for the other
board (`vehicleMac` / `controllerMac`). Fix before flashing:

1. Flash either sketch once, open Serial Monitor, add a line printing
   `WiFi.macAddress()` in `setup()` (or use a throwaway sketch) to read each
   board's MAC.
2. Paste the Vehicle's MAC into `controller_esp32.ino`'s `vehicleMac[]`.
3. Paste the Controller's MAC into `vehicle_esp32.ino`'s `controllerMac[]`.
4. Re-flash both.

Both boards must be on the same Wi-Fi channel (default channel 0 = current
channel; fine as long as neither board also joins a Wi-Fi network on a
different channel).

## Wire protocol

**Host <-> Controller (USB serial, 115200, line-based):**
- Host -> Controller: `DROWSY\n` / `AWAKE\n`
- Controller -> Host: `MPU,ax,ay,az,gx,gy,gz\n`, `LINK,OK\n` / `LINK,LOST\n`

**Controller <-> Vehicle (ESP-NOW, raw structs):**
- Controller -> Vehicle: `ControlPacket { forward, backward, left, right, drowsy }`, sent at 10 Hz (also acts as the heartbeat the vehicle uses for link-loss detection).
- Vehicle -> Controller: `TelemetryPacket { ax, ay, az, gx, gy, gz }`, sent at 20 Hz.

The two structs are duplicated (not shared via a header) since keeping two
small structs in sync by hand across two sketches is simpler than adding a
shared library for a 2-node link — if you change one, change the other.

## Status LED (Vehicle, D4)

| State | Behavior |
|---|---|
| Link lost (no packet from controller for 2s) | Blink, 1s period |
| Link OK, drowsy | Blink, 3s period |
| Link OK, awake | Solid on |

## Safety behavior

Motors stop whenever **either** condition holds, decided on the vehicle:
- ESP-NOW link has been silent for 2+ seconds, or
- The last received `drowsy` flag is 1.

The controller does not need to be trusted or even functioning correctly for
the vehicle to fail safe.

## Not built yet (open items for the rest of the system)

This delivers only the two ESP32 firmwares. Still open, per the wider system
description:
- Host-side script that runs the drowsiness detection (existing
  `Drowsiness_Detection.py` uses `dlib` + full-frame processing — likely too
  heavy for a 1 GB RAM Raspberry Pi; will need a lighter model/pipeline) and
  writes `DROWSY`/`AWAKE` to the Controller's serial port, and parses the
  `MPU,...` / `LINK,...` lines coming back.
- The website itself (live webcam view + alert state), served from the host
  and reached remotely over a VPN (Tailscale).
- GPS + GSM module integration on the Raspberry Pi's GPIO/UART.
- Deciding exactly how "host" maps to hardware: is the Raspberry Pi the one
  running the webcam + website + Controller USB link, with a separate PC
  just as an alternate host, or do both run simultaneously?

Ask before building these so pin/protocol choices match your actual GPIO
budget on the Pi (GPS+GSM will also want UART/GPIO pins, so worth mapping
all of it out together rather than piecemeal).
