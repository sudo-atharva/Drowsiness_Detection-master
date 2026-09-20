"""Accident severity from MPU6050 accel magnitude. Thresholds are placeholders
— calibrate against your actual vehicle/mounting before trusting them.
"""
import math
import time

MINOR_G = 3.0
MODERATE_G = 6.0
SEVERE_G = 10.0
ALERT_COOLDOWN_S = 60  # don't re-text on every frame of the same crash


def severity(ax, ay, az):
    magnitude = math.sqrt(ax * ax + ay * ay + az * az)
    if magnitude >= SEVERE_G:
        return "severe", magnitude
    if magnitude >= MODERATE_G:
        return "moderate", magnitude
    if magnitude >= MINOR_G:
        return "minor", magnitude
    return None, magnitude


class CrashMonitor:
    def __init__(self, on_crash):
        """on_crash(severity: str, magnitude: float) called at most once per cooldown window."""
        self.on_crash = on_crash
        self.log = []  # most recent first: {time, severity, magnitude, lat, lon}
        self._last_alert = 0.0

    def check(self, mpu, gps_fix):
        if not mpu:
            return
        level, magnitude = severity(mpu["ax"], mpu["ay"], mpu["az"])
        if level is None:
            return
        now = time.time()
        if now - self._last_alert < ALERT_COOLDOWN_S:
            return
        self._last_alert = now
        entry = {
            "time": now,
            "severity": level,
            "magnitude": round(magnitude, 2),
            "lat": gps_fix["lat"] if gps_fix else None,
            "lon": gps_fix["lon"] if gps_fix else None,
        }
        self.log.insert(0, entry)
        self.log = self.log[:20]
        self.on_crash(level, magnitude, entry)


if __name__ == "__main__":
    calls = []
    m = CrashMonitor(on_crash=lambda lvl, mag, e: calls.append((lvl, mag)))
    m.check({"ax": 0, "ay": 0, "az": 1}, None)   # resting 1g, no alert
    assert calls == []
    m.check({"ax": 7, "ay": 0, "az": 0}, {"lat": 1.0, "lon": 2.0})
    assert calls and calls[0][0] == "moderate"
    m.check({"ax": 7, "ay": 0, "az": 0}, None)  # within cooldown, suppressed
    assert len(calls) == 1
    print("crash self-check OK")
