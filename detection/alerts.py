"""
detection/alerts.py
====================
Centralized alerting for the driver-monitoring features.

    SideLookDetector    - yaw-based left/right looking with a duration
                          debounce + brief-glance grace.
    FaceCoverageDetector- 4-state face visibility machine
                          (clear / partial / covered / none) with timeouts.
    AlertManager        - single source of truth. Resolves PRIORITY so only
                          ONE audible alert is active, runs the escalating
                          alarm ladder (L1 visual -> L2 audible -> L3 critical
                          -> L4 mobile), selects the voice phrase, manages
                          ALERT_START / ALERT_RESET transitions & cooldown,
                          and emits structured log events.

Alert priority (highest first) - Feature 21:
    1. CRITICAL_DROWSINESS                (critical_alarm.wav)
    2. FACE_COVERED / FACE_NOT_VISIBLE    (face_covered_alarm.wav)
    3. SEVERE_DISTRACTION_LEFT/RIGHT      (side_look_alarm.wav)
    4. DROWSINESS                          (drowsiness_alarm.wav -> critical when escalated)
    5. SIDE_LOOK_LEFT/RIGHT               (side_look_alarm.wav)
    6. YAWNING                             (visual only - no sound)
    7. SUNGLASSES                          (status only - no sound)

Drowsiness and side-looking always use *different* sounds. Only ONE audible
alert plays at a time. Time is injectable (`now`) for deterministic tests.
"""

import time


# ------------------------------------------------------------------------- #
#  side-way looking
# ------------------------------------------------------------------------- #
class SideLookDetector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self._dir = None            # current continuous side direction
        self._since = None          # when the current side-look started
        self._last_side_ts = 0.0    # last frame that was beyond threshold
        self._confirmed = False

    def update(self, found, yaw, now=None):
        """Return (attention, side_look, direction)."""
        now = time.time() if now is None else now
        cfg = self.cfg

        if not found:
            self.reset()
            return "no_face", False, None

        beyond = abs(yaw) >= cfg.SIDE_YAW_THRESHOLD
        if beyond:
            raw = "right" if yaw > 0 else "left"
            if cfg.SIDE_LOOK_INVERT:
                raw = "left" if raw == "right" else "right"
            if self._dir != raw:
                # new (or changed) side direction -> restart timer
                self._dir = raw
                self._since = now
                self._confirmed = False
            self._last_side_ts = now
            if self._since is not None and (now - self._since) >= cfg.SIDE_LOOK_DURATION:
                self._confirmed = True
        else:
            # facing forward-ish: tolerate a brief glance before resetting
            if self._dir is not None and (now - self._last_side_ts) > cfg.SIDE_LOOK_EXIT_GRACE:
                self.reset()

        if self._confirmed and self._dir is not None:
            return self._dir, True, self._dir
        return "forward", False, None


# ------------------------------------------------------------------------- #
#  face coverage / obstruction
# ------------------------------------------------------------------------- #
class FaceCoverageDetector:
    """
    4-state visibility machine. `near_edge` (bool) lets the caller signal
    that the detected face bbox is drifting out of frame -> "partial".
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        from collections import deque
        self._hist = deque(maxlen=self.cfg.FACE_WINDOW)
        self._last_seen = None
        self._lost_since = None

    def update(self, found, now=None, near_edge=False):
        """Return (coverage, covered_alert, kind)."""
        now = time.time() if now is None else now
        cfg = self.cfg
        self._hist.append(1 if found else 0)
        ratio = sum(self._hist) / len(self._hist) if self._hist else 0.0

        if found:
            self._last_seen = now
            self._lost_since = None
            if ratio >= cfg.FACE_PARTIAL_RATIO and not near_edge:
                return "clear", False, None
            # visible but flickering recently, or face partly out of frame
            return "partial", False, None

        # ---- not found this frame ----
        if self._lost_since is None:
            self._lost_since = now
        elapsed = now - self._lost_since
        recent = (self._last_seen is not None) and (now - self._last_seen <= cfg.FACE_RECENT_SEEN)

        if recent:
            # face was just here -> something is likely covering it
            if elapsed >= cfg.FACE_COVERED_TIMEOUT:
                return "covered", True, "FACE_COVERED"
            return "partial", False, None
        else:
            # no face in view for a while (or never seen)
            if elapsed >= cfg.FACE_MISSING_TIMEOUT:
                return "none", True, "FACE_NOT_VISIBLE"
            return "partial", False, None


# ------------------------------------------------------------------------- #
#  Central alert manager
# ------------------------------------------------------------------------- #
DROWSY_LEVEL = "DROWSY"

_SEVERITY = {
    "CRITICAL_DROWSINESS": "high",
    "FACE_COVERED": "high",
    "FACE_NOT_VISIBLE": "high",
    "SEVERE_DISTRACTION_LEFT": "high",
    "SEVERE_DISTRACTION_RIGHT": "high",
    "DROWSINESS": "high",
    "SIDE_LOOK_LEFT": "medium",
    "SIDE_LOOK_RIGHT": "medium",
    "YAWNING": "medium",
}

_LABEL = {
    "CRITICAL_DROWSINESS": "CRITICAL - DRIVER DROWSY",
    "FACE_COVERED": "FACE COVERED",
    "FACE_NOT_VISIBLE": "FACE NOT VISIBLE",
    "SEVERE_DISTRACTION_LEFT": "SEVERE DISTRACTION - LOOK FORWARD",
    "SEVERE_DISTRACTION_RIGHT": "SEVERE DISTRACTION - LOOK FORWARD",
    "DROWSINESS": "DROWSINESS ALERT",
    "SIDE_LOOK_LEFT": "LOOKING LEFT - ATTENTION",
    "SIDE_LOOK_RIGHT": "LOOKING RIGHT - ATTENTION",
    "YAWNING": "YAWNING",
}

# base escalation level per alert type (never "jumps to the top"):
#   1 = visual only, 2 = audible, 3 = critical/louder, (4 = +mobile, by time)
_BASE_LEVEL = {
    "YAWNING": 1,
    "SIDE_LOOK_LEFT": 2, "SIDE_LOOK_RIGHT": 2,
    "DROWSINESS": 2,
    "FACE_COVERED": 2, "FACE_NOT_VISIBLE": 2,
    "SEVERE_DISTRACTION_LEFT": 3, "SEVERE_DISTRACTION_RIGHT": 3,
    "CRITICAL_DROWSINESS": 3,
}


class AlertManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.side = SideLookDetector(cfg)
        self.face = FaceCoverageDetector(cfg)
        self.reset()

    def reset(self):
        self.side.reset()
        self.face.reset()
        self._active_type = None
        self._active_since = 0.0
        self._sunglasses_on = False
        self._drowsy_since = None
        self._side_since = None

    # ------------------------------------------------------------------ #
    def _sound_for(self, alert_type, level):
        cfg = self.cfg
        if alert_type == "CRITICAL_DROWSINESS":
            return cfg.CRITICAL_ALARM_FILE
        if alert_type in ("FACE_COVERED", "FACE_NOT_VISIBLE"):
            return cfg.FACE_COVERED_ALARM_FILE
        if alert_type in ("SEVERE_DISTRACTION_LEFT", "SEVERE_DISTRACTION_RIGHT",
                          "SIDE_LOOK_LEFT", "SIDE_LOOK_RIGHT"):
            return cfg.SIDE_LOOK_ALARM_FILE
        if alert_type == "DROWSINESS":
            # escalate a sustained ordinary drowsiness to the critical sound
            return cfg.CRITICAL_ALARM_FILE if level >= 3 else cfg.DROWSINESS_ALARM_FILE
        return None  # YAWNING / SUNGLASSES -> visual/status only

    def _escalation(self, alert_type, duration):
        cfg = self.cfg
        lvl = _BASE_LEVEL.get(alert_type, 1)
        if lvl >= 2 and duration >= cfg.ESCALATE_CRITICAL_AFTER and lvl < 3:
            lvl = 3
        if lvl >= 2 and duration >= cfg.ESCALATE_NOTIFY_AFTER:
            lvl = 4
        return lvl

    def _voice(self, alert_type):
        cfg = self.cfg
        if alert_type in ("CRITICAL_DROWSINESS", "DROWSINESS"):
            return "drowsy", cfg.VOICE_TEXT_DROWSY
        if alert_type in ("SEVERE_DISTRACTION_LEFT", "SEVERE_DISTRACTION_RIGHT",
                          "SIDE_LOOK_LEFT", "SIDE_LOOK_RIGHT"):
            return "side", cfg.VOICE_TEXT_SIDE
        if alert_type in ("FACE_COVERED", "FACE_NOT_VISIBLE"):
            return "face", cfg.VOICE_TEXT_FACE
        return None, None

    # ------------------------------------------------------------------ #
    def update(self, metrics, scorer_state, sunglasses, near_edge=False, now=None):
        """
        Fuse everything and pick the single active alert.

        metrics       : LandmarkDetector.analyze() output
        scorer_state  : DrowsinessScorer.update() output (unchanged upstream)
        sunglasses    : SunglassesDetector.analyze() output
        near_edge     : bool, face bbox near frame border
        Returns a dict of NEW fields to merge into the state (+ 'events').
        """
        now = time.time() if now is None else now
        cfg = self.cfg
        found = bool(metrics.get("found"))
        yaw = scorer_state.get("yaw", 0.0) if found else 0.0
        events = []

        # ---- run sub-detectors ----
        attention, side_look, side_dir = self.side.update(found, yaw, now)
        coverage, covered_alert, covered_kind = self.face.update(found, now, near_edge)

        drowsy = scorer_state.get("level") == DROWSY_LEVEL
        yawning = bool(scorer_state.get("yawning"))
        sg_detected = bool(sunglasses.get("detected"))

        # ---- drowsiness -> is it CRITICAL? (sustained / micro-sleep) ----
        if drowsy:
            if self._drowsy_since is None:
                self._drowsy_since = now
        else:
            self._drowsy_since = None
        drowsy_dur = (now - self._drowsy_since) if self._drowsy_since is not None else 0.0
        eye_frames = int(scorer_state.get("eye_closed_frames", 0) or 0)
        drowsy_critical = drowsy and (
            drowsy_dur >= cfg.CRITICAL_DROWSINESS_DURATION
            or bool(scorer_state.get("micro_sleep"))
            or eye_frames >= 2 * cfg.EAR_CONSEC_FRAMES
        )

        # ---- side-look -> is it a SEVERE distraction? (sustained) -------
        if side_look:
            if self._side_since is None:
                self._side_since = now
        else:
            self._side_since = None
        side_dur = (now - self._side_since) if self._side_since is not None else 0.0
        severe_distraction = side_look and side_dur >= cfg.CRITICAL_DISTRACTION_DURATION

        # ---- resolve priority -> single active alert (Feature 21) -------
        alert_type = None
        if drowsy_critical:
            alert_type = "CRITICAL_DROWSINESS"
        elif covered_alert:
            alert_type = covered_kind                       # FACE_COVERED / FACE_NOT_VISIBLE
        elif severe_distraction:
            alert_type = "SEVERE_DISTRACTION_LEFT" if side_dir == "left" else "SEVERE_DISTRACTION_RIGHT"
        elif drowsy:
            alert_type = "DROWSINESS"
        elif side_look:
            alert_type = "SIDE_LOOK_LEFT" if side_dir == "left" else "SIDE_LOOK_RIGHT"
        elif yawning:
            alert_type = "YAWNING"

        # ---- transitions (ALERT_START / ALERT_RESET) -------------------
        if alert_type != self._active_type:
            # emit an "ended" marker when a drowsiness episode clears
            if self._active_type in ("DROWSINESS", "CRITICAL_DROWSINESS"):
                events.append({
                    "type": "DROWSINESS_ENDED", "severity": "low",
                    "message": "Drowsiness alert cleared",
                    "duration": round(now - self._active_since, 1),
                })
            if alert_type is not None:
                events.append({
                    "type": alert_type,
                    "severity": _SEVERITY.get(alert_type, "medium"),
                    "message": _LABEL.get(alert_type, alert_type) + " (alert started)",
                })
            self._active_type = alert_type
            self._active_since = now

        # ---- escalation ladder + single audible sound ------------------
        duration = (now - self._active_since) if alert_type else 0.0
        level = self._escalation(alert_type, duration) if alert_type else 0
        audible = level >= 2
        sound = self._sound_for(alert_type, level) if (alert_type and audible) else None

        # ---- voice phrase (spoken in-browser, with cooldown) -----------
        voice_key, voice_text = (None, None)
        if alert_type and audible:
            voice_key, voice_text = self._voice(alert_type)

        # ---- sunglasses status-change event (no sound) ----------------
        if sg_detected != self._sunglasses_on:
            self._sunglasses_on = sg_detected
            events.append({
                "type": "SUNGLASSES",
                "severity": "low",
                "message": "Sunglasses detected" if sg_detected else "Sunglasses removed",
            })

        return {
            "attention": attention,                 # forward / left / right / no_face
            "side_look": side_look,
            "side_direction": side_dir,             # left / right / None
            "severe_distraction": bool(severe_distraction),
            "sunglasses_detected": sg_detected,
            "sunglasses_confidence": sunglasses.get("confidence", 0.0),
            "face_detected": found,
            "face_coverage": coverage,              # clear / partial / covered / none
            "face_covered": bool(covered_alert),
            "drowsiness": bool(drowsy),
            "drowsiness_critical": bool(drowsy_critical),
            "drowsiness_score": scorer_state.get("score", 0.0),
            "yawning": yawning,
            "alert_type": alert_type,               # None or a key above
            "alert_label": _LABEL.get(alert_type) if alert_type else None,
            "alert_severity": _SEVERITY.get(alert_type) if alert_type else None,
            "alert_sound": sound,                   # single active .wav or None
            "alert_active": alert_type is not None,
            "alert_since": self._active_since if alert_type else None,
            "escalation_level": level,              # 0..4
            "notify_ready": level >= 4,             # L4 -> mobile push candidate
            "voice_text": voice_text,
            "voice_key": voice_key,
            "events": events,
        }
