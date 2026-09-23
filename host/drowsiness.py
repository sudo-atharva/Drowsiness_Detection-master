"""Webcam capture + drowsiness detection, background thread so the Flask app
can stream frames to many browser tabs off one shared capture loop.

Uses OpenCV's built-in Haar cascades instead of dlib's 68-point landmark
model: dlib has no prebuilt ARM wheel and its source build routinely takes
hours (or OOMs) on a 1GB Pi. Cascades ship inside opencv itself — no compile,
no extra dependency. Trade-off: cruder signal (eyes detected / not detected,
vs a continuous eye-aspect-ratio), since a face+no-eyes hit is inherently
noisier than distance-based EAR. Revisit if false-positive rate is an issue
(e.g. mediapipe, once it has wheels for the Pi's Python version).
"""
import os
import sys
import threading
import time

import cv2

EYES_CLOSED_FRAME_CHECK = 20  # consecutive no-eyes-in-face frames -> drowsy


def _cascade_path(filename):
    candidates = [
        os.path.join(getattr(cv2.data, "haarcascades", ""), filename) if hasattr(cv2, "data") else None,
        f"/usr/share/opencv4/haarcascades/{filename}",
        f"/usr/share/opencv/haarcascades/{filename}",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(f"Could not find {filename} — checked {candidates}")


class DrowsinessDetector:
    def __init__(self, camera_index=0, on_state_change=None):
        """on_state_change(drowsy: bool) called only when the state flips."""
        self.on_state_change = on_state_change
        self._lock = threading.Lock()
        self._frame_jpeg = None
        self.drowsy = False

        self._face_cascade = cv2.CascadeClassifier(_cascade_path("haarcascade_frontalface_default.xml"))
        self._eye_cascade = cv2.CascadeClassifier(_cascade_path("haarcascade_eye.xml"))

        # MSMF (default backend) hands back blank frames on some Windows webcams; DSHOW doesn't.
        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(camera_index, backend)
        self._closed_frames = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _set_drowsy(self, value):
        if value == self.drowsy:
            return
        self.drowsy = value
        if self.on_state_change:
            self.on_state_change(value)

    def _run(self):
        while True:
            ok, frame = self._cap.read()
            if not ok:
                continue
            frame = cv2.resize(frame, (450, int(frame.shape[0] * 450 / frame.shape[1])))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            faces = self._face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
            if len(faces) == 0:
                continue  # can't judge eyes without a face; leave state as-is

            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (0, 255, 0), 1)
            face_roi = gray[fy:fy + fh // 2, fx:fx + fw]  # eyes live in the top half of the face

            eyes = self._eye_cascade.detectMultiScale(face_roi, scaleFactor=1.1, minNeighbors=5)
            for (ex, ey, ew, eh) in eyes:
                cv2.rectangle(frame, (fx + ex, fy + ey), (fx + ex + ew, fy + ey + eh), (255, 0, 0), 1)

            if len(eyes) == 0:
                self._closed_frames += 1
                if self._closed_frames >= EYES_CLOSED_FRAME_CHECK:
                    self._set_drowsy(True)
                    cv2.putText(frame, "ALERT! DROWSY", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            else:
                self._closed_frames = 0
                self._set_drowsy(False)

            ok, jpeg = cv2.imencode(".jpg", frame)
            if ok:
                with self._lock:
                    self._frame_jpeg = jpeg.tobytes()

    def mjpeg_generator(self):
        # ponytail: fixed 15fps cap via sleep, not a proper "wait for new frame"
        # condition var — good enough for a dashboard, revisit if CPU on the Pi is tight.
        while True:
            with self._lock:
                frame = self._frame_jpeg
            if frame is not None:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(1 / 15)
