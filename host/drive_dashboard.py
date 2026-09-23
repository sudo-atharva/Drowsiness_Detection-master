"""Standalone web dashboard for driving the car — separate from app.py
(the drowsiness/monitoring dashboard, which stays view-only by design).

Run this INSTEAD of app.py when you want to drive from the browser. Uses
the same ControllerLink/USB-serial link; the Controller's physical buttons
still override a web command if pressed. See firmware/README.md.
"""
from flask import Flask, jsonify, render_template

from controller_link import ControllerLink

app = Flask(__name__)
vehicle = ControllerLink()


@app.route("/")
def index():
    return render_template("drive.html")


@app.route("/api/drive/<direction>", methods=["POST"])
def api_drive(direction):
    try:
        vehicle.drive(direction)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/status")
def api_status():
    link = vehicle.snapshot()
    return jsonify(vehicle_link_ok=link["link_ok"], mpu=link["latest_mpu"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, threaded=True)
