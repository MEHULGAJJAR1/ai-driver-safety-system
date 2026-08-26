"""
detection/alerts.py
===================

Centralized alerting system for Driver Drowsiness Detection.

Handles:
    - Left / right side looking
    - Face coverage / face missing
    - Drowsiness
    - Critical drowsiness
    - Yawning
    - Sunglasses status
    - Alert priority
    - Audio alert selection
    - Browser voice alert
    - Alert events
    - Escalation levels

Designed for:
    - Local webcam
    - Browser/mobile camera
    - Flask
    - Render deployment
"""

import time


# ======================================================================
# SAFE CONFIG HELPERS
# ======================================================================

def cfg_value(cfg, name, default):
    """
    Safely read a configuration value.

    Prevents the alert system from crashing when a config option
    is missing from config.py.
    """
    try:
        return getattr(cfg, name, default)
    except Exception:
        return default


# ======================================================================
# ALERT TYPES
# ======================================================================

CRITICAL_DROWSINESS = "CRITICAL_DROWSINESS"
FACE_COVERED = "FACE_COVERED"
FACE_NOT_VISIBLE = "FACE_NOT_VISIBLE"

SEVERE_LEFT = "SEVERE_DISTRACTION_LEFT"
SEVERE_RIGHT = "SEVERE_DISTRACTION_RIGHT"

DROWSINESS = "DROWSINESS"

SIDE_LEFT = "SIDE_LOOK_LEFT"
SIDE_RIGHT = "SIDE_LOOK_RIGHT"

YAWNING = "YAWNING"


# ======================================================================
# SEVERITY
# ======================================================================

_SEVERITY = {
    CRITICAL_DROWSINESS: "high",

    FACE_COVERED: "high",
    FACE_NOT_VISIBLE: "high",

    SEVERE_LEFT: "high",
    SEVERE_RIGHT: "high",

    DROWSINESS: "high",

    SIDE_LEFT: "medium",
    SIDE_RIGHT: "medium",

    YAWNING: "medium",
}


# ======================================================================
# USER-FRIENDLY LABELS
# ======================================================================

_LABEL = {
    CRITICAL_DROWSINESS:
        "CRITICAL - DRIVER DROWSY",

    FACE_COVERED:
        "FACE COVERED",

    FACE_NOT_VISIBLE:
        "FACE NOT VISIBLE",

    SEVERE_LEFT:
        "SEVERE DISTRACTION - LOOK FORWARD",

    SEVERE_RIGHT:
        "SEVERE DISTRACTION - LOOK FORWARD",

    DROWSINESS:
        "DROWSINESS ALERT",

    SIDE_LEFT:
        "LOOKING LEFT - ATTENTION",

    SIDE_RIGHT:
        "LOOKING RIGHT - ATTENTION",

    YAWNING:
        "YAWNING",
}


# ======================================================================
# BASE ESCALATION LEVEL
# ======================================================================

_BASE_LEVEL = {

    YAWNING: 1,

    SIDE_LEFT: 2,
    SIDE_RIGHT: 2,

    DROWSINESS: 2,

    FACE_COVERED: 2,
    FACE_NOT_VISIBLE: 2,

    SEVERE_LEFT: 3,
    SEVERE_RIGHT: 3,

    CRITICAL_DROWSINESS: 3,
}


# ======================================================================
# SIDE LOOK DETECTOR
# ======================================================================

class SideLookDetector:

    def __init__(self, cfg):

        self.cfg = cfg

        self.threshold = float(
            cfg_value(
                cfg,
                "SIDE_YAW_THRESHOLD",
                25.0
            )
        )

        self.duration = float(
            cfg_value(
                cfg,
                "SIDE_LOOK_DURATION",
                1.0
            )
        )

        self.exit_grace = float(
            cfg_value(
                cfg,
                "SIDE_LOOK_EXIT_GRACE",
                0.6
            )
        )

        self.invert = bool(
            cfg_value(
                cfg,
                "SIDE_LOOK_INVERT",
                False
            )
        )

        self.reset()


    # ------------------------------------------------------------------
    def reset(self):

        self._dir = None

        self._since = None

        self._last_side_ts = 0.0

        self._confirmed = False


    # ------------------------------------------------------------------
    def update(
        self,
        found,
        yaw,
        now=None
    ):

        now = (
            time.time()
            if now is None
            else now
        )

        if not found:

            self.reset()

            return (
                "no_face",
                False,
                None
            )


        try:
            yaw = float(yaw or 0.0)
        except Exception:
            yaw = 0.0


        beyond = (
            abs(yaw)
            >= self.threshold
        )


        # --------------------------------------------------------------
        # SIDE LOOK DETECTED
        # --------------------------------------------------------------

        if beyond:

            raw = (
                "right"
                if yaw > 0
                else "left"
            )

            if self.invert:

                raw = (
                    "left"
                    if raw == "right"
                    else "right"
                )


            # New direction
            if self._dir != raw:

                self._dir = raw

                self._since = now

                self._confirmed = False


            self._last_side_ts = now


            if (
                self._since is not None
                and
                (
                    now - self._since
                    >= self.duration
                )
            ):

                self._confirmed = True


        # --------------------------------------------------------------
        # FORWARD
        # --------------------------------------------------------------

        else:

            if (
                self._dir is not None
                and
                (
                    now - self._last_side_ts
                    > self.exit_grace
                )
            ):

                self.reset()


        if (
            self._confirmed
            and
            self._dir is not None
        ):

            return (
                self._dir,
                True,
                self._dir
            )


        return (
            "forward",
            False,
            None
        )


# ======================================================================
# FACE COVERAGE DETECTOR
# ======================================================================

class FaceCoverageDetector:

    def __init__(self, cfg):

        self.cfg = cfg

        self.window = int(
            cfg_value(
                cfg,
                "FACE_WINDOW",
                10
            )
        )

        self.partial_ratio = float(
            cfg_value(
                cfg,
                "FACE_PARTIAL_RATIO",
                0.5
            )
        )

        self.recent_seen = float(
            cfg_value(
                cfg,
                "FACE_RECENT_SEEN",
                1.0
            )
        )

        self.covered_timeout = float(
            cfg_value(
                cfg,
                "FACE_COVERED_TIMEOUT",
                1.5
            )
        )

        self.missing_timeout = float(
            cfg_value(
                cfg,
                "FACE_MISSING_TIMEOUT",
                3.0
            )
        )

        self.reset()


    # ------------------------------------------------------------------
    def reset(self):

        from collections import deque

        self._hist = deque(
            maxlen=max(
                1,
                self.window
            )
        )

        self._last_seen = None

        self._lost_since = None


    # ------------------------------------------------------------------
    def update(
        self,
        found,
        now=None,
        near_edge=False
    ):

        now = (
            time.time()
            if now is None
            else now
        )


        self._hist.append(
            1 if found else 0
        )


        ratio = (
            sum(self._hist)
            /
            len(self._hist)
            if self._hist
            else 0.0
        )


        # ==============================================================
        # FACE FOUND
        # ==============================================================

        if found:

            self._last_seen = now

            self._lost_since = None


            if (
                ratio >= self.partial_ratio
                and
                not near_edge
            ):

                return (
                    "clear",
                    False,
                    None
                )


            return (
                "partial",
                False,
                None
            )


        # ==============================================================
        # FACE NOT FOUND
        # ==============================================================

        if self._lost_since is None:

            self._lost_since = now


        elapsed = (
            now - self._lost_since
        )


        recent = (
            self._last_seen is not None
            and
            (
                now - self._last_seen
                <= self.recent_seen
            )
        )


        # Face was recently detected
        if recent:

            if (
                elapsed
                >= self.covered_timeout
            ):

                return (
                    "covered",
                    True,
                    FACE_COVERED
                )


            return (
                "partial",
                False,
                None
            )


        # Face completely missing
        if (
            elapsed
            >= self.missing_timeout
        ):

            return (
                "none",
                True,
                FACE_NOT_VISIBLE
            )


        return (
            "partial",
            False,
            None
        )


# ======================================================================
# ALERT MANAGER
# ======================================================================

class AlertManager:

    def __init__(self, cfg):

        self.cfg = cfg

        self.side = SideLookDetector(
            cfg
        )

        self.face = FaceCoverageDetector(
            cfg
        )

        self.reset()


    # ------------------------------------------------------------------
    def reset(self):

        self.side.reset()

        self.face.reset()

        self._active_type = None

        self._active_since = 0.0

        self._sunglasses_on = False

        self._drowsy_since = None

        self._side_since = None


    # ==================================================================
    # SOUND SELECTION
    # ==================================================================

    def _sound_for(
        self,
        alert_type,
        level
    ):

        cfg = self.cfg


        if alert_type == CRITICAL_DROWSINESS:

            return cfg_value(
                cfg,
                "CRITICAL_ALARM_FILE",
                None
            )


        if alert_type in (
            FACE_COVERED,
            FACE_NOT_VISIBLE
        ):

            return cfg_value(
                cfg,
                "FACE_COVERED_ALARM_FILE",
                None
            )


        if alert_type in (
            SEVERE_LEFT,
            SEVERE_RIGHT,
            SIDE_LEFT,
            SIDE_RIGHT
        ):

            return cfg_value(
                cfg,
                "SIDE_LOOK_ALARM_FILE",
                None
            )


        if alert_type == DROWSINESS:

            if level >= 3:

                return cfg_value(
                    cfg,
                    "CRITICAL_ALARM_FILE",
                    None
                )

            return cfg_value(
                cfg,
                "DROWSINESS_ALARM_FILE",
                None
            )


        # Yawning does not produce audio
        return None


    # ==================================================================
    # ESCALATION
    # ==================================================================

    def _escalation(
        self,
        alert_type,
        duration
    ):

        if not alert_type:
            return 0


        cfg = self.cfg


        level = int(
            _BASE_LEVEL.get(
                alert_type,
                1
            )
        )


        critical_after = float(
            cfg_value(
                cfg,
                "ESCALATE_CRITICAL_AFTER",
                5.0
            )
        )


        notify_after = float(
            cfg_value(
                cfg,
                "ESCALATE_NOTIFY_AFTER",
                10.0
            )
        )


        if (
            level >= 2
            and
            duration >= critical_after
            and
            level < 3
        ):

            level = 3


        if (
            level >= 2
            and
            duration >= notify_after
        ):

            level = 4


        return level


    # ==================================================================
    # VOICE
    # ==================================================================

    def _voice(
        self,
        alert_type
    ):

        cfg = self.cfg


        if alert_type in (
            CRITICAL_DROWSINESS,
            DROWSINESS
        ):

            return (
                "drowsy",
                cfg_value(
                    cfg,
                    "VOICE_TEXT_DROWSY",
                    "Warning. Please stay alert."
                )
            )


        if alert_type in (
            SEVERE_LEFT,
            SEVERE_RIGHT,
            SIDE_LEFT,
            SIDE_RIGHT
        ):

            return (
                "side",
                cfg_value(
                    cfg,
                    "VOICE_TEXT_SIDE",
                    "Please look forward."
                )
            )


        if alert_type in (
            FACE_COVERED,
            FACE_NOT_VISIBLE
        ):

            return (
                "face",
                cfg_value(
                    cfg,
                    "VOICE_TEXT_FACE",
                    "Please keep your face visible."
                )
            )


        return (
            None,
            None
        )


    # ==================================================================
    # MAIN UPDATE
    # ==================================================================

    def update(
        self,
        metrics,
        scorer_state,
        sunglasses,
        near_edge=False,
        now=None
    ):

        now = (
            time.time()
            if now is None
            else now
        )


        metrics = (
            metrics
            if isinstance(metrics, dict)
            else {}
        )


        scorer_state = (
            scorer_state
            if isinstance(scorer_state, dict)
            else {}
        )


        sunglasses = (
            sunglasses
            if isinstance(sunglasses, dict)
            else {}
        )


        events = []


        # ==============================================================
        # BASIC VALUES
        # ==============================================================

        found = bool(
            metrics.get(
                "found",
                False
            )
        )


        yaw = (
            scorer_state.get(
                "yaw",
                metrics.get(
                    "yaw",
                    0.0
                )
            )
            if found
            else 0.0
        )


        try:
            yaw = float(yaw or 0.0)
        except Exception:
            yaw = 0.0


        # ==============================================================
        # SIDE LOOK
        # ==============================================================

        (
            attention,
            side_look,
            side_dir
        ) = self.side.update(
            found,
            yaw,
            now
        )


        # ==============================================================
        # FACE COVERAGE
        # ==============================================================

        (
            coverage,
            covered_alert,
            covered_kind
        ) = self.face.update(
            found,
            now,
            near_edge
        )


        # ==============================================================
        # DROWSINESS
        # ==============================================================

        drowsy = bool(
            scorer_state.get(
                "level"
            ) == "DROWSY"
            or
            scorer_state.get(
                "drowsiness",
                False
            )
        )


        yawning = bool(
            scorer_state.get(
                "yawning",
                False
            )
        )


        # ==============================================================
        # SUNGLASSES
        # ==============================================================

        sunglasses_detected = bool(
            sunglasses.get(
                "detected",
                False
            )
        )


        # ==============================================================
        # DROWSINESS TIMER
        # ==============================================================

        if drowsy:

            if self._drowsy_since is None:

                self._drowsy_since = now

        else:

            self._drowsy_since = None


        if (
            self._drowsy_since
            is not None
        ):

            drowsy_duration = (
                now
                -
                self._drowsy_since
            )

        else:

            drowsy_duration = 0.0


        eye_frames = int(
            scorer_state.get(
                "eye_closed_frames",
                0
            )
            or 0
        )


        ear_frames = int(
            cfg_value(
                self.cfg,
                "EAR_CONSEC_FRAMES",
                3
            )
        )


        critical_duration = float(
            cfg_value(
                self.cfg,
                "CRITICAL_DROWSINESS_DURATION",
                5.0
            )
        )


        micro_sleep = bool(
            scorer_state.get(
                "micro_sleep",
                False
            )
        )


        drowsy_critical = (
            drowsy
            and
            (
                drowsy_duration
                >= critical_duration
                or
                micro_sleep
                or
                eye_frames
                >= 2 * ear_frames
            )
        )


        # ==============================================================
        # SIDE LOOK TIMER
        # ==============================================================

        if side_look:

            if self._side_since is None:

                self._side_since = now

        else:

            self._side_since = None


        if self._side_since is not None:

            side_duration = (
                now
                -
                self._side_since
            )

        else:

            side_duration = 0.0


        severe_duration = float(
            cfg_value(
                self.cfg,
                "CRITICAL_DISTRACTION_DURATION",
                5.0
            )
        )


        severe_distraction = (
            side_look
            and
            side_duration
            >= severe_duration
        )


        # ==============================================================
        # ALERT PRIORITY
        # ==============================================================

        alert_type = None


        if drowsy_critical:

            alert_type = CRITICAL_DROWSINESS


        elif covered_alert:

            alert_type = (
                covered_kind
                or FACE_NOT_VISIBLE
            )


        elif severe_distraction:

            if side_dir == "left":

                alert_type = SEVERE_LEFT

            else:

                alert_type = SEVERE_RIGHT


        elif drowsy:

            alert_type = DROWSINESS


        elif side_look:

            if side_dir == "left":

                alert_type = SIDE_LEFT

            else:

                alert_type = SIDE_RIGHT


        elif yawning:

            alert_type = YAWNING


        # ==============================================================
        # ALERT TRANSITION
        # ==============================================================

        if (
            alert_type
            != self._active_type
        ):


            # ----------------------------------------------------------
            # Previous drowsiness ended
            # ----------------------------------------------------------

            if self._active_type in (
                DROWSINESS,
                CRITICAL_DROWSINESS
            ):

                duration = (
                    now
                    -
                    self._active_since
                )


                events.append({

                    "type":
                        "DROWSINESS_ENDED",

                    "severity":
                        "low",

                    "message":
                        "Drowsiness alert cleared",

                    "duration":
                        round(
                            duration,
                            1
                        ),
                })


            # ----------------------------------------------------------
            # New alert
            # ----------------------------------------------------------

            if alert_type is not None:

                events.append({

                    "type":
                        alert_type,

                    "severity":
                        _SEVERITY.get(
                            alert_type,
                            "medium"
                        ),

                    "message":
                        _LABEL.get(
                            alert_type,
                            alert_type
                        )
                        +
                        " (alert started)",
                })


            self._active_type = (
                alert_type
            )

            self._active_since = now


        # ==============================================================
        # ALERT DURATION
        # ==============================================================

        if alert_type:

            alert_duration = (
                now
                -
                self._active_since
            )

        else:

            alert_duration = 0.0


        # ==============================================================
        # ESCALATION
        # ==============================================================

        level = self._escalation(
            alert_type,
            alert_duration
        )


        audible = (
            alert_type is not None
            and
            level >= 2
        )


        sound = None


        if audible:

            sound = self._sound_for(
                alert_type,
                level
            )


        # ==============================================================
        # VOICE
        # ==============================================================

        voice_key = None

        voice_text = None


        if audible:

            (
                voice_key,
                voice_text
            ) = self._voice(
                alert_type
            )


        # ==============================================================
        # SUNGLASSES EVENT
        # ==============================================================

        if (
            sunglasses_detected
            !=
            self._sunglasses_on
        ):

            self._sunglasses_on = (
                sunglasses_detected
            )


            events.append({

                "type":
                    "SUNGLASSES",

                "severity":
                    "low",

                "message":
                    (
                        "Sunglasses detected"
                        if sunglasses_detected
                        else
                        "Sunglasses removed"
                    ),
            })


        # ==============================================================
        # SCORE
        # ==============================================================

        try:

            drowsiness_score = float(
                scorer_state.get(
                    "score",
                    0.0
                )
                or 0.0
            )

        except Exception:

            drowsiness_score = 0.0


        drowsiness_score = max(
            0.0,
            min(
                100.0,
                drowsiness_score
            )
        )


        # ==============================================================
        # RETURN STATE
        # ==============================================================

        return {

            # ----------------------------------------------------------
            # Attention
            # ----------------------------------------------------------

            "attention":
                attention,

            "side_look":
                bool(side_look),

            "side_direction":
                side_dir,

            "severe_distraction":
                bool(severe_distraction),

            "distraction_duration":
                round(
                    side_duration,
                    2
                ),

            "distraction_active":
                bool(side_look),


            # ----------------------------------------------------------
            # Face
            # ----------------------------------------------------------

            "face_detected":
                found,

            "face_coverage":
                coverage,

            "face_covered":
                bool(covered_alert),


            # ----------------------------------------------------------
            # Sunglasses
            # ----------------------------------------------------------

            "sunglasses_detected":
                sunglasses_detected,

            "sunglasses_confidence":
                float(
                    sunglasses.get(
                        "confidence",
                        0.0
                    )
                    or 0.0
                ),


            # ----------------------------------------------------------
            # Drowsiness
            # ----------------------------------------------------------

            "drowsiness":
                bool(drowsy),

            "drowsiness_critical":
                bool(drowsy_critical),

            "drowsiness_score":
                drowsiness_score,

            "score":
                drowsiness_score,

            "yawning":
                yawning,


            # ----------------------------------------------------------
            # Alert
            # ----------------------------------------------------------

            "alert_type":
                alert_type,

            "alert_label":
                (
                    _LABEL.get(
                        alert_type
                    )
                    if alert_type
                    else None
                ),

            "alert_severity":
                (
                    _SEVERITY.get(
                        alert_type
                    )
                    if alert_type
                    else None
                ),

            "alert_sound":
                sound,

            "alert_active":
                bool(
                    alert_type is not None
                ),

            "alert_since":
                (
                    self._active_since
                    if alert_type
                    else None
                ),

            "alert_duration":
                round(
                    alert_duration,
                    2
                ),

            "escalation_level":
                level,

            "notify_ready":
                bool(
                    level >= 4
                ),


            # ----------------------------------------------------------
            # Voice
            # ----------------------------------------------------------

            "voice_text":
                voice_text,

            "voice_key":
                voice_key,


            # ----------------------------------------------------------
            # Event list
            # ----------------------------------------------------------

            "events":
                events,
        }


# ======================================================================
# END
# ======================================================================