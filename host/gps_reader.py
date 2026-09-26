"""NEO-6M style GPS module over the Pi's GPIO UART, with WiFi geolocation
fallback when GPS has no fix (indoors, cold start, module missing).

Hand-rolled GGA parsing instead of a pynmea2 dependency — one sentence,
five fields, not worth a library.

WiFi fallback: scans nearby access points with `nmcli` (NetworkManager,
default on Raspberry Pi OS Bookworm) and asks beaconDB — free, no API key,
Mozilla Location Service compatible — where they are. Needs internet;
accuracy is tens to hundreds of metres, not GPS-grade.
"""
import json
import subprocess
import threading
import time
import urllib.request

import serial

GPS_SERIAL_PORT = "/dev/serial0"  # Pi GPIO UART0 (GPIO14 TX / GPIO15 RX)
GPS_BAUD = 9600
GPS_STALE_S = 10       # GPS fix older than this counts as lost
WIFI_LOCATE_EVERY_S = 60
WIFI_GEOLOCATE_URL = "https://api.beacondb.net/v1/geolocate"


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


def _parse_gga(line):
    # $GPGGA / $GNGGA,time,lat,N,lon,E,fix,sats,hdop,alt,M,...
    f = line.split(",")
    if len(f) < 10 or f[6] in ("", "0") or not f[2]:  # fix quality 0 = no fix
        return None
    return {
        "lat": _nmea_to_decimal(f[2], f[3]),
        "lon": _nmea_to_decimal(f[4], f[5]),
        "satellites": int(f[7]) if f[7] else 0,
        "altitude_m": float(f[9]) if f[9] else None,
        "source": "gps",
    }


def _parse_nmcli(output):
    # `nmcli -t -f BSSID,SIGNAL` lines look like: AA\:BB\:CC\:DD\:EE\:FF:72
    aps = []
    for line in output.splitlines():
        bssid, _, signal = line.replace("\\:", "-").rpartition(":")
        if bssid and signal.isdigit():
            # nmcli gives 0-100 %, geolocate wants dBm; rough linear map
            aps.append({"macAddress": bssid.replace("-", ":").lower(),
                        "signalStrength": int(signal) // 2 - 100})
    return aps


def wifi_locate():
    """Returns {lat, lon, accuracy_m, source} or None."""
    try:
        scan = subprocess.run(["nmcli", "-t", "-f", "BSSID,SIGNAL", "dev", "wifi", "list"],
                              capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    aps = _parse_nmcli(scan)
    if len(aps) < 2:  # geolocation services refuse single-AP lookups
        return None
    req = urllib.request.Request(
        WIFI_GEOLOCATE_URL,
        data=json.dumps({"considerIp": False, "wifiAccessPoints": aps}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "drowsiness-dashboard"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.load(resp)
    except (OSError, ValueError):
        return None
    return {
        "lat": body["location"]["lat"],
        "lon": body["location"]["lng"],
        "accuracy_m": body.get("accuracy"),
        "satellites": 0,
        "source": "wifi",
    }


class GPSReader:
    def __init__(self, port=GPS_SERIAL_PORT, baud=GPS_BAUD):
        self._lock = threading.Lock()
        self._gps = None
        self._gps_at = 0.0
        self._wifi = None
        threading.Thread(target=self._wifi_run, daemon=True).start()
        try:
            self._ser = serial.Serial(port, baud, timeout=1)
        except serial.SerialException:
            print(f"GPS: no serial port at {port}, using WiFi location only")
            self._ser = None
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _gps_fresh(self):
        return self._gps is not None and time.time() - self._gps_at < GPS_STALE_S

    def _run(self):
        while True:
            try:
                line = self._ser.readline().decode("ascii", errors="ignore").strip()
            except serial.SerialException:
                time.sleep(1)
                continue
            if line[3:6] != "GGA":  # $GPGGA (GPS-only) or $GNGGA (multi-GNSS modules)
                continue
            fix = _parse_gga(line)
            if fix:
                with self._lock:
                    self._gps = fix
                    self._gps_at = time.time()

    def _wifi_run(self):
        while True:
            if not self._gps_fresh():
                loc = wifi_locate()
                if loc:
                    with self._lock:
                        self._wifi = loc
            time.sleep(WIFI_LOCATE_EVERY_S)

    def snapshot(self):
        with self._lock:
            return self._gps if self._gps_fresh() else self._wifi


if __name__ == "__main__":
    assert _nmea_to_decimal("4807.038", "N") == 48 + 7.038 / 60.0
    assert _nmea_to_decimal("01131.000", "E") == 11 + 31.0 / 60.0
    fix = _parse_gga("$GNGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
    assert fix["satellites"] == 8 and round(fix["lat"], 4) == 48.1173
    assert _parse_gga("$GPGGA,123519,,,,,0,00,,,M,,M,,") is None
    aps = _parse_nmcli("AA\\:BB\\:CC\\:DD\\:EE\\:FF:72\n11\\:22\\:33\\:44\\:55\\:66:40\n")
    assert aps == [{"macAddress": "aa:bb:cc:dd:ee:ff", "signalStrength": -64},
                   {"macAddress": "11:22:33:44:55:66", "signalStrength": -80}]
    print("gps_reader self-check OK")
