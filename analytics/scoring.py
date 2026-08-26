"""
analytics/scoring.py
====================
DriverStateMonitor - the "safety brain".

It consumes the per-frame merged state (drowsiness metrics + AlertManager
fields) and derives the higher-level intelligence that turns a drowsiness
detector into a driver-monitoring system:

    * Driver Attention Score   (Feature 6)   0-100, smoothed, from gaze/visibility
    * Distraction Timer        (Feature 7)   continuous look-away seconds + alert
    * Real-time Safety Score    (Feature 8)   0-100, from drowsiness+attention+face...
    * Driver Risk Level        (Feature 9)   LOW / MEDIUM / HIGH with hysteresis
    * Fatigue Trend            (Feature 15)  STABLE / INCREASING / DECREASING
    * Attention Distribution   (Feature 14)  % forward / left / right / down / none
    * Break Recommendation     (Feature 12)  from real session event history
    * Session Analytics        (Feature 16)  summary produced on stop

Everything is derived from *actual* detection events (never random) and the
clock is injectable (`now=`) so it is fully unit-testable without a webcam.
"""

import time
from collections import deque

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"

TREND_STABLE = "STABLE"
TREND_UP = "INCREASING"
TREND_DOWN = "DECREASING"


class DriverStateMonitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    # ------------------------------------------------------------------ #
    def reset(self):
        cfg = self.cfg
        self._started = None
        self._last_ts = None

        # smoothed scores start "fresh & alert"
        self.attention_score = 100.0
        self.safety_score = 100.0

        # distraction timer
        self._distract_active = False
        self._distract_start = 0.0
        self._distract_last = 0.0
        self.distraction_duration = 0.0

        # risk hysteresis
        self._risk = RISK_LOW
        self._risk_candidate = RISK_LOW
        self._risk_candidate_since = None
        self._high_risk_time = 0.0

        # fatigue trend history: (ts, drowsiness_score)
        self._trend = deque()

        # attention distribution (accumulated seconds)
        self._dist = {"forward": 0.0, "left": 0.0, "right": 0.0,
                      "down": 0.0, "none": 0.0}

        # session counters
        self._att_sum = 0.0
        self._att_n = 0
        self.total_distraction_time = 0.0
        self._left_episodes = 0
        self._right_episodes = 0
        self._covered_episodes = 0
        self._sunglasses_seen = False
        self._max_drowsy_events = 0
        self._max_yawns = 0
        self._prev_side = False
        self._prev_side_dir = None
        self._prev_covered = False

    # ------------------------------------------------------------------ #
    def _raw_dir(self, yaw):
        raw = "right" if yaw > 0 else "left"
        if getattr(self.cfg, "SIDE_LOOK_INVERT", False):
            raw = "left" if raw == "right" else "right"
        return raw

    def update(self, state, now=None):
        """Advance one frame. Returns a dict of NEW fields to merge in."""
        now = time.time() if now is None else now
        cfg = self.cfg
        if self._started is None:
            self._started = now
        dt = 0.0 if self._last_ts is None else max(0.0, min(now - self._last_ts, 1.0))
        self._last_ts = now

        face = bool(state.get("face_detected", state.get("found")))
        yaw = float(state.get("yaw", 0.0) or 0.0)
        pitch = float(state.get("pitch", 0.0) or 0.0)
        nodding = bool(state.get("nodding"))
        eyes_closed = bool(state.get("eyes_closed"))
        yawning = bool(state.get("yawning"))
        drowsiness_score = float(state.get("drowsiness_score",
                                           state.get("score", 0.0)) or 0.0)
        coverage = state.get("face_coverage")
        face_covered = bool(state.get("face_covered"))
        sunglasses = bool(state.get("sunglasses_detected"))
        side_look = bool(state.get("side_look"))
        side_dir = state.get("side_direction")

        looking_away = face and abs(yaw) >= cfg.SIDE_YAW_THRESHOLD

        # ---- gaze category (for distribution + attention target) --------
        if not face:
            category = "none"
        elif nodding or abs(pitch) >= cfg.HEAD_PITCH_THRESHOLD:
            category = "down"
        elif looking_away:
            category = self._raw_dir(yaw)
        else:
            category = "forward"
        self._dist[category] += dt

        # ---- distraction timer (Feature 7) ------------------------------
        if looking_away:
            if not self._distract_active:
                self._distract_active = True
                self._distract_start = now
            self._distract_last = now
            self.distraction_duration = now - self._distract_start
            self.total_distraction_time += dt
        else:
            if self._distract_active and (now - self._distract_last) > cfg.SIDE_LOOK_EXIT_GRACE:
                self._distract_active = False
                self.distraction_duration = 0.0
        distraction_alert = (self._distract_active and
                             self.distraction_duration >= cfg.DISTRACTION_ALERT_THRESHOLD)

        # ---- attention score (Feature 6) --------------------------------
        if category == "none":
            att_target = cfg.ATTENTION_TARGET_NOFACE
        elif category == "down":
            att_target = cfg.ATTENTION_TARGET_DOWN
        elif category in ("left", "right"):
            if self.distraction_duration >= 1.0 or side_look:
                # sustained side-look: sink further the longer it lasts
                att_target = max(15.0, cfg.ATTENTION_TARGET_SIDE
                                 - self.distraction_duration * 6.0)
            else:
                att_target = cfg.ATTENTION_TARGET_GLANCE
        else:
            att_target = cfg.ATTENTION_TARGET_FORWARD
        # eyes shut = not watching the road, whatever the head angle
        if face and eyes_closed:
            att_target = min(att_target, 50.0)
        self.attention_score += cfg.ATTENTION_SMOOTHING * (att_target - self.attention_score)
        self.attention_score = max(0.0, min(100.0, self.attention_score))

        # ---- safety score (Feature 8) -----------------------------------
        pen = cfg.SAFETY_PENALTY_DROWSY * (drowsiness_score / 100.0)
        pen += cfg.SAFETY_PENALTY_ATTENTION * (1.0 - self.attention_score / 100.0)
        if face_covered or coverage in ("covered", "none"):
            pen += cfg.SAFETY_PENALTY_FACE
        if yawning:
            pen += cfg.SAFETY_PENALTY_YAWN
        if sunglasses:
            pen += cfg.SAFETY_PENALTY_SUNGLASSES
        safe_target = max(0.0, min(100.0, 100.0 - pen))
        self.safety_score += cfg.SAFETY_SMOOTHING * (safe_target - self.safety_score)
        self.safety_score = max(0.0, min(100.0, self.safety_score))

        # ---- risk level with hysteresis (Feature 9) ---------------------
        band = self._band(self.safety_score)
        if band == self._risk:
            self._risk_candidate = band
            self._risk_candidate_since = None
        else:
            if band != self._risk_candidate:
                self._risk_candidate = band
                self._risk_candidate_since = now
            elif self._risk_candidate_since is not None and \
                    (now - self._risk_candidate_since) >= cfg.RISK_HYSTERESIS:
                self._risk = band
                self._risk_candidate_since = None
        if self._risk == RISK_HIGH:
            self._high_risk_time += dt
        else:
            self._high_risk_time = 0.0

        # ---- fatigue trend (Feature 15) ---------------------------------
        self._trend.append((now, drowsiness_score))
        cutoff = now - cfg.FATIGUE_WINDOW
        while self._trend and self._trend[0][0] < cutoff:
            self._trend.popleft()
        fatigue_trend = self._compute_trend(now)

        # ---- session counters -------------------------------------------
        self._att_sum += self.attention_score
        self._att_n += 1
        self._max_drowsy_events = max(self._max_drowsy_events,
                                      int(state.get("drowsy_events", 0) or 0))
        self._max_yawns = max(self._max_yawns, int(state.get("yawn_count", 0) or 0))
        if sunglasses:
            self._sunglasses_seen = True
        # count a side-look episode on its rising edge / direction change
        if side_look and (not self._prev_side or side_dir != self._prev_side_dir):
            if side_dir == "left":
                self._left_episodes += 1
            elif side_dir == "right":
                self._right_episodes += 1
        self._prev_side = side_look
        self._prev_side_dir = side_dir if side_look else None
        # count a face-covered episode on its rising edge
        if face_covered and not self._prev_covered:
            self._covered_episodes += 1
        self._prev_covered = face_covered

        # ---- break recommendation (Feature 12) --------------------------
        break_needed = (
            self._max_drowsy_events >= cfg.BREAK_DROWSY_EVENTS
            or self._max_yawns >= cfg.BREAK_YAWN_COUNT
            or self._high_risk_time >= cfg.BREAK_HIGH_RISK_SUSTAIN
            or (fatigue_trend == TREND_UP and self._risk != RISK_LOW)
        )

        total = sum(self._dist.values()) or 1.0
        distribution = {k: round(100.0 * v / total, 1) for k, v in self._dist.items()}

        return {
            "attention_score": round(self.attention_score, 1),
            "attention_band": self._att_band(self.attention_score),
            "safety_score": round(self.safety_score, 1),
            "risk_level": self._risk,
            "distraction_active": self._distract_active,
            "distraction_duration": round(self.distraction_duration, 1),
            "distraction_alert": distraction_alert,
            "fatigue_trend": fatigue_trend,
            "attention_distribution": distribution,
            "break_recommended": bool(break_needed),
            "break_text": ("HIGH FATIGUE DETECTED - TAKE A SHORT BREAK"
                           if break_needed else None),
            "session_seconds": round(now - self._started, 1),
        }

    # ------------------------------------------------------------------ #
    def _band(self, safety):
        if safety >= self.cfg.RISK_LOW_MIN:
            return RISK_LOW
        if safety >= self.cfg.RISK_MED_MIN:
            return RISK_MEDIUM
        return RISK_HIGH

    def _att_band(self, att):
        if att >= self.cfg.ATTENTION_GREEN_MIN:
            return "green"
        if att >= self.cfg.ATTENTION_YELLOW_MIN:
            return "yellow"
        return "red"

    def _compute_trend(self, now):
        pts = list(self._trend)
        if len(pts) < 8:
            return TREND_STABLE
        span = pts[-1][0] - pts[0][0]
        if span < self.cfg.FATIGUE_WINDOW * 0.4:
            return TREND_STABLE
        mid = pts[0][0] + span / 2.0
        old = [v for (t, v) in pts if t <= mid]
        new = [v for (t, v) in pts if t > mid]
        if not old or not new:
            return TREND_STABLE
        delta = (sum(new) / len(new)) - (sum(old) / len(old))
        if delta >= self.cfg.FATIGUE_DELTA:
            return TREND_UP
        if delta <= -self.cfg.FATIGUE_DELTA:
            return TREND_DOWN
        return TREND_STABLE

    # ------------------------------------------------------------------ #
    def session_summary(self, now=None):
        """End-of-session analytics (Feature 16)."""
        now = time.time() if now is None else now
        duration = 0.0 if self._started is None else max(0.0, now - self._started)
        total = sum(self._dist.values()) or 1.0
        distribution = {k: round(100.0 * v / total, 1) for k, v in self._dist.items()}
        avg_att = round(self._att_sum / self._att_n, 1) if self._att_n else 0.0
        return {
            "duration_seconds": round(duration, 1),
            "duration_hms": _hms(duration),
            "drowsiness_events": self._max_drowsy_events,
            "yawn_count": self._max_yawns,
            "left_look_events": self._left_episodes,
            "right_look_events": self._right_episodes,
            "face_covered_events": self._covered_episodes,
            "sunglasses_detected": self._sunglasses_seen,
            "total_distraction_time": round(self.total_distraction_time, 1),
            "total_distraction_hms": _hms(self.total_distraction_time),
            "avg_attention_score": avg_att,
            "final_safety_score": round(self.safety_score, 1),
            "final_risk_level": self._risk,
            "attention_distribution": distribution,
        }


def _hms(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
