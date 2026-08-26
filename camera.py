"""
camera.py
=========
Threaded webcam capture + drowsiness processing.

A background thread continuously grabs frames from the webcam, runs them
through the DrowsinessPipeline, and keeps the latest annotated JPEG and
state dict in memory. Flask's `/video_feed` and `/api/state` just read
those, so slow clients never block the capture loop.

NOTE: the webcam only works where a physical camera is attached (i.e. on
the user's own machine). Inside a headless/sandbox environment `start()`
will simply report that the camera could not be opened.
"""

import time
import threading


class CameraStream:
    def __init__(self, config):
        self.config = config
        self.cap = None
        self.pipeline = None
        self.thread = None
        self.running = False
        self.lock = threading.Lock()
        self._jpeg = None
        self.latest_state = {"found": False, "status_text": "Idle"}
        self._cnn_active = False

    # ------------------------------------------------------------------ #
    @property
    def cnn_active(self):
        # Lazily build the pipeline once to learn whether the CNN is present.
        if self.pipeline is None:
            self._ensure_pipeline()
        return self._cnn_active

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
    def start(self):
        if self.running:
            return True
        import cv2
        self._ensure_pipeline()
        if self.pipeline is None:
            return False
        # Fresh session: reset scores/counters/analytics so each "Start"
        # produces clean session analytics (additive - safe if never run).
        self.pipeline.reset()
        self.latest_state = {"found": False, "status_text": "Starting..."}
        self.cap = cv2.VideoCapture(self.config.CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.FRAME_HEIGHT)
        if not self.cap.isOpened():
            print("[CameraStream] Could not open camera "
                  f"(index {self.config.CAMERA_INDEX}).")
            self.cap = None
            return False
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def reset(self):
        if self.pipeline is not None:
            self.pipeline.reset()
        self.latest_state = {"found": False, "status_text": "Idle"}

    def session_summary(self):
        """End-of-session analytics (Feature 16); empty dict if never started."""
        if self.pipeline is not None and hasattr(self.pipeline, "session_summary"):
            return self.pipeline.session_summary()
        return {}

    # ------------------------------------------------------------------ #
    def _loop(self):
        import cv2
        while self.running and self.cap is not None:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            frame = cv2.flip(frame, 1)  # mirror for a natural selfie view
            annotated, state = self.pipeline.process_frame(frame, draw=True)
            ok, buf = cv2.imencode(".jpg", annotated,
                                   [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self.lock:
                    self._jpeg = buf.tobytes()
                    self.latest_state = state
            time.sleep(0.005)

    def get_annotated_jpeg(self):
        with self.lock:
            return self._jpeg
