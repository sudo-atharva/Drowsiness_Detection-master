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
   - Flask dashboard --------------------- Tailscale ---> your phone/laptop
   - GPS (GPIO UART) + GSM (serial) modules
        |  USB serial (buttons + DROWSY/AWAKE + MPU relay)
        v
   [Controller ESP32]  <-----  ESP-NOW  ----->  [Vehicle ESP32]
    4 buttons (F/B/L/R)                          MPU6050 (I2C)
                                                  2 motors (4 pins)
                                                  status LED (D4)
```

- Driver gets drowsy -> host tells the Controller ESP32 -> it tells the
  Vehicle ESP32 over ESP-NOW -> **vehicle stops itself**, independent of
  whatever the controller's buttons say. The vehicle is the one that
  enforces the stop, not the controller.
- Vehicle's MPU6050 doubles as a crash sensor: a big acceleration spike gets
  logged with severity + GPS location, and can trigger an SMS via the GSM
  module.

## Repo layout

| Path | What |
|---|---|
| `firmware/controller_esp32/` | Handheld RC unit firmware (buttons, USB link to host, ESP-NOW) |
| `firmware/vehicle_esp32/` | Vehicle firmware (motors, MPU6050, kill-switch, status LED) |
| `firmware/README.md` | Wiring, MAC pairing, wire protocol |
| `host/` | Flask dashboard: webcam stream, drowsiness detection, GPS/GSM, crash log |
| `host/README.md` | Serial port config, GSM alert setup, Tailscale hosting |
| `Drowsiness_Detection.py` | Original standalone dlib-based script (webcam window, no hardware/website) — kept as reference; `host/drowsiness.py` is the dashboard version and uses OpenCV Haar cascades instead (dlib doesn't build cleanly on a 1GB Pi) |
| `models/` | dlib landmark model — only used by the original standalone script above, not by the dashboard |
| `install_windows.bat` / `install_linux.sh` | One-shot setup per platform |

## Hardware needed

- 2x ESP32 dev boards
- MPU6050 (on the vehicle)
- Dual motor driver (L298N/L9110-style) + 2 DC motors
- 4 push buttons (controller)
- USB webcam (host)
- GPS module (NEO-6M or similar, UART) — on the host
- GSM module (SIM800L or similar, UART) — on the host
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
dashboard survives reboots. See [`host/README.md`](host/README.md) for what
to edit afterward (serial ports, GSM alert number) and the Tailscale
hosting steps.

**Flash the two ESP32s** (Arduino IDE, ESP32 board package installed):
1. Flash each board once, read its MAC from Serial Monitor.
2. Put the Vehicle's MAC into `controller_esp32.ino`, and the Controller's
   MAC into `vehicle_esp32.ino`.
3. Re-flash both.

Full pin-out and protocol details: [`firmware/README.md`](firmware/README.md).

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
