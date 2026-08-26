"""
detection/drowsiness.py
=======================
The "brain" of the system. It fuses every signal produced by the landmark
detector (and, optionally, the CNN eye-state classifier) into:

    * a rolling **PERCLOS** value (percentage of eye closure),
    * blink / yawn / head-nod counters,
    * a single **composite drowsiness score** (0-100),
    * a discrete **level**  (ALERT / WARNING / DROWSY),
    * discrete **events** worth logging & alarming on.

Two classes:
    DrowsinessScorer   - pure state machine over per-frame metrics.
    DrowsinessPipeline - ties LandmarkDetector + CNN + scorer together and
                         draws the annotated overlay used by the dashboard.
"""

import time
from collections import deque

from config import config
from .landmarks import LandmarkDetector
from .sunglasses import SunglassesDetector
from .alerts import AlertManager
from analytics import DriverStateMonitor


LEVEL_ALERT = "ALERT"
LEVEL_WARNING = "WARNING"
LEVEL_DROWSY = "DROWSY"


class DrowsinessScorer:
    """Frame-by-frame state machine. Call :meth:`update` once per frame."""

    def __init__(self, cfg=config):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.frame_idx = 0
        self.eye_closed_frames = 0
        self.yawn_frames = 0
        self.head_frames = 0
        self.blink_count = 0
        self.yawn_count = 0
        self.nod_count = 0
        self.drowsy_events = 0
        self._eye_history = deque(maxlen=self.cfg.PERCLOS_WINDOW)
        self._in_blink = False
        self._blink_frames = 0
        self._yawn_active = False
        self._nod_active = False
        self._last_alarm_ts = 0.0

    # ------------------------------------------------------------------ #
    def update(self, metrics, cnn_closed_prob=None):
        """
        Advance the state machine with one frame of `metrics`
        (the dict returned by LandmarkDetector.analyze).

        Returns a rich `state` dict ready to be serialized to the UI.
        """
        self.frame_idx += 1
        cfg = self.cfg
        events = []

        if not metrics.get("found"):
            # No face -> treat as "eyes not visible". Let counters decay.
            self._eye_history.append(0)
            self.eye_closed_frames = max(0, self.eye_closed_frames - 1)
            return self._build_state(
                found=False, ear=0.0, mar=0.0, pitch=0.0, yaw=0.0, roll=0.0,
                eyes_closed=False, cnn_closed_prob=cnn_closed_prob, events=events,
            )

        ear = metrics["ear"]
        mar = metrics["mar"]
        pitch = metrics["pitch"]
        yaw = metrics["yaw"]
        roll = metrics["roll"]

        # ---- Eye closure: fuse EAR with optional CNN --------------------
        ear_closed = ear < cfg.EAR_THRESHOLD
        if cnn_closed_prob is not None:
            cnn_closed = cnn_closed_prob >= cfg.CNN_CLOSED_THRESHOLD
            # Require agreement-ish: closed if CNN says so, or EAR is low.
            eyes_closed = cnn_closed or ear_closed
        else:
            eyes_closed = ear_closed

        self._eye_history.append(1 if eyes_closed else 0)

        # ---- Blink vs micro-sleep ---------------------------------------
        if eyes_closed:
            self.eye_closed_frames += 1
            self._blink_frames += 1
            self._in_blink = True
        else:
            if self._in_blink:
                # Eye just re-opened: was it a blink or a long closure?
                if cfg.BLINK_MIN_FRAMES <= self._blink_frames <= cfg.BLINK_MAX_FRAMES:
                    self.blink_count += 1
                self._blink_frames = 0
                self._in_blink = False
            self.eye_closed_frames = 0

        eye_micro_sleep = self.eye_closed_frames >= cfg.EAR_CONSEC_FRAMES
        if eye_micro_sleep and self.eye_closed_frames == cfg.EAR_CONSEC_FRAMES:
            events.append(_ev("EYE_CLOSURE", "high",
                              "Prolonged eye closure detected (micro-sleep)"))

        # ---- PERCLOS ----------------------------------------------------
        perclos = (sum(self._eye_history) / len(self._eye_history)
                   if self._eye_history else 0.0)
        if perclos >= cfg.PERCLOS_ALARM and len(self._eye_history) >= cfg.PERCLOS_WINDOW // 2:
            # only log once per crossing
            if not getattr(self, "_perclos_high", False):
                events.append(_ev("PERCLOS", "high",
                                  f"PERCLOS {perclos*100:.0f}% exceeds alarm level"))
                self._perclos_high = True
        else:
            self._perclos_high = False

        # ---- Yawn -------------------------------------------------------
        if mar >= cfg.MAR_THRESHOLD:
            self.yawn_frames += 1
        else:
            if self._yawn_active:
                self._yawn_active = False
            self.yawn_frames = 0
        yawning = self.yawn_frames >= cfg.MAR_CONSEC_FRAMES
        if yawning and not self._yawn_active:
            self.yawn_count += 1
            self._yawn_active = True
            events.append(_ev("YAWN", "medium", "Yawning detected"))

        # ---- Head nod / distraction ------------------------------------
        head_down = abs(pitch) >= cfg.HEAD_PITCH_THRESHOLD
        looking_away = abs(yaw) >= cfg.HEAD_YAW_THRESHOLD
        if head_down:
            self.head_frames += 1
        else:
            if self._nod_active:
                self._nod_active = False
            self.head_frames = 0
        nodding = self.head_frames >= cfg.HEAD_CONSEC_FRAMES
        if nodding and not self._nod_active:
            self.nod_count += 1
            self._nod_active = True
            events.append(_ev("HEAD_NOD", "high", "Head nodding / dropping detected"))

        # ---- Composite score -------------------------------------------
        eye_comp = min(self.eye_closed_frames / max(cfg.EAR_CONSEC_FRAMES, 1), 1.0)
        perclos_comp = min(perclos / max(cfg.PERCLOS_ALARM, 1e-6), 1.0)
        yawn_comp = min(self.yawn_frames / max(cfg.MAR_CONSEC_FRAMES, 1), 1.0)
        head_comp = min(self.head_frames / max(cfg.HEAD_CONSEC_FRAMES, 1), 1.0)
        score = (cfg.W_EYE * eye_comp
                 + cfg.W_PERCLOS * perclos_comp
                 + cfg.W_YAWN * yawn_comp
                 + cfg.W_HEAD * head_comp)
        score = float(max(0.0, min(100.0, score)))

        level = self._level_for(score)
        if level == LEVEL_DROWSY:
            # count a distinct drowsy episode on entry
            if getattr(self, "_last_level", LEVEL_ALERT) != LEVEL_DROWSY:
                self.drowsy_events += 1
        self._last_level = level

        return self._build_state(
            found=True, ear=ear, mar=mar, pitch=pitch, yaw=yaw, roll=roll,
            eyes_closed=eyes_closed, cnn_closed_prob=cnn_closed_prob,
            perclos=perclos, score=score, level=level,
            yawning=yawning, nodding=nodding, looking_away=looking_away,
            micro_sleep=eye_micro_sleep, events=events,
        )

    # ------------------------------------------------------------------ #
    def _level_for(self, score):
        if score >= self.cfg.SCORE_ALARM:
            return LEVEL_DROWSY
        if score >= self.cfg.SCORE_WARNING:
            return LEVEL_WARNING
        return LEVEL_ALERT

    def _build_state(self, found, ear, mar, pitch, yaw, roll, eyes_closed,
                     cnn_closed_prob, events, perclos=0.0, score=0.0,
                     level=LEVEL_ALERT, yawning=False, nodding=False,
                     looking_away=False, micro_sleep=False):
        # Alarm fires on DROWSY with a cooldown so it doesn't machine-gun.
        alarm = False
        if level == LEVEL_DROWSY and self.cfg.ALARM_ENABLED:
            now = time.time()
            if now - self._last_alarm_ts >= self.cfg.ALARM_COOLDOWN:
                alarm = True
                self._last_alarm_ts = now

        status_text = {
            LEVEL_ALERT: "Alert",
            LEVEL_WARNING: "Warning - signs of fatigue",
            LEVEL_DROWSY: "DROWSY - WAKE UP!",
        }[level]
        if not found:
            status_text = "No face detected"

        return {
            "found": found,
            "ear": round(ear, 4),
            "mar": round(mar, 4),
            "pitch": round(pitch, 2),
            "yaw": round(yaw, 2),
            "roll": round(roll, 2),
            "eyes_closed": eyes_closed,
            "cnn_closed_prob": (round(cnn_closed_prob, 3)
                                if cnn_closed_prob is not None else None),
            "eye_closed_frames": self.eye_closed_frames,
            "perclos": round(perclos, 4),
            "blink_count": self.blink_count,
            "yawn_count": self.yawn_count,
            "nod_count": self.nod_count,
            "drowsy_events": self.drowsy_events,
            "micro_sleep": micro_sleep,
            "yawning": yawning,
            "nodding": nodding,
            "looking_away": looking_away,
            "score": round(score, 1),
            "level": level,
            "status_text": status_text,
            "alarm": alarm,
            "events": events,
            "frame_idx": self.frame_idx,
            "ts": time.time(),
        }


def _ev(etype, severity, message):
    return {"type": etype, "severity": severity, "message": message}


# --------------------------------------------------------------------------- #
#  Full pipeline: landmarks + CNN + scorer + overlay drawing
# --------------------------------------------------------------------------- #
class DrowsinessPipeline:
    """
    End-to-end processor: give it a BGR frame, get back an annotated BGR
    frame and the drowsiness `state` dict.
    """

    def __init__(self, cfg=config, use_cnn=None):
        self.cfg = cfg
        self.detector = LandmarkDetector()
        self.scorer = DrowsinessScorer(cfg)
        # Additive real-time monitors (Features 2-4). These never alter the
        # DrowsinessScorer above - they only add fields to the state dict.
        self.sunglasses = SunglassesDetector(cfg)
        self.alerts = AlertManager(cfg)
        # Safety "brain" (Features 6-16): attention/safety scoring, risk level,
        # distraction timer, fatigue trend, break advice + session analytics.
        # Runs AFTER the alert manager and only merges NEW fields.
        self.monitor = DriverStateMonitor(cfg)
        self._prev_distraction_alert = False
        self._prev_break = False
        self.classifier = None

        use_cnn = cfg.USE_CNN if use_cnn is None else use_cnn
        if use_cnn:
            try:
                from .cnn_model import EyeStateClassifier
                clf = EyeStateClassifier(cfg.CNN_MODEL_PATH, cfg.CNN_INPUT_SIZE)
                self.classifier = clf if clf.available else None
            except Exception as exc:                     # pragma: no cover
                print(f"[DrowsinessPipeline] CNN disabled: {exc}")
                self.classifier = None

    @property
    def cnn_active(self):
        return self.classifier is not None and self.classifier.available

    def reset(self):
        self.scorer.reset()
        self.sunglasses.reset()
        self.alerts.reset()
        self.monitor.reset()
        self._prev_distraction_alert = False
        self._prev_break = False

    def session_summary(self):
        """End-of-session analytics (Feature 16). Safe to call any time."""
        return self.monitor.session_summary()

    # ------------------------------------------------------------------ #
    def process_frame(self, frame_bgr, draw=True):
        metrics = self.detector.analyze(frame_bgr)

        cnn_prob = None
        if self.cnn_active and metrics.get("found"):
            left = self.detector.eye_crop(frame_bgr, metrics["left_eye_pts"])
            right = self.detector.eye_crop(frame_bgr, metrics["right_eye_pts"])
            cnn_prob = self.classifier.predict_pair(left, right)

        state = self.scorer.update(metrics, cnn_closed_prob=cnn_prob)

        # ---- additive monitors: sunglasses + centralized alert manager ----
        # (Features 2 side-look, 3 sunglasses, 4 face-coverage). The scorer
        # state above is left intact; we only merge NEW keys + extra events.
        sg = self.sunglasses.analyze(frame_bgr, metrics)
        near_edge = False
        if metrics.get("found"):
            near_edge = self._near_edge(metrics, frame_bgr.shape[1],
                                        frame_bgr.shape[0])
        alert_fields = self.alerts.update(metrics, state, sg, near_edge=near_edge)
        alert_events = alert_fields.pop("events", [])
        state["events"] = list(state.get("events", [])) + alert_events
        state.update(alert_fields)
        state["sunglasses"] = sg   # raw detail: confidence / dark_ratio / eye_std

        # ---- safety brain: attention/safety/risk/distraction/fatigue ------
        # (Features 6-16). Runs on the *merged* state so it can read side_look,
        # face_coverage, drowsiness_score, etc. Only NEW keys are merged back.
        score_fields = self.monitor.update(state)
        state.update(score_fields)

        # rising-edge events (logged once per crossing, never per frame)
        dist_alert = bool(score_fields.get("distraction_alert"))
        if dist_alert and not self._prev_distraction_alert:
            state["events"].append(_ev(
                "ATTENTION_ALERT", "high",
                "Distraction exceeded safe threshold"))
        self._prev_distraction_alert = dist_alert

        brk = bool(score_fields.get("break_recommended"))
        if brk and not self._prev_break:
            state["events"].append(_ev(
                "BREAK_RECOMMENDED", "medium",
                score_fields.get("break_text") or "Break recommended"))
        self._prev_break = brk

        annotated = frame_bgr
        if draw:
            annotated = self._draw(frame_bgr.copy(), metrics, state)
        return annotated, state

    # ------------------------------------------------------------------ #
    def _near_edge(self, metrics, w, h):
        """True if the detected face bbox is drifting out of the frame."""
        face = metrics.get("landmarks")
        margin = self.cfg.FACE_EDGE_MARGIN
        try:
            xs = [lm.x for lm in face.landmark]
            ys = [lm.y for lm in face.landmark]
        except Exception:
            return False
        if not xs or not ys:
            return False
        return (min(xs) < margin or min(ys) < margin
                or max(xs) > 1.0 - margin or max(ys) > 1.0 - margin)

    # ------------------------------------------------------------------ #
    def _draw(self, frame, metrics, state):
        import cv2
        h, w = frame.shape[:2]
        colors = {
            LEVEL_ALERT: (0, 180, 0),
            LEVEL_WARNING: (0, 170, 255),
            LEVEL_DROWSY: (0, 0, 255),
        }
        color = colors.get(state["level"], (0, 180, 0))

        if metrics.get("found"):
            for pts, c in ((metrics["left_eye_pts"], (0, 255, 0)),
                           (metrics["right_eye_pts"], (0, 255, 0)),
                           (metrics["mouth_pts"], (255, 128, 0))):
                for (x, y) in pts:
                    cv2.circle(frame, (int(x), int(y)), 2, c, -1)

        # translucent header bar
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 96), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

        cv2.putText(frame, f"STATUS: {state['status_text']}", (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        cv2.putText(frame,
                    f"EAR {state['ear']:.2f}  MAR {state['mar']:.2f}  "
                    f"Pitch {state['pitch']:.0f}  Score {state['score']:.0f}",
                    (12, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1)
        flags = []
        if state["eyes_closed"]:
            flags.append("EYES CLOSED")
        if state["yawning"]:
            flags.append("YAWNING")
        if state["nodding"]:
            flags.append("HEAD NOD")
        if state["looking_away"]:
            flags.append("LOOKING AWAY")
        if flags:
            cv2.putText(frame, " | ".join(flags), (12, 86),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1)

        # ---- Feature 2/3/4 overlay: right-aligned status chips ----------
        chips = []
        att = state.get("attention")
        if att == "left":
            chips.append(("LOOKING LEFT", (0, 165, 255)))
        elif att == "right":
            chips.append(("LOOKING RIGHT", (0, 165, 255)))
        if state.get("sunglasses_detected"):
            chips.append(("SUNGLASSES", (255, 200, 0)))
        cov = state.get("face_coverage")
        if cov == "covered":
            chips.append(("FACE COVERED", (0, 0, 255)))
        elif cov == "none":
            chips.append(("FACE NOT VISIBLE", (0, 0, 255)))
        elif cov == "partial":
            chips.append(("FACE PARTIAL", (0, 170, 255)))
        cy = 122
        for text, c in chips:
            (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.putText(frame, text, (w - tw - 14, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)
            cy += 28

        # ---- Feature 6-9 overlay: attention / safety / risk / distraction --
        risk = state.get("risk_level", "LOW")
        risk_colors = {"LOW": (0, 180, 0), "MEDIUM": (0, 170, 255),
                       "HIGH": (0, 0, 255)}
        rc = risk_colors.get(risk, (0, 180, 0))
        att_score = state.get("attention_score")
        safe_score = state.get("safety_score")
        if att_score is not None and safe_score is not None:
            hud = frame.copy()
            cv2.rectangle(hud, (0, h - 128), (232, h - 56), (20, 20, 20), -1)
            cv2.addWeighted(hud, 0.5, frame, 0.5, 0, frame)
            cv2.putText(frame,
                        f"Attention {att_score:.0f}  Safety {safe_score:.0f}",
                        (12, h - 104), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (230, 230, 230), 1)
            cv2.putText(frame, f"Risk: {risk}", (12, h - 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, rc, 2)
            if state.get("distraction_active"):
                cv2.putText(frame,
                            f"Distraction {state.get('distraction_duration', 0):.1f}s",
                            (12, h - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (0, 165, 255), 1)

        # ---- single active alert banner (AlertManager decision) --------
        alert_label = state.get("alert_label")
        if alert_label:
            (tw, th), _ = cv2.getTextSize(alert_label,
                                          cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
            bx = (w - tw) // 2
            band = frame.copy()
            cv2.rectangle(band, (0, h - 52), (w, h), (0, 0, 60), -1)
            cv2.addWeighted(band, 0.55, frame, 0.45, 0, frame)
            cv2.putText(frame, alert_label, (bx, h - 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)

        drowsy_border = state["level"] == LEVEL_DROWSY
        if drowsy_border or state.get("alert_active"):
            bc = (0, 0, 255) if (drowsy_border or state.get("face_covered")) \
                else (0, 165, 255)
            cv2.rectangle(frame, (2, 2), (w - 2, h - 2), bc, 6)
        return frame

    def close(self):
        self.detector.close()
