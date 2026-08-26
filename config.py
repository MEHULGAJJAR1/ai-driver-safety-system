"""
config.py
=========
Central configuration for the Driver Drowsiness Detection Dashboard.

Supports:
- Local webcam development
- Browser/mobile camera in production
- Drowsiness detection
- EAR / MAR / PERCLOS
- CNN eye-state detection
- Head pose / distraction
- Face coverage
- Sunglasses detection
- Driver attention score
- Safety score
- Risk level
- Predictive drowsiness
- Trip risk timeline
- Mobile notifications
- Emergency contact escalation
- Privacy-first video processing

Every tunable value can be overridden using an environment variable.
"""

import os


# ====================================================================== #
# ENVIRONMENT HELPERS
# ====================================================================== #

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

    return val.strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _env_str(key, default=""):
    value = os.environ.get(key)

    if value is None:
        return default

    return value


# ====================================================================== #
# BASE DIRECTORY
# ====================================================================== #

BASE_DIR = os.path.abspath(
    os.path.dirname(__file__)
)


# ====================================================================== #
# CONFIG
# ====================================================================== #

class Config:

    # ================================================================== #
    # FLASK
    # ================================================================== #

    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "change-me-in-production"
    )

    HOST = os.environ.get(
        "HOST",
        "0.0.0.0"
    )

    PORT = _env_int(
        "PORT",
        5000
    )

    DEBUG = _env_bool(
        "DEBUG",
        False
    )

    # Render / cloud detection.
    #
    # Render automatically provides RENDER.
    # Therefore production mode becomes True on Render.
    PRODUCTION = _env_bool(
        "PRODUCTION",
        bool(os.environ.get("RENDER"))
        or os.environ.get("FLASK_ENV") == "production"
    )

    # Browser/mobile camera is enabled by default.
    BROWSER_CAMERA_ENABLED = _env_bool(
        "BROWSER_CAMERA_ENABLED",
        True
    )


    # ================================================================== #
    # PATHS
    # ================================================================== #

    UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        "uploads"
    )

    MODEL_DIR = os.path.join(
        BASE_DIR,
        "models"
    )

    CNN_MODEL_PATH = os.path.join(
        MODEL_DIR,
        "eye_state_cnn.h5"
    )

    DATABASE_PATH = os.path.join(
        BASE_DIR,
        "database",
        "events.db"
    )

    ALARM_PATH = os.path.join(
        BASE_DIR,
        "static",
        "audio",
        "alarm.wav"
    )

    ALLOWED_EXTENSIONS = {
        "mp4",
        "avi",
        "mov",
        "mkv",
        "webm",
        "jpg",
        "jpeg",
        "png",
        "bmp",
    }

    MAX_CONTENT_MB = _env_int(
        "MAX_CONTENT_MB",
        200
    )


    # ================================================================== #
    # CAMERA
    # ================================================================== #

    # Local webcam device.
    #
    # IMPORTANT:
    # This is used only when running locally.
    # Render production does NOT use VideoCapture.
    CAMERA_INDEX = _env_int(
        "CAMERA_INDEX",
        0
    )

    FRAME_WIDTH = _env_int(
        "FRAME_WIDTH",
        640
    )

    FRAME_HEIGHT = _env_int(
        "FRAME_HEIGHT",
        480
    )

    # Browser/mobile incoming frame limit.
    MAX_CAMERA_FRAME_KB = _env_int(
        "MAX_CAMERA_FRAME_KB",
        500
    )

    # JPEG quality for processed frames.
    CAMERA_JPEG_QUALITY = _env_int(
        "CAMERA_JPEG_QUALITY",
        75
    )

    # Browser frame rate.
    BROWSER_CAMERA_FPS = _env_int(
        "BROWSER_CAMERA_FPS",
        5
    )


    # ================================================================== #
    # EAR - EYE ASPECT RATIO
    # ================================================================== #

    # Open eye is normally around 0.25-0.35.
    # Closed eye is normally around 0.10-0.20.
    EAR_THRESHOLD = _env_float(
        "EAR_THRESHOLD",
        0.23
    )

    # Consecutive frames below threshold before drowsiness.
    EAR_CONSEC_FRAMES = _env_int(
        "EAR_CONSEC_FRAMES",
        15
    )

    # Blink duration.
    BLINK_MIN_FRAMES = _env_int(
        "BLINK_MIN_FRAMES",
        1
    )

    BLINK_MAX_FRAMES = _env_int(
        "BLINK_MAX_FRAMES",
        6
    )


    # ================================================================== #
    # MAR - MOUTH ASPECT RATIO
    # ================================================================== #

    MAR_THRESHOLD = _env_float(
        "MAR_THRESHOLD",
        0.55
    )

    MAR_CONSEC_FRAMES = _env_int(
        "MAR_CONSEC_FRAMES",
        12
    )


    # ================================================================== #
    # HEAD POSE
    # ================================================================== #

    HEAD_PITCH_THRESHOLD = _env_float(
        "HEAD_PITCH_THRESHOLD",
        18.0
    )

    HEAD_CONSEC_FRAMES = _env_int(
        "HEAD_CONSEC_FRAMES",
        12
    )

    HEAD_YAW_THRESHOLD = _env_float(
        "HEAD_YAW_THRESHOLD",
        25.0
    )


    # ================================================================== #
    # PERCLOS
    # ================================================================== #

    PERCLOS_WINDOW = _env_int(
        "PERCLOS_WINDOW",
        150
    )

    PERCLOS_WARN = _env_float(
        "PERCLOS_WARN",
        0.25
    )

    PERCLOS_ALARM = _env_float(
        "PERCLOS_ALARM",
        0.40
    )


    # ================================================================== #
    # CNN EYE STATE
    # ================================================================== #

    USE_CNN = _env_bool(
        "USE_CNN",
        True
    )

    CNN_INPUT_SIZE = _env_int(
        "CNN_INPUT_SIZE",
        64
    )

    CNN_CLOSED_THRESHOLD = _env_float(
        "CNN_CLOSED_THRESHOLD",
        0.50
    )


    # ================================================================== #
    # COMPOSITE DROWSINESS SCORE
    # ================================================================== #

    SCORE_WARNING = _env_float(
        "SCORE_WARNING",
        40.0
    )

    SCORE_ALARM = _env_float(
        "SCORE_ALARM",
        70.0
    )

    W_EYE = _env_float(
        "W_EYE",
        45.0
    )

    W_PERCLOS = _env_float(
        "W_PERCLOS",
        25.0
    )

    W_YAWN = _env_float(
        "W_YAWN",
        15.0
    )

    W_HEAD = _env_float(
        "W_HEAD",
        15.0
    )


    # ================================================================== #
    # BASIC ALARM
    # ================================================================== #

    ALARM_ENABLED = _env_bool(
        "ALARM_ENABLED",
        True
    )

    ALARM_COOLDOWN = _env_float(
        "ALARM_COOLDOWN",
        4.0
    )


    # ================================================================== #
    # ALERT AUDIO FILES
    # ================================================================== #

    DROWSINESS_ALARM_FILE = os.environ.get(
        "DROWSINESS_ALARM_FILE",
        "drowsiness_alarm.wav"
    )

    SIDE_LOOK_ALARM_FILE = os.environ.get(
        "SIDE_LOOK_ALARM_FILE",
        "side_look_alarm.wav"
    )

    FACE_COVERED_ALARM_FILE = os.environ.get(
        "FACE_COVERED_ALARM_FILE",
        "face_covered_alarm.wav"
    )

    CRITICAL_ALARM_FILE = os.environ.get(
        "CRITICAL_ALARM_FILE",
        "critical_alarm.wav"
    )


    # ================================================================== #
    # SIDE LOOK / DRIVER ATTENTION
    # ================================================================== #

    SIDE_YAW_THRESHOLD = _env_float(
        "SIDE_YAW_THRESHOLD",
        22.0
    )

    SIDE_LOOK_DURATION = _env_float(
        "SIDE_LOOK_DURATION",
        1.5
    )

    SIDE_LOOK_EXIT_GRACE = _env_float(
        "SIDE_LOOK_EXIT_GRACE",
        0.3
    )

    SIDE_LOOK_INVERT = _env_bool(
        "SIDE_LOOK_INVERT",
        False
    )


    # ================================================================== #
    # FACE COVERAGE
    # ================================================================== #

    FACE_WINDOW = _env_int(
        "FACE_WINDOW",
        30
    )

    FACE_PARTIAL_RATIO = _env_float(
        "FACE_PARTIAL_RATIO",
        0.85
    )

    FACE_COVERED_RATIO = _env_float(
        "FACE_COVERED_RATIO",
        0.50
    )

    FACE_MISSING_TIMEOUT = _env_float(
        "FACE_MISSING_TIMEOUT",
        1.5
    )

    FACE_COVERED_TIMEOUT = _env_float(
        "FACE_COVERED_TIMEOUT",
        1.2
    )

    FACE_RECENT_SEEN = _env_float(
        "FACE_RECENT_SEEN",
        3.0
    )

    FACE_EDGE_MARGIN = _env_float(
        "FACE_EDGE_MARGIN",
        0.03
    )


    # ================================================================== #
    # SUNGLASSES DETECTION
    # ================================================================== #

    SUNGLASSES_DARK_RATIO = _env_float(
        "SUNGLASSES_DARK_RATIO",
        0.62
    )

    SUNGLASSES_STD_MAX = _env_float(
        "SUNGLASSES_STD_MAX",
        38.0
    )

    SUNGLASSES_CONFIDENCE = _env_float(
        "SUNGLASSES_CONFIDENCE",
        0.55
    )

    SUNGLASSES_MIN_FRAMES = _env_int(
        "SUNGLASSES_MIN_FRAMES",
        6
    )

    SUNGLASSES_THRESHOLD = _env_float(
        "SUNGLASSES_THRESHOLD",
        0.55
    )


    # ================================================================== #
    # AI INTELLIGENCE LAYER
    # ================================================================== #


    # ------------------------------------------------------------------ #
    # CRITICAL ALARM
    # ------------------------------------------------------------------ #

    CRITICAL_DROWSINESS_DURATION = _env_float(
        "CRITICAL_DROWSINESS_DURATION",
        2.5
    )

    CRITICAL_DISTRACTION_DURATION = _env_float(
        "CRITICAL_DISTRACTION_DURATION",
        3.5
    )

    # Backward-compatible typo alias.
    CRITICAL_DISRACTION_DURATION = (
        CRITICAL_DISTRACTION_DURATION
    )

    CRITICAL_SAFETY_SCORE = _env_float(
        "CRITICAL_SAFETY_SCORE",
        40.0
    )


    # ------------------------------------------------------------------ #
    # DROWSINESS TIMING
    # ------------------------------------------------------------------ #

    DROWSINESS_THRESHOLD = _env_float(
        "DROWSINESS_THRESHOLD",
        70.0
    )

    DROWSINESS_DURATION = _env_float(
        "DROWSINESS_DURATION",
        1.2
    )


    # ------------------------------------------------------------------ #
    # DISTRACTION TIMER
    # ------------------------------------------------------------------ #

    DISTRACTION_ALERT_THRESHOLD = _env_float(
        "DISTRACTION_ALERT_THRESHOLD",
        2.0
    )


    # ------------------------------------------------------------------ #
    # ALERT ESCALATION
    # ------------------------------------------------------------------ #

    ESCALATE_AUDIBLE_AFTER = _env_float(
        "ESCALATE_AUDIBLE_AFTER",
        0.6
    )

    ESCALATE_CRITICAL_AFTER = _env_float(
        "ESCALATE_CRITICAL_AFTER",
        2.5
    )

    ESCALATE_NOTIFY_AFTER = _env_float(
        "ESCALATE_NOTIFY_AFTER",
        4.0
    )


    # ------------------------------------------------------------------ #
    # DRIVER ATTENTION SCORE
    # ------------------------------------------------------------------ #

    ATTENTION_SMOOTHING = _env_float(
        "ATTENTION_SMOOTHING",
        0.12
    )

    ATTENTION_TARGET_FORWARD = _env_float(
        "ATTENTION_TARGET_FORWARD",
        100.0
    )

    ATTENTION_TARGET_GLANCE = _env_float(
        "ATTENTION_TARGET_GLANCE",
        72.0
    )

    ATTENTION_TARGET_SIDE = _env_float(
        "ATTENTION_TARGET_SIDE",
        35.0
    )

    ATTENTION_TARGET_DOWN = _env_float(
        "ATTENTION_TARGET_DOWN",
        45.0
    )

    ATTENTION_TARGET_NOFACE = _env_float(
        "ATTENTION_TARGET_NOFACE",
        25.0
    )

    ATTENTION_GREEN_MIN = _env_float(
        "ATTENTION_GREEN_MIN",
        75.0
    )

    ATTENTION_YELLOW_MIN = _env_float(
        "ATTENTION_YELLOW_MIN",
        45.0
    )


    # ------------------------------------------------------------------ #
    # SAFETY SCORE
    # ------------------------------------------------------------------ #

    SAFETY_SMOOTHING = _env_float(
        "SAFETY_SMOOTHING",
        0.12
    )

    SAFETY_PENALTY_DROWSY = _env_float(
        "SAFETY_PENALTY_DROWSY",
        55.0
    )

    SAFETY_PENALTY_ATTENTION = _env_float(
        "SAFETY_PENALTY_ATTENTION",
        30.0
    )

    SAFETY_PENALTY_FACE = _env_float(
        "SAFETY_PENALTY_FACE",
        30.0
    )

    SAFETY_PENALTY_YAWN = _env_float(
        "SAFETY_PENALTY_YAWN",
        12.0
    )

    SAFETY_PENALTY_SUNGLASSES = _env_float(
        "SAFETY_PENALTY_SUNGLASSES",
        6.0
    )


    # ------------------------------------------------------------------ #
    # RISK LEVEL
    # ------------------------------------------------------------------ #

    RISK_LOW_MIN = _env_float(
        "RISK_LOW_MIN",
        80.0
    )

    RISK_MED_MIN = _env_float(
        "RISK_MED_MIN",
        50.0
    )

    RISK_HYSTERESIS = _env_float(
        "RISK_HYSTERESIS",
        1.5
    )


    # ------------------------------------------------------------------ #
    # FATIGUE TREND
    # ------------------------------------------------------------------ #

    FATIGUE_WINDOW = _env_float(
        "FATIGUE_WINDOW",
        60.0
    )

    FATIGUE_DELTA = _env_float(
        "FATIGUE_DELTA",
        8.0
    )


    # ------------------------------------------------------------------ #
    # BREAK RECOMMENDATION
    # ------------------------------------------------------------------ #

    BREAK_DROWSY_EVENTS = _env_int(
        "BREAK_DROWSY_EVENTS",
        3
    )

    BREAK_YAWN_COUNT = _env_int(
        "BREAK_YAWN_COUNT",
        3
    )

    BREAK_HIGH_RISK_SUSTAIN = _env_float(
        "BREAK_HIGH_RISK_SUSTAIN",
        12.0
    )


    # ------------------------------------------------------------------ #
    # VOICE ALERTS
    # ------------------------------------------------------------------ #

    VOICE_ALERT_ENABLED = _env_bool(
        "VOICE_ALERT_ENABLED",
        True
    )

    VOICE_ALERT_COOLDOWN = _env_float(
        "VOICE_ALERT_COOLDOWN",
        8.0
    )

    VOICE_TEXT_DROWSY = os.environ.get(
        "VOICE_TEXT_DROWSY",
        "You appear drowsy. Please take a break."
    )

    VOICE_TEXT_SIDE = os.environ.get(
        "VOICE_TEXT_SIDE",
        "Please look forward."
    )

    VOICE_TEXT_FACE = os.environ.get(
        "VOICE_TEXT_FACE",
        "Please keep your face visible."
    )

    VOICE_TEXT_GENERIC = os.environ.get(
        "VOICE_TEXT_GENERIC",
        "Warning. Driver attention is required."
    )


    # ================================================================== #
    # MOBILE PUSH NOTIFICATIONS
    # ================================================================== #

    MOBILE_NOTIFICATION_ENABLED = _env_bool(
        "MOBILE_NOTIFICATION_ENABLED",
        False
    )

    MOBILE_NOTIFICATION_COOLDOWN = _env_float(
        "MOBILE_NOTIFICATION_COOLDOWN",
        30.0
    )

    FCM_CREDENTIALS_FILE = os.environ.get(
        "FCM_CREDENTIALS_FILE",
        os.path.join(
            BASE_DIR,
            "firebase-credentials.json"
        )
    )

    FCM_PROJECT_ID = os.environ.get(
        "FCM_PROJECT_ID",
        ""
    )

    FCM_DEVICE_TOKEN = os.environ.get(
        "FCM_DEVICE_TOKEN",
        ""
    )


    # ================================================================== #
    # PRIVACY
    # ================================================================== #

    # Camera processing is privacy-first.
    PRIVACY_MODE = _env_bool(
        "PRIVACY_MODE",
        True
    )

    # NEVER record video unless explicitly enabled.
    VIDEO_STORAGE_ENABLED = _env_bool(
        "VIDEO_STORAGE_ENABLED",
        False
    )


    # ================================================================== #
    # EVENT LOGGING
    # ================================================================== #

    EVENT_LOG_ENABLED = _env_bool(
        "EVENT_LOG_ENABLED",
        True
    )

    EVENT_LOG_DIR = os.path.join(
        BASE_DIR,
        "logs"
    )


    # ================================================================== #
    # PREDICTIVE DROWSINESS
    # ================================================================== #

    PREDICT_ENABLED = _env_bool(
        "PREDICT_ENABLED",
        True
    )

    PREDICT_WINDOW = _env_float(
        "PREDICT_WINDOW",
        30.0
    )

    PREDICT_HORIZON = _env_float(
        "PREDICT_HORIZON",
        120.0
    )

    PREDICT_MIN_SAMPLES = _env_int(
        "PREDICT_MIN_SAMPLES",
        6
    )

    PREDICT_SMOOTHING = _env_float(
        "PREDICT_SMOOTHING",
        0.25
    )

    PREDICT_SLOPE_REF = _env_float(
        "PREDICT_SLOPE_REF",
        1.5
    )

    PREDICT_EPISODE_REF = _env_float(
        "PREDICT_EPISODE_REF",
        4.0
    )

    PREDICT_W_SCORE = _env_float(
        "PREDICT_W_SCORE",
        0.40
    )

    PREDICT_W_PERCLOS = _env_float(
        "PREDICT_W_PERCLOS",
        0.25
    )

    PREDICT_W_TREND = _env_float(
        "PREDICT_W_TREND",
        0.20
    )

    PREDICT_W_EPISODES = _env_float(
        "PREDICT_W_EPISODES",
        0.15
    )

    PREDICT_PROB_MODERATE = _env_float(
        "PREDICT_PROB_MODERATE",
        0.35
    )

    PREDICT_PROB_HIGH = _env_float(
        "PREDICT_PROB_HIGH",
        0.60
    )

    PREDICT_PROB_IMMINENT = _env_float(
        "PREDICT_PROB_IMMINENT",
        0.80
    )


    # ================================================================== #
    # TRIP RISK TIMELINE
    # ================================================================== #

    TIMELINE_ENABLED = _env_bool(
        "TIMELINE_ENABLED",
        True
    )

    TIMELINE_SAMPLE_INTERVAL = _env_float(
        "TIMELINE_SAMPLE_INTERVAL",
        2.0
    )

    TIMELINE_MAX_POINTS = _env_int(
        "TIMELINE_MAX_POINTS",
        900
    )


    # ================================================================== #
    # EMERGENCY CONTACT
    # ================================================================== #

    EMERGENCY_CONTACT_ENABLED = _env_bool(
        "EMERGENCY_CONTACT_ENABLED",
        False
    )

    EMERGENCY_CONTACT_NAME = os.environ.get(
        "EMERGENCY_CONTACT_NAME",
        ""
    )

    EMERGENCY_CONTACT_PHONE = os.environ.get(
        "EMERGENCY_CONTACT_PHONE",
        ""
    )

    EMERGENCY_CONTACT_WEBHOOK = os.environ.get(
        "EMERGENCY_CONTACT_WEBHOOK",
        ""
    )

    EMERGENCY_SUSTAIN_SECONDS = _env_float(
        "EMERGENCY_SUSTAIN_SECONDS",
        10.0
    )

    EMERGENCY_CONTACT_COOLDOWN = _env_float(
        "EMERGENCY_CONTACT_COOLDOWN",
        120.0
    )

    EMERGENCY_HTTP_TIMEOUT = _env_float(
        "EMERGENCY_HTTP_TIMEOUT",
        5.0
    )


# ====================================================================== #
# GLOBAL CONFIG INSTANCE
# ====================================================================== #

config = Config()