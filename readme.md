# Drowsiness-Aware RC Vehicle System

Webcam drowsiness detection on a host (Raspberry Pi or PC) that acts as a
kill-switch for an ESP32-controlled RC vehicle, plus a live dashboard
(webcam feed, crash severity from an onboard MPU6050, GPS location, GSM
alert) reachable remotely over Tailscale.

## How it fits together

```
                    USB webcam
                        |
                        v
   [Host: Raspberry Pi or PC, 1GB RAM+]
   - drowsiness detection (OpenCV Haar cascades)
   - Flask dashboard (view/monitor only) ---- Tailscale ---> your phone/laptop
   - GPS (Pi GPIO UART) + GSM (USB) modules
        |  USB serial (DROWSY/AWAKE + MPU relay)
        v
   [Controller ESP32]  <---- ESP-NOW ---->  [Vehicle ESP32]
    4 buttons (F/B/L/R)                      MPU6050 (I2C)
    status LED (D4)                          2 motors (4 pins)
                                              status LED (D4)
```

- Driving is buttons-only, on the Controller ESP32 itself — no website
  control, no WiFi in the drive path at all. The Vehicle has no WiFi/network
  of its own; everything reaches it over ESP-NOW.
- The Vehicle enforces its own kill-switch: if the drowsy flag (relayed by
  the Controller from the host) is set, or the ESP-NOW link goes quiet, **it
  stops itself**, independent of what the buttons last said.
- Vehicle's MPU6050 doubles as a crash sensor: a big acceleration spike gets
  logged with severity + GPS location, and can trigger an SMS via the GSM
  module.

## Repo layout

| Path | What |
|---|---|
| `firmware/vehicle_esp32/` | Vehicle firmware (ESP-NOW only, motors, MPU6050, kill-switch, status LED) |
| `firmware/controller_esp32/` | Controller firmware (4 buttons, USB<->ESP-NOW bridge to host, status LED) |
| `firmware/README.md` | Wiring, ESP-NOW pairing, wire protocol |
| `host/` | Flask dashboard: webcam stream, drowsiness detection, GPS/GSM, crash log (view/monitor only, no driving) |
| `host/README.md` | Connection settings, GSM alert setup, Tailscale hosting |
| `Drowsiness_Detection.py` | Original standalone dlib-based script (webcam window, no hardware/website) — kept as reference; `host/drowsiness.py` is the dashboard version and uses OpenCV Haar cascades instead (dlib doesn't build cleanly on a 1GB Pi) |
| `models/` | dlib landmark model — only used by the original standalone script above, not by the dashboard |
| `install_windows.bat` / `install_linux.sh` | One-shot setup per platform |

## Hardware needed

- 2x ESP32 dev boards (one on the vehicle, one as the Controller)
- MPU6050 (on the vehicle)
- Dual motor driver (L298N/L9110-style) + 2 DC motors
- 4 push buttons (Controller)
- USB webcam (host)
- GPS module (NEO-6M or similar) — on the host, via the Pi's GPIO RX/TX
- GSM module (SIM800L or similar) — on the host, via USB
- Raspberry Pi (1GB RAM works) or a PC, as the host

## Setup

```
git clone <this-repo-url>
cd Drowsiness_Detection-master
```

**On the host (Raspberry Pi):**
```
sudo bash install_linux.sh
```
**On the host (Windows PC instead):**
```
install_windows.bat
```
Both scripts install dependencies, and the Linux one also sets up Tailscale,
frees the GPIO UART for GPS, and registers a systemd service so the
dashboard survives reboots. The Controller ESP32's USB port is
auto-detected — see [`host/README.md`](host/README.md) for what else to
edit (GSM alert number) and the Tailscale hosting steps.

**Flash the two ESP32s** (Arduino IDE, ESP32 board package installed). Each
prints its own MAC on boot, pre-formatted to paste into the other:
1. Flash the Controller, copy its printed MAC into `vehicle_esp32.ino`'s `controllerMac[]`.
2. Flash the Vehicle, copy its printed MAC into `controller_esp32.ino`'s `vehicleMac[]`.
3. Re-flash both.

Full pin-out and wire protocol: [`firmware/README.md`](firmware/README.md).

## Status / known limits

- Crash-severity thresholds (`host/crash.py`) are placeholders — calibrate
  against your actual vehicle.
- Dashboard's eye detection (Haar cascades) is cruder than a true EAR
  calculation — more prone to false positives than dlib's landmark
  approach, traded away because dlib won't build on a 1GB Pi.
- No auth on the dashboard — anyone on your tailnet can view it.
- Accident log is in-memory only (lost on restart).

## Credits

Eye-aspect-ratio drowsiness algorithm based on
[Akshay Bahadur's Drowsiness_Detection](https://github.com/akshaybahadur21/Drowsiness_Detection),
itself following [Adrian Rosebrock's PyImageSearch writeup](https://www.pyimagesearch.com/2017/05/08/drowsiness-detection-opencv/).
See `LICENSE.txt`.
