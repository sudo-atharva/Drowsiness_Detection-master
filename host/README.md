# Host dashboard (Raspberry Pi / PC)

Two separate Flask apps, run one at a time (both want the Controller's one
USB-serial port):

- `app.py` — live webcam feed + drowsiness alert, MPU6050 crash severity,
  GPS location, GSM alert status. View/monitor only, no driving from it.
- `drive_dashboard.py` — drives the car from the browser (arrow keys or
  on-screen buttons), sending FWD/BACK/LEFT/RIGHT/STOP over the same link.
  Physical buttons on the Controller ESP32 itself always override it.

Both talk to the Controller ESP32 over USB serial — the Controller relays
everything onward to the Vehicle ESP32 over ESP-NOW, so this host code never
talks to the vehicle directly (see
[`../firmware/README.md`](../firmware/README.md)).

## Files

- `app.py` — Flask routes for the monitoring dashboard
- `drive_dashboard.py` — Flask routes for the drive dashboard
- `drowsiness.py` — webcam capture + Haar-cascade eye detection, background thread
- `controller_link.py` — USB serial to the Controller ESP32 (auto-detects the port): sends drowsy state and drive commands, parses MPU + LINK lines it relays back
- `gps_reader.py` — NEO-6M GPS over Pi GPIO UART, parses `$GPGGA`
- `gsm_alert.py` — SIM800L-style GSM: signal check + SMS alert on crash
- `crash.py` — accel-magnitude crash severity + alert cooldown
- `templates/index.html` — monitoring dashboard page (vanilla JS polling, no build step)
- `templates/drive.html` — drive dashboard page (arrow keys / on-screen buttons)

## Run

Monitoring dashboard:
```
pip install -r requirements.txt
python app.py
```
Open `http://<host>:5000/`.

Drive dashboard (instead of, not alongside, `app.py`):
```
python drive_dashboard.py
```
Open `http://<host>:5001/`.

## Connection settings

| Module | File | Default | Notes |
|---|---|---|---|
| Controller ESP32 | `controller_link.py` | auto-detect | Scans USB devices for a CP210x/CH340/FTDI chip (what ESP32 boards use). Set `CONTROLLER_SERIAL_PORT` to force a specific port if auto-detect picks wrong or you have multiple such devices plugged in. |
| GPS | `gps_reader.py` | `/dev/serial0` | Pi's hardware GPIO UART (GPIO14/15, RX/TX) |
| GSM | `gsm_alert.py` | `/dev/ttyUSB1` | Plain USB (its own USB-serial adapter, or a module with native USB) — doesn't touch the Pi's GPIO at all, so it never competes with GPS for the one GPIO UART |

## GSM alert assumption

Built as: GSM module sends an SMS to `ALERT_PHONE_NUMBER` (in `gsm_alert.py`)
with the OpenStreetMap link + severity when a crash is detected. If you
actually wanted something else from the GSM module (cellular data uplink,
inbound SMS commands, etc.), say so — this part was the most ambiguous item
in the request and easiest to have built wrong.

## Crash severity thresholds

`crash.py` classifies total accel magnitude: 3g minor / 6g moderate / 10g
severe, with a 60s cooldown between alerts. These are placeholders — real
vehicle mounting, sensor noise, and expected impact forces should drive the
real numbers. Calibrate by logging real MPU6050 output during test bumps and
adjusting `MINOR_G`/`MODERATE_G`/`SEVERE_G`.

## 1GB RAM Pi — what to watch

- Drowsiness detection uses OpenCV's Haar cascades (`haarcascade_frontalface_default.xml`
  + `haarcascade_eye.xml`), not dlib's 68-point landmark model. dlib has no
  prebuilt ARM wheel and its source build routinely takes hours (or OOMs) on
  a 1GB board — not worth it here. Cascades ship inside `python3-opencv`
  itself, so this needs no extra install. Trade-off: eyes-detected-or-not is
  a cruder signal than a continuous eye-aspect-ratio, so it's more prone to
  false positives (e.g. looking down, glasses). Revisit with MediaPipe Face
  Mesh if that ever ships a wheel for the Pi's Python version, or accept the
  cascade approach and tune `EYES_CLOSED_FRAME_CHECK` in `drowsiness.py`.
- Video is capped at 15 FPS in `drowsiness.mjpeg_generator` — raise it only
  if the Pi has headroom.

## Hosting over Tailscale (like OctoPrint)

No port forwarding, no public exposure — same pattern OctoPrint uses:

1. Install Tailscale on the Pi: `curl -fsSL https://tailscale.com/install.sh | sh` then `sudo tailscale up`.
2. Install Tailscale on whatever device you're viewing from, log into the same tailnet.
3. Find the Pi's Tailscale IP: `tailscale ip -4`.
4. Run `python app.py` on the Pi (binds `0.0.0.0:5000` already).
5. Browse to `http://<pi-tailscale-ip>:5000` from any device on the tailnet.

If you want a real HTTPS URL instead of an IP:port, `tailscale serve https / http://localhost:5000` proxies it with a Tailscale-issued cert, still private to your tailnet (or `tailscale funnel` if you actually want it public — not recommended for a dashboard with an SMS-sending GSM module attached).

## Not built yet

- Auth on the dashboard — anyone on your tailnet can currently see the feed and trigger nothing, but there's also no login. Add one if the tailnet isn't trusted enough on its own.
- Persisting the accident log to disk (currently in-memory, last 20 events, lost on restart).
