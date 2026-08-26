import os
import time
import base64
import threading

import cv2
import numpy as np

from flask import (
    Flask,
    Response,
    render_template,
    request,
    jsonify,
)

from werkzeug.utils import secure_filename

from config import config
from database import (
    init_db,
    log_event,
    get_events,
    get_stats,
    clear_events,
)
from analyzer import analyze_file
from analytics import (
    EventLogger,
    DrowsinessPredictor,
    TripRiskTimeline,
)
from notifications import (
    NotificationManager,
    EmergencyContactNotifier,
)


# ======================================================================
# FLASK APP
# ======================================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = (
    config.MAX_CONTENT_MB * 1024 * 1024
)

os.makedirs(
    config.UPLOAD_FOLDER,
    exist_ok=True
)

os.makedirs(
    os.path.dirname(config.DATABASE_PATH),
    exist_ok=True
)

init_db()


# ======================================================================
# DROWSINESS PIPELINE
# ======================================================================

try:

    from detection import DrowsinessPipeline

except Exception as exc:

    DrowsinessPipeline = None

    print(
        "[WARNING] Could not import DrowsinessPipeline:",
        exc
    )


pipeline = None

pipeline_lock = threading.Lock()


# ======================================================================
# BROWSER CAMERA STATE
# ======================================================================

browser_camera_running = False

latest_state = {
    "found": False,
    "status_text": "Idle",
    "score": 0,
    "level": "ALERT",
    "camera_processing": "BROWSER",
}

latest_jpeg = None


# ======================================================================
# ANALYTICS / NOTIFICATIONS
# ======================================================================

event_logger = EventLogger(config)

notifier = NotificationManager(config)

predictor = DrowsinessPredictor(config)

timeline = TripRiskTimeline(config)

emergency = EmergencyContactNotifier(config)


_last_logged_ts = 0.0


# ======================================================================
# PIPELINE
# ======================================================================

def create_pipeline():

    global pipeline

    if DrowsinessPipeline is None:

        print(
            "[ERROR] DrowsinessPipeline is unavailable."
        )

        return False

    with pipeline_lock:

        if pipeline is None:

            try:

                print(
                    "[INFO] Loading DrowsinessPipeline..."
                )

                pipeline = DrowsinessPipeline(
                    config
                )

                if hasattr(
                    pipeline,
                    "reset"
                ):

                    pipeline.reset()

                print(
                    "[OK] Drowsiness pipeline initialized."
                )

            except Exception as exc:

                print(
                    "[ERROR] Pipeline initialization failed:",
                    repr(exc)
                )

                pipeline = None

                return False

    return True


def reset_pipeline():

    global pipeline

    if pipeline is None:

        create_pipeline()

    if (
        pipeline is not None
        and hasattr(
            pipeline,
            "reset"
        )
    ):

        try:

            pipeline.reset()

        except Exception as exc:

            print(
                "[WARNING] Pipeline reset failed:",
                repr(exc)
            )


# ======================================================================
# EVENT HOUSEKEEPING
# ======================================================================

def process_events(state):

    global _last_logged_ts

    if not state:

        return

    now = time.time()

    # --------------------------------------------------------------
    # Notifications
    # --------------------------------------------------------------

    try:

        notifier.evaluate(
            state
        )

    except Exception as exc:

        print(
            "[NOTIFY]",
            repr(exc)
        )

    # --------------------------------------------------------------
    # Prediction
    # --------------------------------------------------------------

    try:

        predictor.update(
            state
        )

    except Exception as exc:

        print(
            "[PREDICT]",
            repr(exc)
        )

    # --------------------------------------------------------------
    # Timeline
    # --------------------------------------------------------------

    try:

        timeline.update(
            state
        )

    except Exception as exc:

        print(
            "[TIMELINE]",
            repr(exc)
        )

    # --------------------------------------------------------------
    # Emergency
    # --------------------------------------------------------------

    try:

        emergency.evaluate(
            state
        )

    except Exception as exc:

        print(
            "[EMERGENCY]",
            repr(exc)
        )

    # --------------------------------------------------------------
    # Prevent excessive DB logging
    # --------------------------------------------------------------

    if (
        now - _last_logged_ts
        < 1.0
    ):

        return

    _last_logged_ts = now

    events = (
        state.get("events")
        or []
    )

    if not events:

        return

    extra = {

        "attention_score":
            state.get(
                "attention_score"
            ),

        "safety_score":
            state.get(
                "safety_score"
            ),

        "risk_level":
            state.get(
                "risk_level"
            ),

        "score":
            state.get(
                "score"
            ),

    }

    for ev in events:

        try:

            log_event(

                ev.get(
                    "type",
                    "UNKNOWN"
                ),

                ev.get(
                    "severity",
                    "medium"
                ),

                ev.get(
                    "message",
                    ""
                ),

                ear=state.get(
                    "ear"
                ),

                mar=state.get(
                    "mar"
                ),

                score=state.get(
                    "score"
                ),

                source="browser_camera",

            )

        except Exception as exc:

            print(
                "[DB EVENT]",
                repr(exc)
            )

    try:

        event_logger.log_many(
            events,
            extra=extra
        )

    except Exception as exc:

        print(
            "[EVENT LOGGER]",
            repr(exc)
        )


# ======================================================================
# PAGES
# ======================================================================

@app.route("/")
def index():

    cnn_active = False

    if pipeline is not None:

        try:

            cnn_active = bool(
                pipeline.cnn_active
            )

        except Exception:

            cnn_active = False

    return render_template(

        "dashboard.html",

        config=config,

        cnn_active=cnn_active,

    )


@app.route("/upload")
def upload_page():

    return render_template(

        "upload.html",

        config=config,

    )


@app.route("/history")
def history_page():

    return render_template(

        "history.html",

        config=config,

    )


# ======================================================================
# CAMERA START HELPER
# ======================================================================

def start_browser_camera():

    global browser_camera_running
    global latest_state
    global latest_jpeg

    # --------------------------------------------------------------
    # Load AI pipeline
    # --------------------------------------------------------------

    if not create_pipeline():

        return {

            "ok": False,

            "error":
                "Drowsiness detection pipeline could not be loaded."

        }

    # --------------------------------------------------------------
    # Reset AI state
    # --------------------------------------------------------------

    reset_pipeline()

    try:

        predictor.reset()

    except Exception as exc:

        print(
            "[WARNING] Predictor reset:",
            repr(exc)
        )

    try:

        timeline.reset()

    except Exception as exc:

        print(
            "[WARNING] Timeline reset:",
            repr(exc)
        )

    try:

        emergency.reset()

    except Exception as exc:

        print(
            "[WARNING] Emergency reset:",
            repr(exc)
        )

    # --------------------------------------------------------------
    # Start browser session
    # --------------------------------------------------------------

    browser_camera_running = True

    latest_jpeg = None

    latest_state = {

        "found": False,

        "status_text":
            "Camera ready",

        "score": 0,

        "level":
            "ALERT",

        "camera_processing":
            "BROWSER",

    }

    print(
        "[CAMERA] Browser camera session started."
    )

    return {

        "ok": True,

        "running": True,

        "mode":
            "browser_camera",

    }


# ======================================================================
# CAMERA STOP HELPER
# ======================================================================

def stop_browser_camera():

    global browser_camera_running
    global latest_state
    global latest_jpeg

    browser_camera_running = False

    latest_jpeg = None

    latest_state = {

        "found": False,

        "status_text":
            "Camera stopped",

        "score": 0,

        "level":
            "ALERT",

        "camera_processing":
            "BROWSER",

    }

    print(
        "[CAMERA] Browser camera session stopped."
    )

    return {

        "ok": True,

        "running": False,

    }


# ======================================================================
# CAMERA RESET HELPER
# ======================================================================

def reset_browser_camera():

    global latest_state
    global latest_jpeg

    reset_pipeline()

    try:

        predictor.reset()

    except Exception as exc:

        print(
            "[WARNING] Predictor reset:",
            repr(exc)
        )

    try:

        timeline.reset()

    except Exception as exc:

        print(
            "[WARNING] Timeline reset:",
            repr(exc)
        )

    try:

        emergency.reset()

    except Exception as exc:

        print(
            "[WARNING] Emergency reset:",
            repr(exc)
        )

    latest_jpeg = None

    latest_state = {

        "found": False,

        "status_text":
            "Idle",

        "score": 0,

        "level":
            "ALERT",

        "camera_processing":
            "BROWSER",

    }

    return {

        "ok": True,

        "running":
            browser_camera_running,

    }


# ======================================================================
# NEW CAMERA API
# ======================================================================

@app.route(
    "/api/camera/<action>",
    methods=["POST"]
)
def api_camera(action):

    if action == "start":

        try:

            return jsonify(
                start_browser_camera()
            )

        except Exception as exc:

            print(
                "[CAMERA START ERROR]",
                repr(exc)
            )

            return jsonify({

                "ok": False,

                "error":
                    "Camera session could not be started.",

                "detail":
                    str(exc),

            }), 500


    if action == "stop":

        try:

            return jsonify(
                stop_browser_camera()
            )

        except Exception as exc:

            print(
                "[CAMERA STOP ERROR]",
                repr(exc)
            )

            return jsonify({

                "ok": False,

                "error":
                    str(exc),

            }), 500


    if action == "reset":

        try:

            return jsonify(
                reset_browser_camera()
            )

        except Exception as exc:

            print(
                "[CAMERA RESET ERROR]",
                repr(exc)
            )

            return jsonify({

                "ok": False,

                "error":
                    str(exc),

            }), 500


    return jsonify({

        "ok": False,

        "error":
            "Unknown camera action",

    }), 400


# ======================================================================
# OLD / LEGACY CAMERA ROUTES
#
# IMPORTANT:
# Some versions of your dashboard JavaScript use:
#
#   /start_camera
#   /stop_camera
#   /reset
#
# Keep these routes so old frontend code also works.
# ======================================================================

@app.route(
    "/start_camera",
    methods=["GET", "POST"]
)
def legacy_start_camera():

    try:

        result = start_browser_camera()

        if result.get("ok"):

            return jsonify({

                "status":
                    "started",

                "ok":
                    True,

                "running":
                    True,

                "mode":
                    "browser_camera",

            })

        return jsonify({

            "status":
                "error",

            "ok":
                False,

            "error":
                result.get(
                    "error",
                    "Camera could not be started."
                ),

        }), 500

    except Exception as exc:

        print(
            "[LEGACY START ERROR]",
            repr(exc)
        )

        return jsonify({

            "status":
                "error",

            "ok":
                False,

            "error":
                "Camera session could not be started.",

            "detail":
                str(exc),

        }), 500


@app.route(
    "/stop_camera",
    methods=["GET", "POST"]
)
def legacy_stop_camera():

    try:

        result = stop_browser_camera()

        return jsonify({

            "status":
                "stopped",

            **result,

        })

    except Exception as exc:

        print(
            "[LEGACY STOP ERROR]",
            repr(exc)
        )

        return jsonify({

            "status":
                "error",

            "ok":
                False,

            "error":
                str(exc),

        }), 500


@app.route(
    "/reset",
    methods=["GET", "POST"]
)
def legacy_reset():

    try:

        result = reset_browser_camera()

        return jsonify({

            "status":
                "reset",

            **result,

        })

    except Exception as exc:

        print(
            "[LEGACY RESET ERROR]",
            repr(exc)
        )

        return jsonify({

            "status":
                "error",

            "ok":
                False,

            "error":
                str(exc),

        }), 500


# ======================================================================
# BROWSER FRAME PROCESSING
# ======================================================================

@app.route(
    "/api/process_frame",
    methods=["POST"]
)
def process_frame():

    global latest_state
    global latest_jpeg

    # --------------------------------------------------------------
    # Camera session check
    # --------------------------------------------------------------

    if not browser_camera_running:

        return jsonify({

            "ok":
                False,

            "error":
                "Camera session is not active."

        }), 400

    # --------------------------------------------------------------
    # Pipeline check
    # --------------------------------------------------------------

    if pipeline is None:

        if not create_pipeline():

            return jsonify({

                "ok":
                    False,

                "error":
                    "Detection pipeline unavailable."

            }), 500

    # --------------------------------------------------------------
    # Receive browser frame
    # --------------------------------------------------------------

    image_data = request.files.get(
        "frame"
    )

    if image_data is None:

        return jsonify({

            "ok":
                False,

            "error":
                "No frame received."

        }), 400

    try:

        # ----------------------------------------------------------
        # Read image
        # ----------------------------------------------------------

        raw = image_data.read()

        if not raw:

            return jsonify({

                "ok":
                    False,

                "error":
                    "Empty frame."

            }), 400

        # ----------------------------------------------------------
        # Protect server from oversized frame
        # ----------------------------------------------------------

        max_frame_bytes = (
            getattr(
                config,
                "MAX_CAMERA_FRAME_KB",
                1024
            )
            * 1024
        )

        if len(raw) > max_frame_bytes:

            return jsonify({

                "ok":
                    False,

                "error":
                    (
                        "Camera frame too large. "
                        f"Maximum "
                        f"{getattr(config, 'MAX_CAMERA_FRAME_KB', 1024)} KB."
                    ),

            }), 413

        # ----------------------------------------------------------
        # JPEG -> NumPy
        # ----------------------------------------------------------

        arr = np.frombuffer(

            raw,

            dtype=np.uint8

        )

        # ----------------------------------------------------------
        # NumPy -> OpenCV
        # ----------------------------------------------------------

        frame = cv2.imdecode(

            arr,

            cv2.IMREAD_COLOR

        )

        if frame is None:

            return jsonify({

                "ok":
                    False,

                "error":
                    "Invalid image frame."

            }), 400

        # ----------------------------------------------------------
        # Resize
        # ----------------------------------------------------------

        target_width = int(
            getattr(
                config,
                "FRAME_WIDTH",
                640
            )
        )

        target_height = int(
            getattr(
                config,
                "FRAME_HEIGHT",
                480
            )
        )

        frame = cv2.resize(

            frame,

            (
                target_width,
                target_height
            ),

            interpolation=cv2.INTER_AREA,

        )

        # ----------------------------------------------------------
        # Mirror browser frame
        # ----------------------------------------------------------

        frame = cv2.flip(

            frame,

            1

        )

        # ----------------------------------------------------------
        # AI PROCESSING
        # ----------------------------------------------------------

        with pipeline_lock:

            annotated, state = (
                pipeline.process_frame(

                    frame,

                    draw=True

                )
            )

        # ----------------------------------------------------------
        # Fallback state
        # ----------------------------------------------------------

        if state is None:

            state = {

                "found":
                    False,

                "status_text":
                    "Processing",

                "score":
                    0,

                "level":
                    "ALERT",

            }

        # ----------------------------------------------------------
        # Add browser processing info
        # ----------------------------------------------------------

        state = dict(
            state
        )

        state[
            "camera_processing"
        ] = "BROWSER"

        latest_state = dict(
            state
        )

        # ----------------------------------------------------------
        # Events / notifications / prediction
        # ----------------------------------------------------------

        process_events(
            state
        )

        # ----------------------------------------------------------
        # Encode processed frame
        # ----------------------------------------------------------

        jpeg_quality = int(
            getattr(
                config,
                "CAMERA_JPEG_QUALITY",
                80
            )
        )

        ok, buffer = cv2.imencode(

            ".jpg",

            annotated,

            [

                cv2.IMWRITE_JPEG_QUALITY,

                jpeg_quality

            ],

        )

        if not ok:

            return jsonify({

                "ok":
                    False,

                "error":
                    "Could not encode processed frame."

            }), 500

        jpeg_bytes = (
            buffer.tobytes()
        )

        latest_jpeg = (
            jpeg_bytes
        )

        # ----------------------------------------------------------
        # Base64 response
        # ----------------------------------------------------------

        encoded = base64.b64encode(

            jpeg_bytes

        ).decode(
            "ascii"
        )

        # ----------------------------------------------------------
        # Return to browser
        # ----------------------------------------------------------

        return jsonify({

            "ok":
                True,

            "image":
                "data:image/jpeg;base64,"
                + encoded,

            "frame":
                encoded,

            "state":
                state,

        })

    except Exception as exc:

        print(
            "[FRAME ERROR]",
            repr(exc)
        )

        return jsonify({

            "ok":
                False,

            "error":
                str(exc)

        }), 500


# ======================================================================
# STATE
# ======================================================================

@app.route("/api/state")
def api_state():

    state = dict(

        latest_state

        or {

            "found":
                False,

            "status_text":
                "Idle",

            "score":
                0,

        }

    )

    state[
        "privacy_mode"
    ] = bool(

        getattr(
            config,
            "PRIVACY_MODE",
            False
        )

    )

    state[
        "video_storage"
    ] = bool(

        getattr(
            config,
            "VIDEO_STORAGE_ENABLED",
            False
        )

    )

    state[
        "camera_processing"
    ] = "BROWSER"

    state[
        "browser_camera"
    ] = True

    state[
        "camera_running"
    ] = browser_camera_running

    try:

        state[
            "notifications"
        ] = notifier.status()

    except Exception:

        state[
            "notifications"
        ] = {}

    try:

        state[
            "prediction"
        ] = predictor.current()

    except Exception:

        state[
            "prediction"
        ] = {}

    try:

        state[
            "emergency"
        ] = emergency.status()

    except Exception:

        state[
            "emergency"
        ] = {}

    return jsonify(
        state
    )


# ======================================================================
# VIDEO FEED
# ======================================================================

@app.route("/video_feed")
def video_feed():

    def generate():

        while browser_camera_running:

            frame = latest_jpeg

            if frame is not None:

                yield (

                    b"--frame\r\n"

                    b"Content-Type: image/jpeg\r\n\r\n"

                    + frame

                    + b"\r\n"

                )

            time.sleep(
                0.05
            )

    return Response(

        generate(),

        mimetype=(
            "multipart/x-mixed-replace;"
            " boundary=frame"
        )

    )


# ======================================================================
# UPLOAD ANALYSIS
# ======================================================================

def allowed_file(filename):

    return (

        "."

        in filename

        and filename.rsplit(
            ".",
            1
        )[1].lower()

        in config.ALLOWED_EXTENSIONS

    )


@app.route(
    "/api/analyze",
    methods=["POST"]
)
def api_analyze():

    if "file" not in request.files:

        return jsonify({

            "ok":
                False,

            "error":
                "No file part"

        }), 400

    file = request.files[
        "file"
    ]

    if file.filename == "":

        return jsonify({

            "ok":
                False,

            "error":
                "No file selected"

        }), 400

    if not allowed_file(
        file.filename
    ):

        return jsonify({

            "ok":
                False,

            "error":
                "Unsupported file type"

        }), 400

    filename = secure_filename(
        file.filename
    )

    save_path = os.path.join(

        config.UPLOAD_FOLDER,

        filename

    )

    file.save(
        save_path
    )

    try:

        summary = analyze_file(

            save_path,

            config

        )

    except Exception as exc:

        return jsonify({

            "ok":
                False,

            "error":
                str(exc)

        }), 500

    if (

        summary.get(
            "drowsy_events",
            0
        ) > 0

        or

        summary.get(
            "yawn_count",
            0
        ) > 0

    ):

        log_event(

            "UPLOAD_SUMMARY",

            "medium",

            (
                f"{summary.get('drowsy_events', 0)} "
                f"drowsy episodes in {filename}"
            ),

            score=summary.get(
                "max_score"
            ),

            source="upload",

        )

    summary[
        "ok"
    ] = True

    summary[
        "filename"
    ] = filename

    return jsonify(
        summary
    )


# ======================================================================
# EVENTS
# ======================================================================

@app.route("/api/events")
def api_events():

    limit = request.args.get(

        "limit",

        100,

        type=int

    )

    source = request.args.get(
        "source",
        None
    )

    return jsonify({

        "events":
            get_events(

                limit=limit,

                source=source

            )

    })


@app.route("/api/stats")
def api_stats():

    return jsonify(
        get_stats()
    )


@app.route(
    "/api/events/clear",
    methods=["POST"]
)
def api_clear():

    removed = clear_events()

    return jsonify({

        "ok":
            True,

        "removed":
            removed,

    })


# ======================================================================
# SESSION SUMMARY
# ======================================================================

@app.route(
    "/api/session/summary"
)
def api_session_summary():

    summary = {}

    if (

        pipeline is not None

        and

        hasattr(
            pipeline,
            "session_summary"
        )

    ):

        try:

            summary = (

                pipeline.session_summary()

                or {}

            )

        except Exception as exc:

            print(
                "[SESSION SUMMARY]",
                repr(exc)
            )

            summary = {}

    try:

        summary[
            "timeline"
        ] = timeline.series()

    except Exception:

        summary[
            "timeline"
        ] = {}

    try:

        summary[
            "final_prediction"
        ] = predictor.current()

    except Exception:

        summary[
            "final_prediction"
        ] = {}

    return jsonify(
        summary
    )


# ======================================================================
# PREDICTION
# ======================================================================

@app.route("/api/predict")
def api_predict():

    return jsonify(
        predictor.current()
    )


@app.route("/api/timeline")
def api_timeline():

    return jsonify(
        timeline.series()
    )


# ======================================================================
# NOTIFICATIONS
# ======================================================================

@app.route(
    "/api/notify/status"
)
def api_notify_status():

    return jsonify(
        notifier.status()
    )


@app.route(
    "/api/notify/test",
    methods=["POST"]
)
def api_notify_test():

    try:

        return jsonify(
            notifier.send_test()
        )

    except Exception as exc:

        return jsonify({

            "ok":
                False,

            "detail":
                str(exc)

        }), 500


# ======================================================================
# EMERGENCY
# ======================================================================

@app.route(
    "/api/emergency/status"
)
def api_emergency_status():

    return jsonify(
        emergency.status()
    )


@app.route(
    "/api/emergency/test",
    methods=["POST"]
)
def api_emergency_test():

    try:

        return jsonify(
            emergency.send_test()
        )

    except Exception as exc:

        return jsonify({

            "ok":
                False,

            "detail":
                str(exc)

        }), 500


# ======================================================================
# EXPORT
# ======================================================================

@app.route(
    "/api/events/export"
)
def api_events_export():

    fmt = (

        request.args.get(
            "fmt",
            "json"
        )

        or "json"

    ).lower()

    if fmt not in (
        "json",
        "csv"
    ):

        return jsonify({

            "ok":
                False,

            "error":
                "fmt must be json or csv"

        }), 400

    mimetype, text = (
        event_logger.export(
            fmt
        )
    )

    extension = (

        "csv"

        if fmt == "csv"

        else "json"

    )

    filename = (
        f"driver_events.{extension}"
    )

    return Response(

        text,

        mimetype=mimetype,

        headers={

            "Content-Disposition":
                (
                    "attachment; "
                    f"filename={filename}"
                )

        },

    )


# ======================================================================
# HEALTH
# ======================================================================

@app.route("/api/health")
def api_health():

    cnn_active = False

    if pipeline is not None:

        try:

            cnn_active = bool(
                getattr(
                    pipeline,
                    "cnn_active",
                    False
                )
            )

        except Exception:

            cnn_active = False

    return jsonify({

        "ok":
            True,

        "camera_running":
            browser_camera_running,

        "camera_mode":
            "browser",

        "camera_processing":
            "BROWSER",

        "cnn_active":
            cnn_active,

        "time":
            time.time(),

    })


# ======================================================================
# ERROR HANDLERS
# ======================================================================

@app.errorhandler(413)
def too_large(_):

    return jsonify({

        "ok":
            False,

        "error":
            (
                f"File exceeds "
                f"{config.MAX_CONTENT_MB} MB limit"
            )

    }), 413


# ======================================================================
# LOCAL DEVELOPMENT
# ======================================================================

if __name__ == "__main__":

    print("=" * 60)

    print(
        " Driver Drowsiness Detection Dashboard"
    )

    print("=" * 60)

    print(

        f" Local URL: "
        f"http://127.0.0.1:{config.PORT}"

    )

    print(
        " Camera mode: BROWSER CAMERA"
    )

    print(
        " Server webcam access: DISABLED"
    )

    print("=" * 60)

    app.run(

        host=config.HOST,

        port=config.PORT,

        debug=config.DEBUG,

        threaded=True,

    )