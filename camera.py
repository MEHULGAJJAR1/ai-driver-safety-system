"""
camera.py
=========
Camera processing for local webcam + browser/mobile camera.

LOCAL:
    Uses OpenCV VideoCapture(0).

PRODUCTION / RENDER:
    Does NOT try to access a server webcam.
    Browser/mobile sends JPEG frames to Flask.
    Frames are processed by DrowsinessPipeline.
"""

import os
import time
import threading
import base64

import cv2
import numpy as np

from detection import DrowsinessPipeline


class CameraStream:

    def __init__(self, config):

        self.config = config

        # Local camera
        self.cap = None
        self.thread = None

        # AI pipeline
        self.pipeline = None
        self._cnn_active = False

        # State
        self.running = False
        self.browser_mode = False

        # Thread safety
        self.lock = threading.Lock()

        # Latest processed JPEG
        self._jpeg = None

        # Latest detection state
        self.latest_state = {
            "found": False,
            "status_text": "Idle",
            "score": 0,
            "level": "ALERT",
            "camera_processing": "LOCAL"
        }

    # ================================================================== #
    # CONFIG HELPERS
    # ================================================================== #

    @property
    def max_camera_frame_kb(self):
        """
        Uses config value if available.
        Falls back to 1024 KB.
        """
        return int(
            getattr(
                self.config,
                "MAX_CAMERA_FRAME_KB",
                1024
            )
        )

    @property
    def camera_jpeg_quality(self):
        """
        Uses config value if available.
        Falls back to 80.
        """
        return int(
            getattr(
                self.config,
                "CAMERA_JPEG_QUALITY",
                80
            )
        )

    @property
    def frame_width(self):
        return int(
            getattr(
                self.config,
                "FRAME_WIDTH",
                640
            )
        )

    @property
    def frame_height(self):
        return int(
            getattr(
                self.config,
                "FRAME_HEIGHT",
                480
            )
        )

    @property
    def camera_index(self):
        return int(
            getattr(
                self.config,
                "CAMERA_INDEX",
                0
            )
        )

    # ================================================================== #
    # ENVIRONMENT
    # ================================================================== #

    @property
    def is_render(self):
        """
        Render automatically provides RENDER=true.
        """
        return (
            os.environ.get("RENDER", "").lower() == "true"
            or bool(os.environ.get("RENDER_SERVICE_ID"))
        )

    # ================================================================== #
    # AI PIPELINE
    # ================================================================== #

    @property
    def cnn_active(self):

        if self.pipeline is None:
            self._ensure_pipeline()

        return self._cnn_active

    def _ensure_pipeline(self):

        if self.pipeline is not None:
            return True

        try:

            print(
                "[CameraStream] Loading DrowsinessPipeline..."
            )

            self.pipeline = DrowsinessPipeline(
                self.config
            )

            self._cnn_active = bool(
                getattr(
                    self.pipeline,
                    "cnn_active",
                    False
                )
            )

            print(
                "[CameraStream] DrowsinessPipeline loaded successfully."
            )

            print(
                f"[CameraStream] CNN active: {self._cnn_active}"
            )

            return True

        except Exception as exc:

            print(
                "[CameraStream] Pipeline init failed:"
            )

            print(
                repr(exc)
            )

            self.pipeline = None
            self._cnn_active = False

            return False

    # ================================================================== #
    # START CAMERA
    # ================================================================== #

    def start(self):

        """
        Start camera.

        On Render:
            Never tries to access server webcam.
            Starts browser camera session.

        Locally:
            Uses OpenCV webcam.
        """

        # -------------------------------------------------------------- #
        # If already running
        # -------------------------------------------------------------- #

        if self.running:
            return True

        # -------------------------------------------------------------- #
        # Load AI pipeline
        # -------------------------------------------------------------- #

        if not self._ensure_pipeline():

            self.latest_state = {
                "found": False,
                "status_text": "Drowsiness detection pipeline unavailable",
                "score": 0,
                "level": "ALERT",
                "camera_processing": (
                    "BROWSER"
                    if self.is_render
                    else "LOCAL"
                )
            }

            return False

        # -------------------------------------------------------------- #
        # RENDER / PRODUCTION
        # -------------------------------------------------------------- #

        if self.is_render:

            print(
                "[CameraStream] Render detected."
            )

            print(
                "[CameraStream] Starting browser/mobile camera mode."
            )

            return self.start_browser()

        # -------------------------------------------------------------- #
        # LOCAL DEVELOPMENT
        # -------------------------------------------------------------- #

        return self.start_local()

    # ================================================================== #
    # LOCAL WEBCAM
    # ================================================================== #

    def start_local(self):

        if self.running:
            return True

        if not self._ensure_pipeline():
            return False

        try:

            self.pipeline.reset()

        except Exception as exc:

            print(
                f"[CameraStream] Pipeline reset warning: {exc}"
            )

        self.latest_state = {
            "found": False,
            "status_text": "Starting camera...",
            "score": 0,
            "level": "ALERT",
            "camera_processing": "LOCAL"
        }

        print(
            f"[CameraStream] Opening local camera index "
            f"{self.camera_index}"
        )

        try:

            self.cap = cv2.VideoCapture(
                self.camera_index
            )

            self.cap.set(
                cv2.CAP_PROP_FRAME_WIDTH,
                self.frame_width
            )

            self.cap.set(
                cv2.CAP_PROP_FRAME_HEIGHT,
                self.frame_height
            )

        except Exception as exc:

            print(
                f"[CameraStream] Camera initialization error: {exc}"
            )

            self.cap = None
            return False

        if self.cap is None or not self.cap.isOpened():

            print(
                "[CameraStream] Could not open local camera."
            )

            if self.cap is not None:

                try:
                    self.cap.release()
                except Exception:
                    pass

            self.cap = None

            self.latest_state = {
                "found": False,
                "status_text": "Could not open local camera",
                "score": 0,
                "level": "ALERT",
                "camera_processing": "LOCAL"
            }

            return False

        self.browser_mode = False
        self.running = True

        self.thread = threading.Thread(
            target=self._loop,
            daemon=True
        )

        self.thread.start()

        print(
            "[CameraStream] Local camera started."
        )

        return True

    # ================================================================== #
    # BROWSER / MOBILE CAMERA
    # ================================================================== #

    def start_browser(self):

        """
        Start browser/mobile camera session.

        IMPORTANT:
        This function does NOT access a physical camera.
        The browser/mobile device sends frames using
        process_browser_frame().
        """

        if not self._ensure_pipeline():
            return False

        try:

            self.pipeline.reset()

        except Exception as exc:

            print(
                f"[CameraStream] Pipeline reset warning: {exc}"
            )

        with self.lock:

            self.browser_mode = True
            self.running = True

            self._jpeg = None

            self.latest_state = {
                "found": False,
                "status_text": "Waiting for browser camera...",
                "score": 0,
                "level": "ALERT",
                "camera_processing": "BROWSER"
            }

        print(
            "[CameraStream] Browser/mobile camera session started."
        )

        return True

    # ================================================================== #
    # PROCESS BROWSER FRAME
    # ================================================================== #

    def process_browser_frame(self, image_data):

        """
        Process one JPEG frame received from browser/mobile.

        Accepted formats:

            data:image/jpeg;base64,...

        or:

            raw base64 JPEG
        """

        if not image_data:

            return {
                "ok": False,
                "error": "Empty camera frame"
            }

        # -------------------------------------------------------------- #
        # Ensure pipeline
        # -------------------------------------------------------------- #

        if not self._ensure_pipeline():

            return {
                "ok": False,
                "error": "AI pipeline unavailable"
            }

        try:

            # ---------------------------------------------------------- #
            # Remove data URL prefix
            # ---------------------------------------------------------- #

            if "," in image_data:

                image_data = image_data.split(
                    ",",
                    1
                )[1]

            # ---------------------------------------------------------- #
            # Decode base64
            # ---------------------------------------------------------- #

            try:

                raw = base64.b64decode(
                    image_data,
                    validate=True
                )

            except Exception:

                return {
                    "ok": False,
                    "error": "Invalid base64 camera frame"
                }

            # ---------------------------------------------------------- #
            # Protect server from huge frames
            # ---------------------------------------------------------- #

            max_bytes = (
                self.max_camera_frame_kb
                * 1024
            )

            if len(raw) > max_bytes:

                return {
                    "ok": False,
                    "error": (
                        "Camera frame too large. "
                        f"Maximum {self.max_camera_frame_kb} KB."
                    )
                }

            # ---------------------------------------------------------- #
            # Convert bytes -> NumPy
            # ---------------------------------------------------------- #

            array = np.frombuffer(
                raw,
                dtype=np.uint8
            )

            # ---------------------------------------------------------- #
            # JPEG -> OpenCV frame
            # ---------------------------------------------------------- #

            frame = cv2.imdecode(
                array,
                cv2.IMREAD_COLOR
            )

            if frame is None:

                return {
                    "ok": False,
                    "error": "Invalid JPEG camera frame"
                }

            # ---------------------------------------------------------- #
            # Resize large mobile frames
            # ---------------------------------------------------------- #

            height, width = frame.shape[:2]

            if width > self.frame_width:

                scale = (
                    self.frame_width
                    / float(width)
                )

                new_width = self.frame_width

                new_height = int(
                    height * scale
                )

                frame = cv2.resize(
                    frame,
                    (
                        new_width,
                        new_height
                    ),
                    interpolation=cv2.INTER_AREA
                )

            # ---------------------------------------------------------- #
            # Process with AI
            # ---------------------------------------------------------- #

            annotated, state = (
                self.pipeline.process_frame(
                    frame,
                    draw=True
                )
            )

            # ---------------------------------------------------------- #
            # Encode annotated image
            # ---------------------------------------------------------- #

            ok, buffer = cv2.imencode(
                ".jpg",
                annotated,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    self.camera_jpeg_quality
                ]
            )

            if not ok:

                return {
                    "ok": False,
                    "error": "Could not encode processed frame"
                }

            jpeg = buffer.tobytes()

            # ---------------------------------------------------------- #
            # Base64 response for browser
            # ---------------------------------------------------------- #

            frame_b64 = base64.b64encode(
                jpeg
            ).decode("ascii")

            # ---------------------------------------------------------- #
            # Update shared state
            # ---------------------------------------------------------- #

            with self.lock:

                self._jpeg = jpeg

                self.latest_state = dict(
                    state or {}
                )

                self.latest_state[
                    "camera_processing"
                ] = "BROWSER"

                self.browser_mode = True
                self.running = True

            return {
                "ok": True,
                "state": self.latest_state,
                "frame": frame_b64
            }

        except Exception as exc:

            print(
                "[CameraStream] Browser frame processing error:"
            )

            print(
                repr(exc)
            )

            return {
                "ok": False,
                "error": str(exc)
            }

    # ================================================================== #
    # STOP
    # ================================================================== #

    def stop(self):

        print(
            "[CameraStream] Stopping camera..."
        )

        self.running = False

        # -------------------------------------------------------------- #
        # Stop local camera thread
        # -------------------------------------------------------------- #

        if self.thread is not None:

            try:

                self.thread.join(
                    timeout=1.0
                )

            except Exception:
                pass

            self.thread = None

        # -------------------------------------------------------------- #
        # Release local camera
        # -------------------------------------------------------------- #

        if self.cap is not None:

            try:

                self.cap.release()

            except Exception:
                pass

            self.cap = None

        # -------------------------------------------------------------- #
        # Reset mode
        # -------------------------------------------------------------- #

        with self.lock:

            self.browser_mode = False

            self._jpeg = None

            self.latest_state = {
                "found": False,
                "status_text": "Idle",
                "score": 0,
                "level": "ALERT",
                "camera_processing": (
                    "BROWSER"
                    if self.is_render
                    else "LOCAL"
                )
            }

        print(
            "[CameraStream] Camera stopped."
        )

    # ================================================================== #
    # RESET
    # ================================================================== #

    def reset(self):

        if self.pipeline is not None:

            try:

                self.pipeline.reset()

            except Exception as exc:

                print(
                    f"[CameraStream] Pipeline reset error: {exc}"
                )

        with self.lock:

            self._jpeg = None

            self.latest_state = {
                "found": False,
                "status_text": "Idle",
                "score": 0,
                "level": "ALERT",
                "camera_processing": (
                    "BROWSER"
                    if self.is_render
                    else "LOCAL"
                )
            }

    # ================================================================== #
    # SESSION SUMMARY
    # ================================================================== #

    def session_summary(self):

        if (
            self.pipeline is not None
            and hasattr(
                self.pipeline,
                "session_summary"
            )
        ):

            try:

                return self.pipeline.session_summary()

            except Exception as exc:

                print(
                    f"[CameraStream] Session summary error: {exc}"
                )

        return {}

    # ================================================================== #
    # LOCAL CAMERA LOOP
    # ================================================================== #

    def _loop(self):

        while (
            self.running
            and self.cap is not None
        ):

            try:

                ok, frame = self.cap.read()

                if not ok:

                    time.sleep(0.02)
                    continue

                # Mirror webcam
                frame = cv2.flip(
                    frame,
                    1
                )

                # AI processing
                annotated, state = (
                    self.pipeline.process_frame(
                        frame,
                        draw=True
                    )
                )

                # JPEG encode
                ok, buffer = cv2.imencode(
                    ".jpg",
                    annotated,
                    [
                        cv2.IMWRITE_JPEG_QUALITY,
                        self.camera_jpeg_quality
                    ]
                )

                if ok:

                    with self.lock:

                        self._jpeg = (
                            buffer.tobytes()
                        )

                        self.latest_state = dict(
                            state or {}
                        )

                        self.latest_state[
                            "camera_processing"
                        ] = "LOCAL"

                time.sleep(0.005)

            except Exception as exc:

                print(
                    "[CameraStream] Local camera loop error:"
                )

                print(
                    repr(exc)
                )

                time.sleep(0.1)

    # ================================================================== #
    # GET LATEST JPEG
    # ================================================================== #

    def get_annotated_jpeg(self):

        with self.lock:

            return self._jpeg