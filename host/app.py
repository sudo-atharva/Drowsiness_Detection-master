"""Dashboard: live webcam + drowsiness alert, MPU6050 crash severity, GPS
location, GSM alert status. Host this on the Raspberry Pi, reach it over
Tailscale the same way OctoPrint is reached — no port forwarding, just
`tailscale up` on the Pi and browse to http://<pi-tailscale-ip>:5000.
"""
from flask import Flask, Response, jsonify, render_template

from controller_link import ControllerLink
from crash import CrashMonitor
from drowsiness import DrowsinessDetector
from gps_reader import GPSReader
from gsm_alert import GsmModule

app = Flask(__name__)

controller = ControllerLink()
gps = GPSReader()
gsm = GsmModule()


def on_crash(level, magnitude, entry):
    lat, lon = entry["lat"], entry["lon"]
    where = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}" if lat else "location unknown"
    gsm.send_sms_async(f"Accident detected ({level}, {magnitude:.1f}g). {where}")


crash_monitor = CrashMonitor(on_crash=on_crash)


def on_drowsy_change(is_drowsy):
    controller.set_drowsy(is_drowsy)


detector = DrowsinessDetector(on_state_change=on_drowsy_change)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(detector.mjpeg_generator(),
                     mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/status")
def api_status():
    link = controller.snapshot()
    gps_fix = gps.snapshot()
    crash_monitor.check(link["latest_mpu"], gps_fix)
    return jsonify(
        drowsy=detector.drowsy,
        mpu=link["latest_mpu"],
        vehicle_link_ok=link["link_ok"],
        gps=gps_fix,
        gsm_signal=gsm.signal_quality(),
        accident_log=crash_monitor.log,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
