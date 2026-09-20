"""SIM800L-style GSM module: signal check + SMS alert on accident.

Assumption (flag if wrong): GSM's job here is to text an emergency contact
with location + severity when a crash is detected — not general data/SMS
inbox handling. Swap ALERT_PHONE_NUMBER for the real contact before use.
"""
import threading
import time

import serial

GSM_SERIAL_PORT = "/dev/ttyUSB1"  # separate USB-serial adapter; Pi's one hardware
                                    # UART is already used by the GPS module
GSM_BAUD = 9600
ALERT_PHONE_NUMBER = "+10000000000"


class GsmModule:
    def __init__(self, port=GSM_SERIAL_PORT, baud=GSM_BAUD):
        self._ser = serial.Serial(port, baud, timeout=2)
        self._lock = threading.Lock()
        self._signal_cache = None
        self._signal_cached_at = 0.0

    def _at(self, cmd, wait=0.5):
        with self._lock:
            self._ser.write((cmd + "\r").encode())
            time.sleep(wait)
            return self._ser.read(self._ser.in_waiting or 1).decode(errors="ignore")

    def signal_quality(self, max_age_s=5):
        """Returns 0-31 (higher = better) or None if module didn't answer.
        Cached briefly — this gets polled once per dashboard refresh."""
        now = time.time()
        if self._signal_cache is not None and now - self._signal_cached_at < max_age_s:
            return self._signal_cache
        resp = self._at("AT+CSQ")
        value = None
        for tok in resp.split():
            if tok.isdigit():
                value = int(tok)
                break
        self._signal_cache = value
        self._signal_cached_at = now
        return value

    def send_sms(self, text, number=ALERT_PHONE_NUMBER):
        self._at("AT+CMGF=1")  # text mode
        self._at(f'AT+CMGS="{number}"')
        with self._lock:
            self._ser.write(text.encode() + b"\x1a")  # Ctrl-Z sends
            time.sleep(3)

    def send_sms_async(self, text, number=ALERT_PHONE_NUMBER):
        threading.Thread(target=self.send_sms, args=(text, number), daemon=True).start()


if __name__ == "__main__":
    gsm = GsmModule()
    print("signal:", gsm.signal_quality())
