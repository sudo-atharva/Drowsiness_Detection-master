"""Webcam capture + EAR-based drowsiness detection, refactored from the
original Drowsiness_Detection.py into a background thread so the Flask app
can stream frames to many browser tabs off one shared capture loop.
"""
import os
import threading
import time

import cv2
import dlib
import imutils
from imutils import face_utils
from scipy.spatial import distance

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models",
                           "shape_predictor_68_face_landmarks.dat")
EAR_THRESH = 0.25
FRAME_CHECK = 20


def eye_aspect_ratio(eye):
    a = distance.euclidean(eye[1], eye[5])
    b = distance.euclidean(eye[2], eye[4])
    c = distance.euclidean(eye[0], eye[3])
    return (a + b) / (2.0 * c)


class DrowsinessDetector:
    def __init__(self, camera_index=0, on_state_change=None):
        """on_state_change(drowsy: bool) called only when the state flips."""
        self.on_state_change = on_state_change
        self._lock = threading.Lock()
        self._frame_jpeg = None
        self.drowsy = False

        self._detect = dlib.get_frontal_face_detector()
        self._predict = dlib.shape_predictor(MODEL_PATH)
        (self._lstart, self._lend) = face_utils.FACIAL_LANDMARKS_68_IDXS["left_eye"]
        (self._rstart, self._rend) = face_utils.FACIAL_LANDMARKS_68_IDXS["right_eye"]

        self._cap = cv2.VideoCapture(camera_index)
        self._flag = 0
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
            frame = imutils.resize(frame, width=450)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            for subject in self._detect(gray, 0):
                shape = face_utils.shape_to_np(self._predict(gray, subject))
                left_eye = shape[self._lstart:self._lend]
                right_eye = shape[self._rstart:self._rend]
                ear = (eye_aspect_ratio(left_eye) + eye_aspect_ratio(right_eye)) / 2.0
                cv2.drawContours(frame, [cv2.convexHull(left_eye)], -1, (0, 255, 0), 1)
                cv2.drawContours(frame, [cv2.convexHull(right_eye)], -1, (0, 255, 0), 1)

                if ear < EAR_THRESH:
                    self._flag += 1
                    if self._flag >= FRAME_CHECK:
                        self._set_drowsy(True)
                        cv2.putText(frame, "ALERT! DROWSY", (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                else:
                    self._flag = 0
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
