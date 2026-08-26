"""
config.py
=========
Central configuration for the Driver Drowsiness Detection Dashboard.

Every tunable threshold lives here so you can calibrate the system to a
particular camera / driver without touching the detection code.

You can also override any value at runtime with an environment variable of
the same name, e.g.  `EAR_THRESHOLD=0.23 python app.py`.
"""

import os


def _env_float(key, default):
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key, default):
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_bool(key, default):
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ------------------------------------------------------------------ #
    #  Flask
    # ------------------------------------------------------------------ #
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = _env_int("PORT", 5000)
    DEBUG = os.environ.get("DEBUG", "1") == "1"

    # ------------------------------------------------------------------ #
    #  Paths
    # ------------------------------------------------------------------ #
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MODEL_DIR = os.path.join(BASE_DIR, "models")
    CNN_MODEL_PATH = os.path.join(MODEL_DIR, "eye_state_cnn.h5")
    DATABASE_PATH = os.path.join(BASE_DIR, "database", "events.db")
    ALARM_PATH = os.path.join(BASE_DIR, "static", "audio", "alarm.wav")
    ALLOWED_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm", "jpg", "jpeg", "png", "bmp"}
    MAX_CONTENT_MB = 200  # max upload size

    # ------------------------------------------------------------------ #
    #  Camera
    # ------------------------------------------------------------------ #
    CAMERA_INDEX = _env_int("CAMERA_INDEX", 0)   # webcam device id
    FRAME_WIDTH = _env_int("FRAME_WIDTH", 640)
    FRAME_HEIGHT = _env_int("FRAME_HEIGHT", 480)

    # ------------------------------------------------------------------ #
    #  Eye Aspect Ratio (EAR)  -> eye closure / micro-sleep
    # ------------------------------------------------------------------ #
    # EAR falls as the eyelid closes. Typical open eye ~0.30, closed ~0.10.
    EAR_THRESHOLD = _env_float("EAR_THRESHOLD", 0.23)
    # Number of consecutive frames the eyes must stay below the threshold
    # before we call it "drowsy" (filters out normal blinks).
    EAR_CONSEC_FRAMES = _env_int("EAR_CONSEC_FRAMES", 15)
    # A blink is a short dip (below threshold) that recovers quickly.
    BLINK_MIN_FRAMES = _env_int("BLINK_MIN_FRAMES", 1)
    BLINK_MAX_FRAMES = _env_int("BLINK_MAX_FRAMES", 6)

    # ------------------------------------------------------------------ #
    #  Mouth Aspect Ratio (MAR)  -> yawning
    # ------------------------------------------------------------------ #
    # MAR rises when the mouth opens. Closed ~0.05, wide yawn ~0.6+.
    MAR_THRESHOLD = _env_float("MAR_THRESHOLD", 0.55)
    MAR_CONSEC_FRAMES = _env_int("MAR_CONSEC_FRAMES", 12)

    # ------------------------------------------------------------------ #
    #  Head pose  -> nodding off (pitch) / distraction (yaw)
    # ------------------------------------------------------------------ #
    # Pitch angle (degrees) beyond which the head is considered "down".
    HEAD_PITCH_THRESHOLD = _env_float("HEAD_PITCH_THRESHOLD", 18.0)
    HEAD_CONSEC_FRAMES = _env_int("HEAD_CONSEC_FRAMES", 12)
    # Yaw beyond this (looking away from the road) counts as distraction.
    HEAD_YAW_THRESHOLD = _env_float("HEAD_YAW_THRESHOLD", 25.0)

    # ------------------------------------------------------------------ #
    #  PERCLOS  -> % of time eyes are closed over a rolling window
    # ------------------------------------------------------------------ #
    PERCLOS_WINDOW = _env_int("PERCLOS_WINDOW", 150)     # frames (~5-6 s)
    PERCLOS_WARN = _env_float("PERCLOS_WARN", 0.25)      # 25% -> warning
    PERCLOS_ALARM = _env_float("PERCLOS_ALARM", 0.40)    # 40% -> alarm

    # ------------------------------------------------------------------ #
    #  CNN eye-state classifier (optional)
    # ------------------------------------------------------------------ #
    USE_CNN = os.environ.get("USE_CNN", "1") == "1"   # use if model present
    CNN_INPUT_SIZE = _env_int("CNN_INPUT_SIZE", 64)   # 64x64 grayscale
    CNN_CLOSED_THRESHOLD = _env_float("CNN_CLOSED_THRESHOLD", 0.5)

    # ------------------------------------------------------------------ #
    #  Composite drowsiness score  ->  Alert / Warning / Drowsy
    # ------------------------------------------------------------------ #
    SCORE_WARNING = _env_float("SCORE_WARNING", 40.0)
    SCORE_ALARM = _env_float("SCORE_ALARM", 70.0)
    # Weights for the 0-100 composite score (should sum to 100).
    W_EYE = _env_float("W_EYE", 45.0)
    W_PERCLOS = _env_float("W_PERCLOS", 25.0)
    W_YAWN = _env_float("W_YAWN", 15.0)
    W_HEAD = _env_float("W_HEAD", 15.0)

    # ------------------------------------------------------------------ #
    #  Alarm
    # ------------------------------------------------------------------ #
    ALARM_ENABLED = os.environ.get("ALARM_ENABLED", "1") == "1"
    # Seconds to wait before the same alarm can fire again.
    ALARM_COOLDOWN = _env_float("ALARM_COOLDOWN", 4.0)

    # ------------------------------------------------------------------ #
    #  Audio assets (played by the browser). One distinct sound per alert
    #  type so the driver can tell alarms apart without looking. Files live
    #  in static/audio/. Sunglasses is a *status* only (no sound).
    # ------------------------------------------------------------------ #
    DROWSINESS_ALARM_FILE = os.environ.get("DROWSINESS_ALARM_FILE", "drowsiness_alarm.wav")
    SIDE_LOOK_ALARM_FILE = os.environ.get("SIDE_LOOK_ALARM_FILE", "side_look_alarm.wav")
    FACE_COVERED_ALARM_FILE = os.environ.get("FACE_COVERED_ALARM_FILE", "face_covered_alarm.wav")

    # ------------------------------------------------------------------ #
    #  Feature 2 - Side-way looking / driver attention
    # ------------------------------------------------------------------ #
    # Yaw (deg) away from forward before it counts as "looking to the side".
    SIDE_YAW_THRESHOLD = _env_float("SIDE_YAW_THRESHOLD", 22.0)
    # Continuous seconds of side-looking before the alert fires (debounce).
    SIDE_LOOK_DURATION = _env_float("SIDE_LOOK_DURATION", 1.5)
    # Brief forward glances shorter than this won't reset the timer (jitter).
    SIDE_LOOK_EXIT_GRACE = _env_float("SIDE_LOOK_EXIT_GRACE", 0.3)
    # If LEFT/RIGHT are reversed for your camera/mirror, set SIDE_LOOK_INVERT=1.
    SIDE_LOOK_INVERT = _env_bool("SIDE_LOOK_INVERT", False)

    # ------------------------------------------------------------------ #
    #  Feature 4 - Face coverage / camera obstruction
    # ------------------------------------------------------------------ #
    FACE_WINDOW = _env_int("FACE_WINDOW", 30)              # frames for detect ratio
    FACE_PARTIAL_RATIO = _env_float("FACE_PARTIAL_RATIO", 0.85)   # below => partial
    FACE_COVERED_RATIO = _env_float("FACE_COVERED_RATIO", 0.5)    # below => covered
    FACE_MISSING_TIMEOUT = _env_float("FACE_MISSING_TIMEOUT", 1.5)  # s no-face => alert
    FACE_COVERED_TIMEOUT = _env_float("FACE_COVERED_TIMEOUT", 1.2)  # s covered => alert
    # If a face was seen within this many seconds, a sudden loss is treated as
    # "covered" (something blocking) rather than "no face in view".
    FACE_RECENT_SEEN = _env_float("FACE_RECENT_SEEN", 3.0)
    # Face bbox within this fraction of a frame edge counts as partially out.
    FACE_EDGE_MARGIN = _env_float("FACE_EDGE_MARGIN", 0.03)

    # ------------------------------------------------------------------ #
    #  Feature 3 - Sunglasses detection (lightweight CV, no heavy model)
    # ------------------------------------------------------------------ #
    # Eye-region brightness / skin brightness below this => "dark lens".
    SUNGLASSES_DARK_RATIO = _env_float("SUNGLASSES_DARK_RATIO", 0.62)
    # Eye-region intensity std-dev below this => "smooth lens" (no sclera/iris).
    SUNGLASSES_STD_MAX = _env_float("SUNGLASSES_STD_MAX", 38.0)
    # 0-1 confidence needed to report sunglasses.
    SUNGLASSES_CONFIDENCE = _env_float("SUNGLASSES_CONFIDENCE", 0.55)
    # Consecutive qualifying frames before reporting (debounce).
    SUNGLASSES_MIN_FRAMES = _env_int("SUNGLASSES_MIN_FRAMES", 6)
    # Spec-friendly alias (0-1). Kept in sync with SUNGLASSES_CONFIDENCE.
    SUNGLASSES_THRESHOLD = _env_float("SUNGLASSES_THRESHOLD", 0.55)

    # ================================================================== #
    #  AI Driver Monitoring & Safety System  (intelligence layer)
    #  ---------------------------------------------------------------- #
    #  Everything below powers the higher-level "safety brain": attention
    #  & safety scoring, risk level, distraction timing, escalation, voice
    #  warnings, mobile push and privacy. All tunable here - no magic
    #  numbers scattered through the code.
    # ================================================================== #

    # ---- 4th distinct alarm: the urgent CRITICAL sound ---------------- #
    CRITICAL_ALARM_FILE = os.environ.get("CRITICAL_ALARM_FILE", "critical_alarm.wav")

    # ---- drowsiness timing (spec-named knobs) ------------------------- #
    # Score at/above which the composite level is DROWSY (mirrors SCORE_ALARM).
    DROWSINESS_THRESHOLD = _env_float("DROWSINESS_THRESHOLD", 70.0)
    # Continuous seconds at DROWSY before the drowsiness alarm is audible.
    DROWSINESS_DURATION = _env_float("DROWSINESS_DURATION", 1.2)

    # ---- CRITICAL thresholds (drive escalation + notifications) ------- #
    # Continuous DROWSY time (s) that upgrades DROWSINESS -> CRITICAL_DROWSINESS.
    CRITICAL_DROWSINESS_DURATION = _env_float("CRITICAL_DROWSINESS_DURATION", 2.5)
    # Continuous side-look time (s) that upgrades SIDE_LOOK -> SEVERE_DISTRACTION.
    CRITICAL_DISTRACTION_DURATION = _env_float("CRITICAL_DISTRACTION_DURATION", 3.5)
    # Alias for the spelling used in the original spec (kept in sync).
    CRITICAL_DISRACTION_DURATION = CRITICAL_DISTRACTION_DURATION
    # Safety score at/below which risk is CRITICAL -> may notify the phone.
    CRITICAL_SAFETY_SCORE = _env_float("CRITICAL_SAFETY_SCORE", 40.0)

    # ---- distraction timer (Feature 7) -------------------------------- #
    # Continuous look-away seconds before a distraction *alert* is raised.
    DISTRACTION_ALERT_THRESHOLD = _env_float("DISTRACTION_ALERT_THRESHOLD", 2.0)

    # ---- escalating alarm system (Feature 10) ------------------------- #
    # An active alert climbs L1 (visual) -> L2 (audible) -> L3 (critical /
    # louder) -> L4 (mobile) based on how long it has stayed active. It never
    # jumps straight to the top for an ordinary alert.
    ESCALATE_AUDIBLE_AFTER = _env_float("ESCALATE_AUDIBLE_AFTER", 0.6)   # L1->L2
    ESCALATE_CRITICAL_AFTER = _env_float("ESCALATE_CRITICAL_AFTER", 2.5)  # L2->L3
    ESCALATE_NOTIFY_AFTER = _env_float("ESCALATE_NOTIFY_AFTER", 4.0)     # L3->L4

    # ---- driver attention score (Feature 6), 0-100 -------------------- #
    # Exponential smoothing factor (0-1): higher = more responsive.
    ATTENTION_SMOOTHING = _env_float("ATTENTION_SMOOTHING", 0.12)
    # Instantaneous target the score eases toward for each state.
    ATTENTION_TARGET_FORWARD = _env_float("ATTENTION_TARGET_FORWARD", 100.0)
    ATTENTION_TARGET_GLANCE = _env_float("ATTENTION_TARGET_GLANCE", 72.0)
    ATTENTION_TARGET_SIDE = _env_float("ATTENTION_TARGET_SIDE", 35.0)
    ATTENTION_TARGET_DOWN = _env_float("ATTENTION_TARGET_DOWN", 45.0)
    ATTENTION_TARGET_NOFACE = _env_float("ATTENTION_TARGET_NOFACE", 25.0)
    ATTENTION_GREEN_MIN = _env_float("ATTENTION_GREEN_MIN", 75.0)   # >= => green
    ATTENTION_YELLOW_MIN = _env_float("ATTENTION_YELLOW_MIN", 45.0)  # >= => yellow

    # ---- real-time safety score (Feature 8), 0-100 -------------------- #
    SAFETY_SMOOTHING = _env_float("SAFETY_SMOOTHING", 0.12)
    # How much each factor can pull the safety score down (points).
    SAFETY_PENALTY_DROWSY = _env_float("SAFETY_PENALTY_DROWSY", 55.0)   # x drowsiness/100
    SAFETY_PENALTY_ATTENTION = _env_float("SAFETY_PENALTY_ATTENTION", 30.0)  # x (1-att/100)
    SAFETY_PENALTY_FACE = _env_float("SAFETY_PENALTY_FACE", 30.0)      # face covered/none
    SAFETY_PENALTY_YAWN = _env_float("SAFETY_PENALTY_YAWN", 12.0)      # active yawn
    SAFETY_PENALTY_SUNGLASSES = _env_float("SAFETY_PENALTY_SUNGLASSES", 6.0)

    # ---- driver risk level (Feature 9) w/ hysteresis ------------------ #
    # Safety score bands: >=LOW_MIN LOW, >=MED_MIN MEDIUM, else HIGH.
    RISK_LOW_MIN = _env_float("RISK_LOW_MIN", 80.0)
    RISK_MED_MIN = _env_float("RISK_MED_MIN", 50.0)
    # A new band must persist this many seconds before we switch (anti-flicker).
    RISK_HYSTERESIS = _env_float("RISK_HYSTERESIS", 1.5)

    # ---- fatigue trend (Feature 15) ----------------------------------- #
    FATIGUE_WINDOW = _env_float("FATIGUE_WINDOW", 60.0)   # seconds of history
    FATIGUE_DELTA = _env_float("FATIGUE_DELTA", 8.0)      # pts change => rising/falling

    # ---- break recommendation (Feature 12) ---------------------------- #
    BREAK_DROWSY_EVENTS = _env_int("BREAK_DROWSY_EVENTS", 3)
    BREAK_YAWN_COUNT = _env_int("BREAK_YAWN_COUNT", 3)
    BREAK_HIGH_RISK_SUSTAIN = _env_float("BREAK_HIGH_RISK_SUSTAIN", 12.0)  # s at HIGH risk

    # ---- voice warnings (Feature 11) - spoken in-browser (Web Speech) - #
    VOICE_ALERT_ENABLED = _env_bool("VOICE_ALERT_ENABLED", True)
    VOICE_ALERT_COOLDOWN = _env_float("VOICE_ALERT_COOLDOWN", 8.0)   # s between phrases
    VOICE_TEXT_DROWSY = os.environ.get("VOICE_TEXT_DROWSY", "You appear drowsy. Please take a break.")
    VOICE_TEXT_SIDE = os.environ.get("VOICE_TEXT_SIDE", "Please look forward.")
    VOICE_TEXT_FACE = os.environ.get("VOICE_TEXT_FACE", "Please keep your face visible.")
    VOICE_TEXT_GENERIC = os.environ.get("VOICE_TEXT_GENERIC", "Warning. Driver attention is required.")

    # ---- mobile push notifications (Features 18/19) ------------------- #
    # DISABLED by default: needs your own Firebase project + device token.
    # NEVER hard-code credentials - point these at env vars / a gitignored file.
    MOBILE_NOTIFICATION_ENABLED = _env_bool("MOBILE_NOTIFICATION_ENABLED", False)
    MOBILE_NOTIFICATION_COOLDOWN = _env_float("MOBILE_NOTIFICATION_COOLDOWN", 30.0)
    # Path to the Firebase service-account JSON (kept OUT of git). Env override:
    #   FCM_CREDENTIALS_FILE=/secure/path/service-account.json
    FCM_CREDENTIALS_FILE = os.environ.get(
        "FCM_CREDENTIALS_FILE", os.path.join(BASE_DIR, "firebase-credentials.json"))
    FCM_PROJECT_ID = os.environ.get("FCM_PROJECT_ID", "")
    # The target phone's FCM registration token (from your mobile client).
    FCM_DEVICE_TOKEN = os.environ.get("FCM_DEVICE_TOKEN", "")

    # ---- privacy mode (Feature 20) ------------------------------------ #
    # ON by default: all processing is local and NO camera frames are stored.
    PRIVACY_MODE = _env_bool("PRIVACY_MODE", True)
    # Off by default: we never record/persist video unless the user opts in.
    VIDEO_STORAGE_ENABLED = _env_bool("VIDEO_STORAGE_ENABLED", False)

    # ---- file event log (Feature 17) - JSONL + CSV, alongside SQLite -- #
    EVENT_LOG_ENABLED = _env_bool("EVENT_LOG_ENABLED", True)
    EVENT_LOG_DIR = os.path.join(BASE_DIR, "logs")

    # ================================================================== #
    #  AI Intelligence layer v2  (companion-app upgrade)
    #  ---------------------------------------------------------------- #
    #  Predictive drowsiness, trip-risk timeline and the optional
    #  emergency-contact escalation. All pure-Python, fed from the same
    #  per-frame state, and reused by BOTH the Flask app and the FastAPI
    #  cloud service (no duplicated logic). Everything is env-overridable.
    # ================================================================== #

    # ---- Predictive Drowsiness --------------------------------------- #
    # Forecasts *imminent* drowsiness from the momentum of the composite
    # drowsiness score + PERCLOS + recent fatigue episodes - it answers
    # "how likely is this driver to be drowsy soon?", not just "now".
    PREDICT_ENABLED = _env_bool("PREDICT_ENABLED", True)
    # Rolling history window (seconds) used to measure the trend/slope.
    PREDICT_WINDOW = _env_float("PREDICT_WINDOW", 30.0)
    # Forecast horizon (seconds) for the projected score / ETA cap.
    PREDICT_HORIZON = _env_float("PREDICT_HORIZON", 120.0)
    # Minimum samples before a forecast is considered meaningful.
    PREDICT_MIN_SAMPLES = _env_int("PREDICT_MIN_SAMPLES", 6)
    # EMA smoothing (0-1) applied to the output probability.
    PREDICT_SMOOTHING = _env_float("PREDICT_SMOOTHING", 0.25)
    # Slope (score-points per second) treated as a "fast" rise -> factor 1.0.
    PREDICT_SLOPE_REF = _env_float("PREDICT_SLOPE_REF", 1.5)
    # Recent fatigue episodes (yawn/nod/micro-sleep) treated as "many" -> 1.0.
    PREDICT_EPISODE_REF = _env_float("PREDICT_EPISODE_REF", 4.0)
    # Probability weights (sum ~1.0): current score, PERCLOS, rising trend, episodes.
    PREDICT_W_SCORE = _env_float("PREDICT_W_SCORE", 0.40)
    PREDICT_W_PERCLOS = _env_float("PREDICT_W_PERCLOS", 0.25)
    PREDICT_W_TREND = _env_float("PREDICT_W_TREND", 0.20)
    PREDICT_W_EPISODES = _env_float("PREDICT_W_EPISODES", 0.15)
    # Probability bands -> LOW / MODERATE / HIGH / IMMINENT.
    PREDICT_PROB_MODERATE = _env_float("PREDICT_PROB_MODERATE", 0.35)
    PREDICT_PROB_HIGH = _env_float("PREDICT_PROB_HIGH", 0.60)
    PREDICT_PROB_IMMINENT = _env_float("PREDICT_PROB_IMMINENT", 0.80)

    # ---- Trip Risk Timeline ------------------------------------------ #
    # Records a downsampled risk/safety/attention series per session so the
    # UI/app can draw a coloured "how risky was this trip" timeline.
    TIMELINE_ENABLED = _env_bool("TIMELINE_ENABLED", True)
    # Seconds between recorded samples (downsampling to keep it light).
    TIMELINE_SAMPLE_INTERVAL = _env_float("TIMELINE_SAMPLE_INTERVAL", 2.0)
    # Hard cap on stored points (older points are decimated past this).
    TIMELINE_MAX_POINTS = _env_int("TIMELINE_MAX_POINTS", 900)

    # ---- Optional Emergency Contact escalation ----------------------- #
    # DISABLED by default. When on, a *sustained* critical situation (driver
    # falling asleep / very low safety) that persists past EMERGENCY_SUSTAIN
    # seconds alerts a configured contact - it never fires on a brief blip
    # and has its own long cooldown so the contact is not spammed.
    # NEVER hard-code secrets: point the webhook at an env var.
    EMERGENCY_CONTACT_ENABLED = _env_bool("EMERGENCY_CONTACT_ENABLED", False)
    EMERGENCY_CONTACT_NAME = os.environ.get("EMERGENCY_CONTACT_NAME", "")
    EMERGENCY_CONTACT_PHONE = os.environ.get("EMERGENCY_CONTACT_PHONE", "")
    # A URL that actually delivers the alert (Twilio proxy / IFTTT / your own
    # endpoint). Left blank -> the notifier logs instead of sending.
    EMERGENCY_CONTACT_WEBHOOK = os.environ.get("EMERGENCY_CONTACT_WEBHOOK", "")
    # Continuous seconds of critical danger required before contacting (so we
    # never jump straight to the top level).
    EMERGENCY_SUSTAIN_SECONDS = _env_float("EMERGENCY_SUSTAIN_SECONDS", 10.0)
    # Minimum seconds between emergency-contact alerts.
    EMERGENCY_CONTACT_COOLDOWN = _env_float("EMERGENCY_CONTACT_COOLDOWN", 120.0)
    # HTTP timeout (s) for the webhook call.
    EMERGENCY_HTTP_TIMEOUT = _env_float("EMERGENCY_HTTP_TIMEOUT", 5.0)


config = Config()
