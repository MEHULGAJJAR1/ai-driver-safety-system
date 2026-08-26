"""
detection/drowsiness.py
=======================

Main drowsiness detection pipeline.

Features:
    - MediaPipe facial landmarks
    - EAR eye closure detection
    - MAR yawning detection
    - Head pose / nod detection
    - PERCLOS
    - Optional CNN eye-state classification
    - Drowsiness score
    - ALERT / WARNING / DROWSY levels
    - AlertManager integration
    - Sunglasses detection
    - Driver safety / attention analytics
    - Annotated output frame
"""

import time
from collections import deque

from config import config

from .landmarks import LandmarkDetector
from .sunglasses import SunglassesDetector
from .alerts import AlertManager

from analytics import DriverStateMonitor


# ======================================================================
# LEVELS
# ======================================================================

LEVEL_ALERT = "ALERT"
LEVEL_WARNING = "WARNING"
LEVEL_DROWSY = "DROWSY"


# ======================================================================
# DROWSINESS SCORER
# ======================================================================

class DrowsinessScorer:
    """
    Frame-by-frame drowsiness state machine.

    Receives landmark metrics and optional CNN eye-closure probability.
    """

    def __init__(self, cfg=config):

        self.cfg = cfg

        self.reset()

    # ------------------------------------------------------------------
    # RESET
    # ------------------------------------------------------------------

    def reset(self):

        self.frame_idx = 0

        self.eye_closed_frames = 0
        self.yawn_frames = 0
        self.head_frames = 0

        self.blink_count = 0
        self.yawn_count = 0
        self.nod_count = 0
        self.drowsy_events = 0

        self._eye_history = deque(
            maxlen=self.cfg.PERCLOS_WINDOW
        )

        self._in_blink = False
        self._blink_frames = 0

        self._yawn_active = False
        self._nod_active = False

        self._perclos_high = False

        self._last_level = LEVEL_ALERT

        self._last_alarm_ts = 0.0

    # ------------------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------------------

    def update(
        self,
        metrics,
        cnn_closed_prob=None
    ):
        """
        Process one frame.

        Returns a serializable state dictionary.
        """

        self.frame_idx += 1

        cfg = self.cfg

        events = []

        # ==============================================================
        # NO FACE
        # ==============================================================

        if not metrics.get("found"):

            self._eye_history.append(0)

            self.eye_closed_frames = max(
                0,
                self.eye_closed_frames - 1
            )

            return self._build_state(
                found=False,
                ear=0.0,
                mar=0.0,
                pitch=0.0,
                yaw=0.0,
                roll=0.0,
                eyes_closed=False,
                cnn_closed_prob=cnn_closed_prob,
                events=events,
            )

        # ==============================================================
        # LANDMARK VALUES
        # ==============================================================

        ear = float(
            metrics.get("ear", 0.0)
        )

        mar = float(
            metrics.get("mar", 0.0)
        )

        pitch = float(
            metrics.get("pitch", 0.0)
        )

        yaw = float(
            metrics.get("yaw", 0.0)
        )

        roll = float(
            metrics.get("roll", 0.0)
        )

        # ==============================================================
        # EYE CLOSURE
        # ==============================================================

        ear_closed = (
            ear < cfg.EAR_THRESHOLD
        )

        if cnn_closed_prob is not None:

            cnn_closed = (
                cnn_closed_prob
                >= cfg.CNN_CLOSED_THRESHOLD
            )

            eyes_closed = (
                ear_closed or cnn_closed
            )

        else:

            eyes_closed = ear_closed

        self._eye_history.append(
            1 if eyes_closed else 0
        )

        # ==============================================================
        # BLINK
        # ==============================================================

        if eyes_closed:

            self.eye_closed_frames += 1

            self._blink_frames += 1

            self._in_blink = True

        else:

            if self._in_blink:

                if (
                    cfg.BLINK_MIN_FRAMES
                    <= self._blink_frames
                    <= cfg.BLINK_MAX_FRAMES
                ):

                    self.blink_count += 1

                    events.append(
                        _ev(
                            "BLINK",
                            "low",
                            "Blink detected"
                        )
                    )

                self._blink_frames = 0

                self._in_blink = False

            self.eye_closed_frames = 0

        # ==============================================================
        # MICRO SLEEP
        # ==============================================================

        eye_micro_sleep = (
            self.eye_closed_frames
            >= cfg.EAR_CONSEC_FRAMES
        )

        if (
            eye_micro_sleep
            and self.eye_closed_frames
            == cfg.EAR_CONSEC_FRAMES
        ):

            events.append(
                _ev(
                    "EYE_CLOSURE",
                    "high",
                    "Prolonged eye closure detected"
                )
            )

        # ==============================================================
        # PERCLOS
        # ==============================================================

        if self._eye_history:

            perclos = (
                sum(self._eye_history)
                / len(self._eye_history)
            )

        else:

            perclos = 0.0

        if (
            perclos >= cfg.PERCLOS_ALARM
            and
            len(self._eye_history)
            >= cfg.PERCLOS_WINDOW // 2
        ):

            if not self._perclos_high:

                events.append(
                    _ev(
                        "PERCLOS",
                        "high",
                        (
                            f"PERCLOS "
                            f"{perclos * 100:.0f}% "
                            f"exceeds alarm level"
                        )
                    )
                )

                self._perclos_high = True

        else:

            self._perclos_high = False

        # ==============================================================
        # YAWN
        # ==============================================================

        if mar >= cfg.MAR_THRESHOLD:

            self.yawn_frames += 1

        else:

            if self._yawn_active:

                self._yawn_active = False

            self.yawn_frames = 0

        yawning = (
            self.yawn_frames
            >= cfg.MAR_CONSEC_FRAMES
        )

        if (
            yawning
            and not self._yawn_active
        ):

            self.yawn_count += 1

            self._yawn_active = True

            events.append(
                _ev(
                    "YAWN",
                    "medium",
                    "Yawning detected"
                )
            )

        # ==============================================================
        # HEAD NOD
        # ==============================================================

        head_down = (
            abs(pitch)
            >= cfg.HEAD_PITCH_THRESHOLD
        )

        looking_away = (
            abs(yaw)
            >= cfg.HEAD_YAW_THRESHOLD
        )

        if head_down:

            self.head_frames += 1

        else:

            if self._nod_active:

                self._nod_active = False

            self.head_frames = 0

        nodding = (
            self.head_frames
            >= cfg.HEAD_CONSEC_FRAMES
        )

        if (
            nodding
            and not self._nod_active
        ):

            self.nod_count += 1

            self._nod_active = True

            events.append(
                _ev(
                    "HEAD_NOD",
                    "high",
                    "Head nodding / dropping detected"
                )
            )

        # ==============================================================
        # COMPOSITE SCORE
        # ==============================================================

        eye_comp = min(
            self.eye_closed_frames
            / max(
                cfg.EAR_CONSEC_FRAMES,
                1
            ),
            1.0
        )

        perclos_comp = min(
            perclos
            / max(
                cfg.PERCLOS_ALARM,
                1e-6
            ),
            1.0
        )

        yawn_comp = min(
            self.yawn_frames
            / max(
                cfg.MAR_CONSEC_FRAMES,
                1
            ),
            1.0
        )

        head_comp = min(
            self.head_frames
            / max(
                cfg.HEAD_CONSEC_FRAMES,
                1
            ),
            1.0
        )

        score = (
            cfg.W_EYE * eye_comp
            +
            cfg.W_PERCLOS * perclos_comp
            +
            cfg.W_YAWN * yawn_comp
            +
            cfg.W_HEAD * head_comp
        )

        score = float(
            max(
                0.0,
                min(
                    100.0,
                    score
                )
            )
        )

        # ==============================================================
        # LEVEL
        # ==============================================================

        level = self._level_for(
            score
        )

        if level == LEVEL_DROWSY:

            if (
                self._last_level
                != LEVEL_DROWSY
            ):

                self.drowsy_events += 1

                events.append(
                    _ev(
                        "DROWSINESS",
                        "high",
                        "Drowsiness detected"
                    )
                )

        self._last_level = level

        # ==============================================================
        # BUILD STATE
        # ==============================================================

        return self._build_state(
            found=True,
            ear=ear,
            mar=mar,
            pitch=pitch,
            yaw=yaw,
            roll=roll,
            eyes_closed=eyes_closed,
            cnn_closed_prob=cnn_closed_prob,
            perclos=perclos,
            score=score,
            level=level,
            yawning=yawning,
            nodding=nodding,
            looking_away=looking_away,
            micro_sleep=eye_micro_sleep,
            events=events,
        )

    # ------------------------------------------------------------------
    # LEVEL
    # ------------------------------------------------------------------

    def _level_for(self, score):

        if score >= self.cfg.SCORE_ALARM:

            return LEVEL_DROWSY

        if score >= self.cfg.SCORE_WARNING:

            return LEVEL_WARNING

        return LEVEL_ALERT

    # ------------------------------------------------------------------
    # STATE BUILDER
    # ------------------------------------------------------------------

    def _build_state(
        self,
        found,
        ear,
        mar,
        pitch,
        yaw,
        roll,
        eyes_closed,
        cnn_closed_prob,
        events,
        perclos=0.0,
        score=0.0,
        level=LEVEL_ALERT,
        yawning=False,
        nodding=False,
        looking_away=False,
        micro_sleep=False,
    ):

        alarm = False

        if (
            level == LEVEL_DROWSY
            and self.cfg.ALARM_ENABLED
        ):

            now = time.time()

            if (
                now - self._last_alarm_ts
                >= self.cfg.ALARM_COOLDOWN
            ):

                alarm = True

                self._last_alarm_ts = now

        status_text = {

            LEVEL_ALERT:
                "Alert",

            LEVEL_WARNING:
                "Warning - signs of fatigue",

            LEVEL_DROWSY:
                "DROWSY - WAKE UP!",
        }.get(
            level,
            "Alert"
        )

        if not found:

            status_text = (
                "No face detected"
            )

        return {

            "found":
                bool(found),

            "face_detected":
                bool(found),

            "ear":
                round(
                    float(ear),
                    4
                ),

            "mar":
                round(
                    float(mar),
                    4
                ),

            "pitch":
                round(
                    float(pitch),
                    2
                ),

            "yaw":
                round(
                    float(yaw),
                    2
                ),

            "roll":
                round(
                    float(roll),
                    2
                ),

            "eyes_closed":
                bool(eyes_closed),

            "cnn_closed_prob":
                (
                    round(
                        float(cnn_closed_prob),
                        3
                    )
                    if cnn_closed_prob is not None
                    else None
                ),

            "eye_closed_frames":
                int(
                    self.eye_closed_frames
                ),

            "perclos":
                round(
                    float(perclos),
                    4
                ),

            "blink_count":
                int(
                    self.blink_count
                ),

            "yawn_count":
                int(
                    self.yawn_count
                ),

            "nod_count":
                int(
                    self.nod_count
                ),

            "drowsy_events":
                int(
                    self.drowsy_events
                ),

            "micro_sleep":
                bool(micro_sleep),

            "yawning":
                bool(yawning),

            "nodding":
                bool(nodding),

            "looking_away":
                bool(looking_away),

            "drowsiness":
                level == LEVEL_DROWSY,

            "score":
                round(
                    float(score),
                    1
                ),

            "level":
                level,

            "status_text":
                status_text,

            "alarm":
                bool(alarm),

            "events":
                events,

            "frame_idx":
                int(self.frame_idx),

            "ts":
                time.time(),
        }


# ======================================================================
# EVENT HELPER
# ======================================================================

def _ev(
    etype,
    severity,
    message
):

    return {
        "type": etype,
        "severity": severity,
        "message": message,
    }


# ======================================================================
# FULL PIPELINE
# ======================================================================

class DrowsinessPipeline:
    """
    Complete real-time driver monitoring pipeline.

    Input:
        BGR OpenCV frame

    Output:
        annotated BGR frame
        state dictionary
    """

    def __init__(
        self,
        cfg=config,
        use_cnn=None
    ):

        self.cfg = cfg

        # --------------------------------------------------------------
        # MediaPipe detector
        # --------------------------------------------------------------

        self.detector = (
            LandmarkDetector()
        )

        # --------------------------------------------------------------
        # Drowsiness scorer
        # --------------------------------------------------------------

        self.scorer = (
            DrowsinessScorer(
                cfg
            )
        )

        # --------------------------------------------------------------
        # Sunglasses
        # --------------------------------------------------------------

        self.sunglasses = (
            SunglassesDetector(
                cfg
            )
        )

        # --------------------------------------------------------------
        # Alert manager
        # --------------------------------------------------------------

        self.alerts = (
            AlertManager(
                cfg
            )
        )

        # --------------------------------------------------------------
        # Safety monitor
        # --------------------------------------------------------------

        self.monitor = (
            DriverStateMonitor(
                cfg
            )
        )

        self._prev_distraction_alert = False
        self._prev_break = False

        # --------------------------------------------------------------
        # CNN
        # --------------------------------------------------------------

        self.classifier = None

        if use_cnn is None:

            use_cnn = bool(
                getattr(
                    cfg,
                    "USE_CNN",
                    False
                )
            )

        if use_cnn:

            try:

                from .cnn_model import (
                    EyeStateClassifier
                )

                clf = EyeStateClassifier(
                    cfg.CNN_MODEL_PATH,
                    cfg.CNN_INPUT_SIZE
                )

                if clf.available:

                    self.classifier = clf

                    print(
                        "[DrowsinessPipeline] CNN eye model active."
                    )

                else:

                    print(
                        "[DrowsinessPipeline] CNN model unavailable. "
                        "Using EAR."
                    )

            except Exception as exc:

                print(
                    "[DrowsinessPipeline] CNN disabled:",
                    exc
                )

                self.classifier = None

    # ------------------------------------------------------------------
    # CNN STATUS
    # ------------------------------------------------------------------

    @property
    def cnn_active(self):

        return (
            self.classifier is not None
            and self.classifier.available
        )

    # ------------------------------------------------------------------
    # RESET
    # ------------------------------------------------------------------

    def reset(self):

        self.scorer.reset()

        self.sunglasses.reset()

        self.alerts.reset()

        self.monitor.reset()

        self._prev_distraction_alert = False

        self._prev_break = False

    # ------------------------------------------------------------------
    # SESSION SUMMARY
    # ------------------------------------------------------------------

    def session_summary(self):

        try:

            return (
                self.monitor.session_summary()
                or {}
            )

        except Exception as exc:

            print(
                "[DrowsinessPipeline] "
                "Session summary error:",
                exc
            )

            return {}

    # ------------------------------------------------------------------
    # PROCESS FRAME
    # ------------------------------------------------------------------

    def process_frame(
        self,
        frame_bgr,
        draw=True
    ):

        # ==============================================================
        # LANDMARK DETECTION
        # ==============================================================

        metrics = (
            self.detector.analyze(
                frame_bgr
            )
        )

        # ==============================================================
        # CNN
        # ==============================================================

        cnn_prob = None

        if (
            self.cnn_active
            and metrics.get("found")
        ):

            left = (
                self.detector.eye_crop(
                    frame_bgr,
                    metrics[
                        "left_eye_pts"
                    ]
                )
            )

            right = (
                self.detector.eye_crop(
                    frame_bgr,
                    metrics[
                        "right_eye_pts"
                    ]
                )
            )

            cnn_prob = (
                self.classifier.predict_pair(
                    left,
                    right
                )
            )

        # ==============================================================
        # DROWSINESS SCORER
        # ==============================================================

        state = (
            self.scorer.update(
                metrics,
                cnn_closed_prob=cnn_prob
            )
        )

        # ==============================================================
        # SUNGLASSES
        # ==============================================================

        try:

            sg = (
                self.sunglasses.analyze(
                    frame_bgr,
                    metrics
                )
            )

        except Exception as exc:

            print(
                "[DrowsinessPipeline] "
                "Sunglasses detector error:",
                exc
            )

            sg = {
                "detected": False,
                "confidence": 0.0,
            }

        # ==============================================================
        # FACE EDGE
        # ==============================================================

        near_edge = False

        if metrics.get("found"):

            near_edge = (
                self._near_edge(
                    metrics,
                    frame_bgr.shape[1],
                    frame_bgr.shape[0]
                )
            )

        # ==============================================================
        # ALERT MANAGER
        # ==============================================================

        try:

            alert_fields = (
                self.alerts.update(
                    metrics,
                    state,
                    sg,
                    near_edge=near_edge
                )
            )

        except Exception as exc:

            print(
                "[DrowsinessPipeline] "
                "Alert manager error:",
                exc
            )

            alert_fields = {
                "events": []
            }

        alert_events = (
            alert_fields.pop(
                "events",
                []
            )
        )

        state["events"] = (
            list(
                state.get(
                    "events",
                    []
                )
            )
            +
            list(
                alert_events
            )
        )

        state.update(
            alert_fields
        )

        state["sunglasses"] = sg

        # ==============================================================
        # SAFETY MONITOR
        # ==============================================================

        try:

            score_fields = (
                self.monitor.update(
                    state
                )
            )

        except Exception as exc:

            print(
                "[DrowsinessPipeline] "
                "Safety monitor error:",
                exc
            )

            score_fields = {}

        state.update(
            score_fields
        )

        # ==============================================================
        # DISTRACTION EVENT
        # ==============================================================

        dist_alert = bool(
            score_fields.get(
                "distraction_alert"
            )
        )

        if (
            dist_alert
            and not self._prev_distraction_alert
        ):

            state.setdefault(
                "events",
                []
            ).append(
                _ev(
                    "ATTENTION_ALERT",
                    "high",
                    "Distraction exceeded safe threshold"
                )
            )

        self._prev_distraction_alert = (
            dist_alert
        )

        # ==============================================================
        # BREAK EVENT
        # ==============================================================

        brk = bool(
            score_fields.get(
                "break_recommended"
            )
        )

        if (
            brk
            and not self._prev_break
        ):

            state.setdefault(
                "events",
                []
            ).append(
                _ev(
                    "BREAK_RECOMMENDED",
                    "medium",
                    (
                        score_fields.get(
                            "break_text"
                        )
                        or
                        "Break recommended"
                    )
                )
            )

        self._prev_break = brk

        # ==============================================================
        # EXTRA STATE
        # ==============================================================

        state["camera_processing"] = (
            "BROWSER"
        )

        state["cnn_active"] = (
            self.cnn_active
        )

        # ==============================================================
        # DRAW
        # ==============================================================

        if draw:

            annotated = (
                self._draw(
                    frame_bgr.copy(),
                    metrics,
                    state
                )
            )

        else:

            annotated = frame_bgr

        return (
            annotated,
            state
        )

    # ------------------------------------------------------------------
    # FACE NEAR EDGE
    # ------------------------------------------------------------------

    def _near_edge(
        self,
        metrics,
        w,
        h
    ):

        face = metrics.get(
            "landmarks"
        )

        margin = float(
            getattr(
                self.cfg,
                "FACE_EDGE_MARGIN",
                0.08
            )
        )

        try:

            xs = [
                lm.x
                for lm in face.landmark
            ]

            ys = [
                lm.y
                for lm in face.landmark
            ]

        except Exception:

            return False

        if not xs or not ys:

            return False

        return (
            min(xs) < margin
            or
            min(ys) < margin
            or
            max(xs) > 1.0 - margin
            or
            max(ys) > 1.0 - margin
        )

    # ------------------------------------------------------------------
    # DRAW OVERLAY
    # ------------------------------------------------------------------

    def _draw(
        self,
        frame,
        metrics,
        state
    ):

        import cv2

        h, w = frame.shape[:2]

        # ==============================================================
        # LEVEL COLORS
        # ==============================================================

        colors = {

            LEVEL_ALERT:
                (0, 180, 0),

            LEVEL_WARNING:
                (0, 170, 255),

            LEVEL_DROWSY:
                (0, 0, 255),
        }

        color = colors.get(
            state.get(
                "level",
                LEVEL_ALERT
            ),
            (0, 180, 0)
        )

        # ==============================================================
        # FACE LANDMARKS
        # ==============================================================

        if metrics.get("found"):

            eye_groups = (

                (
                    metrics.get(
                        "left_eye_pts",
                        []
                    ),
                    (0, 255, 0)
                ),

                (
                    metrics.get(
                        "right_eye_pts",
                        []
                    ),
                    (0, 255, 0)
                ),

                (
                    metrics.get(
                        "mouth_pts",
                        []
                    ),
                    (255, 128, 0)
                ),
            )

            for pts, point_color in eye_groups:

                for x, y in pts:

                    cv2.circle(
                        frame,
                        (
                            int(x),
                            int(y)
                        ),
                        2,
                        point_color,
                        -1
                    )

        # ==============================================================
        # HEADER
        # ==============================================================

        overlay = frame.copy()

        cv2.rectangle(
            overlay,
            (0, 0),
            (w, 100),
            (20, 20, 20),
            -1
        )

        cv2.addWeighted(
            overlay,
            0.55,
            frame,
            0.45,
            0,
            frame
        )

        cv2.putText(
            frame,
            f"STATUS: {state.get('status_text', 'Idle')}",
            (12, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            color,
            2
        )

        cv2.putText(
            frame,
            (
                f"EAR {state.get('ear', 0):.2f}  "
                f"MAR {state.get('mar', 0):.2f}  "
                f"Pitch {state.get('pitch', 0):.0f}  "
                f"Yaw {state.get('yaw', 0):.0f}"
            ),
            (12, 58),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (230, 230, 230),
            1
        )

        cv2.putText(
            frame,
            (
                f"Score {state.get('score', 0):.0f}  "
                f"Blink {state.get('blink_count', 0)}  "
                f"Yawn {state.get('yawn_count', 0)}  "
                f"Nod {state.get('nod_count', 0)}"
            ),
            (12, 82),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (230, 230, 230),
            1
        )

        # ==============================================================
        # FLAGS
        # ==============================================================

        flags = []

        if state.get(
            "eyes_closed"
        ):

            flags.append(
                "EYES CLOSED"
            )

        if state.get(
            "yawning"
        ):

            flags.append(
                "YAWNING"
            )

        if state.get(
            "nodding"
        ):

            flags.append(
                "HEAD NOD"
            )

        if state.get(
            "looking_away"
        ):

            flags.append(
                "LOOKING AWAY"
            )

        if flags:

            cv2.putText(
                frame,
                " | ".join(flags),
                (12, 106),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                1
            )

        # ==============================================================
        # STATUS CHIPS
        # ==============================================================

        chips = []

        attention = state.get(
            "attention"
        )

        if attention == "left":

            chips.append(
                (
                    "LOOKING LEFT",
                    (0, 165, 255)
                )
            )

        elif attention == "right":

            chips.append(
                (
                    "LOOKING RIGHT",
                    (0, 165, 255)
                )
            )

        if state.get(
            "sunglasses_detected"
        ):

            chips.append(
                (
                    "SUNGLASSES",
                    (255, 200, 0)
                )
            )

        coverage = state.get(
            "face_coverage"
        )

        if coverage == "covered":

            chips.append(
                (
                    "FACE COVERED",
                    (0, 0, 255)
                )
            )

        elif coverage == "none":

            chips.append(
                (
                    "FACE NOT VISIBLE",
                    (0, 0, 255)
                )
            )

        elif coverage == "partial":

            chips.append(
                (
                    "FACE PARTIAL",
                    (0, 170, 255)
                )
            )

        cy = 130

        for text, chip_color in chips:

            size = cv2.getTextSize(
                text,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                2
            )

            tw = size[0][0]

            cv2.putText(
                frame,
                text,
                (
                    max(
                        10,
                        w - tw - 14
                    ),
                    cy
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                chip_color,
                2
            )

            cy += 26

        # ==============================================================
        # SAFETY SCORES
        # ==============================================================

        risk = state.get(
            "risk_level",
            "LOW"
        )

        risk_colors = {

            "LOW":
                (0, 180, 0),

            "MEDIUM":
                (0, 170, 255),

            "HIGH":
                (0, 0, 255),
        }

        risk_color = risk_colors.get(
            risk,
            (0, 180, 0)
        )

        attention_score = (
            state.get(
                "attention_score"
            )
        )

        safety_score = (
            state.get(
                "safety_score"
            )
        )

        if (
            attention_score is not None
            and
            safety_score is not None
        ):

            hud = frame.copy()

            cv2.rectangle(
                hud,
                (0, h - 130),
                (245, h - 55),
                (20, 20, 20),
                -1
            )

            cv2.addWeighted(
                hud,
                0.5,
                frame,
                0.5,
                0,
                frame
            )

            cv2.putText(
                frame,
                (
                    f"Attention "
                    f"{float(attention_score):.0f}  "
                    f"Safety "
                    f"{float(safety_score):.0f}"
                ),
                (12, h - 105),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (230, 230, 230),
                1
            )

            cv2.putText(
                frame,
                f"Risk: {risk}",
                (12, h - 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.58,
                risk_color,
                2
            )

            if state.get(
                "distraction_active"
            ):

                duration = float(
                    state.get(
                        "distraction_duration",
                        0
                    )
                )

                cv2.putText(
                    frame,
                    (
                        f"Distraction "
                        f"{duration:.1f}s"
                    ),
                    (12, h - 58),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.48,
                    (0, 165, 255),
                    1
                )

        # ==============================================================
        # ALERT BANNER
        # ==============================================================

        alert_label = state.get(
            "alert_label"
        )

        if alert_label:

            size = cv2.getTextSize(
                alert_label,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                2
            )

            tw = size[0][0]

            bx = max(
                10,
                (w - tw) // 2
            )

            band = frame.copy()

            cv2.rectangle(
                band,
                (0, h - 52),
                (w, h),
                (0, 0, 60),
                -1
            )

            cv2.addWeighted(
                band,
                0.55,
                frame,
                0.45,
                0,
                frame
            )

            cv2.putText(
                frame,
                alert_label,
                (bx, h - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2
            )

        # ==============================================================
        # WARNING / ALERT BORDER
        # ==============================================================

        drowsy_border = (
            state.get("level")
            == LEVEL_DROWSY
        )

        if (
            drowsy_border
            or state.get(
                "alert_active"
            )
        ):

            if (
                drowsy_border
                or state.get(
                    "face_covered"
                )
            ):

                border_color = (
                    0,
                    0,
                    255
                )

            else:

                border_color = (
                    0,
                    165,
                    255
                )

            cv2.rectangle(
                frame,
                (2, 2),
                (
                    w - 2,
                    h - 2
                ),
                border_color,
                5
            )

        return frame

    # ------------------------------------------------------------------
    # CLOSE
    # ------------------------------------------------------------------

    def close(self):

        try:

            self.detector.close()

        except Exception:

            pass