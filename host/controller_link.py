"""USB-serial link to the Controller ESP32.

Sends DROWSY/AWAKE and website drive commands, parses the MPU + LINK lines
the Controller relays back from the Vehicle ESP32 over ESP-NOW.
See firmware/README.md for the wire protocol.
"""
import threading
import time

import serial

CONTROLLER_SERIAL_PORT = "/dev/ttyUSB0"  # Windows: e.g. "COM3"
CONTROLLER_BAUD = 115200


class ControllerLink:
    def __init__(self, port=CONTROLLER_SERIAL_PORT, baud=CONTROLLER_BAUD):
        self._lock = threading.Lock()
        self.latest_mpu = None      # dict: ax, ay, az, gx, gy, gz
        self.link_ok = False
        self._drowsy = False
        try:
            self._ser = serial.Serial(port, baud, timeout=1)
        except serial.SerialException:
            print(f"Controller: no serial port at {port}, drive/telemetry disabled")
            self._ser = None
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_drowsy(self, drowsy: bool):
        if drowsy == self._drowsy:
            return
        self._drowsy = drowsy
        if self._ser:
            self._ser.write(b"DROWSY\n" if drowsy else b"AWAKE\n")

    def send_control(self, direction: str):
        if self._ser:
            self._ser.write(f"DIR,{direction}\n".encode())

    def _run(self):
        while True:
            try:
                line = self._ser.readline().decode("ascii", errors="ignore").strip()
            except serial.SerialException:
                time.sleep(1)
                continue
            if not line:
                continue
            if line.startswith("MPU,"):
                parts = line.split(",")
                if len(parts) == 7:
                    ax, ay, az, gx, gy, gz = (float(p) for p in parts[1:])
                    with self._lock:
                        self.latest_mpu = {
                            "ax": ax, "ay": ay, "az": az,
                            "gx": gx, "gy": gy, "gz": gz,
                        }
            elif line == "LINK,OK":
                with self._lock:
                    self.link_ok = True
            elif line == "LINK,LOST":
                with self._lock:
                    self.link_ok = False

    def snapshot(self):
        with self._lock:
            return dict(latest_mpu=self.latest_mpu, link_ok=self.link_ok)


if __name__ == "__main__":
    link = ControllerLink()
    print("Listening for MPU/LINK lines, Ctrl+C to stop")
    while True:
        time.sleep(1)
        print(link.snapshot())
