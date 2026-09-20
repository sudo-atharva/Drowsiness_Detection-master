"""NEO-6M style GPS module over the Pi's GPIO UART.

Hand-rolled $GPGGA parsing instead of a pynmea2 dependency — one sentence,
five fields, not worth a library.
"""
import threading
import time

import serial

GPS_SERIAL_PORT = "/dev/serial0"  # Pi GPIO UART (GPIO14/15)
GPS_BAUD = 9600


def _nmea_to_decimal(raw, hemisphere):
    if not raw:
        return None
    # ddmm.mmmm (lat) or dddmm.mmmm (lon)
    dot = raw.index(".")
    deg_len = dot - 2
    degrees = float(raw[:deg_len])
    minutes = float(raw[deg_len:])
    decimal = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return decimal


def _parse_gpgga(line):
    # $GPGGA,time,lat,N,lon,E,fix,sats,hdop,alt,M,...
    f = line.split(",")
    if len(f) < 10 or f[6] == "0":  # fix quality 0 = no fix
        return None
    return {
        "lat": _nmea_to_decimal(f[2], f[3]),
        "lon": _nmea_to_decimal(f[4], f[5]),
        "satellites": int(f[7]) if f[7] else 0,
        "altitude_m": float(f[9]) if f[9] else None,
    }


class GPSReader:
    def __init__(self, port=GPS_SERIAL_PORT, baud=GPS_BAUD):
        self._lock = threading.Lock()
        self.latest = None
        self._ser = serial.Serial(port, baud, timeout=1)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            try:
                line = self._ser.readline().decode("ascii", errors="ignore").strip()
            except serial.SerialException:
                time.sleep(1)
                continue
            if not line.startswith("$GPGGA"):
                continue
            fix = _parse_gpgga(line)
            if fix:
                with self._lock:
                    self.latest = fix

    def snapshot(self):
        with self._lock:
            return self.latest


if __name__ == "__main__":
    assert _nmea_to_decimal("4807.038", "N") == 48 + 7.038 / 60.0
    assert _nmea_to_decimal("01131.000", "E") == 11 + 31.0 / 60.0
    fix = _parse_gpgga("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
    assert fix["satellites"] == 8 and round(fix["lat"], 4) == 48.1173
    print("gps_reader self-check OK")
