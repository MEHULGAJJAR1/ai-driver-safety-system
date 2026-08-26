"""
camera.py
=========
Camera processing for local webcam and browser/mobile camera.

LOCAL:
    Uses OpenCV VideoCapture(0).

PRODUCTION:
    Does NOT try to access a server webcam.
    Browser/mobile sends JPEG frames to Flask.
    Frames are processed by the existing DrowsinessPipeline.
"""

import time
import threading
import base64

import cv2
import numpy as np


class CameraStream:
    def __init__(self, config):
        self.config = config

        self.cap = None
        self.pipeline = None
        self.thread = None

        self.running = False
        self.browser_mode = False

        self.lock = threading.Lock()

        self._jpeg = None

        self.latest_state = {
            "found": False,
            "status_text": "Idle"
        }

        self._cnn_active = False

    # ------------------------------------------------------------------ #
    @property
    def cnn_active(self):
        if self.pipeline is None:
            self._ensure_pipeline()

        return self._cnn_active

    # ------------------------------------------------------------------ #
    def _ensure_pipeline(self):
        if self.pipeline is not None:
            return

        try:
            from detection import DrowsinessPipeline

            self.pipeline = DrowsinessPipeline(self.config)
            self._cnn_active = self.pipeline.cnn_active

        except Exception as exc:
            print(f"[CameraStream] Pipeline init failed: {exc}")

            self.pipeline = None
            self._cnn_active = False

    # ------------------------------------------------------------------ #
    # LOCAL WEBCAM MODE
    # ------------------------------------------------------------------ #
    def start(self):
        """
        Start local physical webcam.

        Used only during local development.
        """

        if self.running:
            return True

        self._ensure_pipeline()

        if self.pipeline is None:
            return False

        self.pipeline.reset()

        self.latest_state = {
            "found": False,
            "status_text": "Starting..."
        }

        self.cap = cv2.VideoCapture(
            self.config.CAMERA_INDEX
        )

        self.cap.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            self.config.FRAME_WIDTH
        )

        self.cap.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            self.config.FRAME_HEIGHT
        )

        if not self.cap.isOpened():

            print(
                "[CameraStream] Could not open local camera "
                f"(index {self.config.CAMERA_INDEX})"
            )

            self.cap.release()
            self.cap = None

            return False

        self.browser_mode = False
        self.running = True

        self.thread = threading.Thread(
            target=self._loop,
            daemon=True
        )

        self.thread.start()

        return True

    # ------------------------------------------------------------------ #
    # BROWSER / MOBILE MODE
    # ------------------------------------------------------------------ #
    def start_browser(self):
        """
        Start a browser/mobile camera session.

        IMPORTANT:
        This does NOT access a physical camera on the server.
        """

        self._ensure_pipeline()

        if self.pipeline is None:
            return False

        self.pipeline.reset()

        with self.lock:
            self.browser_mode = True
            self.running = True
            self._jpeg = None

            self.latest_state = {
                "found": False,
                "status_text": "Waiting for camera..."
            }

        return True

    # ------------------------------------------------------------------ #
    def process_browser_frame(self, image_data):
        """
        Process one JPEG frame sent from the browser/mobile device.

        Accepts:
            data:image/jpeg;base64,...
        or:
            raw base64 JPEG
        """

        if not image_data:
            return {
                "ok": False,
                "error": "Empty camera frame"
            }

        self._ensure_pipeline()

        if self.pipeline is None:
            return {
                "ok": False,
                "error": "AI pipeline unavailable"
            }

        try:

            # Remove data URL prefix.
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]

            raw = base64.b64decode(
                image_data,
                validate=True
            )

            max_bytes = (
                self.config.MAX_CAMERA_FRAME_KB * 1024
            )

            if len(raw) > max_bytes:
                return {
                    "ok": False,
                    "error": "Camera frame too large"
                }

            array = np.frombuffer(
                raw,
                dtype=np.uint8
            )

            frame = cv2.imdecode(
                array,
                cv2.IMREAD_COLOR
            )

            if frame is None:
                return {
                    "ok": False,
                    "error": "Invalid camera frame"
                }

            # ---------------------------------------------------------- #
            # Resize large mobile frames.
            # ---------------------------------------------------------- #
            height, width = frame.shape[:2]

            max_width = self.config.FRAME_WIDTH

            if width > max_width:

                scale = max_width / float(width)

                frame = cv2.resize(
                    frame,
                    (
                        int(width * scale),
                        int(height * scale)
                    ),
                    interpolation=cv2.INTER_AREA
                )

            # ---------------------------------------------------------- #
            # Existing AI pipeline.
            # ---------------------------------------------------------- #
            annotated, state = (
                self.pipeline.process_frame(
                    frame,
                    draw=True
                )
            )

            # ---------------------------------------------------------- #
            # Encode processed frame.
            # ---------------------------------------------------------- #
            ok, buffer = cv2.imencode(
                ".jpg",
                annotated,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    self.config.CAMERA_JPEG_QUALITY
                ]
            )

            if not ok:
                return {
                    "ok": False,
                    "error": "Could not encode processed frame"
                }

            jpeg = buffer.tobytes()

            frame_b64 = base64.b64encode(
                jpeg
            ).decode("ascii")

            with self.lock:

                self._jpeg = jpeg
                self.latest_state = state
                self.browser_mode = True
                self.running = True

            return {
                "ok": True,
                "state": state,
                "frame": frame_b64
            }

        except Exception as exc:

            print(
                f"[CameraStream] Browser frame error: {exc}"
            )

            return {
                "ok": False,
                "error": str(exc)
            }

    # ------------------------------------------------------------------ #
    def stop(self):

        self.running = False

        if self.thread is not None:

            self.thread.join(
                timeout=1.0
            )

            self.thread = None

        if self.cap is not None:

            self.cap.release()
            self.cap = None

        with self.lock:
            self.browser_mode = False

    # ------------------------------------------------------------------ #
    def reset(self):

        if self.pipeline is not None:
            self.pipeline.reset()

        with self.lock:

            self._jpeg = None

            self.latest_state = {
                "found": False,
                "status_text": "Idle"
            }

    # ------------------------------------------------------------------ #
    def session_summary(self):

        if (
            self.pipeline is not None
            and hasattr(
                self.pipeline,
                "session_summary"
            )
        ):
            return self.pipeline.session_summary()

        return {}

    # ------------------------------------------------------------------ #
    # LOCAL WEBCAM LOOP
    # ------------------------------------------------------------------ #
    def _loop(self):

        while (
            self.running
            and self.cap is not None
        ):

            ok, frame = self.cap.read()

            if not ok:

                time.sleep(0.02)
                continue

            frame = cv2.flip(
                frame,
                1
            )

            annotated, state = (
                self.pipeline.process_frame(
                    frame,
                    draw=True
                )
            )

            ok, buffer = cv2.imencode(
                ".jpg",
                annotated,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    self.config.CAMERA_JPEG_QUALITY
                ]
            )

            if ok:

                with self.lock:

                    self._jpeg = buffer.tobytes()
                    self.latest_state = state

            time.sleep(0.005)

    # ------------------------------------------------------------------ #
    def get_annotated_jpeg(self):

        with self.lock:
            return self._jpeg